"""Toma de inventario (conteo físico de la mercancía).

CÓMO FUNCIONA (en palabras sencillas)
-------------------------------------
1. El administrador o el director técnico CREA un conteo: de toda la
   droguería o solo de una categoría. Solo puede haber uno abierto a la vez.
2. Cualquier usuario CUENTA: busca el producto (o lo escanea), ve cuánto dice
   el sistema de cada lote y escribe cuánto hay de verdad en la estantería.
   Si aparece un lote que no está en el sistema, lo agrega ahí mismo
   (así se carga el inventario inicial después de importar los productos).
3. Se REVISAN las diferencias: faltantes y sobrantes, en unidades y en pesos.
4. El administrador o el director técnico APLICA el conteo: todos los lotes
   se corrigen de una vez, queda en el kardex y en la bitácora, y se puede
   descargar el ACTA en PDF.

¿Y SI SE VENDE MIENTRAS SE CUENTA?
----------------------------------
Al guardar lo contado de un lote, el programa anota cuánto decía el sistema EN
ESE MOMENTO (cantidad_sistema). La diferencia es: contado - cantidad_sistema.
Al aplicar NO se reemplaza la cantidad por lo contado; se SUMA la diferencia a
lo que haya en ese momento. Ejemplo:
    - El sistema dice 10. Cuentas 9 (falta 1). Diferencia = -1.
    - Antes de aplicar se venden 2 -> el sistema queda en 8.
    - Al aplicar: 8 + (-1) = 7. ✔ (Si se pusiera "9" se perderían las 2 ventas.)
Por eso lo importante es escribir la cantidad apenas termines de contar ese lote.
"""
import re
from datetime import date
from io import BytesIO

from flask import (Blueprint, abort, flash, g, jsonify, redirect, render_template,
                   request, send_file, url_for)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .audit import registrar
from .auth import login_required, roles_required
from .configuracion import obtener_config
from .db import ahora, get_db
from .pdf_utils import encabezado_pdf

bp = Blueprint("conteos", __name__, url_prefix="/inventario/conteos")

POR_PAGINA = 40          # productos que se muestran por página en la pantalla de conteo
CERO = 1e-9              # para comparar números con decimales sin errores de redondeo


# =====================================================================
# Ayudas
# =====================================================================

def _json_error(mensaje, codigo=400):
    return jsonify({"ok": False, "error": mensaje}), codigo


def _numero(texto):
    """Convierte lo que escribe el usuario en número. '12' -> 12, '2,5' -> 2.5.
    Devuelve None si está vacío y 'error' si no es un número."""
    texto = str(texto if texto is not None else "").strip().replace(" ", "")
    if not texto:
        return None
    # En Colombia: punto = miles, coma = decimales  (6.420,50 -> 6420.50)
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") == 1 and len(texto.split(".")[1]) == 3:
        texto = texto.replace(".", "")   # 6.420 -> 6420
    try:
        return float(texto)
    except ValueError:
        return "error"


def _obtener(conteo_id):
    """Trae el conteo con el nombre de su categoría, o error 404 si no existe."""
    c = get_db().execute(
        "SELECT c.*, cat.nombre AS categoria FROM conteos c "
        "LEFT JOIN catalogos cat ON cat.id = c.categoria_id WHERE c.id = ?",
        (conteo_id,),
    ).fetchone()
    if c is None:
        abort(404)
    return c


def _conteo_abierto():
    return get_db().execute(
        "SELECT * FROM conteos WHERE estado = 'abierto' ORDER BY id DESC LIMIT 1"
    ).fetchone()


def _siguiente_numero():
    fila = get_db().execute("SELECT numero FROM conteos ORDER BY id DESC LIMIT 1").fetchone()
    try:
        n = int(fila["numero"].split("-")[1]) + 1 if fila else 1
    except (ValueError, IndexError):
        n = 1
    return f"CNT-{n:04d}"


def _filtro_alcance(conteo, alias="p"):
    """Trozo de SQL que limita los productos al alcance del conteo (todo o una categoría)."""
    if conteo["categoria_id"]:
        return (f" AND {alias}.id IN (SELECT producto_id FROM productos_categorias "
                f"WHERE catalogo_id = {int(conteo['categoria_id'])})")
    return ""


