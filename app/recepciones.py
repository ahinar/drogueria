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
        "p.maneja_vencimiento "
        "FROM recepcion_lineas rl JOIN productos p ON p.id = rl.producto_id "
        "WHERE rl.recepcion_id = ? ORDER BY rl.id",
        (rec_id,),
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


# ---------- Nueva / Editar ----------

def _productos():
    return get_db().execute(
        "SELECT id, codigo, nombre, maneja_vencimiento, cadena_frio, control_especial, "
        "registro_sanitario, registro_vence "
        "FROM productos WHERE activo = 1 ORDER BY nombre COLLATE NOCASE"
    ).fetchall()


def _proveedores():
    return get_db().execute(
        "SELECT id, nit, razon_social FROM proveedores WHERE activo = 1 "
        "ORDER BY razon_social COLLATE NOCASE"
    ).fetchall()


def _contexto_form(rec=None):
    unidades = get_db().execute(
        "SELECT id, nombre, cantidad FROM unidades_medida WHERE activo = 1 ORDER BY cantidad, nombre"
    ).fetchall()
    return {
        "proveedores": _proveedores(),
        "productos": _productos(),
        "unidades": unidades,
        "estados": ESTADOS,
        "empaques": EMPAQUES,
        "resultados": RESULTADOS,
        "numero_sugerido": _siguiente_numero() if not rec else None,
        "recepcion": rec,
        "lineas": _lineas_de(rec["id"]) if rec else [],
    }


def _guardar_foto(archivo, rec_id):
    """Guarda la foto opcional en static/uploads/recepciones/<rec_id>.<ext>."""
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

        # Leer líneas
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
        for i, pid in enumerate(prod_ids):
            if not pid or not pid.isdigit():
                continue
            try:
                cf = float((cant_fact[i] if i < len(cant_fact) else "0").replace(",", ".") or 0)
                cr = float((cant_rec[i] if i < len(cant_rec) else "0").replace(",", ".") or 0)
                co = float((costos[i] if i < len(costos) else "0").replace(",", ".") or 0)
            except ValueError:
                cf, cr, co = 0, 0, 0
            lineas.append({
                "producto_id": int(pid),
                "lote": (lotes[i] if i < len(lotes) else "").strip() or None,
                "vencimiento": (vencimientos[i] if i < len(vencimientos) else "").strip() or None,
                "cantidad_facturada": cf,
                "cantidad_recibida": cr,
                "costo_unitario": co,
                "estado_empaque": (empaques[i] if i < len(empaques) else "bueno") or "bueno",
                "resultado": (resultados[i] if i < len(resultados) else "aceptado") or "aceptado",
                "motivo_rechazo": (motivos[i] if i < len(motivos) else "").strip() or None,
                "observaciones": (obs_lineas[i] if i < len(obs_lineas) else "").strip() or None,
            })

        errores = []
        if not proveedor_id or not proveedor_id.isdigit():
            errores.append("Debes seleccionar un proveedor.")
        if not lineas:
            errores.append("Debes agregar al menos una línea.")

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

                # Foto opcional
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
    aprobadas = 0
    for l in lineas:
        if l["resultado"] == "rechazado":
            estado = "rechazado"
            cantidad = 0
        else:
            estado = "disponible"
            cantidad = l["cantidad_recibida"]
            aprobadas += 1

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
    celda = ParagraphStyle("c", parent=estilos["Normal"], fontSize=8)

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

    encabezados = ["Producto", "Lote", "Vence", "Cant. Fact.", "Cant. Rec.", "Costo", "Empaque", "Resultado"]
    data = [[Paragraph(f"<b>{h}</b>", celda) for h in encabezados]]
    for l in lineas:
        data.append([
            Paragraph(f"{l['producto_codigo']} — {l['producto_nombre']}", celda),
            Paragraph(l["lote"] or "—", celda),
            Paragraph(l["vencimiento"] or "—", celda),
            Paragraph(f"{l['cantidad_facturada']:.2f}", celda),
            Paragraph(f"{l['cantidad_recibida']:.2f}", celda),
            Paragraph(f"${l['costo_unitario']:.2f}", celda),
            Paragraph(EMPAQUES.get(l["estado_empaque"], l["estado_empaque"]), celda),
            Paragraph(RESULTADOS.get(l["resultado"], l["resultado"]), celda),
        ])
    tabla = Table(data, colWidths=[5 * cm, 2 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm],
                  repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe6ef")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c4cd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7f9")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
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
@bp.route("/api/crear-producto", methods=["POST"])
@login_required
def api_crear_producto():
    """Alta rápida de producto desde el formulario de recepción."""
    from .productos import _siguiente_codigo

    nombre = (request.form.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"ok": False, "error": "El nombre es obligatorio."}), 400

    codigo = (request.form.get("codigo") or "").strip() or _siguiente_codigo()
    registro = (request.form.get("registro_sanitario") or "").strip() or None
    registro_vence = (request.form.get("registro_vence") or "").strip() or None
    unidad_venta_id = request.form.get("unidad_venta_id", "").strip()

    try:
        precio = float((request.form.get("precio_venta") or "0").replace(",", ".") or 0)
    except ValueError:
        precio = 0.0

    if not unidad_venta_id or not unidad_venta_id.isdigit():
        return jsonify({"ok": False, "error": "Debes elegir la unidad de venta."}), 400

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
            "INSERT INTO productos (codigo, nombre, registro_sanitario, registro_vence, "
            "precio_venta, unidad_venta_id, maneja_vencimiento, requiere_formula, "
            "cadena_frio, control_especial, activo, creado_en) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
            (codigo, nombre, registro, registro_vence, precio, int(unidad_venta_id),
             maneja_venc, requiere_formula, cadena_frio, control_especial, ahora()),
        )
        db.commit()
        registrar("producto_creado_rapido", "productos", cur.lastrowid,
                  f"código={codigo} nombre={nombre} (desde recepción)")
        return jsonify({
            "ok": True,
            "id": cur.lastrowid,
            "codigo": codigo,
            "nombre": nombre,
            "registro_sanitario": registro or "",
            "maneja_vencimiento": maneja_venc,
        })
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "Ya existe un producto con ese código."}), 400