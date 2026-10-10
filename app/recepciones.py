"""Recepción técnica: ingreso de mercancía, cuarentena, aprobación, PDF."""
import os
import sqlite3
from datetime import datetime
from io import BytesIO
from .pdf_utils import encabezado_pdf

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
        "(SELECT nombre FROM catalogos WHERE id = p.principio_id) AS principio_nombre, "
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
        "FROM productos p WHERE p.activo = 1 ORDER BY p.nombre COLLATE NOCASE"
    ).fetchall()


def _proveedores():
    return get_db().execute(
        "SELECT id, nit, razon_social FROM proveedores WHERE activo = 1 "
        "ORDER BY razon_social COLLATE NOCASE"
    ).fetchall()


def _unidades():
    return get_db().execute(
        "SELECT id, nombre, cantidad FROM unidades_medida WHERE activo = 1 "
        "ORDER BY cantidad, nombre"
    ).fetchall()


def _laboratorios():
    return get_db().execute(
        "SELECT id, nombre FROM catalogos WHERE tipo = 'laboratorio' AND activo = 1 "
        "ORDER BY nombre COLLATE NOCASE"
    ).fetchall()


def _contexto_form(rec=None):
    return {
        "proveedores": _proveedores(),
        "productos": _productos(),
        "unidades": _unidades(),
        "laboratorios": _laboratorios(),
        "estados": ESTADOS,
        "empaques": EMPAQUES,
        "resultados": RESULTADOS,
        "numero_sugerido": _siguiente_numero() if not rec else None,
        "recepcion": rec,
        "lineas": _lineas_de(rec["id"]) if rec else [],
    }


def _guardar_foto(archivo, rec_id):
    if not archivo or not archivo.filename:
        return None
    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".pdf"):
        return None
    carpeta = current_app.config.get("UPLOADS_DIR") or os.path.join("static", "uploads")
    destino_dir = os.path.join(carpeta, "recepciones")
    os.makedirs(destino_dir, exist_ok=True)
    ruta = os.path.join(destino_dir, f"{rec_id}{ext}")
    archivo.save(ruta)
    return f"uploads/recepciones/{rec_id}{ext}"


def _lineas_previas_formulario():
    """Lee las líneas del formulario tal cual (sin validar) para repintarlas al fallar."""
    prod_ids = request.form.getlist("linea_producto_id")
    lotes = request.form.getlist("linea_lote")
    vencimientos = request.form.getlist("linea_vencimiento")
    cant_rec = request.form.getlist("linea_cantidad_recibida")
    costos = request.form.getlist("linea_costo")
    temps_ing = request.form.getlist("linea_temperatura_ingreso")
    empaques = request.form.getlist("linea_empaque")
    resultados = request.form.getlist("linea_resultado")
    motivos = request.form.getlist("linea_motivo")
    presentaciones = request.form.getlist("linea_presentacion")
    factores_otros = request.form.getlist("linea_factor_otro")

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
    base = db.execute("SELECT um.id, um.cantidad FROM productos p JOIN unidades_medida um "
                      "ON um.id = p.unidad_venta_id WHERE p.id = ?", (producto_id,)).fetchone()
    if base and base["id"] == unidad_id:
        return {"nombre": u["nombre"], "factor": 1.0}
    cant_base = float(base["cantidad"] or 1) if base else 1.0
    return {"nombre": u["nombre"], "factor": round(float(u["cantidad"] or 1) / cant_base, 4)}


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
            # así lo pidió Fernando, como en Odoo. Cuántas trae sale de la unidad.
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

        lineas.append({
            "producto_id": int(pid),
            "lote": v(lotes, i).strip() or None,
            "vencimiento": v(vencimientos, i).strip() or None,
            "cantidad_facturada": round(cr * factor, 4),
            "cantidad_recibida": round(cr * factor, 4),
            "costo_unitario": co / factor,
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
    return render_template("recepciones/lista.html", filas=filas, q=q, filtro=filtro,
                           estados=ESTADOS)


# ---------- Nueva ----------

@bp.route("/nueva", methods=["GET", "POST"])
@login_required
def nueva():
    if request.method == "POST":
        proveedor_id = request.form.get("proveedor_id", "").strip()
        factura = request.form.get("factura_numero", "").strip() or None
        remision = request.form.get("remision_numero", "").strip() or None
        temperatura = request.form.get("temperatura_llegada", "").strip()
        observaciones = request.form.get("observaciones", "").strip() or None
        numero = request.form.get("numero", "").strip() or _siguiente_numero()

        lineas, errores = _leer_lineas_formulario()
        error_cabecera = None

        if not factura and not remision:
            error_cabecera = "Debes indicar el número de factura o el número de remisión."
        elif not lineas:
            error_cabecera = "Debes agregar al menos una línea."
        elif errores:
            error_cabecera = errores[0]

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
                    "recibido_por_nombre, observaciones, creado_en) "
                    "VALUES (?,?,?,?,?,?, 'cuarentena', ?, ?, ?, ?)",
                    (numero, ahora(), int(proveedor_id), factura, remision, temp_llegada,
                     g.user["id"], g.user["nombre"], observaciones, ahora()),
                )
                rec_id = cur.lastrowid

                for l in lineas:
                    db.execute(
                        "INSERT INTO recepcion_lineas (recepcion_id, producto_id, lote, vencimiento, "
                        "cantidad_facturada, cantidad_recibida, costo_unitario, estado_empaque, "
                        "resultado, motivo_rechazo, observaciones, temperatura_ingreso, presentacion, factor) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (rec_id, l["producto_id"], l["lote"], l["vencimiento"],
                         l["cantidad_facturada"], l["cantidad_recibida"], l["costo_unitario"],
                         l["estado_empaque"], l["resultado"], l["motivo_rechazo"],
                         l["observaciones"], l["temperatura_ingreso"], l["presentacion"], l["factor"]),
                    )
                db.commit()

                archivo = request.files.get("foto")
                if archivo and archivo.filename:
                    ruta = _guardar_foto(archivo, rec_id)
                    if ruta:
                        db.execute("UPDATE recepciones SET foto_ruta = ? WHERE id = ?", (ruta, rec_id))
                        db.commit()

                registrar("recepcion_creada", "recepciones", rec_id,
                          f"numero={numero} proveedor={proveedor_id}")
                flash(f"Recepción {numero} creada en cuarentena. Pendiente de aprobación.", "ok")
                return redirect(url_for("recepciones.ver", rec_id=rec_id))
            except Exception as e:
                error_cabecera = f"Error al guardar: {e}"

        valores_previos = {
            "numero": numero,
            "proveedor_id": proveedor_id,
            "factura_numero": factura or "",
            "remision_numero": remision or "",
            "temperatura_llegada": temperatura,
            "observaciones": observaciones or "",
        }
        return render_template(
            "recepciones/form.html",
            **_contexto_form(),
            error_cabecera=error_cabecera,
            valores_previos=valores_previos,
            lineas_previas=_lineas_previas_formulario(),
        )
    return render_template("recepciones/form.html", **_contexto_form())


