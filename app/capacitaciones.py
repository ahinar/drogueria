"""
CAPACITACIONES (Fase 4.3)
=========================

PARA QUÉ (para aprender):
    La Secretaría de Salud revisa que el personal de la droguería se capacite
    y que haya PRUEBA de eso: un plan (cronograma) del año, y por cada
    capacitación el tema, la fecha, quién la dio, quién asistió (con firma)
    y, si se evaluó, la nota. La Resolución 591 de 2024 (residuos) también
    pide capacitar en el manejo de residuos y guardar la asistencia.

    Este módulo tiene:
      - PERSONAL: quienes trabajan en la droguería, incluso los que van de
        vez en cuando (no necesitan usuario en el programa).
      - PLAN DEL AÑO: las capacitaciones programadas. El botón "Cargar plan
        sugerido" crea 12 temas, uno por mes (se pueden cambiar).
      - Cada capacitación: se "registra como realizada" con la fecha, las
        horas, los asistentes y su nota. Se imprime el ACTA en PDF para que
        firmen, y luego se sube el acta firmada escaneada.
      - Cronograma del año en PDF y aviso en el Inicio si una capacitación
        programada ya pasó y no se ha hecho.

QUIÉN PUEDE:
    Ver: todos. Crear, registrar y editar: administrador y director técnico.

TABLAS (migración 32 en app/db.py): personal, capacitaciones,
capacitacion_asistentes.
"""
from datetime import date, datetime
from io import BytesIO

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   send_file, url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db
from .utils_imagenes import guardar_documento

bp = Blueprint("capacitaciones", __name__, url_prefix="/capacitaciones")

JEFES = ("administrador", "director_tecnico")

TIPOS = {
    "interna": "Interna (la da la droguería)",
    "externa": "Externa (laboratorio, SENA, Secretaría…)",
    "induccion": "Inducción (personal nuevo)",
}
ESTADOS = {
    "programada": ("Programada", "amarillo"),
    "realizada": ("Realizada", "verde"),
    "cancelada": ("Cancelada", "gris"),
}
MESES_ES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
            "septiembre", "octubre", "noviembre", "diciembre"]

# Plan sugerido: un tema por mes, pensado para una droguería pequeña. Cada
# tema dice qué se ve, en pocas palabras (el DT lo amplía al dictarlo).
PLAN_SUGERIDO = [
    (1, "Recepción técnica y administrativa",
     "Pasos de la recepción; qué revisar (INVIMA, lote, vencimiento, empaque, temperatura); "
     "cuarentena y rechazo; cómo se registra en el programa."),
    (2, "Almacenamiento y control de temperatura y humedad",
     "Condiciones de almacenamiento, rangos, lectura del termohigrómetro, registro AM/PM y qué hacer si se sale del rango."),
    (3, "Manejo de residuos (Resolución 591 de 2024)",
     "Clasificación de residuos y colores de canecas, guardián de cortopunzantes, almacenamiento, entrega al gestor, posconsumo."),
    (4, "Dispensación y uso adecuado de medicamentos",
     "Qué es dispensar, información al usuario, venta con fórmula, lo que el auxiliar no puede hacer, errores frecuentes."),
    (5, "Control de vencimientos y devoluciones",
     "Semáforo de vencimientos, FEFO (primero en vencer, primero en salir), devoluciones a proveedor y de clientes."),
    (6, "Limpieza, desinfección y control de plagas",
     "Planilla de limpieza, productos y diluciones, orden de limpieza, señales de plagas."),
    (7, "Farmacovigilancia",
     "Qué es un evento adverso o un problema relacionado con medicamentos, cómo se reporta, alertas sanitarias del INVIMA."),
    (8, "Cadena de frío",
     "Medicamentos refrigerados, rango 2 a 8 °C, nevera, transporte con el usuario, qué hacer si se corta la luz."),
    (9, "Atención al usuario, quejas y reclamos",
     "Trato al usuario, cómo recibir y registrar una queja, tiempos de respuesta."),
    (10, "Normatividad y precios regulados",
     "Decreto 780 de 2016, Resolución 1403 de 2007, precios máximos de venta, lo que revisa la Secretaría en la visita."),
    (11, "Bioseguridad y plan de emergencias",
     "Lavado de manos, elementos de protección, accidente con aguja, extintor, ruta de evacuación."),
    (12, "Uso del programa de la droguería",
     "POS, recepciones, temperaturas, inventario y saneamiento: cómo registrar todo bien."),
]


