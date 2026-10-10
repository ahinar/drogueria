"""
IMPORTAR EXISTENCIAS (LOTES) DESDE ODOO
=======================================

Para qué sirve:
    Cargar el inventario inicial de una vez, con cada lote, su vencimiento y
    su cantidad, desde el Excel que exporta Odoo en
    Inventario → Operaciones → Ajustes físicos de inventario → Exportar.

Cómo funciona (en dos pasos, como el importador de productos):
    1. PREVISUALIZAR: se lee el archivo, se busca cada producto y se muestra
       qué va a entrar y qué no (y por qué). No se guarda nada todavía.
    2. CONFIRMAR: se crean los lotes y su entrada en el kardex
       (movimiento "ajuste" con referencia "Carga inicial (Odoo)").

Reglas (las mismas de todo el programa):
    - Las cantidades de Odoo vienen en la unidad de medida del producto
      (ej. 22,5 SELLO X 10). Aquí se guardan en UNIDADES: 225.
    - Cantidades en 0 o negativas NO se cargan: se listan aparte para revisarlas
      (en Odoo había negativos porque se vendía sin existencias).
    - Si queda una fracción de unidad (ej. 37,67) se redondea y se avisa.
    - Si el mismo lote ya existe en el programa, no se repite (importar dos
      veces el mismo archivo no duplica el inventario).
    - El costo de cada lote es el costo de 1 unidad de la ficha del producto.
"""
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from .audit import registrar
from .auth import roles_required
from .db import ahora, get_db
from .importador import _abrir_archivo, _num
from . import presentaciones as pres

bp = Blueprint("existencias", __name__, url_prefix="/productos/importar/existencias")

REFERENCIA = "Carga inicial (Odoo)"

# Nombres con que Odoo (o un Excel propio) puede traer cada dato
COLUMNAS = {
    "producto": ["producto", "nombre en pantalla", "nombre", "articulo"],
    "lote": ["numero de serie/lote", "lote/numero de serie", "numero de lote/serie", "lote", "numero de lote"],
    "vence": ["fecha de caducidad", "numero de serie/lote/fecha de caducidad", "lote/numero de serie/fecha de caducidad",
              "lote/fecha de caducidad", "vencimiento", "fecha de vencimiento", "vence"],
    "cantidad": ["cantidad a la mano", "cantidad", "cantidad contada", "existencias", "a la mano"],
    "unidad": ["unidad de medida", "udm", "unidad"],
    "ubicacion": ["ubicacion"],
}


