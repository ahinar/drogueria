"""Recepción técnica: ingreso de mercancía, cuarentena, aprobación, PDF."""
import json
import os
import sqlite3
from datetime import datetime
from io import BytesIO
from .pdf_utils import encabezado_pdf, pie_de_pagina

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect,
                   render_template, request, send_file, url_for)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .audit import registrar
from .auth import login_required, roles_required
from .configuracion import obtener_config
from .db import ahora, get_db
from . import presentaciones as pres

bp = Blueprint("recepciones", __name__, url_prefix="/recepciones")

ESTADOS = {
    "borrador": "Borrador",
    "cuarentena": "En cuarentena",
    "aprobada": "Aprobada",
    "rechazada": "Rechazada",
}
EMPAQUES = {"bueno": "Bueno", "dañado": "Dañado", "roto": "Roto", "otro": "Otro"}
RESULTADOS = {"aceptado": "Aceptado", "cuarentena": "Cuarentena", "rechazado": "Rechazado"}


# ---------- Helpers ----------

def _siguiente_numero():
    db = get_db()
    fila = db.execute(
        "SELECT numero FROM recepciones WHERE numero LIKE 'REC-%' "
        "ORDER BY CAST(SUBSTR(numero, 5) AS INTEGER) DESC LIMIT 1"
    ).fetchone()
    if fila is None:
        return "REC-0001"
    try:
        n = int(fila["numero"][4:]) + 1
    except ValueError:
        return "REC-0001"
    return f"REC-{n:04d}"