def _resumen(conteo):
    """Números para la barra de progreso: lotes contados, pendientes y diferencias."""
    db = get_db()
    lineas = db.execute(
        "SELECT cantidad_contada, cantidad_sistema, costo_unitario, lote_id "
        "FROM conteo_lineas WHERE conteo_id = ?", (conteo["id"],)
    ).fetchall()
    con_diferencia = [l for l in lineas if abs(l["cantidad_contada"] - l["cantidad_sistema"]) > CERO]
    # Lotes con existencias, dentro del alcance, que nadie ha contado todavía
    pendientes = db.execute(
        "SELECT COUNT(*) FROM lotes l JOIN productos p ON p.id = l.producto_id "
        "WHERE l.cantidad_disponible > 0 AND l.estado <> 'rechazado' AND p.activo = 1"
        + _filtro_alcance(conteo) +
        " AND l.id NOT IN (SELECT lote_id FROM conteo_lineas WHERE conteo_id = ? "
        "                  AND lote_id IS NOT NULL)",
        (conteo["id"],),
    ).fetchone()[0]
    valor = sum((l["cantidad_contada"] - l["cantidad_sistema"]) * l["costo_unitario"]
                for l in con_diferencia)
    return {
        "contados": len(lineas),
        "pendientes": pendientes,
        "con_diferencia": len(con_diferencia),
        "lotes_nuevos": sum(1 for l in lineas if l["lote_id"] is None),
        "valor_diferencia": round(valor, 2),
    }


def _linea_json(l):
    """Convierte una línea de conteo en el formato que usa la pantalla."""
    if l is None:
        return None
    return {"id": l["id"], "contada": l["cantidad_contada"], "sistema": l["cantidad_sistema"],
            "diferencia": round(l["cantidad_contada"] - l["cantidad_sistema"], 4),
            "contado_por": l["contado_por_nombre"], "contado_en": l["contado_en"]}


# =====================================================================
# Lista de conteos y crear uno nuevo
# =====================================================================

@bp.route("/")
@login_required
def lista():
    db = get_db()
    conteos = db.execute(
        "SELECT c.*, cat.nombre AS categoria, "
        "  (SELECT COUNT(*) FROM conteo_lineas WHERE conteo_id = c.id) AS n_lineas "
        "FROM conteos c LEFT JOIN catalogos cat ON cat.id = c.categoria_id "
        "ORDER BY c.id DESC LIMIT 100"
    ).fetchall()
    categorias = db.execute(
        "SELECT id, nombre FROM catalogos WHERE tipo = 'categoria' AND activo = 1 "
        "ORDER BY nombre COLLATE NOCASE"
    ).fetchall()
    return render_template("conteos/lista.html", conteos=conteos, categorias=categorias,
                           abierto=_conteo_abierto())


