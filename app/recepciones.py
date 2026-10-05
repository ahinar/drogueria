"""Recepción técnica: ingreso de mercancía, cuarentena, aprobación, PDF."""
import os
import sqlite3
from datetime import datetime
from io import BytesIO

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect,
                   render_template, request, send_file, url_for)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .audit import registrar
from .auth import login_required, roles_required
from .configuracion import obtener_config
from .db import ahora, get_db

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
        "SELECT rl.*, p.codigo AS producto_codigo, p.nombre AS producto_nombre, "
        "p.registro_sanitario AS producto_registro, p.maneja_vencimiento, "
        "p.concentracion, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS lab_nombre, "
        "(SELECT nombre FROM catalogos WHERE id = p.forma_farmaceutica_id) AS forma_nombre "
        "FROM recepcion_lineas rl JOIN productos p ON p.id = rl.producto_id "
        "WHERE rl.recepcion_id = ? ORDER BY rl.id",
        (rec_id,),
    ).fetchall()


def _nombre_largo(p):
    """Devuelve el nombre enriquecido para mostrar en pantalla."""
    partes = [p["nombre"]]
    if p.get("concentracion"):
        partes.append(p["concentracion"])
    if p.get("forma_nombre"):
        partes.append(p["forma_nombre"])
    nombre = " ".join(partes)
    if p.get("lab_nombre"):
        nombre += f" — {p['lab_nombre']}"
    return nombre


def _productos():
    """Lista de productos activos con toda la info para el select enriquecido."""
    return get_db().execute(
        "SELECT p.id, p.codigo, p.nombre, p.concentracion, p.maneja_vencimiento, "
        "p.cadena_frio, p.control_especial, p.registro_sanitario, p.registro_vence, "
        "p.precio_venta, p.codigo_barras, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS lab_nombre, "
        "(SELECT nombre FROM catalogos WHERE id = p.forma_farmaceutica_id) AS forma_nombre, "
        "(SELECT nombre FROM unidades_medida WHERE id = p.unidad_venta_id) AS unidad_nombre "
        "FROM productos p WHERE p.activo = 1 ORDER BY p.nombre COLLATE NOCASE"
    ).fetchall()


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


# ---------- Helpers formulario ----------

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


def _leer_lineas_formulario():
    """Lee las líneas del formulario y aplica validaciones."""
    prod_ids = request.form.getlist("linea_producto_id")
    lotes = request.form.getlist("linea_lote")
    vencimientos = request.form.getlist("linea_vencimiento")
    cant_fact = request.form.getlist("linea_cantidad_facturada")
    cant_rec = request.form.getlist("linea_cantidad_recibida")
    costos = request.form.getlist("linea_costo")
    empaques = request.form.getlist("linea_empaque")
    resultados = request.form.getlist("linea_resultado")
    motivos = request.form.getlist("linea_motivo")
    obs_lineas = request.form.getlist("linea_observaciones")

    lineas = []
    errores = []
    for i, pid in enumerate(prod_ids):
        if not pid or not pid.isdigit():
            continue

        producto = get_db().execute(
            "SELECT maneja_vencimiento, nombre FROM productos WHERE id = ?", (int(pid),)
        ).fetchone()
        if producto is None:
            continue

        def val(lista, idx):
            return lista[idx] if idx < len(lista) else ""

        try:
            cf = float(val(cant_fact, i).replace(",", ".") or 0)
        except ValueError:
            cf = 0
        try:
            cr = float(val(cant_rec, i).replace(",", ".") or 0)
        except ValueError:
            cr = 0
        try:
            co = float(val(costos, i).replace(",", ".") or 0)
        except ValueError:
            co = 0

        lote = val(lotes, i).strip()
        vencimiento = val(vencimientos, i).strip()

        # ===== Validaciones por línea =====
        if cf <= 0:
            errores.append(f"Línea {i+1}: cantidad facturada debe ser mayor a 0.")
        if cr <= 0:
            errores.append(f"Línea {i+1}: cantidad recibida debe ser mayor a 0.")
        if co <= 0:
            errores.append(f"Línea {i+1}: el costo debe ser mayor a 0.")
        if producto["maneja_vencimiento"]:
            if not lote:
                errores.append(f"Línea {i+1} ({producto['nombre']}): el lote es obligatorio.")
            if not vencimiento:
                errores.append(f"Línea {i+1} ({producto['nombre']}): el vencimiento es obligatorio.")

        lineas.append({
            "producto_id": int(pid),
            "lote": lote or None,
            "vencimiento": vencimiento or None,
            "cantidad_facturada": cf,
            "cantidad_recibida": cr,
            "costo_unitario": co,
            "estado_empaque": val(empaques, i) or "bueno",
            "resultado": val(resultados, i) or "aceptado",
            "motivo_rechazo": val(motivos, i).strip() or None,
            "observaciones": val(obs_lineas, i).strip() or None,
        })
    return lineas, errores


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

        # ===== Validaciones de cabecera =====
        if not proveedor_id or not proveedor_id.isdigit():
            errores.insert(0, "Debes seleccionar un proveedor.")
        if not factura and not remision:
            errores.insert(0, "Debes indicar el número de factura o de remisión.")
        if not lineas:
            errores.insert(0, "Debes agregar al menos una línea.")

        if not errores:
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
                        "resultado, motivo_rechazo, observaciones) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (rec_id, l["producto_id"], l["lote"], l["vencimiento"],
                         l["cantidad_facturada"], l["cantidad_recibida"], l["costo_unitario"],
                         l["estado_empaque"], l["resultado"], l["motivo_rechazo"], l["observaciones"]),
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
                errores.append(f"Error al guardar: {e}")

        for e in errores:
            flash(e, "error")
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
        if l["resultado"] == "rechazado":
            estado = "rechazado"
            cantidad = 0
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

        if cantidad > 0:
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