def _obtener(rec_id):
    fila = get_db().execute("SELECT * FROM recepciones WHERE id = ?", (rec_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def _lineas_de(rec_id):
    return get_db().execute(
        "SELECT rl.*, "
        "p.codigo AS producto_codigo, p.nombre AS producto_nombre, "
        "p.registro_sanitario AS producto_registro, p.maneja_vencimiento, "
        "p.concentracion, p.cadena_frio, p.control_especial, p.requiere_formula, "
        "p.codigo_barras, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS lab_nombre, "
        "(SELECT nombre FROM catalogos WHERE id = p.forma_farmaceutica_id) AS forma_nombre, "
        "COALESCE((SELECT GROUP_CONCAT(c.nombre, ' + ') FROM (SELECT c2.nombre FROM producto_principios pp2 JOIN catalogos c2 ON c2.id = pp2.catalogo_id WHERE pp2.producto_id = p.id ORDER BY pp2.orden) c), (SELECT nombre FROM catalogos WHERE id = p.principio_id)) AS principio_nombre, "
        "(SELECT nombre FROM unidades_medida WHERE id = p.unidad_venta_id) AS unidad_nombre "
        "FROM recepcion_lineas rl JOIN productos p ON p.id = rl.producto_id "
        "WHERE rl.recepcion_id = ? ORDER BY rl.id",
        (rec_id,),
    ).fetchall()


def _productos():
    return get_db().execute(
        "SELECT p.id, p.codigo, p.nombre, p.concentracion, p.maneja_vencimiento, "
        "p.cadena_frio, p.control_especial, p.registro_sanitario, p.registro_vence, "
        "p.precio_venta, p.codigo_barras, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS lab_nombre, "
        "(SELECT nombre FROM catalogos WHERE id = p.forma_farmaceutica_id) AS forma_nombre, "
        "(SELECT nombre FROM unidades_medida WHERE id = p.unidad_venta_id) AS unidad_nombre "
        "FROM productos p WHERE p.activo = 1 ORDER BY p.nombre COLLATE ES"
    ).fetchall()


def _proveedores():
    return get_db().execute(
        "SELECT id, nit, razon_social, plazo_dias FROM proveedores WHERE activo = 1 "
        "ORDER BY razon_social COLLATE ES"
    ).fetchall()


def _unidades():
    # "Unidad" primero y después por tamaño (Sello x 4, Caja x 10, Sello x 10...): app/nombres.py
    from .nombres import orden_unidades
    return orden_unidades(get_db().execute(
        "SELECT id, nombre, cantidad FROM unidades_medida WHERE activo = 1").fetchall())


def _laboratorios():
    return get_db().execute(
        "SELECT id, nombre FROM catalogos WHERE tipo = 'laboratorio' AND activo = 1 "
        "ORDER BY nombre COLLATE ES"
    ).fetchall()


def _catalogo(tipo):
    return get_db().execute(
        "SELECT id, nombre FROM catalogos WHERE tipo = ? AND activo = 1 ORDER BY nombre COLLATE ES",
        (tipo,)).fetchall()


def _contexto_form(rec=None):
    return {
        "proveedores": _proveedores(),
        "productos": _productos(),
        "unidades": _unidades(),
        "laboratorios": _laboratorios(),
        # Para la ventana "Completar datos" de cada línea (datos técnicos del producto)
        "principios": _catalogo("principio"),
        "formas": _catalogo("forma_farmaceutica"),
        "estados": ESTADOS,
        "empaques": EMPAQUES,
        "resultados": RESULTADOS,
        # Versión 1.1.7: de dónde puede salir la plata si la factura se paga de contado
        "origenes_pago": __import__("app.cuentas_pagar", fromlist=["ORIGENES"]).ORIGENES,
        "numero_sugerido": _siguiente_numero() if not rec else None,
        "recepcion": rec,
        "lineas": _lineas_de(rec["id"]) if rec else [],
    }


def _guardar_foto(archivo, rec_id):
    if not archivo or not archivo.filename:
        return None
    ext = os.path.splitext(archivo.filename)[1].lower()
    # Versión 1.1.8: una foto ".jfif" (o .jpe, .pjpeg, .pjp) es una foto JPG con otro
    # nombre (así las guarda Windows al bajarlas de internet): se guarda como ".jpg".
    from .utils_imagenes import EXT_JPG_OTROS
    if ext in EXT_JPG_OTROS:
        ext = ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".pdf"):
        return None
    from .utils_imagenes import carpeta_uploads
    destino_dir = os.path.join(str(carpeta_uploads()), "recepciones")
    os.makedirs(destino_dir, exist_ok=True)
    ruta = os.path.join(destino_dir, f"{rec_id}{ext}")
    archivo.save(ruta)
    return f"uploads/recepciones/{rec_id}{ext}"


def _lineas_previas_formulario(form=None):
    """Lee las líneas del formulario tal cual (sin validar) para repintarlas al fallar.

    form: de dónde se leen. Por defecto, lo que llegó del navegador (request.form).
    Versión 1.1.8: también puede ser una recepción EN ESPERA (lo guardado otro día).
    """
    form = request.form if form is None else form
    prod_ids = form.getlist("linea_producto_id")
    lotes = form.getlist("linea_lote")
    vencimientos = form.getlist("linea_vencimiento")
    cant_rec = form.getlist("linea_cantidad_recibida")
    costos = form.getlist("linea_costo")
    temps_ing = form.getlist("linea_temperatura_ingreso")
    empaques = form.getlist("linea_empaque")
    resultados = form.getlist("linea_resultado")
    motivos = form.getlist("linea_motivo")
    presentaciones = form.getlist("linea_presentacion")
    factores_otros = form.getlist("linea_factor_otro")
    ivas = form.getlist("linea_iva")            # IVA % de cada línea (versión 1.1.6)

    db = get_db()
    lineas = []
    for i, pid in enumerate(prod_ids):
        if not pid or not pid.isdigit():
            continue
        p = db.execute(
            "SELECT codigo, nombre, concentracion, registro_sanitario, registro_vence, "
            "maneja_vencimiento, cadena_frio, control_especial "
            "FROM productos WHERE id = ?", (int(pid),)
        ).fetchone()
        if p is None:
            continue

        def v(lista, idx):
            return lista[idx] if idx < len(lista) else ""

        lineas.append({
            "producto_id": int(pid),
            "producto_codigo": p["codigo"],
            "producto_nombre": p["nombre"],
            "concentracion": p["concentracion"] or "",
            "registro_sanitario": p["registro_sanitario"] or "",
            "registro_vence": p["registro_vence"] or "",
            "maneja_vencimiento": p["maneja_vencimiento"],
            "cadena_frio": p["cadena_frio"],
            "control_especial": p["control_especial"],
            "lote": v(lotes, i),
            "vencimiento": v(vencimientos, i),
            "cantidad_recibida": v(cant_rec, i) or "0",
            "costo_unitario": v(costos, i) or "0",
            "iva_tarifa": v(ivas, i) or "0",
            "temperatura_ingreso": v(temps_ing, i),
            "estado_empaque": v(empaques, i) or "bueno",
            "resultado": v(resultados, i) or "aceptado",
            "motivo_rechazo": v(motivos, i),
            # "otra" = una caja que no está en la ficha, con su "cuántas trae" escrito
            # "u12" = una unidad de medida cualquiera (CAJA X 12) que no está en la ficha
            "presentacion_id": (int(v(presentaciones, i)) if v(presentaciones, i).isdigit()
                                else v(presentaciones, i) if (v(presentaciones, i) == "otra"
                                                              or v(presentaciones, i).startswith("u")) else 0),
            "factor_otro": v(factores_otros, i),
            "presentaciones": _presentaciones_simples(int(pid)),
        })
    return lineas


def _presentacion_por_unidad(producto_id, unidad_id):
    """"Viene en" una unidad de medida cualquiera (ej. CAJA X 12).

    Si el producto ya la tiene como presentación, se usa ese "cuántas trae".
    Si no: cantidad de la unidad ÷ cantidad de la unidad del inventario
    (CAJA X 12 sobre Unidad -> 12). Devuelve {nombre, factor} o None.
    """
    db = get_db()
    u = db.execute("SELECT id, nombre, cantidad FROM unidades_medida WHERE id = ?", (unidad_id,)).fetchone()
    if u is None:
        return None
    propia = db.execute("SELECT factor FROM producto_presentaciones WHERE producto_id = ? AND unidad_id = ?",
                        (producto_id, unidad_id)).fetchone()
    if propia:
        return {"nombre": u["nombre"], "factor": float(propia["factor"])}
    base = db.execute("SELECT um.id, um.nombre, um.cantidad FROM productos p JOIN unidades_medida um "
                      "ON um.id = p.unidad_venta_id WHERE p.id = ?", (producto_id,)).fetchone()
    if base and base["id"] == unidad_id:
        return {"nombre": u["nombre"], "factor": 1.0}
    cant_base = pres.cantidad_efectiva(base["nombre"], base["cantidad"]) if base else 1.0
    return {"nombre": u["nombre"], "factor": round(pres.cantidad_efectiva(u["nombre"], u["cantidad"]) / cant_base, 4)}


def _leer_lineas_formulario():
    """Lee y valida las líneas."""
    prod_ids = request.form.getlist("linea_producto_id")
    lotes = request.form.getlist("linea_lote")
    vencimientos = request.form.getlist("linea_vencimiento")
    cant_rec = request.form.getlist("linea_cantidad_recibida")
    costos = request.form.getlist("linea_costo")
    temps_ing = request.form.getlist("linea_temperatura_ingreso")
    empaques = request.form.getlist("linea_empaque")
    resultados = request.form.getlist("linea_resultado")
    motivos = request.form.getlist("linea_motivo")
    obs_lineas = request.form.getlist("linea_observaciones")
    # "Viene en": id de la presentación (0 = unidad de inventario, otro = sobre, caja...)
    presentaciones = request.form.getlist("linea_presentacion")
    # Si escogieron "Otra caja…": cuántas unidades trae esa caja (ej. 300)
    factores_otros = request.form.getlist("linea_factor_otro")
    # ---- IVA (versión 1.1.6) ----
    # linea_iva = % de IVA de cada línea (0, 5, 19...). precios_con_iva = la factura
    # ya trae el IVA dentro del costo. declara_iva (Configuración) decide qué costo
    # se usa para la utilidad: con IVA (no declara) o sin IVA (sí declara).
    ivas = request.form.getlist("linea_iva")
    precios_con_iva = bool(request.form.get("precios_con_iva"))
    from .configuracion import obtener_config
    declara_iva = obtener_config().get("declara_iva") == "si"

    lineas, errores = [], []
    for i, pid in enumerate(prod_ids):
        if not pid or not pid.isdigit():
            continue

        def v(lista, idx):
            return lista[idx] if idx < len(lista) else ""

        try:
            cr = float(v(cant_rec, i).replace(",", ".") or 0)
        except ValueError:
            cr = 0
        try:
            co = float(v(costos, i).replace(",", ".") or 0)
        except ValueError:
            co = 0

        try:
            t_ing = float(v(temps_ing, i).replace(",", ".")) if v(temps_ing, i) else None
        except ValueError:
            t_ing = None

        # ---- VALIDACIONES (reglas del proyecto) ----
        # Buscamos el producto para saber su nombre y si maneja vencimiento.
        prod = get_db().execute(
            "SELECT nombre, maneja_vencimiento FROM productos WHERE id = ?", (int(pid),)
        ).fetchone()
        nombre = prod["nombre"] if prod else f"producto {pid}"
        resultado_linea = v(resultados, i) or "aceptado"
        lote_txt = v(lotes, i).strip()
        venc_txt = v(vencimientos, i).strip()

        if prod is None:
            errores.append(f"El producto {pid} no existe.")
        if cr <= 0:
            errores.append(f"{nombre}: la cantidad recibida debe ser mayor a cero.")
        if co <= 0:
            errores.append(f"{nombre}: el costo unitario debe ser mayor a cero.")
        # Si el producto maneja vencimiento, lote y fecha son obligatorios.
        if prod and prod["maneja_vencimiento"] and (not lote_txt or not venc_txt):
            errores.append(f"{nombre}: debes indicar el lote y la fecha de vencimiento.")
        # La fecha debe tener formato AAAA-MM-DD (así la entrega el calendario del formulario).
        if venc_txt:
            try:
                datetime.strptime(venc_txt, "%Y-%m-%d")
            except ValueError:
                errores.append(f"{nombre}: la fecha de vencimiento no es válida.")

        # ---- PRESENTACIÓN EN QUE LLEGÓ (ej: 3 Caja x 100 a $25.000 c/u) ----
        # Se guarda TODO en unidades de inventario: 3 cajas x 100 = 300 tabletas
        # y el costo por tableta = $25.000 / 100 = $250. Así el resto del
        # programa (lotes, kardex, utilidades) sigue igual.
        pres_txt = v(presentaciones, i)
        # La UdM ("Viene en") es obligatoria (versión 1.1.3). La pantalla siempre
        # manda este campo; si no llegó ninguno (formularios viejos), se usa la unidad.
        if presentaciones and pres_txt in ("", "nueva"):
            errores.append(f"{nombre}: escoge en qué unidad llegó (UdM).")
        if pres_txt == "otra":
            # Caja que no está en la ficha (hoy llegó x 300, otro día x 100)
            try:
                factor_otro = float(v(factores_otros, i).replace(",", ".") or 0)
            except ValueError:
                factor_otro = 0
            if factor_otro <= 1:
                errores.append(f"{nombre}: escribe cuántas unidades trae la caja (más de 1).")
                factor_otro = 1
            presentacion = {"nombre": f"Caja x {factor_otro:g}", "factor": factor_otro}
        elif pres_txt.startswith("u") and pres_txt[1:].isdigit():
            # Cualquier unidad de medida (ej. "CAJA X 12"), aunque no esté en la ficha:
            # así lo pidió Fernando. Cuántas trae sale de la unidad.
            presentacion = _presentacion_por_unidad(int(pid), int(pres_txt[1:]))
            if presentacion is None:
                errores.append(f"{nombre}: esa unidad no existe.")
            elif presentacion["factor"] < 1:
                errores.append(f"{nombre}: la unidad {presentacion['nombre']} es más pequeña que la del inventario.")
        else:
            presentacion = pres.presentacion_para_vender(int(pid), int(pres_txt)) if pres_txt.isdigit() else None
        if presentacion is None:
            presentacion = {"nombre": None, "factor": 1}
        factor = float(presentacion["factor"] or 1)

        # IVA de la línea y los dos costos (por unidad de inventario)
        try:
            iva = float(v(ivas, i).replace(",", ".") or 0)
        except ValueError:
            iva = 0.0
        if not 0 <= iva <= 100:
            errores.append(f"{nombre}: el IVA debe estar entre 0 y 100 %.")
            iva = 0.0
        tasa = iva / 100
        costo_sin = co / (1 + tasa) if precios_con_iva else co      # por la unidad en que llegó (caja)
        costo_con = costo_sin * (1 + tasa)

        lineas.append({
            "producto_id": int(pid),
            "iva_tarifa": iva,
            "costo_sin_iva": costo_sin / factor,
            "costo_con_iva": costo_con / factor,
            "lote": v(lotes, i).strip() or None,
            "vencimiento": v(vencimientos, i).strip() or None,
            "cantidad_facturada": round(cr * factor, 4),
            "cantidad_recibida": round(cr * factor, 4),
            # Costo para la UTILIDAD: con IVA si no declara IVA; sin IVA si lo declara
            "costo_unitario": (costo_sin if declara_iva else costo_con) / factor,
            "presentacion": presentacion["nombre"] if factor != 1 else None,
            "factor": factor,
            "temperatura_ingreso": t_ing,
            "estado_empaque": v(empaques, i) or "bueno",
            "resultado": v(resultados, i) or "aceptado",
            "motivo_rechazo": v(motivos, i).strip() or None,
            "observaciones": v(obs_lineas, i).strip() or None,
        })
    return lineas, errores


# ---------- Lista ----------

@bp.route("/")
@login_required
def lista():
    q = request.args.get("q", "").strip()
    filtro = request.args.get("filtro", "")
    sql = (
        "SELECT r.*, p.razon_social AS proveedor_nombre "
        "FROM recepciones r JOIN proveedores p ON p.id = r.proveedor_id"
    )
    cond, params = [], []
    if filtro and filtro in ESTADOS:
        cond.append("r.estado = ?")
        params.append(filtro)
    if q:
        cond.append("(r.numero LIKE ? OR r.factura_numero LIKE ? OR p.razon_social LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY r.id DESC LIMIT 200"
    filas = get_db().execute(sql, params).fetchall()
    # Versión 1.1.8: las recepciones EN ESPERA (a medias) van arriba, con "Continuar"
    en_espera = get_db().execute(
        "SELECT e.*, p.razon_social AS proveedor_nombre FROM recepciones_espera e "
        "LEFT JOIN proveedores p ON p.id = e.proveedor_id "
        "ORDER BY COALESCE(e.actualizado_en, e.creado_en) DESC").fetchall()
    return render_template("recepciones/lista.html", filas=filas, q=q, filtro=filtro,
                           estados=ESTADOS, en_espera=en_espera)


# ---------- Nueva ----------

@bp.route("/nueva", methods=["GET", "POST"])
@login_required
def nueva():
    if request.method == "POST":
        # Versión 1.1.8: si esta recepción venía "en espera", aquí llega su número
        # (campo oculto espera_id). Al guardarla de verdad, la espera se borra.
        espera_id = request.form.get("espera_id", "").strip()
        espera_id = int(espera_id) if espera_id.isdigit() else None
        # Botón "Guardar en espera": guarda lo escrito hasta ahora SIN revisar nada
        # y SIN tocar el inventario. Se sigue después con "Continuar".
        if request.form.get("accion") == "espera":
            return _guardar_en_espera(espera_id)
        # Versión 1.1.9: si esta pantalla ya confirmó su recepción (doble clic, o
        # volver atrás y darle otra vez), no se crea una segunda recepción igual.
        token = _token_de(request.form)
        ya = _ya_confirmada(token)
        if ya:
            flash(f"Esa recepción ya estaba confirmada: {ya['numero']}.", "ok")
            return redirect(url_for("recepciones.ver", rec_id=ya["id"]))

        proveedor_id = request.form.get("proveedor_id", "").strip()
        factura = request.form.get("factura_numero", "").strip() or None
        remision = request.form.get("remision_numero", "").strip() or None
        temperatura = request.form.get("temperatura_llegada", "").strip()
        observaciones = request.form.get("observaciones", "").strip() or None
        numero = request.form.get("numero", "").strip() or _siguiente_numero()

        lineas, errores = _leer_lineas_formulario()
        error_cabecera = None

        # Pago de la factura (versión 1.1.7): a crédito (con vencimiento) o de contado
        pago_modo = request.form.get("pago_modo", "credito")
        pago_vence = request.form.get("pago_vence", "").strip()
        pago_origen = request.form.get("pago_origen", "").strip()
        from .cuentas_pagar import ORIGENES as ORIGENES_PAGO, registrar_pago, total_de_lineas
        caja_abierta = get_db().execute("SELECT 1 FROM cajas WHERE estado = 'abierta'").fetchone()

        if not factura and not remision:
            error_cabecera = "Debes indicar el número de factura o el número de remisión."
        elif not lineas:
            error_cabecera = "Debes agregar al menos una línea."
        elif errores:
            # Todos los errores de una vez (versión 1.1.3). Antes solo salía el primero:
            # se corregía y al guardar aparecía el siguiente.
            error_cabecera = errores[0] if len(errores) == 1 else errores
        elif pago_modo == "contado" and pago_origen not in ORIGENES_PAGO:
            error_cabecera = "La factura es de contado: escoge de dónde salió la plata."
        elif pago_modo == "contado" and pago_origen == "caja_pos" and not caja_abierta:
            error_cabecera = "No hay caja del POS abierta: escoge otro lugar de donde salió la plata."

        if not error_cabecera:
            db = get_db()
            try:
                temp_llegada = None
                if temperatura:
                    try:
                        temp_llegada = float(temperatura.replace(",", "."))
                    except ValueError:
                        pass

                cur = db.execute(
                    "INSERT INTO recepciones (numero, fecha, proveedor_id, factura_numero, "
                    "remision_numero, temperatura_llegada, estado, recibido_por, "
                    "recibido_por_nombre, observaciones, creado_en, precios_con_iva) "
                    "VALUES (?,?,?,?,?,?, 'cuarentena', ?, ?, ?, ?, ?)",
                    (numero, ahora(), int(proveedor_id), factura, remision, temp_llegada,
                     g.user["id"], g.user["nombre"], observaciones, ahora(),
                     1 if request.form.get("precios_con_iva") else 0),
                )
                rec_id = cur.lastrowid

                for l in lineas:
                    db.execute(
                        "INSERT INTO recepcion_lineas (recepcion_id, producto_id, lote, vencimiento, "
                        "cantidad_facturada, cantidad_recibida, costo_unitario, estado_empaque, "
                        "resultado, motivo_rechazo, observaciones, temperatura_ingreso, presentacion, factor, "
                        "iva_tarifa, costo_sin_iva, costo_con_iva) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (rec_id, l["producto_id"], l["lote"], l["vencimiento"],
                         l["cantidad_facturada"], l["cantidad_recibida"], l["costo_unitario"],
                         l["estado_empaque"], l["resultado"], l["motivo_rechazo"],
                         l["observaciones"], l["temperatura_ingreso"], l["presentacion"], l["factor"],
                         l["iva_tarifa"], l["costo_sin_iva"], l["costo_con_iva"]),
                    )

                # ---- Pago de la factura (versión 1.1.7) ----
                total_pagar = total_de_lineas(lineas)
                if total_pagar <= 0:
                    estado_pago, vence = "no_aplica", None
                elif pago_modo == "contado":
                    estado_pago, vence = "pagada", None
                else:
                    # Sin fecha escrita: hoy + el plazo del proveedor (30 días si no tiene)
                    if not pago_vence:
                        from .cuentas_pagar import vence_sugerido
                        plazo = db.execute("SELECT plazo_dias FROM proveedores WHERE id = ?",
                                           (int(proveedor_id),)).fetchone()
                        pago_vence = vence_sugerido(ahora(), (plazo["plazo_dias"] if plazo else 0) or 30)
                    estado_pago, vence = "pendiente", pago_vence
                db.execute("UPDATE recepciones SET total_pagar = ?, pago_estado = ?, pago_vence = ?, "
                           "borrador_token = ? WHERE id = ?", (total_pagar, estado_pago, vence, token, rec_id))
                if estado_pago == "pagada":
                    rec_fila = db.execute("SELECT * FROM recepciones WHERE id = ?", (rec_id,)).fetchone()
                    _, error_pago = registrar_pago(db, rec_fila, total_pagar, ahora(), pago_origen,
                                                   "Pagada de contado al recibir")
                    if error_pago:
                        raise ValueError(error_pago)
                # Versión 1.1.8: la recepción venía "en espera": ya quedó guardada de
                # verdad, así que la espera se borra (en el mismo commit: o todo o nada).
                # (1.1.9: también la que guardó el guardado automático, por su clave)
                db.execute("DELETE FROM recepciones_espera WHERE id = ? OR (token IS NOT NULL AND token = ?)",
                           (espera_id or 0, token or ""))
                db.commit()

                archivo = request.files.get("foto")
                if archivo and archivo.filename:
                    ruta = _guardar_foto(archivo, rec_id)
                    if ruta:
                        db.execute("UPDATE recepciones SET foto_ruta = ? WHERE id = ?", (ruta, rec_id))
                        db.commit()

                registrar("recepcion_creada", "recepciones", rec_id,
                          f"numero={numero} proveedor={proveedor_id}"
                          + (f" (venía en espera #{espera_id})" if espera_id else ""))
                flash(f"Recepción {numero} CONFIRMADA. Quedó en cuarentena, pendiente de aprobación.", "ok")
                return redirect(url_for("recepciones.ver", rec_id=rec_id))
            except Exception as e:
                db.rollback()          # que no quede nada a medias (ni la recepción ni el pago)
                error_cabecera = f"Error al guardar: {e}"

        valores_previos = {
            "numero": numero,
            "proveedor_id": proveedor_id,
            "factura_numero": factura or "",
            "remision_numero": remision or "",
            "temperatura_llegada": temperatura,
            "observaciones": observaciones or "",
            "precios_con_iva": bool(request.form.get("precios_con_iva")),
            "pago_modo": pago_modo, "pago_vence": pago_vence, "pago_origen": pago_origen,
        }
        return render_template(
            "recepciones/form.html",
            **_contexto_form(),
            error_cabecera=error_cabecera,
            valores_previos=valores_previos,
            lineas_previas=_lineas_previas_formulario(),
            espera=_espera_o_none(espera_id),
            borrador_token=token or _token_nuevo(),
        )

    # ---- Versión 1.1.8: CONTINUAR una recepción que quedó en espera ----
    # /recepciones/nueva?espera=3 abre el formulario con todo lo que se había escrito.
    espera_txt = request.args.get("espera", "")
    if espera_txt.isdigit():
        fila = _espera_o_none(int(espera_txt))
        if fila is None:
            flash("Esa recepción en espera ya no existe (quizá ya se terminó o se descartó).", "error")
            return redirect(url_for("recepciones.lista"))
        form = _form_de_espera(fila)
        # Las abiertas de la versión 1.1.8 no tenían clave: se les pone una
        token = fila["token"]
        if not token:
            token = _token_nuevo()
            get_db().execute("UPDATE recepciones_espera SET token = ? WHERE id = ?", (token, fila["id"]))
            get_db().commit()
        return render_template(
            "recepciones/form.html",
            **_contexto_form(),
            valores_previos=_valores_previos(form),
            lineas_previas=_lineas_previas_formulario(form),
            espera=fila,
            borrador_token=token,
        )
    return render_template("recepciones/form.html", **_contexto_form(), borrador_token=_token_nuevo())


def _token_nuevo():
    """Clave al azar para una pantalla de recepción nueva (ej. '9f2c41d07ab35e10')."""
    import secrets
    return secrets.token_hex(8)


# ---------- Versión 1.1.8: RECEPCIONES EN ESPERA (desde la 1.1.9: «ABIERTAS») ----------
# Desde la 1.1.9 funciona como el conteo de inventario: la recepción queda ABIERTA
# y se GUARDA SOLA mientras se recibe (api_borrador, más abajo). En la lista sale
# «Continuar recibiendo» y solo se cierra al darle «Confirmar recepción».
# Cómo funciona (para aprender):
#   1. En el formulario, el botón "Guardar en espera" manda TODO lo escrito.
#   2. _guardar_en_espera() lo convierte en texto JSON y lo guarda en la tabla
#      recepciones_espera (no en "recepciones": todavía no es una recepción).
#      No se revisa nada (puede haber líneas a medias) y no se toca el inventario.
#   3. En Recepciones aparece la lista "En espera" con el botón "Continuar".
#   4. Continuar abre /recepciones/nueva?espera=ID: _form_de_espera() vuelve a
#      armar el formulario con lo guardado y la pantalla lo pinta igualito.
#   5. Al darle "Guardar recepción" se crea la recepción normal (cuarentena,
#      Acta, pago...) y la espera se borra.

def _espera_o_none(espera_id):
    """La fila de recepciones_espera con ese id (o None si no hay)."""
    if not espera_id:
        return None
    return get_db().execute(
        "SELECT e.*, p.razon_social AS proveedor_nombre FROM recepciones_espera e "
        "LEFT JOIN proveedores p ON p.id = e.proveedor_id WHERE e.id = ?", (espera_id,)).fetchone()


def _form_de_espera(fila):
    """Vuelve a armar el formulario (con varias líneas) a partir del JSON guardado.

    Se guarda así: {"linea_lote": ["L1", "L2"], "proveedor_id": ["3"], ...}
    (cada campo con la lista de sus valores, porque las líneas repiten el nombre).
    MultiDict es el mismo tipo de objeto que request.form: así el resto del
    código lo lee igual que si acabara de llegar del navegador.
    """
    from werkzeug.datastructures import MultiDict
    try:
        datos = json.loads(fila["datos"] or "{}")
    except ValueError:
        datos = {}
    return MultiDict([(campo, valor) for campo, valores in datos.items() for valor in valores])


def _valores_previos(form):
    """Los datos generales (proveedor, factura, pago...) para volver a pintarlos."""
    numero = (form.get("numero") or "").strip()
    # Mientras estuvo en espera pudieron guardarse otras recepciones: si su número
    # ya lo tiene otra, se le pone el siguiente libre.
    if not numero or get_db().execute("SELECT 1 FROM recepciones WHERE numero = ?", (numero,)).fetchone():
        numero = _siguiente_numero()
    return {
        "numero": numero,
        "proveedor_id": (form.get("proveedor_id") or "").strip(),
        "factura_numero": (form.get("factura_numero") or "").strip(),
        "remision_numero": (form.get("remision_numero") or "").strip(),
        "temperatura_llegada": (form.get("temperatura_llegada") or "").strip(),
        "observaciones": (form.get("observaciones") or "").strip(),
        "precios_con_iva": bool(form.get("precios_con_iva")),
        "pago_modo": form.get("pago_modo", "credito"),
        "pago_vence": (form.get("pago_vence") or "").strip(),
        "pago_origen": (form.get("pago_origen") or "").strip(),
    }


def _token_de(form):
    """La clave al azar de la pantalla de recepción (versión 1.1.9, ver migración 40)."""
    return (form.get("borrador_token") or "").strip()[:40] or None


def _ya_confirmada(token):
    """La recepción que ya se confirmó desde esta misma pantalla (o None)."""
    if not token:
        return None
    return get_db().execute("SELECT id, numero FROM recepciones WHERE borrador_token = ?", (token,)).fetchone()


def _guardar_borrador(form, espera_id, token):
    """Guarda lo escrito como recepción ABIERTA (sin confirmar). No hace commit.

    Versión 1.1.9: lo usan el botón «Guardar y seguir después» y el guardado
    AUTOMÁTICO que hace la pantalla mientras se va recibiendo.
    Devuelve (id de la recepción abierta, número de líneas), o (None, 0) si no
    hay nada escrito todavía (ni proveedor, ni factura, ni productos).
    """
    # Todos los campos con todos sus valores (las líneas repiten nombre), menos los
    # de control: la clave de seguridad (_csrf), el botón y el número de la espera.
    datos = {campo: form.getlist(campo) for campo in form.keys()
             if campo not in ("_csrf", "accion", "espera_id")}
    total_lineas = sum(1 for pid in form.getlist("linea_producto_id") if pid.strip().isdigit())
    proveedor = (form.get("proveedor_id") or "").strip()
    proveedor = int(proveedor) if proveedor.isdigit() else None
    factura = ((form.get("factura_numero") or "").strip()
               or (form.get("remision_numero") or "").strip() or None)
    if not total_lineas and not proveedor and not factura:
        return None, 0

    db = get_db()
    texto = json.dumps(datos, ensure_ascii=False)
    # ¿Ya existe esta recepción abierta? Por su número, o por la clave de la pantalla
    # (si el primer guardado automático todavía no le había avisado el número).
    fila = _espera_o_none(espera_id) if espera_id else None
    if fila is None and token:
        fila = db.execute("SELECT * FROM recepciones_espera WHERE token = ?", (token,)).fetchone()
    if fila is not None:
        db.execute("UPDATE recepciones_espera SET proveedor_id = ?, factura_numero = ?, total_lineas = ?, "
                   "datos = ?, token = COALESCE(token, ?), actualizado_por_nombre = ?, actualizado_en = ? "
                   "WHERE id = ?",
                   (proveedor, factura, total_lineas, texto, token, g.user["nombre"], ahora(), fila["id"]))
        return fila["id"], total_lineas
    cur = db.execute("INSERT INTO recepciones_espera (proveedor_id, factura_numero, total_lineas, datos, "
                     "token, creado_por, creado_por_nombre, creado_en) VALUES (?,?,?,?,?,?,?,?)",
                     (proveedor, factura, total_lineas, texto, token, g.user["id"], g.user["nombre"], ahora()))
    return cur.lastrowid, total_lineas


def _guardar_en_espera(espera_id):
    """Botón «Guardar y seguir después»: guarda la recepción ABIERTA y vuelve a la lista."""
    token = _token_de(request.form)
    ya = _ya_confirmada(token)
    if ya:
        flash(f"Esta recepción ya se había confirmado ({ya['numero']}).", "ok")
        return redirect(url_for("recepciones.ver", rec_id=ya["id"]))
    espera_id, total_lineas = _guardar_borrador(request.form, espera_id, token)
    if espera_id is None:
        flash("No hay nada escrito para guardar.", "error")
        return redirect(url_for("recepciones.nueva"))
    get_db().commit()
    registrar("recepcion_en_espera", "recepciones_espera", espera_id, f"lineas={total_lineas}")

    flash(f"Recepción ABIERTA guardada con {total_lineas} línea(s). Todavía no entró nada al "
          f"inventario. Para seguir, dale «Continuar recibiendo» en la lista de abajo.", "ok")
    archivo = request.files.get("foto")
    if archivo and archivo.filename:
        flash("La foto del empaque/factura no se guarda mientras la recepción está abierta: "
              "adjúntala al confirmar.", "error")
    return redirect(url_for("recepciones.lista"))


@bp.route("/api/borrador", methods=["POST"])
@login_required
def api_borrador():
    """GUARDADO AUTOMÁTICO (versión 1.1.9), como el conteo de inventario.

    La pantalla de recepción llama aquí sola, unos segundos después de cada cambio
    (y al salir de la página). Así nada se pierde aunque se cierre la ventana o se
    vaya la luz: queda como recepción ABIERTA hasta que se le dé «Confirmar recepción».
    Devuelve el número de la recepción abierta para que la pantalla lo recuerde.
    """
    form = request.form
    token = _token_de(form)
    if _ya_confirmada(token):
        # Llegó tarde: la recepción ya se confirmó. No se crea otra abierta.
        return jsonify({"ok": False, "confirmada": True})
    espera_txt = (form.get("espera_id") or "").strip()
    espera_id, total_lineas = _guardar_borrador(form, int(espera_txt) if espera_txt.isdigit() else None, token)
    if espera_id is None:
        return jsonify({"ok": True, "vacia": True})
    get_db().commit()
    # Justo en ese instante se pudo haber confirmado (dos pedidos al tiempo): si ya
    # está confirmada, la abierta que se acaba de guardar sobra y se borra.
    if _ya_confirmada(token):
        get_db().execute("DELETE FROM recepciones_espera WHERE id = ?", (espera_id,))
        get_db().commit()
        return jsonify({"ok": False, "confirmada": True})
    return jsonify({"ok": True, "espera_id": espera_id, "lineas": total_lineas, "hora": ahora()[11:16]})


@bp.route("/espera/<int:espera_id>/descartar", methods=["POST"])
@login_required
def descartar_espera(espera_id):
    """Borra una recepción en espera (por ejemplo, si se metió por error)."""
    fila = _espera_o_none(espera_id)
    if fila is None:
        abort(404)
    db = get_db()
    db.execute("DELETE FROM recepciones_espera WHERE id = ?", (espera_id,))
    db.commit()
    registrar("recepcion_espera_descartada", "recepciones_espera", espera_id,
              f"factura={fila['factura_numero'] or '—'} lineas={fila['total_lineas']}")
    flash("Recepción en espera descartada.", "ok")
    return redirect(url_for("recepciones.lista"))


# ---------- Ver detalle ----------

@bp.route("/<int:rec_id>")
@login_required
def ver(rec_id):
    rec = _obtener(rec_id)
    lineas = _lineas_de(rec_id)
    proveedor = get_db().execute(
        "SELECT * FROM proveedores WHERE id = ?", (rec["proveedor_id"],)
    ).fetchone()
    # Versión 1.1.7: el pago de esta factura (si ya se pagó)
    from .cuentas_pagar import ORIGENES
    pago = get_db().execute("SELECT * FROM pagos_proveedores WHERE recepcion_id = ? AND anulado = 0 "
                            "ORDER BY id DESC LIMIT 1", (rec_id,)).fetchone()
    return render_template("recepciones/ver.html",
                           rec=rec, lineas=lineas, proveedor=proveedor, pago=pago, origenes_pago=ORIGENES,
                           estados=ESTADOS, empaques=EMPAQUES, resultados=RESULTADOS)


# ---------- Aprobar ----------

@bp.route("/<int:rec_id>/aprobar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def aprobar(rec_id):
    rec = _obtener(rec_id)
    if rec["estado"] not in ("cuarentena", "borrador"):
        flash("Esta recepción ya fue procesada.", "error")
        return redirect(url_for("recepciones.ver", rec_id=rec_id))

    db = get_db()
    lineas = _lineas_de(rec_id)
    for l in lineas:
        # Según el resultado de la línea, el lote nace en un estado distinto:
        #   rechazado  -> no entra stock
        #   cuarentena -> el lote existe pero NO se puede vender hasta que se libere
        #   aceptado   -> disponible para vender
        if l["resultado"] == "rechazado":
            estado = "rechazado"
            cantidad = 0
        elif l["resultado"] == "cuarentena":
            estado = "cuarentena"
            cantidad = l["cantidad_recibida"]
        else:
            estado = "disponible"
            cantidad = l["cantidad_recibida"]

        cur = db.execute(
            "INSERT INTO lotes (producto_id, lote, vencimiento, cantidad_inicial, "
            "cantidad_disponible, costo_unitario, estado, recepcion_id, recepcion_linea_id, creado_en) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (l["producto_id"], l["lote"], l["vencimiento"], l["cantidad_recibida"],
             cantidad, l["costo_unitario"], estado, rec_id, l["id"], ahora()),
        )
        lote_id = cur.lastrowid

        # El kardex solo registra entradas de stock vendible (lotes disponibles).
        if estado == "disponible" and cantidad > 0:
            db.execute(
                "INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, cantidad, "
                "referencia, referencia_id, usuario_id, usuario_nombre, creado_en) "
                "VALUES (?,?,?, 'recepcion', ?, ?, ?, ?, ?, ?)",
                (ahora(), lote_id, l["producto_id"], cantidad, f"Recepción {rec['numero']}",
                 rec_id, g.user["id"], g.user["nombre"], ahora()),
            )

    db.execute(
        "UPDATE recepciones SET estado = 'aprobada', aprobado_por = ?, aprobado_por_nombre = ?, "
        "aprobado_en = ?, actualizado_en = ? WHERE id = ?",
        (g.user["id"], g.user["nombre"], ahora(), ahora(), rec_id),
    )
    db.commit()

    registrar("recepcion_aprobada", "recepciones", rec_id,
              f"numero={rec['numero']} lotes={len(lineas)}")
    flash(f"Recepción {rec['numero']} aprobada. {len(lineas)} lote(s) creados.", "ok")
    return redirect(url_for("recepciones.ver", rec_id=rec_id))


# ---------- Rechazar ----------

@bp.route("/<int:rec_id>/rechazar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def rechazar(rec_id):
    rec = _obtener(rec_id)
    motivo = request.form.get("motivo", "").strip()
    if not motivo:
        flash("Debes indicar el motivo del rechazo.", "error")
        return redirect(url_for("recepciones.ver", rec_id=rec_id))

    db = get_db()
    db.execute(
        "UPDATE recepciones SET estado = 'rechazada', aprobado_por = ?, aprobado_por_nombre = ?, "
        "aprobado_en = ?, observaciones = COALESCE(observaciones, '') || ' | RECHAZO: ' || ?, "
        "actualizado_en = ? WHERE id = ?",
        (g.user["id"], g.user["nombre"], ahora(), motivo, ahora(), rec_id),
    )
    # Versión 1.1.7: una recepción rechazada no se paga (si ya se había pagado, queda como estaba)
    db.execute("UPDATE recepciones SET pago_estado = 'no_aplica' WHERE id = ? "
               "AND pago_estado IN ('pendiente', 'por_revisar')", (rec_id,))
    db.commit()
    registrar("recepcion_rechazada", "recepciones", rec_id,
              f"numero={rec['numero']} motivo={motivo}")
    flash(f"Recepción {rec['numero']} rechazada.", "ok")
    return redirect(url_for("recepciones.ver", rec_id=rec_id))


# ---------- Búsqueda de productos para autocompletado ----------

def _presentaciones_simples(producto_id):
    """[{id, nombre, factor, defecto, cuenta}] para el selector "Viene en" de cada línea.

    - defecto = True en la forma en que el producto se VENDE normalmente (ej.
      Sello x 10): la recepción muestra la conversión en esa unidad
      ("1 Caja x 150 = 15 Sello x 10").
    - cuenta (solo en la primera, la unidad de inventario) = cuántas unidades
      mínimas trae esa unidad. Casi siempre 1 (Tableta, Unidad), pero si el
      inventario se cuenta en SELLO X 10 es 10: así una CAJA X 150 son 15 sellos.
    """
    opciones = pres.presentaciones_de([producto_id]).get(producto_id, [])
    fila = get_db().execute(
        "SELECT p.venta_defecto_unidad_id, um.nombre, um.cantidad FROM productos p "
        "LEFT JOIN unidades_medida um ON um.id = p.unidad_venta_id WHERE p.id = ?", (producto_id,)).fetchone()
    defecto = pres.id_por_defecto(opciones, fila["venta_defecto_unidad_id"]) if fila else pres.PRINCIPAL
    cuenta = pres.cantidad_efectiva(fila["nombre"], fila["cantidad"]) if fila and fila["nombre"] else 1.0
    return [{"id": o["id"], "nombre": o["nombre"], "factor": o["factor"], "defecto": o["id"] == defecto,
             "cuenta": cuenta if o["id"] == pres.PRINCIPAL else None} for o in opciones]


def _fila_a_dict(f):
    return {
        # En qué puede llegar (Tableta, Sobre x 10, Caja x 100): ver "Viene en"
        "presentaciones": _presentaciones_simples(f["id"]),
        "id": f["id"],
        "codigo": f["codigo"],
        "nombre": f["nombre"],
        "concentracion": f["concentracion"] or "",
        "laboratorio": f["lab_nombre"] or "",
        "forma": f["forma_nombre"] or "",
        "unidad": f["unidad_nombre"] or "",
        "precio": f["precio_venta"] or 0,
        "registro": f["registro_sanitario"] or "",
        "registro_vence": f["registro_vence"] or "",
        "codigo_barras": f["codigo_barras"] or "",
        "maneja_vencimiento": f["maneja_vencimiento"] or 0,
        "cadena_frio": f["cadena_frio"] or 0,
        "control_especial": f["control_especial"] or 0,
        # IVA del producto (versión 1.1.6): la recepción lo pone solo en la línea
        "iva": (f["iva_tarifa"] or 0) if f["iva_tipo"] == "gravado" else 0,
    }


_SELECT_BUSQUEDA = (
    "SELECT p.id, p.codigo, p.nombre, p.concentracion, p.codigo_barras, "
    "p.registro_sanitario, p.registro_vence, p.precio_venta, p.iva_tipo, p.iva_tarifa, "
    "p.maneja_vencimiento, p.cadena_frio, p.control_especial, "
    "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS lab_nombre, "
    "(SELECT nombre FROM catalogos WHERE id = p.forma_farmaceutica_id) AS forma_nombre, "
    "(SELECT nombre FROM unidades_medida WHERE id = p.unidad_venta_id) AS unidad_nombre "
    "FROM productos p "
)


@bp.route("/api/buscar-productos")
@login_required
def api_buscar_productos():
    q = (request.args.get("q") or "").strip()
    if len(q) < 3:
        return jsonify({"ok": True, "resultados": []})

    # Cada palabra puede estar en el nombre, la concentración o el LABORATORIO
    # (ver app/busqueda.py): "trazodona san fer 50" encuentra ese producto exacto.
    from .busqueda import ORDEN_NOMBRE_LAB, condicion_palabras, palabras
    cond, params = condicion_palabras(q)
    primera = palabras(q)[0]
    filas = get_db().execute(
        _SELECT_BUSQUEDA + "WHERE p.activo = 1" + cond + " "
        # Orden de los resultados:
        #   0 = el código o código de barras exacto
        #   1 = el NOMBRE empieza por lo escrito      (MELOXICAM 15 MG)
        #   2 = el NOMBRE contiene lo escrito          (MEBLAINEX MELOXICAM)
        #   3 = lo demás (coincide por laboratorio, principio activo...)
        "ORDER BY "
        "  CASE WHEN p.codigo = ? THEN 0 "
        "       WHEN p.codigo_barras = ? THEN 0 "
        "       WHEN p.nombre LIKE ? THEN 1 "
        "       WHEN p.nombre LIKE ? THEN 2 "
        "       ELSE 3 END, " + ORDEN_NOMBRE_LAB + " "
        # 40 resultados (la lista tiene barra para bajar). Antes eran 8: si había
        # muchos "MELOXICAM ...", el "MEBLAINEX MELOXICAM" quedaba por fuera.
        "LIMIT 40",
        params + [q, q, f"{primera}%", f"%{primera}%"],
    ).fetchall()
    return jsonify({"ok": True, "resultados": [_fila_a_dict(f) for f in filas]})


@bp.route("/api/buscar-barras")
@login_required
def api_buscar_barras():
    codigo = (request.args.get("codigo") or "").strip()
    if not codigo:
        return jsonify({"ok": False, "error": "Código vacío."})
    db = get_db()
    fila = db.execute(
        _SELECT_BUSQUEDA + "WHERE p.activo = 1 AND p.codigo_barras = ? LIMIT 1",
        (codigo,),
    ).fetchone()
    presentacion_id = 0
    if fila is None:
        # ¿Es el código de una CAJA o un SOBRE? Entonces la línea queda en esa presentación
        pp = db.execute("SELECT id, producto_id FROM producto_presentaciones WHERE codigo_barras = ? LIMIT 1",
                        (codigo,)).fetchone()
        if pp:
            presentacion_id = pp["id"]
            fila = db.execute(_SELECT_BUSQUEDA + "WHERE p.activo = 1 AND p.id = ?", (pp["producto_id"],)).fetchone()
    if fila is None:
        return jsonify({"ok": False, "error": "Producto no encontrado."})
    return jsonify({"ok": True, "producto": _fila_a_dict(fila), "presentacion_id": presentacion_id})


# ---------- Alta rápida de producto desde recepción ----------

def _producto_duplicado(nombre, laboratorio_id, concentracion):
    db = get_db()
    return db.execute(
        "SELECT id, codigo, nombre FROM productos "
        "WHERE LOWER(TRIM(nombre)) = LOWER(TRIM(?)) "
        "AND COALESCE(laboratorio_id, 0) = ? "
        "AND COALESCE(LOWER(TRIM(concentracion)), '') = COALESCE(LOWER(TRIM(?)), '') "
        "LIMIT 1",
        (nombre, laboratorio_id or 0, concentracion or ""),
    ).fetchone()


@bp.route("/api/crear-producto", methods=["POST"])
@login_required
def api_crear_producto():
    from .productos import _siguiente_codigo

    nombre = (request.form.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"ok": False, "error": "El nombre es obligatorio."}), 400

    codigo = (request.form.get("codigo") or "").strip() or _siguiente_codigo()
    registro = (request.form.get("registro_sanitario") or "").strip() or None
    registro_vence = (request.form.get("registro_vence") or "").strip() or None
    unidad_venta_id = (request.form.get("unidad_venta_id") or "").strip()
    laboratorio_id = (request.form.get("laboratorio_id") or "").strip()
    concentracion = (request.form.get("concentracion") or "").strip() or None

    # Laboratorio o marca: OPCIONAL desde la versión 1.1.6 (un jabón, un pañal...
    # puede no tenerlo, o no saberse en el momento). Sin él queda "Sin laboratorio".
    laboratorio_id = int(laboratorio_id) if laboratorio_id.isdigit() else None
    # ---- Cómo se vende (igual que la ficha del producto) ----
    # Formulario nuevo: "Unidad de venta" (Sello x 10) + precio + ¿suelto?.
    # Por dentro se cuenta en "Unidad" (ver productos._traducir_venta).
    from .importador import _num
    from .productos import _id_unidad_basica, _cantidad_unidad
    venta_uid = (request.form.get("venta_unidad_id") or "").strip()
    factor = 1.0
    if venta_uid.isdigit():
        venta_uid = int(venta_uid)
        trae = _num((request.form.get("venta_trae") or "").strip(), None)
        basica = _id_unidad_basica()
        if trae and trae > 1:
            factor = float(trae)
        elif basica and venta_uid != basica and _cantidad_unidad(venta_uid) > 1:
            factor = _cantidad_unidad(venta_uid) / _cantidad_unidad(basica)
        # Si trae más de 1, se cuenta en Unidad; si no (Frasco), se cuenta en lo mismo que se vende
        unidad_venta_id = str(basica if factor > 1 and basica else venta_uid)
    else:
        venta_uid = None
    if not unidad_venta_id or not unidad_venta_id.isdigit():
        return jsonify({"ok": False, "error": "Debes elegir la unidad de venta."}), 400

    dup = _producto_duplicado(nombre, laboratorio_id, concentracion)
    if dup:
        return jsonify({
            "ok": False,
            "error": f"Ya existe un producto idéntico: {dup['codigo']} — {dup['nombre']}. "
                     f"Si es una presentación distinta, cambia la concentración o el laboratorio.",
            "duplicado_id": dup["id"],
        }), 409

    precio = _num((request.form.get("precio_venta") or "").strip(), 0.0)
    vende_suelto = 1 if (factor <= 1 or request.form.get("vende_suelto")) else 0
    precio_unidad = round(precio / factor, 2) if factor > 1 else precio   # $4.000 ÷ 10 = $400
    # Costo de la unidad de venta (el del sello): se guarda el de 1 unidad
    costo_unidad = round(_num((request.form.get("venta_costo") or "").strip(), 0.0) / factor, 4)
    codigo_barras = (request.form.get("codigo_barras") or "").strip() or None
    if codigo_barras and get_db().execute(
            "SELECT 1 FROM productos WHERE codigo_barras = ? UNION ALL "
            "SELECT 1 FROM producto_presentaciones WHERE codigo_barras = ?",
            (codigo_barras, codigo_barras)).fetchone():
        return jsonify({"ok": False, "error": f"El código de barras {codigo_barras} ya lo tiene otro producto."}), 400

    maneja_venc = 1 if request.form.get("maneja_vencimiento") else 0
    requiere_formula = 1 if request.form.get("requiere_formula") else 0
    cadena_frio = 1 if request.form.get("cadena_frio") else 0
    control_especial = 1 if request.form.get("control_especial") else 0

    if (cadena_frio or control_especial) and not registro:
        return jsonify({"ok": False, "error":
                        "Un producto de cadena de frío o control especial debe tener registro INVIMA."}), 400

    if control_especial or cadena_frio:
        maneja_venc = 1

    db = get_db()
    try:
        # IVA (versión 1.1.3, pedido de Fernando): el producto creado aquí queda
        # EXCLUIDO de IVA (tarifa 0). Si sí tiene IVA, se cambia después en la ficha
        # del producto. Antes quedaba "gravado 19 %" (lo que trae la base por defecto).
        cur = db.execute(
            "INSERT INTO productos (codigo, nombre, concentracion, laboratorio_id, "
            "registro_sanitario, registro_vence, precio_venta, unidad_venta_id, "
            "maneja_vencimiento, requiere_formula, cadena_frio, control_especial, activo, creado_en, "
            "iva_tipo, iva_tarifa) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,'excluido',0)",
            (codigo, nombre, concentracion, laboratorio_id,
             registro, registro_vence, precio_unidad, int(unidad_venta_id),
             maneja_venc, requiere_formula, cadena_frio, control_especial, ahora()),
        )
        nuevo_id = cur.lastrowid
        db.execute("UPDATE productos SET vende_suelto = ?, precio_compra = ?, codigo_barras = ? WHERE id = ?",
                   (vende_suelto, costo_unidad, codigo_barras, nuevo_id))
        if factor > 1:
            # La unidad de venta (Sello x 10) queda como presentación y se vende por defecto
            db.execute("INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, "
                       "creado_en) VALUES (?,?,?,?,?)", (nuevo_id, venta_uid, factor, precio, ahora()))
            db.execute("UPDATE productos SET venta_defecto_unidad_id = ? WHERE id = ?", (venta_uid, nuevo_id))
        db.commit()
        registrar("producto_creado_rapido", "productos", nuevo_id,
                  f"código={codigo} nombre={nombre} (desde recepción)")

        # ---- Versión 1.1.8: FOTO DEL PRODUCTO desde la recepción ----
        # Si en la ventana "Nuevo producto" escogieron una foto, se guarda igual
        # que en la ficha del producto (carpeta uploads/productos, máx. 5 MB).
        # Si la foto falla (formato raro, muy pesada), el producto SÍ queda creado
        # y solo se avisa: así no se pierde lo demás que se escribió.
        aviso_foto = _guardar_foto_producto(nuevo_id)

        lab = db.execute("SELECT nombre FROM catalogos WHERE id = ?", (laboratorio_id,)).fetchone() \
            if laboratorio_id else None
        return jsonify({
            "ok": True,
            "id": nuevo_id,
            "codigo": codigo,
            "nombre": nombre,
            "concentracion": concentracion or "",
            "laboratorio": lab["nombre"] if lab else "",
            "registro_sanitario": registro or "",
            "maneja_vencimiento": maneja_venc,
            "cadena_frio": cadena_frio,
            "control_especial": control_especial,
            # Para el selector "Viene en" de la línea (Unidad, Sello x 10, Otra caja…)
            "presentaciones": _presentaciones_simples(nuevo_id),
            "unidad": (db.execute("SELECT nombre FROM unidades_medida WHERE id = ?",
                                  (int(unidad_venta_id),)).fetchone() or {"nombre": ""})["nombre"],
            "aviso": aviso_foto,          # None si la foto se guardó bien (o no había foto)
        })
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "Ya existe un producto con ese código."}), 400