@bp.route("/nuevo", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def nuevo():
    abierto = _conteo_abierto()
    if abierto:
        flash(f"Ya hay un conteo abierto ({abierto['numero']}). Termínalo o anúlalo antes de crear otro.",
              "error")
        return redirect(url_for("conteos.contar", conteo_id=abierto["id"]))

    descripcion = (request.form.get("descripcion") or "").strip() or None
    cat = (request.form.get("categoria_id") or "").strip()
    categoria_id = int(cat) if cat.isdigit() else None

    db = get_db()
    numero = _siguiente_numero()
    cur = db.execute(
        "INSERT INTO conteos (numero, descripcion, categoria_id, estado, creado_en, "
        "creado_por, creado_por_nombre) VALUES (?,?,?, 'abierto', ?,?,?)",
        (numero, descripcion, categoria_id, ahora(), g.user["id"], g.user["nombre"]),
    )
    db.commit()
    registrar("conteo_creado", "conteos", cur.lastrowid,
              f"{numero} alcance={'categoría ' + str(categoria_id) if categoria_id else 'todo'}")
    flash(f"Conteo {numero} creado. ¡A contar!", "ok")
    return redirect(url_for("conteos.contar", conteo_id=cur.lastrowid))


# =====================================================================
# Pantalla de conteo (la página; los datos los trae JS con /api/buscar)
# =====================================================================

@bp.route("/<int:conteo_id>")
@login_required
def contar(conteo_id):
    conteo = _obtener(conteo_id)
    if conteo["estado"] != "abierto":
        return redirect(url_for("conteos.revisar", conteo_id=conteo_id))
    return render_template("conteos/contar.html", conteo=conteo, resumen=_resumen(conteo))


@bp.route("/<int:conteo_id>/api/buscar")
@login_required
def api_buscar(conteo_id):
    """Busca productos del conteo y devuelve sus lotes con lo que ya se contó.

    Parámetros: q (texto o código de barras), filtro (todos / pendientes /
    contados / diferencias) y pagina (0, 1, 2...).
    """
    conteo = _obtener(conteo_id)
    db = get_db()
    q = (request.args.get("q") or "").strip()
    filtro = request.args.get("filtro") or "todos"
    try:
        pagina = max(0, int(request.args.get("pagina") or 0))
    except ValueError:
        pagina = 0

    # ---- 1. Productos activos dentro del alcance que coinciden con lo buscado ----
    sql = ("SELECT p.id, p.codigo, p.codigo_barras, p.nombre, p.concentracion, "
           "p.maneja_vencimiento, p.precio_compra FROM productos p WHERE p.activo = 1"
           + _filtro_alcance(conteo))
    params = []
    # Si lo buscado es exactamente un código de barras, mostramos solo ese producto
    # (también sirve el código de una caja o sobre: producto_presentaciones)
    exacto = db.execute(
        "SELECT id FROM productos WHERE activo = 1 AND codigo_barras = ? "
        "UNION ALL SELECT pp.producto_id FROM producto_presentaciones pp "
        "JOIN productos p ON p.id = pp.producto_id WHERE p.activo = 1 AND pp.codigo_barras = ? "
        "LIMIT 1", (q, q)).fetchone() if q else None
    if exacto:
        sql += " AND p.id = ?"
        params.append(exacto["id"])
    else:
        for palabra in q.split():
            sql += " AND (p.nombre LIKE ? OR p.codigo LIKE ? OR p.codigo_barras LIKE ?)"
            params += [f"%{palabra}%"] * 3
    sql += " ORDER BY p.nombre COLLATE NOCASE"
    productos = db.execute(sql, params).fetchall()
    if not productos:
        return jsonify({"ok": True, "productos": [], "hay_mas": False, "exacto": False,
                        "resumen": _resumen(conteo)})
    ids = [p["id"] for p in productos]
    marcas = ",".join("?" * len(ids))

    # ---- 2. Lotes de esos productos (con existencias, o ya contados en este conteo) ----
    lotes = db.execute(
        f"SELECT l.* FROM lotes l WHERE l.producto_id IN ({marcas}) AND l.estado <> 'rechazado' "
        "AND (l.cantidad_disponible > 0 OR l.id IN "
        "     (SELECT lote_id FROM conteo_lineas WHERE conteo_id = ? AND lote_id IS NOT NULL)) "
        "ORDER BY (l.vencimiento IS NULL OR l.vencimiento = ''), l.vencimiento, l.id",
        ids + [conteo_id],
    ).fetchall()
    lineas = db.execute(
        f"SELECT * FROM conteo_lineas WHERE conteo_id = ? AND producto_id IN ({marcas})",
        [conteo_id] + ids,
    ).fetchall()
    linea_por_lote = {l["lote_id"]: l for l in lineas if l["lote_id"] is not None}

    # ---- 3. Armar cada producto con sus lotes ----
    resultado = []
    for p in productos:
        filas = []
        for l in (x for x in lotes if x["producto_id"] == p["id"]):
            filas.append({
                "lote_id": l["id"], "lote": l["lote"], "vencimiento": l["vencimiento"],
                "estado": l["estado"], "sistema_actual": l["cantidad_disponible"],
                "costo": l["costo_unitario"], "nuevo": False,
                "linea": _linea_json(linea_por_lote.get(l["id"])),
            })
        # Lotes encontrados en la estantería que todavía no existen en el sistema
        for ln in (x for x in lineas if x["producto_id"] == p["id"] and x["lote_id"] is None):
            filas.append({
                "lote_id": None, "lote": ln["lote"], "vencimiento": ln["vencimiento"],
                "estado": "nuevo", "sistema_actual": 0, "costo": ln["costo_unitario"],
                "nuevo": True, "linea": _linea_json(ln),
            })
        contados = [f for f in filas if f["linea"]]
        pendiente = any(not f["linea"] for f in filas) or not filas
        con_dif = any(f["linea"] and abs(f["linea"]["diferencia"]) > CERO for f in filas)
        if filtro == "pendientes" and not pendiente:
            continue
        if filtro == "contados" and not contados:
            continue
        if filtro == "diferencias" and not con_dif:
            continue
        resultado.append({
            "id": p["id"], "codigo": p["codigo"], "codigo_barras": p["codigo_barras"],
            "nombre": p["nombre"], "concentracion": p["concentracion"],
            "maneja_vencimiento": bool(p["maneja_vencimiento"]),
            "costo_sugerido": _costo_sugerido(p),
            "lotes": filas,
        })

    inicio = pagina * POR_PAGINA
    return jsonify({
        "ok": True,
        "productos": resultado[inicio:inicio + POR_PAGINA],
        "hay_mas": len(resultado) > inicio + POR_PAGINA,
        "total": len(resultado),
        "exacto": bool(exacto),
        "resumen": _resumen(conteo),
    })


def _costo_sugerido(producto):
    """Costo para proponer en un lote nuevo: última compra o, si no hay, el de la ficha."""
    fila = get_db().execute(
        "SELECT costo_unitario FROM lotes WHERE producto_id = ? AND costo_unitario > 0 "
        "ORDER BY id DESC LIMIT 1", (producto["id"],)
    ).fetchone()
    return fila["costo_unitario"] if fila else (producto["precio_compra"] or 0)


# =====================================================================
# Guardar lo contado de un lote (o de un lote encontrado)
# =====================================================================

@bp.route("/<int:conteo_id>/api/contar", methods=["POST"])
@login_required
def api_contar(conteo_id):
    conteo = _obtener(conteo_id)
    if conteo["estado"] != "abierto":
        return _json_error("Este conteo ya está cerrado.")
    db = get_db()
    f = request.form

    cantidad = _numero(f.get("cantidad"))
    if cantidad in (None, "error") or cantidad < 0:
        return _json_error("Escribe una cantidad válida (0 o más).")

    lote_id = int(f["lote_id"]) if (f.get("lote_id") or "").isdigit() else None
    linea_id = int(f["linea_id"]) if (f.get("linea_id") or "").isdigit() else None

    # ---- Caso A: corregir un lote NUEVO que ya se había anotado ----
    if linea_id and not lote_id:
        ln = db.execute("SELECT * FROM conteo_lineas WHERE id = ? AND conteo_id = ? "
                        "AND lote_id IS NULL", (linea_id, conteo_id)).fetchone()
        if ln is None:
            return _json_error("Esa línea ya no existe. Recarga la página.")
        db.execute("UPDATE conteo_lineas SET cantidad_contada = ?, contado_en = ?, contado_por = ?, "
                   "contado_por_nombre = ? WHERE id = ?",
                   (cantidad, ahora(), g.user["id"], g.user["nombre"], linea_id))
        db.commit()
        return _respuesta_linea(conteo, linea_id)

    # ---- Caso B: lote encontrado que no está en el sistema ----
    if not lote_id:
        producto_id = int(f["producto_id"]) if (f.get("producto_id") or "").isdigit() else None
        prod = db.execute("SELECT * FROM productos WHERE id = ? AND activo = 1",
                          (producto_id,)).fetchone() if producto_id else None
        if prod is None:
            return _json_error("Producto no válido.")
        lote_txt = (f.get("lote") or "").strip().upper()
        vence = (f.get("vencimiento") or "").strip()
        if prod["maneja_vencimiento"] and (not lote_txt or not vence):
            return _json_error("Este producto maneja lotes: escribe el lote y el vencimiento.")
        if vence and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", vence):
            return _json_error("La fecha de vencimiento no es válida.")
        if cantidad <= 0:
            return _json_error("Para agregar un lote encontrado la cantidad debe ser mayor a 0.")
        costo = _numero(f.get("costo"))
        if costo is None:
            costo = _costo_sugerido(prod)
        if costo == "error" or costo <= 0:
            return _json_error("Escribe el costo unitario (lo necesitas para calcular utilidades).")

        # ¿Ese lote YA existe en el sistema? Entonces se cuenta sobre el lote existente.
        existente = db.execute(
            "SELECT id FROM lotes WHERE producto_id = ? AND UPPER(TRIM(COALESCE(lote,''))) = ? "
            "AND estado <> 'rechazado' ORDER BY id DESC LIMIT 1",
            (prod["id"], lote_txt),
        ).fetchone()
        if existente:
            lote_id = existente["id"]
        else:
            # ¿Ya se había anotado este mismo lote nuevo en este conteo? -> se actualiza
            ya = db.execute(
                "SELECT id FROM conteo_lineas WHERE conteo_id = ? AND producto_id = ? "
                "AND lote_id IS NULL AND UPPER(COALESCE(lote,'')) = ?",
                (conteo_id, prod["id"], lote_txt),
            ).fetchone()
            if ya:
                db.execute("UPDATE conteo_lineas SET cantidad_contada = ?, vencimiento = ?, "
                           "costo_unitario = ?, contado_en = ?, contado_por = ?, "
                           "contado_por_nombre = ? WHERE id = ?",
                           (cantidad, vence or None, costo, ahora(), g.user["id"],
                            g.user["nombre"], ya["id"]))
                linea_id = ya["id"]
            else:
                cur = db.execute(
                    "INSERT INTO conteo_lineas (conteo_id, producto_id, lote_id, lote, vencimiento, "
                    "costo_unitario, cantidad_sistema, cantidad_contada, contado_en, contado_por, "
                    "contado_por_nombre) VALUES (?,?,NULL,?,?,?,0,?,?,?,?)",
                    (conteo_id, prod["id"], lote_txt or None, vence or None, costo, cantidad,
                     ahora(), g.user["id"], g.user["nombre"]),
                )
                linea_id = cur.lastrowid
            db.commit()
            return _respuesta_linea(conteo, linea_id)

    # ---- Caso C: lote que ya existe en el sistema ----
    lote = db.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    if lote is None or lote["estado"] == "rechazado":
        return _json_error("Ese lote no existe.")
    # Guardamos lo que dice el sistema AHORA (ver explicación al inicio del archivo)
    ya = db.execute("SELECT id FROM conteo_lineas WHERE conteo_id = ? AND lote_id = ?",
                    (conteo_id, lote_id)).fetchone()
    if ya:
        db.execute("UPDATE conteo_lineas SET cantidad_sistema = ?, cantidad_contada = ?, "
                   "costo_unitario = ?, contado_en = ?, contado_por = ?, contado_por_nombre = ? "
                   "WHERE id = ?",
                   (lote["cantidad_disponible"], cantidad, lote["costo_unitario"], ahora(),
                    g.user["id"], g.user["nombre"], ya["id"]))
        linea_id = ya["id"]
    else:
        cur = db.execute(
            "INSERT INTO conteo_lineas (conteo_id, producto_id, lote_id, lote, vencimiento, "
            "costo_unitario, cantidad_sistema, cantidad_contada, contado_en, contado_por, "
            "contado_por_nombre) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (conteo_id, lote["producto_id"], lote_id, lote["lote"], lote["vencimiento"],
             lote["costo_unitario"], lote["cantidad_disponible"], cantidad, ahora(),
             g.user["id"], g.user["nombre"]),
        )
        linea_id = cur.lastrowid
    db.commit()
    return _respuesta_linea(conteo, linea_id)