# ---------- Alta rápida de producto desde recepción ----------

def _producto_duplicado(nombre, laboratorio_id, concentracion):
    """Verifica si ya existe un producto con mismo nombre+laboratorio+concentración."""
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
    if not unidad_venta_id or not unidad_venta_id.isdigit():
        return jsonify({"ok": False, "error": "Debes elegir la unidad de venta."}), 400

    # ===== Bloqueo de duplicados =====
    dup = _producto_duplicado(nombre, int(laboratorio_id), concentracion)
    if dup:
        return jsonify({
            "ok": False,
            "error": f"Ya existe un producto idéntico: {dup['codigo']} — {dup['nombre']}. "
                     f"Si es una presentación distinta, cambia la concentración o el laboratorio.",
            "duplicado_id": dup["id"],
        }), 409

    try:
        precio = float((request.form.get("precio_venta") or "0").replace(",", ".") or 0)
    except ValueError:
        precio = 0.0

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
             registro, registro_vence, precio, int(unidad_venta_id),
             maneja_venc, requiere_formula, cadena_frio, control_especial, ahora()),
        )
        db.commit()
        registrar("producto_creado_rapido", "productos", cur.lastrowid,
                  f"código={codigo} nombre={nombre} (desde recepción)")

        # Devolver también el "nombre largo" para el select
        lab = db.execute("SELECT nombre FROM catalogos WHERE id = ?", (int(laboratorio_id),)).fetchone()
        return jsonify({
            "ok": True,
            "id": cur.lastrowid,
            "codigo": codigo,
            "nombre": nombre,
            "concentracion": concentracion or "",
            "laboratorio": lab["nombre"] if lab else "",
            "registro_sanitario": registro or "",
            "maneja_vencimiento": maneja_venc,
            "cadena_frio": cadena_frio,
            "control_especial": control_especial,
        })
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "Ya existe un producto con ese código."}), 400

# ---------- Búsqueda de productos para autocompletado ----------