def _guardar_foto_producto(producto_id):
    """Guarda (o quita) la foto del producto que llegó en el formulario.

    Versión 1.1.8. Lo usan "Nuevo producto" y "Completar datos" de la recepción.
      - campo "imagen": la foto nueva (reemplaza la anterior, que se borra del disco)
      - campo "imagen_accion" = "eliminar": quitar la foto que tenía
    Devuelve None si todo bien, o el texto del problema para avisarle a la persona.
    """
    from .utils_imagenes import eliminar_imagen, guardar_imagen
    db = get_db()
    anterior = db.execute("SELECT imagen FROM productos WHERE id = ?", (producto_id,)).fetchone()
    anterior = anterior["imagen"] if anterior else None
    archivo = request.files.get("imagen")
    if archivo and archivo.filename:
        ruta, error = guardar_imagen(archivo, "productos", max_px=1200, max_bytes=5 * 1024 * 1024)
        if error:
            return f"El producto quedó guardado, pero la foto no: {error}"
        db.execute("UPDATE productos SET imagen = ? WHERE id = ?", (ruta, producto_id))
        db.commit()
        if anterior:
            eliminar_imagen(anterior)            # la foto vieja ya no sirve
        registrar("producto_imagen", "productos", producto_id, "foto cargada desde recepción")
    elif request.form.get("imagen_accion") == "eliminar" and anterior:
        db.execute("UPDATE productos SET imagen = NULL WHERE id = ?", (producto_id,))
        db.commit()
        eliminar_imagen(anterior)
        registrar("producto_imagen", "productos", producto_id, "foto quitada desde recepción")
    return None