def _respuesta_linea(conteo, linea_id):
    ln = get_db().execute("SELECT * FROM conteo_lineas WHERE id = ?", (linea_id,)).fetchone()
    return jsonify({"ok": True, "linea": _linea_json(ln), "lote_id": ln["lote_id"],
                    "resumen": _resumen(conteo)})


@bp.route("/<int:conteo_id>/api/quitar", methods=["POST"])
@login_required
def api_quitar(conteo_id):
    """Borra lo anotado de un lote (por si se equivocaron de lote o de producto)."""
    conteo = _obtener(conteo_id)
    if conteo["estado"] != "abierto":
        return _json_error("Este conteo ya está cerrado.")
    linea_id = request.form.get("linea_id", "")
    if not linea_id.isdigit():
        return _json_error("Línea no válida.")
    db = get_db()
    db.execute("DELETE FROM conteo_lineas WHERE id = ? AND conteo_id = ?", (int(linea_id), conteo_id))
    db.commit()
    return jsonify({"ok": True, "resumen": _resumen(conteo)})


# =====================================================================
# Revisar diferencias, aplicar, anular y acta
# =====================================================================

def _lineas_detalle(conteo_id):
    return get_db().execute(
        "SELECT cl.*, p.codigo, p.nombre, p.concentracion, "
        "       (cl.cantidad_contada - cl.cantidad_sistema) AS diferencia "
        "FROM conteo_lineas cl JOIN productos p ON p.id = cl.producto_id "
        "WHERE cl.conteo_id = ? ORDER BY p.nombre COLLATE NOCASE, cl.vencimiento",
        (conteo_id,),
    ).fetchall()