def _fila_a_dict(f):
    return {
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
    """Búsqueda de productos para autocompletado. Mínimo 3 caracteres, 8 resultados."""
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
    """Búsqueda exacta por código de barras (para escaneo)."""
    codigo = (request.args.get("codigo") or "").strip()
    if not codigo:
        return jsonify({"ok": False, "error": "Código vacío."})
    fila = get_db().execute(
        _SELECT_BUSQUEDA + "WHERE p.activo = 1 AND p.codigo_barras = ? LIMIT 1",
        (codigo,),
    ).fetchone()
    if fila is None:
        return jsonify({"ok": False, "error": "Producto no encontrado."})
    return jsonify({"ok": True, "producto": _fila_a_dict(fila)})

# ---------- PDF ----------

@bp.route("/<int:rec_id>/pdf")
@login_required
def pdf(rec_id):
    rec = _obtener(rec_id)
    lineas = _lineas_de(rec_id)
    proveedor = get_db().execute("SELECT * FROM proveedores WHERE id = ?",
                                 (rec["proveedor_id"],)).fetchone()
    config = obtener_config()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                            title=f"Recepción {rec['numero']}")

    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("t", parent=estilos["Title"], fontSize=14,
                            textColor=colors.HexColor("#0a4f8a"))
    sub = ParagraphStyle("s", parent=estilos["Normal"], fontSize=9,
                         textColor=colors.HexColor("#555"))
    celda = ParagraphStyle("c", parent=estilos["Normal"], fontSize=7.5, leading=9)
    celda_chica = ParagraphStyle("cc", parent=estilos["Normal"], fontSize=6.5, leading=8)

    elementos = []
    elementos.append(Paragraph(config.get("razon_social") or "Droguería", titulo))
    nit = config.get("nit") or ""
    direccion = config.get("direccion") or ""
    linea2 = " · ".join([x for x in [f"NIT {nit}", direccion] if x])
    if linea2:
        elementos.append(Paragraph(linea2, sub))
    elementos.append(Spacer(1, 10))
    elementos.append(Paragraph(f"<b>Recepción técnica N° {rec['numero']}</b>", estilos["Heading2"]))
    elementos.append(Spacer(1, 6))

    info = [
        ["Fecha:", rec["fecha"], "Estado:", ESTADOS.get(rec["estado"], rec["estado"])],
        ["Proveedor:", proveedor["razon_social"] if proveedor else "—", "NIT:",
         proveedor["nit"] if proveedor else "—"],
        ["Factura N°:", rec["factura_numero"] or "—", "Remisión:", rec["remision_numero"] or "—"],
        ["Temperatura llegada:", f"{rec['temperatura_llegada']} °C" if rec["temperatura_llegada"] is not None else "—",
         "Recibido por:", rec["recibido_por_nombre"] or "—"],
    ]
    tabla_info = Table(info, colWidths=[3 * cm, 6 * cm, 3 * cm, 5 * cm])
    tabla_info.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elementos.append(tabla_info)
    elementos.append(Spacer(1, 10))

    # ===== Tabla con RS =====
    encabezados = ["Producto", "Reg. INVIMA", "Lote", "Vence",
                   "Cant. Fact.", "Cant. Rec.", "Costo", "Empaque", "Resultado"]
    data = [[Paragraph(f"<b>{h}</b>", celda_chica) for h in encabezados]]
    for l in lineas:
       producto_txt = f"{l['producto_codigo']} — {l['producto_nombre']}"
       if l["concentracion"]:
            producto_txt += f" {l['concentracion']}"
       if l["lab_nombre"]:
            producto_txt += f"<br/><i>{l['lab_nombre']}</i>"
       data.append([
            Paragraph(producto_txt, celda_chica),
            Paragraph(l["producto_registro"] or "—", celda_chica),
            Paragraph(l["lote"] or "—", celda_chica),
            Paragraph(l["vencimiento"] or "—", celda_chica),
            Paragraph(f"{l['cantidad_facturada']:.2f}", celda_chica),
            Paragraph(f"{l['cantidad_recibida']:.2f}", celda_chica),
            Paragraph(f"${l['costo_unitario']:.2f}", celda_chica),
            Paragraph(EMPAQUES.get(l["estado_empaque"], l["estado_empaque"]), celda_chica),
            Paragraph(RESULTADOS.get(l["resultado"], l["resultado"]), celda_chica),
        ])
    tabla = Table(
        data,
        colWidths=[4.6 * cm, 2.2 * cm, 1.6 * cm, 1.6 * cm, 1.5 * cm, 1.5 * cm, 1.5 * cm, 1.5 * cm, 1.8 * cm],
        repeatRows=1,
    )
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe6ef")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c4cd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7f9")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elementos.append(tabla)

    if rec["observaciones"]:
        elementos.append(Spacer(1, 10))
        elementos.append(Paragraph(f"<b>Observaciones:</b> {rec['observaciones']}", sub))

    elementos.append(Spacer(1, 25))
    regente = config.get("regente_nombre") or ""
    tarjeta = config.get("regente_tarjeta") or ""
    if regente:
        elementos.append(Paragraph(
            f"<br/><br/>_______________________________________<br/>"
            f"<b>{regente}</b><br/>Director Técnico — TP {tarjeta or '—'}", sub))

    doc.build(elementos)
    buffer.seek(0)
    nombre = f"{rec['numero']}.pdf"
    return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                     download_name=nombre)