# ---------- Completar los datos técnicos del producto desde la recepción ----------
# Pasa mucho: llega un producto al que le falta el registro INVIMA, el
# laboratorio o la concentración. En vez de salir a la ficha, se completan
# aquí mismo (ventana "Completar datos" de la línea) y quedan guardados en la
# ficha del producto. Queda en la bitácora.
_CAMPOS_TECNICOS = ("laboratorio_id", "principio_id", "forma_farmaceutica_id",
                    "concentracion", "registro_sanitario", "registro_vence")


def _tecnicos_de(producto_id):
    p = get_db().execute(
        "SELECT p.id, p.nombre, p.laboratorio_id, p.principio_id, p.forma_farmaceutica_id, p.concentracion, "
        "p.registro_sanitario, p.registro_vence, p.cadena_frio, p.control_especial, p.imagen, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS laboratorio "
        "FROM productos p WHERE p.id = ?", (producto_id,)).fetchone()
    if not p:
        return None
    datos = dict(p)
    # Versión 1.1.8: dirección de la foto para mostrarla en "Completar datos"
    datos["imagen_url"] = url_for("static", filename=p["imagen"]) if p["imagen"] else ""
    # Varios principios activos, como se escriben: "Acetaminofén, Codeína" (versión 1.1.6)
    from .principios import texto_de
    datos["principios"] = texto_de(get_db(), producto_id)
    return datos