@bp.route("/<int:conteo_id>/revisar")
@login_required
def revisar(conteo_id):
    conteo = _obtener(conteo_id)
    lineas = _lineas_detalle(conteo_id)
    con_diferencia = [l for l in lineas if abs(l["diferencia"]) > CERO]
    faltantes = [l for l in con_diferencia if l["diferencia"] < 0]
    # "Encontrados" = lotes que el sistema tenía en 0 (o no existían): es inventario
    # inicial, no un sobrante. Se muestran aparte para no confundir.
    encontrados = [l for l in con_diferencia if l["diferencia"] > 0 and l["cantidad_sistema"] <= CERO]
    sobrantes = [l for l in con_diferencia if l["diferencia"] > 0 and l["cantidad_sistema"] > CERO]

    # Lotes con existencias que nadie contó (al aplicar NO se tocan)
    sin_contar = []
    if conteo["estado"] == "abierto":
        sin_contar = get_db().execute(
            "SELECT l.lote, l.vencimiento, l.cantidad_disponible, p.nombre, p.concentracion "
            "FROM lotes l JOIN productos p ON p.id = l.producto_id "
            "WHERE l.cantidad_disponible > 0 AND l.estado <> 'rechazado' AND p.activo = 1"
            + _filtro_alcance(conteo) +
            " AND l.id NOT IN (SELECT lote_id FROM conteo_lineas WHERE conteo_id = ? "
            "                  AND lote_id IS NOT NULL) "
            "ORDER BY p.nombre COLLATE NOCASE LIMIT 200",
            (conteo_id,),
        ).fetchall()

    valor = lambda filas: sum(l["diferencia"] * l["costo_unitario"] for l in filas)
    return render_template(
        "conteos/revisar.html", conteo=conteo, lineas=lineas, faltantes=faltantes,
        sobrantes=sobrantes, encontrados=encontrados, sin_contar=sin_contar,
        resumen=_resumen(conteo), valor_faltantes=valor(faltantes),
        valor_sobrantes=valor(sobrantes), valor_encontrados=valor(encontrados),
    )


