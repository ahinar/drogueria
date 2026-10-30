"""
QUEJAS Y RECLAMOS — PQRS (Fase 4.4)
===================================

PARA QUÉ (para aprender):
    PQRS = Peticiones, Quejas, Reclamos y Sugerencias (aquí también las
    felicitaciones). La Secretaría de Salud revisa que la droguería tenga
    cómo recibirlas, que las responda a tiempo y que haga algo para que el
    problema no se repita (acción de mejora). Aunque nunca haya llegado una,
    el registro debe existir.

    - Cualquier usuario del programa puede REGISTRAR una (el auxiliar es
      quien casi siempre la recibe).
    - Cada una queda con un número (PQ-0001) y una FECHA LÍMITE para
      responder: 15 días hábiles (Ley 1755 de 2015), sin contar sábados,
      domingos ni festivos (ver app/festivos.py).
    - El DT la RESPONDE: qué se le contestó, la acción de mejora y si el
      usuario quedó satisfecho. Así queda cerrada.
    - Aviso en el Inicio cuando falta poco para la fecha límite o ya pasó.

QUIÉN PUEDE:
    Ver y registrar: todos. Responder, cerrar y reabrir: administrador y DT.

TABLA (migración 33 en app/db.py): pqrs.
"""
from datetime import date
from io import BytesIO

from flask import (Blueprint, flash, g, redirect, render_template, request, send_file,
                   url_for)

from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db
from .utiles import obtener_o_404, siguiente_numero   # versión 1.1.15: ayudas comunes (app/utiles.py)
from .festivos import dias_habiles_entre, sumar_dias_habiles

bp = Blueprint("pqrs", __name__, url_prefix="/quejas")

JEFES = ("administrador", "director_tecnico")
DIAS_HABILES = 15            # plazo para responder (Ley 1755 de 2015)
DIAS_AVISO = 3               # avisar cuando falten 3 días hábiles o menos

TIPOS = {
    "queja": "Queja",
    "reclamo": "Reclamo",
    "peticion": "Petición",
    "sugerencia": "Sugerencia",
    "felicitacion": "Felicitación",
}
CANALES = {
    "presencial": "En persona",
    "telefono": "Teléfono",
    "whatsapp": "WhatsApp",
    "buzon": "Buzón de sugerencias",
    "escrito": "Por escrito / correo",
    "otro": "Otro",
}
SATISFECHO = {"si": "Sí", "no": "No", "sin_dato": "No se pudo saber"}
PROCESOS = ["Atención al usuario", "Dispensación", "Precio", "Producto (calidad)", "Producto agotado",
            "Tiempo de espera", "Instalaciones", "Otro"]


def estado_plazo(fila, hoy=None):
    """Para una PQRS ABIERTA: ('vencida' | 'por_vencer' | 'a_tiempo', días hábiles que quedan)."""
    hoy = hoy or date.today()
    quedan = dias_habiles_entre(hoy, date.fromisoformat(fila["fecha_limite"]))
    if hoy > date.fromisoformat(fila["fecha_limite"]):
        return "vencida", quedan
    return ("por_vencer" if quedan <= DIAS_AVISO else "a_tiempo"), quedan


def _con_estado(fila, hoy=None):
    d = dict(fila)
    d["tipo_texto"] = TIPOS[d["tipo"]]
    d["canal_texto"] = CANALES[d["canal"]]
    if d["estado"] == "abierta":
        d["plazo"], d["quedan"] = estado_plazo(d, hoy)
        d["estado_texto"], d["estado_color"] = {
            "vencida": ("Vencida sin responder", "rojo"),
            "por_vencer": ("Por responder", "amarillo"),
            "a_tiempo": ("Abierta", "amarillo"),
        }[d["plazo"]]
    else:
        d["plazo"], d["quedan"] = None, None
        a_tiempo = d["fecha_respuesta"] and d["fecha_respuesta"] <= d["fecha_limite"]
        d["estado_texto"] = "Respondida" + ("" if a_tiempo else " (tarde)")
        d["estado_color"] = "verde" if a_tiempo else "gris"
    return d


def pqrs_por_vencer(hoy=None):
    """Abiertas vencidas o con 3 días hábiles o menos (para el aviso del Inicio)."""
    filas = get_db().execute("SELECT * FROM pqrs WHERE estado = 'abierta' ORDER BY fecha_limite").fetchall()
    return [(estado_plazo(f, hoy), f) for f in filas if estado_plazo(f, hoy)[0] in ("vencida", "por_vencer")]


def _obtener(pqrs_id):
    return obtener_o_404("pqrs", pqrs_id)


def _siguiente_numero(db):
    return siguiente_numero(db, "pqrs", "PQ")