@bp.route("/api/producto/<int:producto_id>/tecnicos", methods=["GET", "POST"])
@login_required
def api_datos_tecnicos(producto_id):
    actual = _tecnicos_de(producto_id)
    if actual is None:
        return jsonify({"ok": False, "error": "Ese producto no existe."}), 404
    if request.method == "GET":
        return jsonify({"ok": True, "producto": actual})
    f = request.form
    nuevos = {}
    for campo in ("laboratorio_id", "principio_id", "forma_farmaceutica_id"):
        v = (f.get(campo) or "").strip()
        nuevos[campo] = int(v) if v.isdigit() else None
    for campo in ("concentracion", "registro_sanitario"):
        nuevos[campo] = (f.get(campo) or "").strip() or None
    vence = (f.get("registro_vence") or "").strip()
    if vence:
        try:
            datetime.strptime(vence, "%Y-%m-%d")
        except ValueError:
            return jsonify({"ok": False, "error": "La fecha de vencimiento del registro no es válida."}), 400
    nuevos["registro_vence"] = vence or None
    if (actual["cadena_frio"] or actual["control_especial"]) and not nuevos["registro_sanitario"]:
        return jsonify({"ok": False, "error": "Este producto es de cadena de frío o control especial: "
                                              "el registro INVIMA es obligatorio."}), 400
    # Principios activos (versión 1.1.6): si llega el texto con comas, manda ese
    db = get_db()
    cambio_principios = False
    if "principios" in f:
        from . import principios
        antes = actual["principios"]
        principios.guardar(db, producto_id, f.get("principios") or "")
        nuevos["principio_id"] = db.execute("SELECT principio_id FROM productos WHERE id = ?",
                                            (producto_id,)).fetchone()[0]
        cambio_principios = principios.texto_de(db, producto_id) != antes
    cambios = [c for c in _CAMPOS_TECNICOS if (actual[c] or None) != nuevos[c]]
    if cambio_principios and "principio_id" not in cambios:
        cambios.append("principio_id")
    if cambios:
        db.execute("UPDATE productos SET " + ", ".join(f"{c} = ?" for c in cambios) + ", actualizado_en = ? "
                   "WHERE id = ?", [nuevos[c] for c in cambios] + [ahora(), producto_id])
        db.commit()
        registrar("producto_datos_tecnicos", "productos", producto_id,
                  "desde recepción: " + ", ".join(f"{c}={nuevos[c]}" for c in cambios))
    else:
        db.commit()
    # Versión 1.1.8: también se puede poner, cambiar o quitar la FOTO del producto
    aviso_foto = _guardar_foto_producto(producto_id)
    return jsonify({"ok": True, "producto": _tecnicos_de(producto_id), "cambios": len(cambios),
                    "aviso": aviso_foto})