def _normal(texto):
    """'Número de serie/Lote ' -> 'numero de serie/lote' (sin tildes, minúsculas, espacios simples)."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().replace("*", "").split())


def _mapear(encabezados):
    """{dato: encabezado del archivo} para producto, lote, vence, cantidad, unidad, ubicación."""
    normales = {_normal(e): e for e in encabezados}
    mapa = {}
    for dato, opciones in COLUMNAS.items():
        for o in opciones:
            if o in normales and normales[o] not in mapa.values():
                mapa[dato] = normales[o]
                break
    return mapa


def _fecha(valor):
    """'2026-12-31 05:00:00', '31/12/2026', '2026-12-31' -> '2026-12-31'. Vacío o '0' -> None."""
    t = str(valor or "").strip()
    if not t or t in ("0", "False", "None"):
        return None
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(t[:19] if "%H" in formato else t[:10], formato).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


class _BuscadorProductos:
    """Encuentra el producto de cada fila: por código de barras, código o nombre.

    Odoo escribe el producto así: "[7702027440106] DOLEX GRIPA" (la parte entre
    corchetes es la referencia interna, que a veces es el código de barras) o
    solo "DOLEX GRIPA".
    """
    def __init__(self, db):
        self.por_barras, self.por_codigo, self.por_nombre = {}, {}, {}
        for p in db.execute("SELECT id, codigo, codigo_barras, nombre FROM productos"):
            if p["codigo_barras"]:
                self.por_barras[p["codigo_barras"].strip()] = p["id"]
            self.por_codigo[p["codigo"].strip().lower()] = p["id"]
            self.por_nombre.setdefault(_normal(p["nombre"]), p["id"])
        for pp in db.execute("SELECT producto_id, codigo_barras FROM producto_presentaciones "
                             "WHERE codigo_barras IS NOT NULL"):
            self.por_barras.setdefault(pp["codigo_barras"].strip(), pp["producto_id"])

    def buscar(self, texto):
        texto = str(texto or "").strip()
        m = re.match(r"^\[(.+?)\]\s*(.*)$", texto)
        ref, nombre = (m.group(1).strip(), m.group(2)) if m else ("", texto)
        for intento in (self.por_barras.get(ref), self.por_codigo.get(ref.lower()),
                        self.por_nombre.get(_normal(nombre)), self.por_barras.get(texto),
                        self.por_nombre.get(_normal(texto))):
            if intento:
                return intento
        return None


def _analizar(filas):
    """Revisa cada fila y la agrupa por producto + lote. Devuelve (lineas, problemas)."""
    db = get_db()
    mapa = _mapear(filas[0].keys())
    if "producto" not in mapa or "cantidad" not in mapa:
        return None, [f"No encontré las columnas 'Producto' y 'Cantidad a la mano'. Columnas del archivo: "
                      f"{', '.join(list(filas[0].keys())[:10])}"]
    buscador = _BuscadorProductos(db)
    productos = {p["id"]: p for p in db.execute("SELECT * FROM productos")}
    opciones = pres.presentaciones_de(list(productos))
    unidades = {_normal(u["nombre"]): u for u in db.execute("SELECT nombre, cantidad FROM unidades_medida")}

    grupos, problemas = {}, []
    for i, f in enumerate(filas, 2):                    # fila 1 = encabezados
        texto_prod = (f.get(mapa["producto"]) or "").strip()
        if not texto_prod:
            continue
        ubic = _normal(f.get(mapa.get("ubicacion", ""), ""))
        if any(x in ubic for x in ("virtual", "partner", "cliente", "proveedor", "scrap", "desecho")):
            continue                                    # no es mercancía en la droguería
        pid = buscador.buscar(texto_prod)
        if not pid:
            problemas.append({"fila": i, "producto": texto_prod, "motivo": "No existe en el programa (impórtalo primero)"})
            continue
        prod = productos[pid]
        cantidad = _num(f.get(mapa["cantidad"]), 0)
        if cantidad <= 0:
            problemas.append({"fila": i, "producto": prod["nombre"],
                              "motivo": f"Cantidad {cantidad:g} en Odoo (0 o negativa): no se carga"})
            continue
        # ¿En qué unidad viene? La de la columna, o la que el producto vende normalmente
        # (al importar de Odoo, la unidad de medida quedó como unidad de venta)
        nombre_unidad = _normal(f.get(mapa.get("unidad", ""), ""))
        if nombre_unidad in ("unidades", "unidad", "unidad(es)", "units"):
            factor = 1.0
        elif nombre_unidad in unidades:
            u = unidades[nombre_unidad]
            factor = pres.cantidad_efectiva(u["nombre"], u["cantidad"])
        elif nombre_unidad:
            factor = pres.cantidad_efectiva(nombre_unidad, 1)
        else:
            ops = opciones.get(pid, [])
            defecto = pres.id_por_defecto(ops, prod["venta_defecto_unidad_id"])
            factor = next((o["factor"] for o in ops if o["id"] == defecto), 1.0)
        lote = (str(f.get(mapa.get("lote", ""), "") or "").strip().upper()) or None
        if lote in ("FALSE", "0", "NONE"):
            lote = None
        vence = _fecha(f.get(mapa.get("vence", ""), ""))
        clave = (pid, lote)
        g_ = grupos.setdefault(clave, {"producto_id": pid, "nombre": prod["nombre"], "lote": lote,
                                       "vence": vence, "unidades": 0.0, "filas": [],
                                       "maneja": bool(prod["maneja_vencimiento"]),
                                       "costo": float(prod["precio_compra"] or 0)})
        g_["unidades"] += cantidad * factor
        g_["vence"] = g_["vence"] or vence
        g_["filas"].append(i)

    lineas = []
    for g_ in grupos.values():
        avisos = []
        exacto = round(g_["unidades"], 4)
        g_["unidades"] = round(exacto)
        if abs(exacto - g_["unidades"]) > 1e-6:
            avisos.append(f"{exacto:g} unidades: se redondea a {g_['unidades']}")
        if g_["unidades"] <= 0:
            problemas.append({"fila": g_["filas"][0], "producto": g_["nombre"], "motivo": "Menos de 1 unidad: no se carga"})
            continue
        if g_["maneja"] and not g_["lote"]:
            avisos.append("Maneja vencimiento pero no trae lote: entra 'sin lote' (corrígelo en el conteo)")
        elif g_["maneja"] and not g_["vence"]:
            avisos.append("Sin fecha de vencimiento")
        ya = db.execute("SELECT 1 FROM lotes WHERE producto_id = ? AND "
                        "UPPER(TRIM(COALESCE(lote, ''))) = ? AND estado <> 'rechazado'",
                        (g_["producto_id"], g_["lote"] or "")).fetchone()
        g_["estado"] = "existe" if ya else "ok"
        g_["avisos"] = avisos
        lineas.append(g_)
    lineas.sort(key=lambda x: (x["estado"] != "ok", not x["avisos"], x["nombre"]))
    return lineas, problemas


@bp.route("/", methods=["GET"])
@roles_required("administrador", "director_tecnico")
def inicio():
    return render_template("importador/existencias_inicio.html")


@bp.route("/previsualizar", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def previsualizar():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Escoge el archivo.", "error")
        return redirect(url_for("existencias.inicio"))
    filas, error = _abrir_archivo(archivo.filename, archivo.read())
    if error or not filas:
        flash(error or "El archivo no tiene filas.", "error")
        return redirect(url_for("existencias.inicio"))
    lineas, problemas = _analizar(filas)
    if lineas is None:
        flash(problemas[0], "error")
        return redirect(url_for("existencias.inicio"))
    # Se guarda el análisis para el paso 2 (igual que el importador de productos)
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(lineas, tmp, ensure_ascii=False)
    tmp.close()
    session["existencias_tmp"] = tmp.name
    nuevas = [l for l in lineas if l["estado"] == "ok"]
    return render_template("importador/existencias_previa.html", lineas=lineas, problemas=problemas,
                           nuevas=len(nuevas), repetidas=len(lineas) - len(nuevas),
                           unidades=sum(l["unidades"] for l in nuevas),
                           valor=sum(l["unidades"] * l["costo"] for l in nuevas),
                           sin_costo=sum(1 for l in nuevas if l["costo"] <= 0))


@bp.route("/confirmar", methods=["POST"])
@roles_required("administrador", "director_tecnico")
def confirmar():
    tmp = session.pop("existencias_tmp", None)
    if not tmp or not os.path.exists(tmp):
        flash("La importación expiró. Vuelve a subir el archivo.", "error")
        return redirect(url_for("existencias.inicio"))
    with open(tmp, encoding="utf-8") as f:
        lineas = json.load(f)
    os.unlink(tmp)
    db = get_db()
    creados, unidades = 0, 0
    for l in lineas:
        if l["estado"] != "ok":
            continue
        # Se vuelve a revisar por si entre el paso 1 y el 2 alguien creó el lote
        if db.execute("SELECT 1 FROM lotes WHERE producto_id = ? AND UPPER(TRIM(COALESCE(lote, ''))) = ? "
                      "AND estado <> 'rechazado'", (l["producto_id"], l["lote"] or "")).fetchone():
            continue
        cur = db.execute(
            "INSERT INTO lotes (producto_id, lote, vencimiento, cantidad_inicial, cantidad_disponible, "
            "costo_unitario, estado, creado_en) VALUES (?,?,?,?,?,?, 'disponible', ?)",
            (l["producto_id"], l["lote"], l["vence"], l["unidades"], l["unidades"], l["costo"], ahora()))
        db.execute(
            "INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, cantidad, referencia, "
            "usuario_id, usuario_nombre, observaciones, creado_en) VALUES (?,?,?, 'ajuste', ?, ?, ?, ?, ?, ?)",
            (ahora(), cur.lastrowid, l["producto_id"], l["unidades"], REFERENCIA, g.user["id"], g.user["nombre"],
             "; ".join(l["avisos"]) or None, ahora()))
        creados += 1
        unidades += l["unidades"]
    db.commit()
    registrar("existencias_importadas", "lotes", None, f"{creados} lotes, {unidades} unidades ({REFERENCIA})")
    flash(f"Listo: {creados} lote(s) cargados al inventario ({unidades:,} unidades).".replace(",", "."), "ok")
    return redirect(url_for("productos.lista", vista="lista"))