# ----------------------------------------------------------------------
# Lista
# ----------------------------------------------------------------------

@bp.route("/")
@login_required
def lista():
    hoy = date.today()
    filtro = request.args.get("filtro", "abiertas")
    anio = request.args.get("anio", type=int) or hoy.year
    sql, params = "SELECT * FROM pqrs WHERE substr(fecha, 1, 4) = ?", [str(anio)]
    if filtro == "abiertas":
        sql += " AND estado = 'abierta'"
    elif filtro == "cerradas":
        sql += " AND estado = 'cerrada'"
    filas = [_con_estado(f, hoy) for f in get_db().execute(sql + " ORDER BY fecha DESC, id DESC", params).fetchall()]

    # Indicadores del año (los del objetivo de calidad "atender bien al usuario")
    todas = [_con_estado(f, hoy) for f in get_db().execute(
        "SELECT * FROM pqrs WHERE substr(fecha, 1, 4) = ?", (str(anio),)).fetchall()]
    cerradas = [d for d in todas if d["estado"] == "cerrada" and d["tipo"] != "felicitacion"]
    a_tiempo = sum(1 for d in cerradas if d["fecha_respuesta"] <= d["fecha_limite"])
    indicadores = {
        "total": len(todas),
        "por_tipo": {k: sum(1 for d in todas if d["tipo"] == k) for k in TIPOS},
        "abiertas": sum(1 for d in todas if d["estado"] == "abierta"),
        "a_tiempo_pct": round(a_tiempo * 100 / len(cerradas)) if cerradas else None,
    }
    return render_template("pqrs/lista.html", filas=filas, filtro=filtro, anio=anio, ind=indicadores,
                           tipos=TIPOS, anios=list(range(hoy.year - 2, hoy.year + 1)))


# ----------------------------------------------------------------------
# Registrar (todos)
# ----------------------------------------------------------------------

@bp.route("/nueva", methods=["GET", "POST"])
@login_required
def nueva():
    hoy = date.today()
    datos = {"fecha": hoy.isoformat(), "tipo": "queja", "canal": "presencial"}
    if request.method == "POST":
        datos = {k: (request.form.get(k) or "").strip() for k in
                 ("fecha", "tipo", "canal", "cliente_nombre", "cliente_contacto", "descripcion", "proceso")}
        errores = []
        try:
            fecha = date.fromisoformat(datos["fecha"])
            if fecha > hoy:
                errores.append("La fecha no puede ser futura.")
        except ValueError:
            errores.append("Indica la fecha en que se recibió.")
            fecha = hoy
        if datos["tipo"] not in TIPOS:
            errores.append("Elige el tipo.")
        if datos["canal"] not in CANALES:
            errores.append("Elige por dónde llegó.")
        if not datos["descripcion"]:
            errores.append("Escribe lo que dijo el usuario.")
        if not errores:
            db = get_db()
            numero = _siguiente_numero(db)
            limite = sumar_dias_habiles(fecha, DIAS_HABILES)
            cur = db.execute(
                "INSERT INTO pqrs (numero, fecha, tipo, canal, cliente_nombre, cliente_contacto, descripcion, proceso, "
                "fecha_limite, estado, usuario_id, usuario_nombre, creado_en) "
                "VALUES (?,?,?,?,?,?,?,?,?, 'abierta', ?,?,?)",
                (numero, fecha.isoformat(), datos["tipo"], datos["canal"], datos["cliente_nombre"] or None,
                 datos["cliente_contacto"] or None, datos["descripcion"], datos["proceso"] or None,
                 limite.isoformat(), g.user["id"], g.user["nombre"], ahora()))
            db.commit()
            registrar("pqrs_registrada", "pqrs", cur.lastrowid, f"{numero} {datos['tipo']}")
            flash(f"{TIPOS[datos['tipo']]} {numero} registrada. Hay que responderla a más tardar el "
                  f"{limite.strftime('%d/%m/%Y')} (15 días hábiles).", "ok")
            return redirect(url_for("pqrs.ver", pqrs_id=cur.lastrowid))
        for e in errores:
            flash(e, "error")
    return render_template("pqrs/form.html", d=datos, tipos=TIPOS, canales=CANALES, procesos=PROCESOS,
                           hoy=hoy.isoformat())


# ----------------------------------------------------------------------
# Ver, responder, reabrir
# ----------------------------------------------------------------------

@bp.route("/<int:pqrs_id>")
@login_required
def ver(pqrs_id):
    d = _con_estado(_obtener(pqrs_id))
    from .configuracion import obtener_config
    return render_template("pqrs/ver.html", d=d, satisfecho=SATISFECHO, hoy=date.today().isoformat(),
                           responde=obtener_config().get("regente_nombre") or g.user["nombre"])