# ----------------------------------------------------------------------
# Ayudas
# ----------------------------------------------------------------------

def _es_jefe():
    return g.user["rol"] in JEFES


def _fecha_form(nombre, defecto=None):
    try:
        return date.fromisoformat(request.form.get(nombre) or "")
    except ValueError:
        return defecto


def _numero(nombre):
    try:
        return float((request.form.get(nombre) or "").replace(",", "."))
    except ValueError:
        return None


def _obtener(cap_id):
    fila = get_db().execute("SELECT * FROM capacitaciones WHERE id = ?", (cap_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def _con_estado(fila, hoy=None):
    """Fila -> diccionario listo para mostrar. 'atrasada' = programada con la fecha ya pasada."""
    hoy = (hoy or date.today()).isoformat()
    d = dict(fila)
    d["estado_texto"], d["estado_color"] = ESTADOS[d["estado"]]
    d["atrasada"] = d["estado"] == "programada" and bool(d["fecha_programada"]) and d["fecha_programada"] < hoy
    if d["atrasada"]:
        d["estado_texto"], d["estado_color"] = "Atrasada", "rojo"
    d["tipo_texto"] = TIPOS[d["tipo"]].split(" (")[0]
    return d


def capacitaciones_atrasadas(hoy=None):
    """Las programadas cuya fecha ya pasó (para el aviso del Inicio)."""
    hoy = (hoy or date.today()).isoformat()
    return get_db().execute("SELECT * FROM capacitaciones WHERE estado = 'programada' AND fecha_programada < ? "
                            "ORDER BY fecha_programada", (hoy,)).fetchall()


def _personal_activo():
    return get_db().execute("SELECT * FROM personal WHERE activo = 1 ORDER BY ocasional, nombre COLLATE ES").fetchall()


def _capacitador_por_defecto():
    from .configuracion import obtener_config
    return obtener_config().get("regente_nombre") or g.user["nombre"]


# ----------------------------------------------------------------------
# Plan del año
# ----------------------------------------------------------------------

@bp.route("/")
@login_required
def plan():
    hoy = date.today()
    anio = request.args.get("anio", type=int) or hoy.year
    filas = get_db().execute(
        "SELECT c.*, (SELECT COUNT(*) FROM capacitacion_asistentes a WHERE a.capacitacion_id = c.id) AS asistentes "
        "FROM capacitaciones c WHERE substr(COALESCE(c.fecha_realizada, c.fecha_programada), 1, 4) = ? "
        "ORDER BY COALESCE(c.fecha_programada, c.fecha_realizada), c.id", (str(anio),)).fetchall()
    caps = [_con_estado(f, hoy) for f in filas]
    resumen = {
        "total": sum(1 for c in caps if c["estado"] != "cancelada"),
        "realizadas": sum(1 for c in caps if c["estado"] == "realizada"),
        "atrasadas": sum(1 for c in caps if c["atrasada"]),
        "horas": sum(c["duracion_horas"] or 0 for c in caps if c["estado"] == "realizada"),
    }
    return render_template("capacitaciones/plan.html", caps=caps, anio=anio, resumen=resumen,
                           anios=list(range(hoy.year - 2, hoy.year + 2)), hay_personal=bool(_personal_activo()),
                           pestana="plan")


def fechas_del_plan(anio, meses, hoy=None):
    """Fechas para los temas del plan sugerido.

    - Un año futuro (o uno que apenas empieza): un tema por mes, el día 15.
    - El año en curso ya avanzado: no tiene sentido programar en meses que ya
      pasaron (quedarían "atrasadas" desde el primer día). Los temas se
      reparten parejo desde dentro de una semana hasta el 15 de diciembre.
    """
    hoy = hoy or date.today()
    mensual = [date(anio, mes, 15) for mes in meses]       # cada tema en su mes
    cuantos = len(mensual)
    if anio != hoy.year or not mensual or mensual[0] >= hoy:
        return mensual
    from datetime import timedelta
    inicio, fin = hoy + timedelta(days=7), date(anio, 12, 15)
    if inicio >= fin or cuantos == 1:
        return [max(inicio, fin)] * cuantos if inicio >= fin else [inicio]
    paso = (fin - inicio) / (cuantos - 1)
    return [inicio + paso * i for i in range(cuantos)]


@bp.route("/sugerido", methods=["POST"])
@roles_required(*JEFES)
def cargar_sugerido():
    """Crea el plan sugerido del año (los temas que todavía no estén ese año)."""
    anio = request.form.get("anio", type=int) or date.today().year
    db = get_db()
    existentes = {f["tema"].lower() for f in db.execute(
        "SELECT tema FROM capacitaciones WHERE substr(fecha_programada, 1, 4) = ?", (str(anio),))}
    capacitador = _capacitador_por_defecto()
    faltan = [(mes, tema, contenido) for mes, tema, contenido in PLAN_SUGERIDO if tema.lower() not in existentes]
    fechas = fechas_del_plan(anio, [mes for mes, _, _ in faltan])
    for (_, tema, contenido), fecha in zip(faltan, fechas):
        db.execute("INSERT INTO capacitaciones (tema, contenido, tipo, capacitador, fecha_programada, duracion_horas, "
                   "estado, usuario_id, usuario_nombre, creado_en) VALUES (?,?, 'interna', ?,?, 1, 'programada', ?,?,?)",
                   (tema, contenido, capacitador, fecha.isoformat(), g.user["id"], g.user["nombre"], ahora()))
    db.commit()
    nuevas = len(faltan)
    registrar("capacitaciones_plan_sugerido", "capacitaciones", None, f"anio={anio} creadas={nuevas}")
    if not nuevas:
        flash(f"El plan {anio} ya tenía todos los temas sugeridos.", "ok")
    elif all(f == date(anio, mes, 15) for f, (mes, _, _) in zip(fechas, faltan)):
        flash(f"Plan {anio}: se agregaron {nuevas} capacitación(es), una por mes (el día 15). "
              "Cámbiales la fecha si quieres.", "ok")
    else:
        flash(f"Plan {anio}: como el año ya va avanzado, las {nuevas} capacitaciones se repartieron entre el "
              f"{fechas[0].strftime('%d/%m')} y el {fechas[-1].strftime('%d/%m')}. Cámbiales la fecha si quieres.", "ok")
    return redirect(url_for("capacitaciones.plan", anio=anio))


# ----------------------------------------------------------------------
# Crear y editar una capacitación
# ----------------------------------------------------------------------

def _leer_form():
    return {
        "tema": (request.form.get("tema") or "").strip(),
        "contenido": (request.form.get("contenido") or "").strip() or None,
        "tipo": request.form.get("tipo") or "interna",
        "entidad": (request.form.get("entidad") or "").strip() or None,
        "capacitador": (request.form.get("capacitador") or "").strip() or None,
        "fecha_programada": request.form.get("fecha_programada") or None,
        "duracion_horas": _numero("duracion_horas"),
        "evaluacion": 1 if request.form.get("evaluacion") else 0,
        "observaciones": (request.form.get("observaciones") or "").strip() or None,
    }


def _validar(datos):
    errores = []
    if not datos["tema"]:
        errores.append("Escribe el tema de la capacitación.")
    if datos["tipo"] not in TIPOS:
        errores.append("Tipo no válido.")
    try:
        date.fromisoformat(datos["fecha_programada"] or "")
    except ValueError:
        errores.append("Indica la fecha programada.")
    if datos["duracion_horas"] is not None and not 0 < datos["duracion_horas"] <= 40:
        errores.append("La duración debe estar entre 0 y 40 horas.")
    return errores


@bp.route("/nueva", methods=["GET", "POST"])
@roles_required(*JEFES)
def nueva():
    datos = {"tipo": request.args.get("tipo", "interna"), "capacitador": _capacitador_por_defecto(),
             "evaluacion": 1, "duracion_horas": 1}
    if request.method == "POST":
        datos = _leer_form()
        errores = _validar(datos)
        if not errores:
            db = get_db()
            cur = db.execute(
                "INSERT INTO capacitaciones (tema, contenido, tipo, entidad, capacitador, fecha_programada, duracion_horas, "
                "evaluacion, observaciones, estado, usuario_id, usuario_nombre, creado_en) "
                "VALUES (?,?,?,?,?,?,?,?,?, 'programada', ?,?,?)",
                (datos["tema"], datos["contenido"], datos["tipo"], datos["entidad"], datos["capacitador"],
                 datos["fecha_programada"], datos["duracion_horas"], datos["evaluacion"], datos["observaciones"],
                 g.user["id"], g.user["nombre"], ahora()))
            db.commit()
            registrar("capacitacion_creada", "capacitaciones", cur.lastrowid, datos["tema"])
            flash("Capacitación programada.", "ok")
            return redirect(url_for("capacitaciones.ver", cap_id=cur.lastrowid))
        for e in errores:
            flash(e, "error")
    return render_template("capacitaciones/form.html", cap=datos, tipos=TIPOS, nueva=True, pestana="plan")


@bp.route("/<int:cap_id>/editar", methods=["GET", "POST"])
@roles_required(*JEFES)
def editar(cap_id):
    cap = _obtener(cap_id)
    if request.method == "POST":
        datos = _leer_form()
        errores = _validar(datos)
        if not errores:
            db = get_db()
            db.execute("UPDATE capacitaciones SET tema=?, contenido=?, tipo=?, entidad=?, capacitador=?, "
                       "fecha_programada=?, duracion_horas=?, evaluacion=?, observaciones=?, actualizado_en=? WHERE id=?",
                       (datos["tema"], datos["contenido"], datos["tipo"], datos["entidad"], datos["capacitador"],
                        datos["fecha_programada"], datos["duracion_horas"], datos["evaluacion"],
                        datos["observaciones"], ahora(), cap_id))
            db.commit()
            registrar("capacitacion_editada", "capacitaciones", cap_id, datos["tema"])
            flash("Capacitación actualizada.", "ok")
            return redirect(url_for("capacitaciones.ver", cap_id=cap_id))
        for e in errores:
            flash(e, "error")
        cap = dict(cap, **datos)
    return render_template("capacitaciones/form.html", cap=cap, tipos=TIPOS, nueva=False, pestana="plan")


# ----------------------------------------------------------------------
# Ver, registrar como realizada, cancelar
# ----------------------------------------------------------------------

def _asistentes(cap_id):
    return get_db().execute(
        "SELECT a.*, p.nombre, p.cargo, p.documento FROM capacitacion_asistentes a "
        "JOIN personal p ON p.id = a.personal_id WHERE a.capacitacion_id = ? ORDER BY p.nombre COLLATE ES",
        (cap_id,)).fetchall()


@bp.route("/<int:cap_id>")
@login_required
def ver(cap_id):
    cap = _con_estado(_obtener(cap_id))
    asistentes = _asistentes(cap_id)
    marcados = {a["personal_id"]: a for a in asistentes}
    # En el formulario de asistencia salen los activos y también los que ya
    # asistieron aunque hoy estén inactivos
    personal = list(_personal_activo())
    ids = {p["id"] for p in personal}
    personal += [p for p in get_db().execute("SELECT * FROM personal WHERE id IN (%s)" % ",".join("?" * len(marcados)),
                                             tuple(marcados)).fetchall() if p["id"] not in ids] if marcados else []
    return render_template("capacitaciones/ver.html", cap=cap, asistentes=asistentes, marcados=marcados,
                           personal=personal, hoy=date.today().isoformat(), pestana="plan")


@bp.route("/<int:cap_id>/realizar", methods=["POST"])
@roles_required(*JEFES)
def realizar(cap_id):
    """Registra (o corrige) que la capacitación se hizo: fecha, horas, asistentes y notas."""
    cap = _obtener(cap_id)
    volver = redirect(url_for("capacitaciones.ver", cap_id=cap_id))
    if cap["estado"] == "cancelada":
        flash("La capacitación está cancelada. Reprográmala primero.", "error")
        return volver
    fecha = _fecha_form("fecha_realizada")
    horas = _numero("duracion_horas")
    ids = [int(x) for x in request.form.getlist("personal_id") if x.isdigit()]
    errores = []
    if fecha is None or fecha > date.today():
        errores.append("Indica la fecha en que se hizo (no puede ser futura).")
    if not horas or not 0 < horas <= 40:
        errores.append("Indica cuántas horas duró (ej: 1 o 1,5).")
    if not ids:
        errores.append("Marca al menos un asistente.")
    # Notas: de 0 a 5, opcionales
    notas = {}
    for pid in ids:
        texto = (request.form.get(f"nota_{pid}") or "").replace(",", ".").strip()
        if texto:
            try:
                nota = float(texto)
            except ValueError:
                nota = -1
            if not 0 <= nota <= 5:
                errores.append("Las notas van de 0 a 5.")
                break
            notas[pid] = nota
    if errores:
        for e in errores:
            flash(e, "error")
        return volver

    archivo = cap["archivo"]
    if request.files.get("archivo") and request.files["archivo"].filename:
        archivo, error = guardar_documento(request.files["archivo"], "capacitaciones")
        if error:
            flash(f"No se guardó: {error}", "error")
            return volver

    db = get_db()
    validos = {f["id"] for f in db.execute("SELECT id FROM personal")}
    db.execute("DELETE FROM capacitacion_asistentes WHERE capacitacion_id = ?", (cap_id,))
    for pid in ids:
        if pid in validos:
            db.execute("INSERT INTO capacitacion_asistentes (capacitacion_id, personal_id, nota) VALUES (?,?,?)",
                       (cap_id, pid, notas.get(pid)))
    db.execute("UPDATE capacitaciones SET estado = 'realizada', fecha_realizada = ?, duracion_horas = ?, archivo = ?, "
               "capacitador = COALESCE(?, capacitador), actualizado_en = ? WHERE id = ?",
               (fecha.isoformat(), horas, archivo, (request.form.get("capacitador") or "").strip() or None,
                ahora(), cap_id))
    db.commit()
    registrar("capacitacion_realizada", "capacitaciones", cap_id,
              f"{cap['tema']} fecha={fecha} asistentes={len(ids)} horas={horas}")
    flash("Capacitación registrada como realizada." +
          ("" if archivo else " Imprime el acta, hazla firmar y súbela escaneada."), "ok")
    return volver


@bp.route("/<int:cap_id>/cancelar", methods=["POST"])
@roles_required(*JEFES)
def cancelar(cap_id):
    """Cancela una programada, o la vuelve a programar si estaba cancelada."""
    cap = _obtener(cap_id)
    if cap["estado"] == "realizada":
        flash("Una capacitación realizada no se cancela.", "error")
        return redirect(url_for("capacitaciones.ver", cap_id=cap_id))
    nuevo = "programada" if cap["estado"] == "cancelada" else "cancelada"
    db = get_db()
    db.execute("UPDATE capacitaciones SET estado = ?, actualizado_en = ? WHERE id = ?", (nuevo, ahora(), cap_id))
    db.commit()
    registrar("capacitacion_" + nuevo, "capacitaciones", cap_id, cap["tema"])
    flash("Capacitación cancelada." if nuevo == "cancelada" else "Capacitación programada de nuevo.", "ok")
    return redirect(url_for("capacitaciones.ver", cap_id=cap_id))


# ----------------------------------------------------------------------
# Personal
# ----------------------------------------------------------------------

def _leer_personal():
    return {
        "nombre": (request.form.get("nombre") or "").strip(),
        "documento": (request.form.get("documento") or "").strip() or None,
        "cargo": (request.form.get("cargo") or "").strip() or None,
        "fecha_ingreso": request.form.get("fecha_ingreso") or None,
        "ocasional": 1 if request.form.get("ocasional") else 0,
        "usuario_id": request.form.get("usuario_id", type=int) or None,
        "observaciones": (request.form.get("observaciones") or "").strip() or None,
    }


@bp.route("/personal", methods=["GET", "POST"])
@login_required
def personal():
    db = get_db()
    if request.method == "POST":
        if not _es_jefe():
            abort(403)
        datos = _leer_personal()
        if not datos["nombre"]:
            flash("Escribe el nombre.", "error")
        else:
            cur = db.execute("INSERT INTO personal (nombre, documento, cargo, fecha_ingreso, ocasional, usuario_id, "
                             "observaciones, activo, creado_en) VALUES (?,?,?,?,?,?,?,1,?)",
                             (datos["nombre"], datos["documento"], datos["cargo"], datos["fecha_ingreso"],
                              datos["ocasional"], datos["usuario_id"], datos["observaciones"], ahora()))
            db.commit()
            registrar("personal_creado", "personal", cur.lastrowid, datos["nombre"])
            flash(f"{datos['nombre']} agregado(a) al personal. Programa su inducción.", "ok")
        return redirect(url_for("capacitaciones.personal"))

    anio = str(date.today().year)
    filas = db.execute(
        "SELECT p.*, "
        "(SELECT COUNT(*) FROM capacitacion_asistentes a JOIN capacitaciones c ON c.id = a.capacitacion_id "
        " WHERE a.personal_id = p.id AND c.estado = 'realizada' AND substr(c.fecha_realizada, 1, 4) = :anio) AS cantidad, "
        "(SELECT COALESCE(SUM(c.duracion_horas), 0) FROM capacitacion_asistentes a JOIN capacitaciones c "
        " ON c.id = a.capacitacion_id WHERE a.personal_id = p.id AND c.estado = 'realizada' "
        " AND substr(c.fecha_realizada, 1, 4) = :anio) AS horas, "
        "(SELECT COUNT(*) FROM capacitacion_asistentes a JOIN capacitaciones c ON c.id = a.capacitacion_id "
        " WHERE a.personal_id = p.id AND c.estado = 'realizada' AND c.tipo = 'induccion') AS inducciones "
        "FROM personal p ORDER BY p.activo DESC, p.ocasional, p.nombre COLLATE ES", {"anio": anio}).fetchall()
    usuarios = db.execute("SELECT id, nombre FROM usuarios WHERE activo = 1 ORDER BY nombre").fetchall()
    return render_template("capacitaciones/personal.html", personal=filas, usuarios=usuarios, anio=anio,
                           pestana="personal")


@bp.route("/personal/<int:persona_id>", methods=["GET", "POST"])
@login_required
def persona(persona_id):
    db = get_db()
    p = db.execute("SELECT * FROM personal WHERE id = ?", (persona_id,)).fetchone()
    if p is None:
        abort(404)
    if request.method == "POST":
        if not _es_jefe():
            abort(403)
        if request.form.get("accion") == "activar":
            db.execute("UPDATE personal SET activo = ?, actualizado_en = ? WHERE id = ?",
                       (0 if p["activo"] else 1, ahora(), persona_id))
            db.commit()
            registrar("personal_" + ("retirado" if p["activo"] else "activado"), "personal", persona_id, p["nombre"])
            flash("Marcado(a) como retirado(a); su historial se conserva." if p["activo"] else "Activo(a) de nuevo.", "ok")
            return redirect(url_for("capacitaciones.personal"))
        datos = _leer_personal()
        if not datos["nombre"]:
            flash("Escribe el nombre.", "error")
        else:
            db.execute("UPDATE personal SET nombre=?, documento=?, cargo=?, fecha_ingreso=?, ocasional=?, usuario_id=?, "
                       "observaciones=?, actualizado_en=? WHERE id=?",
                       (datos["nombre"], datos["documento"], datos["cargo"], datos["fecha_ingreso"], datos["ocasional"],
                        datos["usuario_id"], datos["observaciones"], ahora(), persona_id))
            db.commit()
            registrar("personal_editado", "personal", persona_id, datos["nombre"])
            flash("Datos actualizados.", "ok")
            return redirect(url_for("capacitaciones.persona", persona_id=persona_id))
    historial = db.execute(
        "SELECT c.*, a.nota FROM capacitacion_asistentes a JOIN capacitaciones c ON c.id = a.capacitacion_id "
        "WHERE a.personal_id = ? AND c.estado = 'realizada' ORDER BY c.fecha_realizada DESC", (persona_id,)).fetchall()
    usuarios = db.execute("SELECT id, nombre FROM usuarios WHERE activo = 1 ORDER BY nombre").fetchall()
    return render_template("capacitaciones/persona.html", p=p, historial=historial, usuarios=usuarios, tipos=TIPOS,
                           pestana="personal")


# ----------------------------------------------------------------------
# PDF: acta de una capacitación y cronograma del año
# ----------------------------------------------------------------------

def _pdf(titulo, nombre_archivo, armar, horizontal=False, firma_dt=True):
    """Igual que en saneamiento: encabezado y pie de siempre; `armar` pone el contenido."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    from .configuracion import obtener_config
    from .pdf_utils import COLOR_SUAVE, encabezado_pdf, pie_de_pagina

    config = obtener_config()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4) if horizontal else A4, leftMargin=1.5 * cm,
                            rightMargin=1.5 * cm, topMargin=1.2 * cm, bottomMargin=1.5 * cm, title=titulo)
    base = getSampleStyleSheet()
    est = {
        "celda": ParagraphStyle("Celda", parent=base["Normal"], fontSize=8.5, leading=10.5),
        "normal": ParagraphStyle("Normal2", parent=base["Normal"], fontSize=9.5, leading=13),
        "sub": ParagraphStyle("Sub", parent=base["Normal"], fontSize=9, textColor=COLOR_SUAVE),
        "h": ParagraphStyle("H", parent=base["Normal"], fontSize=10.5, spaceBefore=10, spaceAfter=4),
        "ancho": doc.width,
    }
    elementos = list(encabezado_pdf(config, titulo))
    armar(elementos, est)
    regente = config.get("regente_nombre") or ""
    if firma_dt and regente:
        elementos.append(Spacer(1, 24))
        elementos.append(Paragraph(
            f"_______________________________________<br/><b>{regente}</b><br/>"
            f"Director Técnico — Tarjeta profesional {config.get('regente_tarjeta') or '—'}", est["sub"]))
    doc.build(elementos, onFirstPage=pie_de_pagina, onLaterPages=pie_de_pagina)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=nombre_archivo)


def _f(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}" if iso else "—"


@bp.route("/<int:cap_id>/acta.pdf")
@login_required
def acta_pdf(cap_id):
    """Acta para imprimir y firmar. Si aún no se ha hecho, sale con las filas en blanco
    (se imprime el día de la capacitación y se llena a mano)."""
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Spacer, Table

    from .pdf_utils import estilo_tabla

    cap = _con_estado(_obtener(cap_id))
    asistentes = _asistentes(cap_id)

    def armar(el, est):
        datos = [
            ["Tema", Paragraph(f"<b>{cap['tema']}</b>", est["celda"])],
            ["Tipo", cap["tipo_texto"] + (f" · {cap['entidad']}" if cap["entidad"] else "")],
            ["Fecha", _f(cap["fecha_realizada"]) if cap["fecha_realizada"] else "____ / ____ / ________"],
            ["Duración", f"{cap['duracion_horas']:g} hora(s)".replace(".", ",") if cap["duracion_horas"] else "______"],
            ["Capacitador", cap["capacitador"] or "—"],
            ["Contenido", Paragraph(cap["contenido"] or "", est["celda"])],
        ]
        t = Table(datos, colWidths=[3.2 * cm, est["ancho"] - 3.2 * cm])
        t.setStyle(estilo_tabla(cabecera=False))
        el.append(t)
        el.append(Paragraph("Asistentes", est["h"]))
        cab = ["N.º", "Nombre", "Documento", "Cargo"] + (["Nota (0-5)"] if cap["evaluacion"] else []) + ["Firma"]
        filas = [cab]
        # Si todavía no se ha registrado la asistencia: el personal activo ya
        # escrito (para que solo firmen) y 2 filas en blanco por si llega alguien más
        lista = list(asistentes) or ([{"nombre": p["nombre"], "documento": p["documento"], "cargo": p["cargo"],
                                       "nota": None} for p in _personal_activo()] + [None, None])
        for i, a in enumerate(lista, 1):
            fila = [str(i), a["nombre"] if a else "", (a["documento"] or "") if a else "", (a["cargo"] or "") if a else ""]
            if cap["evaluacion"]:
                fila.append(f"{a['nota']:g}".replace(".", ",") if a and a["nota"] is not None else "")
            fila.append("")
            filas.append(fila)
        anchos = [1 * cm, 5.2 * cm, 2.8 * cm, 3 * cm] + ([1.9 * cm] if cap["evaluacion"] else [])
        anchos.append(est["ancho"] - sum(anchos))
        t = Table(filas, colWidths=anchos, rowHeights=[None] + [0.9 * cm] * len(lista), repeatRows=1)
        t.setStyle(estilo_tabla([("VALIGN", (0, 1), (-1, -1), "MIDDLE")]))
        el.append(t)
        if cap["observaciones"]:
            el.append(Spacer(1, 8))
            el.append(Paragraph(f"<b>Observaciones:</b> {cap['observaciones']}", est["normal"]))
        el.append(Spacer(1, 28))
        el.append(Paragraph(f"_______________________________________<br/><b>{cap['capacitador'] or ''}</b><br/>"
                            "Capacitador", est["sub"]))

    return _pdf("ACTA DE CAPACITACIÓN", f"acta_capacitacion_{cap_id}.pdf", armar, firma_dt=False)


@bp.route("/plan.pdf")
@login_required
def plan_pdf():
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Table

    from .pdf_utils import estilo_tabla

    anio = request.args.get("anio", type=int) or date.today().year
    filas = get_db().execute(
        "SELECT c.*, (SELECT COUNT(*) FROM capacitacion_asistentes a WHERE a.capacitacion_id = c.id) AS asistentes "
        "FROM capacitaciones c WHERE substr(COALESCE(c.fecha_realizada, c.fecha_programada), 1, 4) = ? "
        "ORDER BY COALESCE(c.fecha_programada, c.fecha_realizada), c.id", (str(anio),)).fetchall()
    caps = [_con_estado(f) for f in filas]

    def armar(el, est):
        hechas = sum(1 for c in caps if c["estado"] == "realizada")
        total = sum(1 for c in caps if c["estado"] != "cancelada")
        el.append(Paragraph(f"Año <b>{anio}</b> · Programadas: {total} · Realizadas: {hechas}"
                            + (f" ({hechas * 100 // total} %)" if total else ""), est["sub"]))
        data = [["Mes", "Tema", "Tipo", "Capacitador", "Programada", "Realizada", "Horas", "Asist.", "Estado"]]
        for c in caps:
            mes = (c["fecha_programada"] or c["fecha_realizada"])[5:7]
            data.append([MESES_ES[int(mes)].capitalize(), Paragraph(c["tema"], est["celda"]), c["tipo_texto"],
                         Paragraph(c["capacitador"] or "—", est["celda"]), _f(c["fecha_programada"]),
                         _f(c["fecha_realizada"]),
                         f"{c['duracion_horas']:g}".replace(".", ",") if c["duracion_horas"] else "—",
                         str(c["asistentes"]) if c["estado"] == "realizada" else "—", c["estado_texto"]])
        if len(data) == 1:
            data.append(["—", "Sin capacitaciones este año", "", "", "", "", "", "", ""])
        t = Table(data, colWidths=[2 * cm, 7.4 * cm, 2.2 * cm, 4.2 * cm, 2.3 * cm, 2.3 * cm, 1.3 * cm, 1.3 * cm,
                                   est["ancho"] - 23 * cm], repeatRows=1)
        t.setStyle(estilo_tabla())
        el.append(t)

    return _pdf(f"CRONOGRAMA DE CAPACITACIÓN {anio}", f"cronograma_capacitacion_{anio}.pdf", armar, horizontal=True)