@bp.route("/api/crear-unidad", methods=["POST"])
@login_required
def api_crear_unidad():
    """Crea una unidad de medida desde la línea de la recepción (ej. "CAJA X 12").

    Si el nombre ya existe, devuelve la que hay. Si no escriben cuántas trae,
    se lee del nombre ("CAJA X 12" -> 12).
    """
    import re
    from .importador import _num
    nombre = " ".join((request.form.get("nombre") or "").upper().split())
    if not nombre:
        return jsonify({"ok": False, "error": "Escribe el nombre (ej. CAJA X 12)."}), 400
    cantidad = _num((request.form.get("cantidad") or "").strip(), 0)
    if cantidad <= 0:
        m = re.search(r"x\s*(\d+(?:[.,]\d+)?)\s*$", nombre, re.I)
        cantidad = float(m.group(1).replace(",", ".")) if m else 0
    if cantidad <= 1:
        return jsonify({"ok": False, "error": "Escribe cuántas unidades trae (más de 1)."}), 400
    db = get_db()
    from .nombres import unidad_igual
    fila = unidad_igual(db, nombre)          # "CAJA X12" = "Caja x 12": no se crea otra
    if fila is None:
        cur = db.execute("INSERT INTO unidades_medida (nombre, cantidad, referencia_id, activo, creado_en) "
                         "VALUES (?, ?, NULL, 1, ?)", (nombre, cantidad, ahora()))
        db.commit()
        registrar("unidad_medida_creada_api", "unidades_medida", cur.lastrowid,
                  f"nombre={nombre} cantidad={cantidad:g} (desde recepción)")
        fila = {"id": cur.lastrowid, "nombre": nombre, "cantidad": cantidad}
    return jsonify({"ok": True, "id": fila["id"], "nombre": fila["nombre"], "cantidad": fila["cantidad"]})