@bp.route("/<int:pqrs_id>/responder", methods=["POST"])
@roles_required(*JEFES)
def responder(pqrs_id):
    d = _obtener(pqrs_id)
    volver = redirect(url_for("pqrs.ver", pqrs_id=pqrs_id))
    respuesta = (request.form.get("respuesta") or "").strip()
    try:
        fecha = date.fromisoformat(request.form.get("fecha_respuesta") or "")
    except ValueError:
        fecha = None
    satisfecho = request.form.get("satisfecho") if request.form.get("satisfecho") in SATISFECHO else "sin_dato"
    errores = []
    if not respuesta:
        errores.append("Escribe qué se le respondió al usuario.")
    if fecha is None or fecha > date.today() or fecha.isoformat() < d["fecha"]:
        errores.append("La fecha de respuesta debe estar entre la fecha en que llegó y hoy.")
    if errores:
        for e in errores:
            flash(e, "error")
        return volver
    db = get_db()
    db.execute("UPDATE pqrs SET estado = 'cerrada', respuesta = ?, fecha_respuesta = ?, accion_mejora = ?, "
               "satisfecho = ?, responde_nombre = ?, actualizado_en = ? WHERE id = ?",
               (respuesta, fecha.isoformat(), (request.form.get("accion_mejora") or "").strip() or None, satisfecho,
                (request.form.get("responde_nombre") or "").strip() or g.user["nombre"], ahora(), pqrs_id))
    db.commit()
    registrar("pqrs_respondida", "pqrs", pqrs_id, f"{d['numero']} fecha={fecha}")
    tarde = fecha.isoformat() > d["fecha_limite"]
    flash(f"{d['numero']} respondida y cerrada." + (" Quedó registrada como respondida TARDE." if tarde else ""),
          "ok")
    return volver


@bp.route("/<int:pqrs_id>/reabrir", methods=["POST"])
@roles_required(*JEFES)
def reabrir(pqrs_id):
    d = _obtener(pqrs_id)
    db = get_db()
    db.execute("UPDATE pqrs SET estado = 'abierta', actualizado_en = ? WHERE id = ?", (ahora(), pqrs_id))
    db.commit()
    registrar("pqrs_reabierta", "pqrs", pqrs_id, d["numero"])
    flash(f"{d['numero']} abierta de nuevo (la respuesta anterior se conserva hasta que la cambies).", "ok")
    return redirect(url_for("pqrs.ver", pqrs_id=pqrs_id))


@bp.route("/<int:pqrs_id>/pdf")
@login_required
def pdf(pqrs_id):
    """Constancia de la PQRS y su respuesta (para el archivo o para entregar al usuario)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    from .configuracion import obtener_config
    from .pdf_utils import encabezado_pdf, estilo_tabla, estilos_pdf, pie_de_pagina

    d = _con_estado(_obtener(pqrs_id))
    f = lambda iso: f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}" if iso else "—"
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.4 * cm,
                            bottomMargin=1.6 * cm, title=f"PQRS {d['numero']}")
    est = estilos_pdf()
    celda, sub = est["celda"], est["sub"]
    el = list(encabezado_pdf(obtener_config(), f"{d['tipo_texto'].upper()} N.º {d['numero']}"))
    filas = [
        ["Recibida", f"{f(d['fecha'])} · {d['canal_texto']} · recibió {d['usuario_nombre'] or '—'}"],
        ["Usuario", Paragraph(f"{d['cliente_nombre'] or 'Anónimo'}"
                              + (f" · {d['cliente_contacto']}" if d["cliente_contacto"] else ""), celda)],
        ["Tiene que ver con", d["proceso"] or "—"],
        ["Lo que dijo", Paragraph(d["descripcion"], celda)],
        ["Responder a más tardar", f(d["fecha_limite"])],
        ["Respuesta", Paragraph(d["respuesta"] or "Pendiente", celda)],
        ["Fecha de respuesta", f(d["fecha_respuesta"])],
        ["Acción de mejora", Paragraph(d["accion_mejora"] or "—", celda)],
        ["¿Quedó satisfecho?", SATISFECHO.get(d["satisfecho"], "—") if d["satisfecho"] else "—"],
        ["Estado", d["estado_texto"]],
    ]
    t = Table(filas, colWidths=[4.2 * cm, doc.width - 4.2 * cm])
    t.setStyle(estilo_tabla(cabecera=False))
    el.append(t)
    el.append(Spacer(1, 30))
    el.append(Paragraph(f"_______________________________________<br/><b>{d['responde_nombre'] or ''}</b><br/>"
                        "Responsable de la respuesta", sub))
    doc.build(el, onFirstPage=pie_de_pagina, onLaterPages=pie_de_pagina)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=f"{d['numero']}.pdf")
