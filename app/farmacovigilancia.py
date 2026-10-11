"""
FARMACOVIGILANCIA (Fase 4.5)
============================

PARA QUÉ (para aprender):
    Farmacovigilancia = estar pendiente de los problemas que causan los
    medicamentos ya en uso, y REPORTARLOS. La droguería, como parte de la
    Red Nacional de Farmacovigilancia, registra y reporta:
      - RAM: sospecha de reacción adversa (le salió brote, le dio mareo...)
      - Fallo terapéutico: el medicamento no hizo efecto
      - Error de medicación: se entregó o se tomó mal
      - Problema de calidad: el producto vino dañado, cambiado de color, etc.

    PLAZOS para reportar (lineamientos del INVIMA y de las Secretarías):
      - GRAVE (hospitalización, riesgo de muerte, discapacidad...): máximo 72 horas.
      - NO GRAVE: hasta el día 5 del mes siguiente.
      - No se hacen "reportes en cero" (si no pasó nada, no se reporta nada).

    EL REPORTE: lo hace el profesional en el formulario en línea del INVIMA
    (eReporting) o por el medio que indique la Secretaría de Salud. Este
    módulo guarda el caso con los datos mínimos (los del formato FOREAM),
    imprime un PDF con esos datos y, cuando se reporta, guarda la fecha y
    el número del reporte.

    Del paciente solo se guardan INICIALES, edad y sexo (protección de datos).

QUIÉN PUEDE:
    Ver y registrar un caso: todos (el auxiliar es el que suele enterarse).
    Editar y marcar como reportado: administrador y DT.

TABLA (migración 33 en app/db.py): farmacovigilancia.
"""
from datetime import date, timedelta
from io import BytesIO

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   send_file, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db

bp = Blueprint("farmacovigilancia", __name__, url_prefix="/farmacovigilancia")

JEFES = ("administrador", "director_tecnico")
EREPORTING = "https://primaryreporting.who-umc.org/CO"     # formulario en línea del INVIMA

TIPOS = {
    "ram": "Sospecha de reacción adversa (RAM)",
    "fallo": "Fallo terapéutico (no hizo efecto)",
    "error": "Error de medicación",
    "calidad": "Problema de calidad del producto",
}
DESENLACES = {
    "recuperado": "Se recuperó",
    "recuperando": "Se está recuperando",
    "no_recuperado": "No se ha recuperado",
    "secuelas": "Se recuperó con secuelas",
    "muerte": "Murió",
    "desconocido": "No se sabe",
}
SEXOS = {"F": "Femenino", "M": "Masculino", "O": "Otro / no dice"}
CAMPOS_TEXTO = ("paciente_iniciales", "paciente_edad", "medicamento", "lote", "laboratorio", "registro_sanitario",
                "dosis", "indicacion", "descripcion", "accion", "observaciones")


def plazo_reporte(fecha_conocimiento, grave):
    """Fecha límite para reportar: grave = 72 horas (3 días); no grave = día 5 del mes siguiente."""
    if grave:
        return fecha_conocimiento + timedelta(days=3)
    siguiente = (fecha_conocimiento.replace(day=28) + timedelta(days=4)).replace(day=1)
    return siguiente.replace(day=5)


def _con_estado(fila, hoy=None):
    hoy = hoy or date.today()
    d = dict(fila)
    d["tipo_texto"] = TIPOS[d["tipo"]]
    d["desenlace_texto"] = DESENLACES.get(d["desenlace"] or "", "—")
    if d["reportado"]:
        d["estado_texto"], d["estado_color"], d["dias"] = "Reportado", "verde", None
    else:
        d["dias"] = (date.fromisoformat(d["plazo_reporte"]) - hoy).days
        if d["dias"] < 0:
            d["estado_texto"], d["estado_color"] = "Plazo vencido", "rojo"
        else:
            d["estado_texto"], d["estado_color"] = "Por reportar", "rojo" if d["grave"] else "amarillo"
    return d


def casos_por_reportar(hoy=None):
    """Casos sin reportar: todos los graves, y los no graves cuando faltan 5 días o menos (aviso del Inicio)."""
    hoy = hoy or date.today()
    filas = get_db().execute("SELECT * FROM farmacovigilancia WHERE reportado = 0 ORDER BY plazo_reporte").fetchall()
    return [f for f in filas if f["grave"] or (date.fromisoformat(f["plazo_reporte"]) - hoy).days <= 5]