# ---------- PDF ----------

@bp.route("/<int:rec_id>/pdf")
@login_required
def pdf(rec_id):
    from datetime import datetime as _dt

    rec = _obtener(rec_id)
    lineas = _lineas_de(rec_id)
    proveedor = get_db().execute("SELECT * FROM proveedores WHERE id = ?",
                                 (rec["proveedor_id"],)).fetchone()
    config = obtener_config()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            leftMargin=1.3 * cm, rightMargin=1.3 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                            title=f"Acta de recepción técnica {rec['numero']}")

    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("t", parent=estilos["Title"], fontSize=13,
                            textColor=colors.HexColor("#0F766E"), spaceAfter=2)
    subtit = ParagraphStyle("st", parent=estilos["Normal"], fontSize=9,
                            textColor=colors.HexColor("#555"))
    encab = ParagraphStyle("e", parent=estilos["Heading2"], fontSize=12,
                           textColor=colors.HexColor("#13201D"), alignment=1)
    celda = ParagraphStyle("c", parent=estilos["Normal"], fontSize=6.8, leading=8.2)
    celda_chica = ParagraphStyle("cc", parent=estilos["Normal"], fontSize=6.3, leading=7.5)
    celda_head = ParagraphStyle("ch", parent=estilos["Normal"], fontSize=6.5,
                                leading=7.5, textColor=colors.HexColor("#0F766E"))
    seccion = ParagraphStyle("s", parent=estilos["Heading3"], fontSize=9,
                             textColor=colors.HexColor("#0F766E"), spaceBefore=6, spaceAfter=3)

    elementos = []

    # ===== ENCABEZADO con logo =====
    from .pdf_utils import encabezado_pdf, pie_de_pagina
    elementos.extend(encabezado_pdf(
        config,
        f"ACTA DE RECEPCIÓN TÉCNICA N° {rec['numero']}"
    ))
    elementos.append(Spacer(1, 8))

    # ===== DATOS GENERALES =====
    fecha_dt = rec["fecha"]
    recibido = rec["recibido_por_nombre"] or "—"
    temp_llegada = f"{rec['temperatura_llegada']} °C" if rec["temperatura_llegada"] is not None else "—"
    estado_txt = ESTADOS.get(rec["estado"], rec["estado"])

    # Versión 1.1.8: los datos generales van en 2 filas (antes 4) para que quepan
    # más productos en la primera hoja. Cada fila tiene 4 parejas "Etiqueta: dato".
    datos_gen = [
        ["Fecha:", fecha_dt, "Proveedor:", proveedor["razon_social"] if proveedor else "—",
         "NIT:", proveedor["nit"] if proveedor else "—", "Estado:", estado_txt],
        ["Factura N°:", rec["factura_numero"] or "—", "Remisión N°:", rec["remision_numero"] or "—",
         "T° llegada:", temp_llegada, "Recibido por:", recibido],
    ]
    tabla_gen = Table(datos_gen, colWidths=[1.8 * cm, 3.6 * cm, 2.0 * cm, 8.1 * cm,
                                            1.6 * cm, 3.0 * cm, 2.2 * cm, 4.8 * cm])
    tabla_gen.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        # Las etiquetas (columnas 0, 2, 4 y 6) en gris
        *[("TEXTCOLOR", (c, 0), (c, -1), colors.HexColor("#555")) for c in (0, 2, 4, 6)],
    ]))
    elementos.append(tabla_gen)
    elementos.append(Spacer(1, 4))

    # ===== TABLA DE LÍNEAS =====
    elementos.append(Paragraph("DETALLE DE PRODUCTOS RECIBIDOS", seccion))

    encabezados = [
        "#", "Producto / Concentración", "Principio activo (DCI)",
        "Forma / Presentación", "Reg. INVIMA", "Lote",
        "Vence", "Vida útil", "Cant.", "Empaque",
        "Cond. especiales", "Resultado"
    ]
    data = [[Paragraph(f"<b>{h}</b>", celda_head) for h in encabezados]]

    # ---- Versión 1.1.8: AL MENOS 20 PRODUCTOS POR HOJA (pedido de Fernando) ----
    # Antes cada producto ocupaba 3 renglones (nombre / concentración / laboratorio,
    # uno debajo del otro) y cabían unos 13 por hoja. Ahora todo va SEGUIDO en el
    # mismo renglón, separado por " · ", y la columna del producto es más ancha.
    # Así cada producto ocupa 1 renglón (2 si el nombre es muy largo).
    hoy = _dt.now().date()
    for i, l in enumerate(lineas, 1):
        producto_txt = f"<b>{l['producto_nombre']}</b>"
        if l["concentracion"]:
            producto_txt += f" {l['concentracion']}"
        if l["lab_nombre"]:
            producto_txt += f" · <i>{l['lab_nombre']}</i>"

        forma_txt = l["forma_nombre"] or "—"
        if l["unidad_nombre"]:
            forma_txt += f" · <i>{l['unidad_nombre']}</i>"

        vida_txt = "—"
        if l["vencimiento"]:
            try:
                fv = _dt.strptime(l["vencimiento"][:10], "%Y-%m-%d").date()
                dias = (fv - hoy).days
                if dias < 0:
                    vida_txt = "<b>VENCIDO</b>"
                else:
                    pct = min(100, (dias / 730) * 100)
                    color = "#0d6b3d" if pct >= 75 else ("#a67c00" if pct >= 50 else "#b3261e")
                    vida_txt = f'<font color="{color}"><b>{pct:.0f}%</b></font> {dias} d'
            except (ValueError, TypeError):
                pass

        conds = []
        if l["cadena_frio"]:
            t_ing = l["temperatura_ingreso"] if "temperatura_ingreso" in l.keys() else None
            if t_ing is not None:
                conds.append(f"❄ Frío ({t_ing} °C)")
            else:
                conds.append("❄ Frío")
        if l["control_especial"]:
            conds.append("⚠ FNE")
        if l["requiere_formula"]:
            conds.append("℞ Fórmula")
        cond_txt = " ".join(conds) if conds else "—"       # seguidas, en un solo renglón

        data.append([
            Paragraph(str(i), celda_chica),
            Paragraph(producto_txt, celda_chica),
            Paragraph(l["principio_nombre"] or "—", celda_chica),
            Paragraph(forma_txt, celda_chica),
            Paragraph(l["producto_registro"] or "—", celda_chica),
            Paragraph(l["lote"] or "—", celda_chica),
            Paragraph(l["vencimiento"] or "—", celda_chica),
            Paragraph(vida_txt, celda_chica),
            Paragraph(f"{l['cantidad_recibida']:.2f}", celda_chica),
            Paragraph(EMPAQUES.get(l["estado_empaque"], l["estado_empaque"]), celda_chica),
            Paragraph(cond_txt, celda_chica),
            Paragraph(RESULTADOS.get(l["resultado"], l["resultado"]), celda_chica),
        ])

    # Anchos de las 12 columnas (la hoja acostada deja 27,1 cm). La del producto
    # pasó de 4,2 a 6,8 cm para que el nombre, la concentración y el laboratorio
    # quepan en un solo renglón; la del registro INVIMA, de 2,4 a 3,2 cm, para
    # que el número no se parta en dos renglones.
    tabla = Table(
        data,
        colWidths=[0.6 * cm, 6.8 * cm, 2.7 * cm, 2.6 * cm, 3.2 * cm, 1.8 * cm,
                   1.6 * cm, 1.5 * cm, 1.2 * cm, 1.4 * cm, 2.0 * cm, 1.6 * cm],
        repeatRows=1,          # el encabezado de la tabla se repite en cada hoja
    )
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe6ef")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8c4cd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7f9")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        # Menos espacio arriba y abajo de cada renglón (antes 2,5): caben más por hoja
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (8, 0), (8, -1), "RIGHT"),
    ]))
    elementos.append(tabla)

    # ===== CONCEPTO TÉCNICO =====
    total_lineas = len(lineas)
    aceptadas = sum(1 for l in lineas if l["resultado"] == "aceptado")
    cuarentena = sum(1 for l in lineas if l["resultado"] == "cuarentena")
    rechazadas = sum(1 for l in lineas if l["resultado"] == "rechazado")

    concepto_txt = (
        f"Del total de {total_lineas} producto(s) verificados: "
        f"<b>{aceptadas} aceptado(s)</b>, "
        f"{cuarentena} en cuarentena, "
        f"{rechazadas} rechazado(s)."
    )
    if rechazadas > 0:
        concepto_txt += " Los productos rechazados serán devueltos al proveedor con la debida justificación."
    if any(l["cadena_frio"] for l in lineas):
        concepto_txt += " Se verificó el mantenimiento de la cadena de frío durante el transporte."
    if any(l["control_especial"] for l in lineas):
        concepto_txt += " Los productos de control especial se registrarán en el libro oficial del FNE."

    elementos.append(Spacer(1, 8))
    elementos.append(Paragraph("CONCEPTO TÉCNICO", seccion))
    elementos.append(Paragraph(concepto_txt, celda))

    if rec["observaciones"]:
        elementos.append(Spacer(1, 4))
        elementos.append(Paragraph(f"<b>Observaciones:</b> {rec['observaciones']}", celda))

    # ===== RESPONSABLES =====
    elementos.append(Spacer(1, 20))
    elementos.append(Paragraph("RESPONSABLES", seccion))

    regente = config.get("regente_nombre") or "—"
    tarjeta = config.get("regente_tarjeta") or "—"
    cargo_regente = "Director Técnico / Regente de Farmacia"

    responsables = [
        ["Recibido y verificado por:", "Aprobado por:"],
        ["", ""],
        ["__________________________________", "__________________________________"],
        [recibido, regente],
        ["Auxiliar de Farmacia", cargo_regente],
        ["", f"Tarjeta profesional: {tarjeta}"],
    ]
    tabla_resp = Table(responsables, colWidths=[9 * cm, 9 * cm])
    tabla_resp.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#555")),
    ]))
    elementos.append(tabla_resp)

    pie = config.get("pie_pagina") or ""
    if pie:
        elementos.append(Spacer(1, 10))
        elementos.append(Paragraph(f"<i>{pie}</i>", subtit))

    doc.build(elementos, onFirstPage=pie_de_pagina, onLaterPages=pie_de_pagina)
    buffer.seek(0)
    nombre = f"Acta_recepcion_{rec['numero']}.pdf"
    return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                     download_name=nombre)