@bp.route("/<int:conteo_id>/aplicar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def aplicar(conteo_id):
    """Corrige todos los lotes contados de una sola vez. O se aplica TODO o NADA."""
    conteo = _obtener(conteo_id)
    if conteo["estado"] != "abierto":
        flash("Este conteo ya estaba cerrado.", "error")
        return redirect(url_for("conteos.revisar", conteo_id=conteo_id))

    db = get_db()
    referencia = f"Conteo {conteo['numero']}"
    ajustados = creados = 0
    db.execute("BEGIN IMMEDIATE")   # nadie más escribe mientras aplicamos (ni el POS)
    try:
        for ln in db.execute("SELECT * FROM conteo_lineas WHERE conteo_id = ? ORDER BY id",
                             (conteo_id,)).fetchall():
            diferencia = ln["cantidad_contada"] - ln["cantidad_sistema"]
            lote = None
            if ln["lote_id"]:
                lote = db.execute("SELECT * FROM lotes WHERE id = ?", (ln["lote_id"],)).fetchone()
            else:
                # Lote encontrado: por si una recepción lo creó mientras se contaba
                lote = db.execute(
                    "SELECT * FROM lotes WHERE producto_id = ? AND UPPER(TRIM(COALESCE(lote,''))) = ? "
                    "AND estado <> 'rechazado' ORDER BY id DESC LIMIT 1",
                    (ln["producto_id"], (ln["lote"] or "").upper()),
                ).fetchone()

            if lote is None:
                # ---- Crear el lote encontrado (así entra el inventario inicial) ----
                cur = db.execute(
                    "INSERT INTO lotes (producto_id, lote, vencimiento, cantidad_inicial, "
                    "cantidad_disponible, costo_unitario, estado, creado_en) "
                    "VALUES (?,?,?,?,?,?, 'disponible', ?)",
                    (ln["producto_id"], ln["lote"], ln["vencimiento"], ln["cantidad_contada"],
                     ln["cantidad_contada"], ln["costo_unitario"], ahora()),
                )
                lote_id, real, creados = cur.lastrowid, ln["cantidad_contada"], creados + 1
                obs = "Lote encontrado en el conteo físico"
            else:
                # ---- Ajustar un lote que ya existía ----
                lote_id = lote["id"]
                actual = lote["cantidad_disponible"]
                nueva = max(0.0, round(actual + diferencia, 4))
                real = round(nueva - actual, 4)
                if abs(real) > CERO:
                    estado = lote["estado"]
                    if nueva <= CERO and estado == "disponible":
                        estado = "agotado"
                    elif nueva > CERO and estado == "agotado":
                        estado = "disponible"
                    db.execute("UPDATE lotes SET cantidad_disponible = ?, estado = ?, "
                               "actualizado_en = ? WHERE id = ?", (nueva, estado, ahora(), lote_id))
                    ajustados += 1
                obs = (f"Conteo físico: sistema {ln['cantidad_sistema']:g}, "
                       f"contado {ln['cantidad_contada']:g}")

            if abs(real) > CERO:
                db.execute(
                    "INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, cantidad, "
                    "referencia, referencia_id, usuario_id, usuario_nombre, observaciones, creado_en) "
                    "VALUES (?,?,?, 'ajuste', ?,?,?,?,?,?,?)",
                    (ahora(), lote_id, ln["producto_id"], real, referencia, conteo_id,
                     g.user["id"], g.user["nombre"], obs, ahora()),
                )
            db.execute("UPDATE conteo_lineas SET lote_id = ?, diferencia_aplicada = ? WHERE id = ?",
                       (lote_id, real, ln["id"]))

        db.execute("UPDATE conteos SET estado = 'aplicado', aplicado_en = ?, aplicado_por = ?, "
                   "aplicado_por_nombre = ? WHERE id = ?",
                   (ahora(), g.user["id"], g.user["nombre"], conteo_id))
        db.commit()
    except Exception:
        db.rollback()
        raise

    registrar("conteo_aplicado", "conteos", conteo_id,
              f"{conteo['numero']}: {ajustados} lotes ajustados, {creados} lotes nuevos")
    flash(f"Conteo {conteo['numero']} aplicado: {ajustados} lotes ajustados y {creados} lotes nuevos.",
          "ok")
    return redirect(url_for("conteos.revisar", conteo_id=conteo_id))


@bp.route("/<int:conteo_id>/anular", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def anular(conteo_id):
    conteo = _obtener(conteo_id)
    motivo = (request.form.get("motivo") or "").strip()
    if conteo["estado"] != "abierto":
        flash("Solo se puede anular un conteo abierto.", "error")
    elif len(motivo) < 3:
        flash("Escribe el motivo para anular el conteo.", "error")
    else:
        db = get_db()
        db.execute("UPDATE conteos SET estado = 'anulado', observaciones = ? WHERE id = ?",
                   (motivo, conteo_id))
        db.commit()
        registrar("conteo_anulado", "conteos", conteo_id, f"{conteo['numero']} motivo={motivo}")
        flash(f"Conteo {conteo['numero']} anulado. No se cambió ningún lote.", "ok")
    return redirect(url_for("conteos.revisar", conteo_id=conteo_id))


@bp.route("/<int:conteo_id>/acta")
@login_required
def acta(conteo_id):
    """Acta del conteo en PDF: resumen, diferencias, lotes nuevos y firmas."""
    conteo = _obtener(conteo_id)
    lineas = _lineas_detalle(conteo_id)
    config = obtener_config()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.4 * cm, rightMargin=1.4 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                            title=f"Acta de toma de inventario {conteo['numero']}")
    est = getSampleStyleSheet()
    seccion = ParagraphStyle("s", parent=est["Heading3"], fontSize=10,
                             textColor=colors.HexColor("#0a4f8a"), spaceBefore=8, spaceAfter=4)
    normal = ParagraphStyle("n", parent=est["Normal"], fontSize=8.5, leading=11)
    celda = ParagraphStyle("c", parent=est["Normal"], fontSize=7.5, leading=9)

    borrador = " (BORRADOR — SIN APLICAR)" if conteo["estado"] == "abierto" else ""
    if conteo["estado"] == "anulado":
        borrador = " (ANULADO)"
    el = list(encabezado_pdf(config, f"ACTA DE TOMA DE INVENTARIO N° {conteo['numero']}{borrador}"))
    el.append(Spacer(1, 6))

    con_dif = [l for l in lineas if abs(l["diferencia"]) > CERO]
    # Separamos igual que en la pantalla de revisión
    faltantes = [l for l in con_dif if l["diferencia"] < 0]
    sobrantes = [l for l in con_dif if l["diferencia"] > 0 and l["cantidad_sistema"] > CERO]
    encontrados = [l for l in con_dif if l["diferencia"] > 0 and l["cantidad_sistema"] <= CERO]
    valor = lambda filas: sum(l["diferencia"] * l["costo_unitario"] for l in filas)
    # 1234.5 -> "$1.235"   y   -600 -> "-$600"
    peso = lambda v: ("-" if v < 0 else "") + "$" + f"{abs(v):,.0f}".replace(",", ".")
    # "2027-03-15" -> "15/03/2027"
    fecha = lambda f: f"{f[8:10]}/{f[5:7]}/{f[0:4]}" if f and len(f) >= 10 else "—"

    datos = [
        ["Alcance:", conteo["categoria"] or "Toda la droguería",
         "Estado:", conteo["estado"].capitalize()],
        ["Creado:", f"{fecha(conteo['creado_en'])} {conteo['creado_en'][11:16]} · "
                    f"{conteo['creado_por_nombre'] or '—'}",
         "Aplicado:", (f"{fecha(conteo['aplicado_en'])} {conteo['aplicado_en'][11:16]} · "
                       f"{conteo['aplicado_por_nombre'] or ''}") if conteo["aplicado_en"] else "—"],
        ["Lotes contados:", str(len(lineas)), "Con diferencia:", str(len(con_dif))],
        ["Faltantes (costo):", peso(valor(faltantes)), "Sobrantes (costo):", peso(valor(sobrantes))],
        ["Encontrados (costo):", peso(valor(encontrados)), "", ""],
    ]
    t = Table(datos, colWidths=[3.2 * cm, 5.8 * cm, 3.2 * cm, 5.8 * cm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8.5),
                           ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555")),
                           ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#555"))]))
    el.append(t)
    if conteo["descripcion"]:
        el.append(Paragraph(f"<b>Descripción:</b> {conteo['descripcion']}", normal))

    def tabla(titulo, filas):
        el.append(Paragraph(titulo, seccion))
        if not filas:
            el.append(Paragraph("Ninguno.", normal))
            return
        cuerpo = [["Producto", "Lote", "Vence", "Sistema", "Contado", "Dif.", "Valor"]]
        for l in filas:
            cuerpo.append([
                Paragraph(f"{l['nombre']} {l['concentracion'] or ''}", celda),
                l["lote"] or "—", fecha(l["vencimiento"]),
                f"{l['cantidad_sistema']:g}", f"{l['cantidad_contada']:g}",
                f"{l['diferencia']:+g}", peso(l["diferencia"] * l["costo_unitario"]),
            ])
        tb = Table(cuerpo, colWidths=[6.4 * cm, 2.2 * cm, 2 * cm, 1.6 * cm, 1.6 * cm, 1.4 * cm, 2.6 * cm],
                   repeatRows=1)
        tb.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f1fb")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0a4f8a")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cfd8e0")),
            ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        el.append(tb)

    tabla("FALTANTES (hay menos de lo que decía el sistema)", faltantes)
    tabla("SOBRANTES (hay más de lo que decía el sistema)", sobrantes)
    tabla("LOTES ENCONTRADOS / INVENTARIO INICIAL", encontrados)

    # Firmas
    el.append(Spacer(1, 26))
    regente = config.get("regente_nombre") or "—"
    firmas = Table([
        ["__________________________________", "__________________________________"],
        [conteo["creado_por_nombre"] or "Responsable del conteo", regente],
        ["Responsable del conteo", "Director Técnico / Regente de Farmacia"],
        ["", f"Tarjeta profesional: {config.get('regente_tarjeta') or '—'}"],
    ], colWidths=[9 * cm, 9 * cm])
    firmas.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    el.append(firmas)

    doc.build(el)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                     download_name=f"Acta_conteo_{conteo['numero']}.pdf")