# ---------- Ver detalle ----------

@bp.route("/<int:rec_id>")
@login_required
def ver(rec_id):
    rec = _obtener(rec_id)
    lineas = _lineas_de(rec_id)
    proveedor = get_db().execute(
        "SELECT * FROM proveedores WHERE id = ?", (rec["proveedor_id"],)
    ).fetchone()
    return render_template("recepciones/ver.html",
                           rec=rec, lineas=lineas, proveedor=proveedor,
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
    db.commit()
    registrar("recepcion_rechazada", "recepciones", rec_id,
              f"numero={rec['numero']} motivo={motivo}")
    flash(f"Recepción {rec['numero']} rechazada.", "ok")
    return redirect(url_for("recepciones.ver", rec_id=rec_id))


# ---------- Búsqueda de productos para autocompletado ----------

def _presentaciones_simples(producto_id):
    """[{id, nombre, factor}] para el selector "Viene en" de cada línea."""
    return [{"id": o["id"], "nombre": o["nombre"], "factor": o["factor"]}
            for o in pres.presentaciones_de([producto_id]).get(producto_id, [])]


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
    }


_SELECT_BUSQUEDA = (
    "SELECT p.id, p.codigo, p.nombre, p.concentracion, p.codigo_barras, "
    "p.registro_sanitario, p.registro_vence, p.precio_venta, "
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

    like = f"%{q}%"
    filas = get_db().execute(
        _SELECT_BUSQUEDA +
        "WHERE p.activo = 1 AND ("
        "  p.nombre LIKE ? OR p.codigo LIKE ? OR p.codigo_barras LIKE ? "
        "  OR p.concentracion LIKE ? "
        "  OR p.principio_id IN (SELECT id FROM catalogos WHERE nombre LIKE ?) "
        "  OR p.laboratorio_id IN (SELECT id FROM catalogos WHERE nombre LIKE ?)"
        ") "
        "ORDER BY "
        "  CASE WHEN p.codigo = ? THEN 0 "
        "       WHEN p.codigo_barras = ? THEN 0 "
        "       WHEN p.nombre LIKE ? THEN 1 "
        "       ELSE 2 END, "
        "  p.nombre COLLATE NOCASE "
        "LIMIT 8",
        (like, like, like, like, like, like, q, q, f"{q}%"),
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

    if not laboratorio_id or not laboratorio_id.isdigit():
        return jsonify({"ok": False, "error": "El laboratorio es obligatorio."}), 400
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

    dup = _producto_duplicado(nombre, int(laboratorio_id), concentracion)
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
        cur = db.execute(
            "INSERT INTO productos (codigo, nombre, concentracion, laboratorio_id, "
            "registro_sanitario, registro_vence, precio_venta, unidad_venta_id, "
            "maneja_vencimiento, requiere_formula, cadena_frio, control_especial, activo, creado_en) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
            (codigo, nombre, concentracion, int(laboratorio_id),
             registro, registro_vence, precio_unidad, int(unidad_venta_id),
             maneja_venc, requiere_formula, cadena_frio, control_especial, ahora()),
        )
        nuevo_id = cur.lastrowid
        db.execute("UPDATE productos SET vende_suelto = ? WHERE id = ?", (vende_suelto, nuevo_id))
        if factor > 1:
            # La unidad de venta (Sello x 10) queda como presentación y se vende por defecto
            db.execute("INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, "
                       "creado_en) VALUES (?,?,?,?,?)", (nuevo_id, venta_uid, factor, precio, ahora()))
            db.execute("UPDATE productos SET venta_defecto_unidad_id = ? WHERE id = ?", (venta_uid, nuevo_id))
        db.commit()
        registrar("producto_creado_rapido", "productos", nuevo_id,
                  f"código={codigo} nombre={nombre} (desde recepción)")

        lab = db.execute("SELECT nombre FROM catalogos WHERE id = ?", (int(laboratorio_id),)).fetchone()
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
        })
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "Ya existe un producto con ese código."}), 400


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
    fila = db.execute("SELECT id, nombre, cantidad FROM unidades_medida WHERE nombre = ? COLLATE NOCASE",
                      (nombre,)).fetchone()
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
                            textColor=colors.HexColor("#0a4f8a"), spaceAfter=2)
    subtit = ParagraphStyle("st", parent=estilos["Normal"], fontSize=9,
                            textColor=colors.HexColor("#555"))
    encab = ParagraphStyle("e", parent=estilos["Heading2"], fontSize=12,
                           textColor=colors.HexColor("#1a2733"), alignment=1)
    celda = ParagraphStyle("c", parent=estilos["Normal"], fontSize=6.8, leading=8.2)
    celda_chica = ParagraphStyle("cc", parent=estilos["Normal"], fontSize=6.3, leading=7.5)
    celda_head = ParagraphStyle("ch", parent=estilos["Normal"], fontSize=6.5,
                                leading=7.5, textColor=colors.HexColor("#0a4f8a"))
    seccion = ParagraphStyle("s", parent=estilos["Heading3"], fontSize=9,
                             textColor=colors.HexColor("#0a4f8a"), spaceBefore=6, spaceAfter=3)

    elementos = []

    # ===== ENCABEZADO con logo =====
    from .pdf_utils import encabezado_pdf
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

    datos_gen = [
        ["Fecha y hora:", fecha_dt, "Estado:", estado_txt],
        ["Proveedor:", proveedor["razon_social"] if proveedor else "—",
         "NIT proveedor:", proveedor["nit"] if proveedor else "—"],
        ["Factura N°:", rec["factura_numero"] or "—",
         "Remisión N°:", rec["remision_numero"] or "—"],
        ["Temperatura de llegada:", temp_llegada, "Recibido por:", recibido],
    ]
    tabla_gen = Table(datos_gen, colWidths=[3.5 * cm, 8 * cm, 3.5 * cm, 10 * cm])
    tabla_gen.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#555")),
    ]))
    elementos.append(tabla_gen)
    elementos.append(Spacer(1, 8))

    # ===== TABLA DE LÍNEAS =====
    elementos.append(Paragraph("DETALLE DE PRODUCTOS RECIBIDOS", seccion))

    encabezados = [
        "#", "Producto / Concentración", "Principio activo (DCI)",
        "Forma / Presentación", "Reg. INVIMA", "Lote",
        "Vence", "Vida útil", "Cant.", "Empaque",
        "Cond. especiales", "Resultado"
    ]
    data = [[Paragraph(f"<b>{h}</b>", celda_head) for h in encabezados]]

    hoy = _dt.now().date()
    for i, l in enumerate(lineas, 1):
        producto_txt = f"<b>{l['producto_nombre']}</b>"
        if l["concentracion"]:
            producto_txt += f"<br/>{l['concentracion']}"
        if l["lab_nombre"]:
            producto_txt += f"<br/><i>{l['lab_nombre']}</i>"

        forma_txt = l["forma_nombre"] or "—"
        if l["unidad_nombre"]:
            forma_txt += f"<br/><i>{l['unidad_nombre']}</i>"

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
                    vida_txt = f'<font color="{color}"><b>{pct:.0f}%</b></font><br/>{dias} días'
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
        cond_txt = "<br/>".join(conds) if conds else "—"

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

    tabla = Table(
        data,
        colWidths=[0.6 * cm, 4.2 * cm, 2.8 * cm, 2.6 * cm, 2.4 * cm, 1.8 * cm,
                   1.7 * cm, 1.5 * cm, 1.3 * cm, 1.5 * cm, 2.0 * cm, 1.6 * cm],
        repeatRows=1,
    )
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe6ef")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8c4cd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7f9")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
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

    doc.build(elementos)
    buffer.seek(0)
    nombre = f"Acta_recepcion_{rec['numero']}.pdf"
    return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                     download_name=nombre)