def _obtener(caso_id):
    fila = get_db().execute("SELECT * FROM farmacovigilancia WHERE id = ?", (caso_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def _siguiente_numero(db):
    fila = db.execute("SELECT numero FROM farmacovigilancia ORDER BY id DESC LIMIT 1").fetchone()
    return f"FV-{(int(fila['numero'].split('-')[-1]) + 1) if fila else 1:04d}"


def _productos():
    """Para la lista de sugerencias del campo medicamento."""
    return get_db().execute("SELECT id, codigo, nombre FROM productos WHERE activo = 1 "
                            "ORDER BY nombre COLLATE NOCASE").fetchall()


def _leer_form():
    """Lee el formulario y valida. Devuelve (datos, errores)."""
    hoy = date.today()
    d = {k: (request.form.get(k) or "").strip() for k in CAMPOS_TEXTO}
    d["tipo"] = request.form.get("tipo")
    d["grave"] = 1 if request.form.get("grave") == "1" else 0
    d["paciente_sexo"] = request.form.get("paciente_sexo") if request.form.get("paciente_sexo") in SEXOS else None
    d["desenlace"] = request.form.get("desenlace") if request.form.get("desenlace") in DESENLACES else None
    d["paciente_iniciales"] = d["paciente_iniciales"].upper()[:6]
    errores = []
    try:
        d["fecha_conocimiento"] = date.fromisoformat(request.form.get("fecha_conocimiento") or "")
        if d["fecha_conocimiento"] > hoy:
            errores.append("La fecha en que se supo no puede ser futura.")
    except ValueError:
        errores.append("Indica la fecha en que la droguería se enteró.")
        d["fecha_conocimiento"] = hoy
    try:
        d["fecha_inicio"] = date.fromisoformat(request.form.get("fecha_inicio") or "").isoformat()
    except ValueError:
        d["fecha_inicio"] = None
    if d["tipo"] not in TIPOS:
        errores.append("Elige qué tipo de problema es.")
    if not d["medicamento"]:
        errores.append("Escribe el medicamento.")
    if not d["descripcion"]:
        errores.append("Describe qué pasó.")
    # Si el medicamento es uno de los productos del programa, se enlaza y se
    # completan laboratorio y registro sanitario si quedaron en blanco
    d["producto_id"] = None
    texto = d["medicamento"]
    codigo = texto.split(" · ")[0].strip() if " · " in texto else None
    p = get_db().execute(
        "SELECT p.id, p.nombre, p.registro_sanitario, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS lab FROM productos p "
        "WHERE p.codigo = ? OR UPPER(p.nombre) = UPPER(?) LIMIT 1", (codigo or "", texto)).fetchone()
    if p:
        d["producto_id"], d["medicamento"] = p["id"], p["nombre"]
        d["laboratorio"] = d["laboratorio"] or (p["lab"] or "")
        d["registro_sanitario"] = d["registro_sanitario"] or (p["registro_sanitario"] or "")
    return d, errores


# ----------------------------------------------------------------------
# Rutas
# ----------------------------------------------------------------------

@bp.route("/")
@login_required
def lista():
    filtro = request.args.get("filtro", "todos")
    sql = "SELECT * FROM farmacovigilancia"
    if filtro == "pendientes":
        sql += " WHERE reportado = 0"
    casos = [_con_estado(f) for f in get_db().execute(sql + " ORDER BY fecha_conocimiento DESC, id DESC").fetchall()]
    return render_template("farmacovigilancia/lista.html", casos=casos, filtro=filtro, ereporting=EREPORTING)


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    d = {"fecha_conocimiento": date.today(), "tipo": "ram", "grave": 0}
    if request.method == "POST":
        d, errores = _leer_form()
        if not errores:
            db = get_db()
            numero = _siguiente_numero(db)
            plazo = plazo_reporte(d["fecha_conocimiento"], d["grave"])
            cur = db.execute(
                "INSERT INTO farmacovigilancia (numero, fecha_conocimiento, fecha_inicio, tipo, grave, paciente_iniciales, "
                "paciente_edad, paciente_sexo, producto_id, medicamento, lote, laboratorio, registro_sanitario, dosis, "
                "indicacion, descripcion, desenlace, accion, plazo_reporte, observaciones, usuario_id, usuario_nombre, "
                "creado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (numero, d["fecha_conocimiento"].isoformat(), d["fecha_inicio"], d["tipo"], d["grave"],
                 d["paciente_iniciales"] or None, d["paciente_edad"] or None, d["paciente_sexo"], d["producto_id"],
                 d["medicamento"], d["lote"].upper() or None, d["laboratorio"] or None, d["registro_sanitario"] or None,
                 d["dosis"] or None, d["indicacion"] or None, d["descripcion"], d["desenlace"], d["accion"] or None,
                 plazo.isoformat(), d["observaciones"] or None, g.user["id"], g.user["nombre"], ahora()))
            db.commit()
            registrar("farmacovigilancia_caso", "farmacovigilancia", cur.lastrowid,
                      f"{numero} {d['tipo']} grave={d['grave']} {d['medicamento']}")
            flash(f"Caso {numero} registrado. Se debe reportar a más tardar el {plazo.strftime('%d/%m/%Y')}"
                  + (" (es GRAVE: 72 horas)." if d["grave"] else "."), "ok")
            return redirect(url_for("farmacovigilancia.ver", caso_id=cur.lastrowid))
        for e in errores:
            flash(e, "error")
    return render_template("farmacovigilancia/form.html", d=d, nuevo=True, tipos=TIPOS, desenlaces=DESENLACES,
                           sexos=SEXOS, productos=_productos(), hoy=date.today().isoformat())


@bp.route("/<int:caso_id>/editar", methods=["GET", "POST"])
@roles_required(*JEFES)
def editar(caso_id):
    caso = _obtener(caso_id)
    d = dict(caso, fecha_conocimiento=date.fromisoformat(caso["fecha_conocimiento"]))
    if request.method == "POST":
        d, errores = _leer_form()
        if not errores:
            plazo = plazo_reporte(d["fecha_conocimiento"], d["grave"])
            db = get_db()
            db.execute(
                "UPDATE farmacovigilancia SET fecha_conocimiento=?, fecha_inicio=?, tipo=?, grave=?, paciente_iniciales=?, "
                "paciente_edad=?, paciente_sexo=?, producto_id=?, medicamento=?, lote=?, laboratorio=?, "
                "registro_sanitario=?, dosis=?, indicacion=?, descripcion=?, desenlace=?, accion=?, plazo_reporte=?, "
                "observaciones=?, actualizado_en=? WHERE id=?",
                (d["fecha_conocimiento"].isoformat(), d["fecha_inicio"], d["tipo"], d["grave"],
                 d["paciente_iniciales"] or None, d["paciente_edad"] or None, d["paciente_sexo"], d["producto_id"],
                 d["medicamento"], d["lote"].upper() or None, d["laboratorio"] or None, d["registro_sanitario"] or None,
                 d["dosis"] or None, d["indicacion"] or None, d["descripcion"], d["desenlace"], d["accion"] or None,
                 plazo.isoformat(), d["observaciones"] or None, ahora(), caso_id))
            db.commit()
            registrar("farmacovigilancia_editado", "farmacovigilancia", caso_id, caso["numero"])
            flash("Caso actualizado.", "ok")
            return redirect(url_for("farmacovigilancia.ver", caso_id=caso_id))
        for e in errores:
            flash(e, "error")
        d["id"] = caso_id
    return render_template("farmacovigilancia/form.html", d=d, nuevo=False, tipos=TIPOS, desenlaces=DESENLACES,
                           sexos=SEXOS, productos=_productos(), hoy=date.today().isoformat())


@bp.route("/<int:caso_id>")
@login_required
def ver(caso_id):
    caso = _con_estado(_obtener(caso_id))
    # Si el lote está en el inventario, se ofrece ir a bloquearlo (problemas de calidad sobre todo)
    lote = None
    if caso["producto_id"] and caso["lote"]:
        lote = get_db().execute("SELECT id, estado, cantidad_disponible FROM lotes WHERE producto_id = ? "
                                "AND UPPER(lote) = ? ORDER BY id DESC LIMIT 1",
                                (caso["producto_id"], caso["lote"].upper())).fetchone()
    return render_template("farmacovigilancia/ver.html", c=caso, lote=lote, ereporting=EREPORTING,
                           sexos=SEXOS, hoy=date.today().isoformat())


@bp.route("/<int:caso_id>/reportado", methods=["POST"])
@roles_required(*JEFES)
def reportado(caso_id):
    """Guarda que el caso ya se reportó (fecha, por dónde y el número que dio el sistema)."""
    caso = _obtener(caso_id)
    volver = redirect(url_for("farmacovigilancia.ver", caso_id=caso_id))
    try:
        fecha = date.fromisoformat(request.form.get("fecha_reporte") or "")
    except ValueError:
        fecha = None
    medio = (request.form.get("medio_reporte") or "").strip()
    if fecha is None or fecha > date.today() or fecha.isoformat() < caso["fecha_conocimiento"]:
        flash("La fecha del reporte debe estar entre la fecha en que se supo y hoy.", "error")
        return volver
    if not medio:
        flash("Escribe por dónde se reportó (eReporting, Secretaría...).", "error")
        return volver
    db = get_db()
    db.execute("UPDATE farmacovigilancia SET reportado = 1, fecha_reporte = ?, medio_reporte = ?, numero_reporte = ?, "
               "actualizado_en = ? WHERE id = ?",
               (fecha.isoformat(), medio, (request.form.get("numero_reporte") or "").strip() or None, ahora(), caso_id))
    db.commit()
    registrar("farmacovigilancia_reportado", "farmacovigilancia", caso_id, f"{caso['numero']} {fecha} {medio}")
    tarde = fecha.isoformat() > caso["plazo_reporte"]
    flash(f"{caso['numero']} marcado como reportado." + (" Quedó fuera del plazo." if tarde else ""), "ok")
    return volver


@bp.route("/<int:caso_id>/pdf")
@login_required
def pdf(caso_id):
    """El caso con los datos mínimos del reporte (los del formato FOREAM), para el archivo."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    from .configuracion import obtener_config
    from .pdf_utils import COLOR_SUAVE, encabezado_pdf, estilo_tabla, pie_de_pagina

    c = _con_estado(_obtener(caso_id))
    config = obtener_config()
    f = lambda iso: f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}" if iso else "—"
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.4 * cm,
                            bottomMargin=1.6 * cm, title=f"Farmacovigilancia {c['numero']}")
    base = getSampleStyleSheet()
    celda = ParagraphStyle("Celda", parent=base["Normal"], fontSize=9, leading=12)
    h = ParagraphStyle("H", parent=base["Normal"], fontSize=10.5, spaceBefore=8, spaceAfter=4)
    sub = ParagraphStyle("Sub", parent=base["Normal"], fontSize=9, textColor=COLOR_SUAVE)
    el = list(encabezado_pdf(config, f"REPORTE DE FARMACOVIGILANCIA N.º {c['numero']}"))

    def bloque(titulo, filas):
        el.append(Paragraph(titulo, h))
        t = Table([[a, Paragraph(str(b or "—"), celda)] for a, b in filas], colWidths=[4.6 * cm, doc.width - 4.6 * cm])
        t.setStyle(estilo_tabla(cabecera=False))
        el.append(t)

    bloque("1. Paciente", [("Iniciales", c["paciente_iniciales"]), ("Edad", c["paciente_edad"]),
                           ("Sexo", SEXOS.get(c["paciente_sexo"] or "", "—"))])
    bloque("2. Medicamento", [("Medicamento", c["medicamento"]), ("Lote", c["lote"]), ("Laboratorio", c["laboratorio"]),
                              ("Registro sanitario", c["registro_sanitario"]), ("Dosis, vía y frecuencia", c["dosis"]),
                              ("Para qué lo tomaba", c["indicacion"])])
    bloque("3. Evento", [("Tipo", c["tipo_texto"]), ("¿Grave?", "Sí" if c["grave"] else "No"),
                         ("Empezó", f(c["fecha_inicio"])), ("La droguería se enteró", f(c["fecha_conocimiento"])),
                         ("Qué pasó", c["descripcion"]), ("Qué se hizo", c["accion"]), ("Desenlace", c["desenlace_texto"])])
    bloque("4. Reportante y reporte", [
        ("Establecimiento", config.get("razon_social") or config.get("nombre_comercial")),
        ("Reporta", config.get("regente_nombre")), ("Registró en la droguería", c["usuario_nombre"]),
        ("Plazo para reportar", f(c["plazo_reporte"])),
        ("Reportado", f"{f(c['fecha_reporte'])} · {c['medio_reporte']}" + (f" · N.º {c['numero_reporte']}" if c["numero_reporte"] else "")
         if c["reportado"] else "Pendiente"),
        ("Observaciones", c["observaciones"])])
    el.append(Spacer(1, 28))
    el.append(Paragraph(f"_______________________________________<br/><b>{config.get('regente_nombre') or ''}</b><br/>"
                        f"Director Técnico — Tarjeta profesional {config.get('regente_tarjeta') or '—'}", sub))
    doc.build(el, onFirstPage=pie_de_pagina, onLaterPages=pie_de_pagina)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=f"{c['numero']}.pdf")
