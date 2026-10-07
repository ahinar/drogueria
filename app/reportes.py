"""Reportes: historial de temperaturas con gráfico y PDF, y otros por venir."""
from datetime import datetime
from io import BytesIO

from flask import (Blueprint, current_app, make_response, redirect,
                   render_template, request, send_file, url_for)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from .auth import login_required
from .configuracion import obtener_config
from .db import get_db
from .pdf_utils import encabezado_pdf

bp = Blueprint("reportes", __name__, url_prefix="/reportes")


# ---------------- Utilidades ----------------

def _filtros_temperatura():
    """Lee los filtros del query string (comunes para pantalla y PDF)."""
    return {
        "zona_id": request.args.get("zona_id", type=int),
        "desde": request.args.get("desde", "").strip(),
        "hasta": request.args.get("hasta", "").strip(),
        "fuera": request.args.get("fuera", "") == "1",
    }


def _query_temperaturas(filtros):
    cond, params = [], []
    if filtros["zona_id"]:
        cond.append("r.zona_id = ?")
        params.append(filtros["zona_id"])
    if filtros["desde"]:
        cond.append("r.fecha >= ?")
        params.append(filtros["desde"] + " 00:00:00")
    if filtros["hasta"]:
        cond.append("r.fecha <= ?")
        params.append(filtros["hasta"] + " 23:59:59")
    if filtros["fuera"]:
        cond.append("r.dentro_de_rango = 0")
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    sql = (
        "SELECT r.*, z.nombre AS zona_nombre "
        "FROM temperatura_registros r "
        "JOIN zonas_temperatura z ON z.id = r.zona_id "
        f"{where} ORDER BY r.fecha ASC"
    )
    return get_db().execute(sql, params).fetchall()


def _zonas():
    return get_db().execute("SELECT id, nombre FROM zonas_temperatura ORDER BY nombre").fetchall()


# ---------------- Rutas ----------------

@bp.route("/")
@login_required
def index():
    return render_template("reportes/index.html")


@bp.route("/temperaturas")
@login_required
def temperaturas():
    filtros = _filtros_temperatura()
    filas = _query_temperaturas(filtros)

    datos = [
        {
            "fecha": f["fecha"],
            "zona": f["zona_nombre"],
            "temperatura": f["temperatura"],
            "humedad": f["humedad"],
            "en_rango": bool(f["dentro_de_rango"]),
        }
        for f in filas
    ]

    return render_template(
        "reportes/temperaturas.html",
        filas=filas[-500:],
        datos=datos,
        zonas=_zonas(),
        filtros=filtros,
        total=len(filas),
    )


@bp.route("/temperaturas/pdf")
@login_required
def temperaturas_pdf():
    filtros = _filtros_temperatura()
    filas = _query_temperaturas(filtros)
    config = obtener_config()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title="Historial de temperaturas",
        author=config.get("razon_social") or "Droguería",
    )

    estilos = getSampleStyleSheet()
    estilo_sub = ParagraphStyle(
        "Sub", parent=estilos["Normal"], fontSize=9,
        textColor=colors.HexColor("#555555"),
    )
    estilo_celda = ParagraphStyle("Celda", parent=estilos["Normal"], fontSize=8)
    estilo_celda_chica = ParagraphStyle("CeldaChica", parent=estilos["Normal"], fontSize=7.5)

    elementos = []
    elementos.extend(encabezado_pdf(config, "REPORTE DE TEMPERATURA Y HUMEDAD"))
    elementos.append(Spacer(1, 8))

    zona_txt = "Todas las zonas"
    if filtros["zona_id"]:
        for z in _zonas():
            if z["id"] == filtros["zona_id"]:
                zona_txt = z["nombre"]
                break
    rango = []
    if filtros["desde"]:
        rango.append(f"desde {filtros['desde']}")
    if filtros["hasta"]:
        rango.append(f"hasta {filtros['hasta']}")
    solo_fuera = " · Solo lecturas fuera de rango" if filtros["fuera"] else ""
    elementos.append(Paragraph(
        f"Zona: <b>{zona_txt}</b>" + (f" · Rango: {' '.join(rango)}" if rango else "") + solo_fuera,
        estilo_sub,
    ))
    elementos.append(Paragraph(
        f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
        f"Total de registros: {len(filas)}",
        estilo_sub,
    ))
    elementos.append(Spacer(1, 10))

    encabezados = ["Fecha", "Zona", "Temp (°C)", "Humedad (%)", "En rango", "Usuario", "Acción correctiva"]
    data = [[Paragraph(f"<b>{h}</b>", estilo_celda) for h in encabezados]]
    for f in filas:
        data.append([
            Paragraph(f["fecha"], estilo_celda_chica),
            Paragraph(f["zona_nombre"], estilo_celda_chica),
            Paragraph(f"{f['temperatura']:.1f}", estilo_celda_chica),
            Paragraph(f"{f['humedad']:.1f}" if f["humedad"] is not None else "—", estilo_celda_chica),
            Paragraph("Sí" if f["dentro_de_rango"] else "NO", estilo_celda_chica),
            Paragraph(f["usuario_nombre"] or "—", estilo_celda_chica),
            Paragraph(f["accion_correctiva"] or "—", estilo_celda_chica),
        ])
    if len(data) == 1:
        data.append([Paragraph("Sin registros con esos filtros.", estilo_celda)] + [""] * 6)

    tabla = Table(
        data,
        colWidths=[3.6 * cm, 2.5 * cm, 1.8 * cm, 2.0 * cm, 1.8 * cm, 2.4 * cm, 8.0 * cm],
        repeatRows=1,
    )
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe6ef")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c4cd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    elementos.append(tabla)

    elementos.append(Spacer(1, 20))
    regente = config.get("regente_nombre") or ""
    tarjeta = config.get("regente_tarjeta") or ""
    if regente:
        elementos.append(Paragraph(
            f"<br/><br/>_______________________________________<br/>"
            f"<b>{regente}</b><br/>Director Técnico — Tarjeta profesional {tarjeta or '—'}",
            estilo_sub,
        ))

    pie = config.get("pie_pagina") or ""
    if pie:
        elementos.append(Spacer(1, 10))
        elementos.append(Paragraph(f"<i>{pie}</i>", estilo_sub))

    doc.build(elementos)
    buffer.seek(0)

    nombre_archivo = f"temperaturas_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return send_file(
        buffer, mimetype="application/pdf",
        as_attachment=True, download_name=nombre_archivo,
    )


# ============================================================
# PLANTILLA MENSUAL DE TEMPERATURAS
# ============================================================

MESES_ES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def _dias_del_mes(mes, anio):
    import calendar
    return calendar.monthrange(anio, mes)[1]


def _turno_de_hora(hora_str):
    try:
        hh, _ = map(int, hora_str.split(":"))
    except (ValueError, AttributeError):
        return "am"
    if hh < 12:
        return "am"
    if hh < 19:
        return "pm"
    return "noche"


@bp.route("/temperaturas/mensual", methods=["GET"])
@login_required
def temperaturas_mensual_form():
    return render_template("reportes/temperaturas_mensual.html", zonas=_zonas())


@bp.route("/temperaturas/mensual/pdf")
@login_required
def temperaturas_mensual_pdf():
    """Genera la plantilla mensual en PDF (una sola hoja)."""
    zona_id = request.args.get("zona_id", type=int)
    mes = request.args.get("mes", type=int) or datetime.now().month
    anio = request.args.get("anio", type=int) or datetime.now().year

    if not zona_id:
        return redirect(url_for("reportes.temperaturas_mensual_form"))

    zona = get_db().execute(
        "SELECT * FROM zonas_temperatura WHERE id = ?", (zona_id,)
    ).fetchone()
    if zona is None:
        return redirect(url_for("reportes.temperaturas_mensual_form"))

    config = obtener_config()
    dias = _dias_del_mes(mes, anio)

    inicio = f"{anio:04d}-{mes:02d}-01"
    fin = f"{anio:04d}-{mes:02d}-{dias:02d} 23:59:59"
    registros = get_db().execute(
        "SELECT * FROM temperatura_registros "
        "WHERE zona_id = ? AND fecha >= ? AND fecha <= ? "
        "ORDER BY fecha ASC",
        (zona_id, inicio, fin),
    ).fetchall()

    por_dia = {}
    for r in registros:
        dia = int(r["fecha"][8:10])
        try:
            hora = int(r["fecha"][11:13])
        except (ValueError, TypeError):
            continue
        if hora < 12:
            turno = "am"
        elif hora < 19:
            turno = "pm"
        else:
            turno = "noche"
        key = (dia, turno)
        if key not in por_dia:
            por_dia[key] = r

    # ===== PDF =====
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=0.7 * cm, rightMargin=0.7 * cm,
        topMargin=0.5 * cm, bottomMargin=0.5 * cm,
        title=f"Registro mensual · {zona['nombre']} · {MESES_ES[mes]} {anio}",
    )

    estilos = getSampleStyleSheet()
    estilo_celda = ParagraphStyle("cc", parent=estilos["Normal"], fontSize=9, leading=10.5)
    estilo_head = ParagraphStyle("ch", parent=estilos["Normal"], fontSize=8.5,
                                 leading=10, textColor=colors.HexColor("#0a4f8a"),
                                 alignment=1)
    estilo_head_grupo = ParagraphStyle("chg", parent=estilos["Normal"], fontSize=9.5,
                                       leading=11, textColor=colors.white,
                                       alignment=1)
    estilo_centrado = ParagraphStyle("cen", parent=estilos["Normal"], fontSize=9,
                                     leading=10.5, alignment=1)

    elementos = []

    # ===== Encabezado con logo =====
    from pathlib import Path

    logo_ruta = config.get("logo_ruta")
    logo_path = None
    if logo_ruta:
        ruta_fisica = Path(current_app.static_folder) / logo_ruta
        if ruta_fisica.exists():
            logo_path = str(ruta_fisica)

    razon = config.get("razon_social") or "Droguería"
    partes = []
    if config.get("nit"): partes.append(f"NIT {config['nit']}")
    if config.get("direccion"): partes.append(config["direccion"])
    if config.get("ciudad"): partes.append(config["ciudad"])
    if config.get("telefono"): partes.append(f"Tel. {config['telefono']}")

    titulo_style = ParagraphStyle("t", fontSize=11, leading=13,
                                  textColor=colors.HexColor("#0a4f8a"), alignment=1)
    sub_style = ParagraphStyle("s", fontSize=8, leading=9.5,
                               textColor=colors.HexColor("#555"), alignment=1)

    if logo_path:
        logo_img = Image(logo_path, width=1.6 * cm, height=1.6 * cm, kind="proportional")
        texto_emp = [Paragraph(razon, titulo_style)]
        if partes:
            texto_emp.append(Paragraph(" · ".join(partes), sub_style))
        tabla_head = Table([[logo_img, texto_emp]], colWidths=[2.0 * cm, None])
        tabla_head.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        elementos.append(tabla_head)
    else:
        elementos.append(Paragraph(razon, titulo_style))
        if partes:
            elementos.append(Paragraph(" · ".join(partes), sub_style))

    elementos.append(Spacer(1, 2))
    elementos.append(Paragraph(
        "<b>REGISTRO MENSUAL DE TEMPERATURA Y HUMEDAD</b>", titulo_style))
    elementos.append(Spacer(1, 2))

    rango = f"{zona['temp_min']} a {zona['temp_max']} °C"
    if zona["controla_humedad"]:
        rango += f" · Humedad {zona['humedad_min']}–{zona['humedad_max']} %"
    elementos.append(Paragraph(
        f"<b>Zona:</b> {zona['nombre']} &nbsp;&nbsp; "
        f"<b>Rango:</b> {rango} &nbsp;&nbsp; "
        f"<b>Mes/Año:</b> {MESES_ES[mes]} {anio}",
        estilo_celda,
    ))
    elementos.append(Spacer(1, 4))

    # ===== Turnos =====
    horarios = [h.strip() for h in (zona["horarios"] or "").split(",") if h.strip()]
    turnos_config = []
    for h in horarios:
        t = _turno_de_hora(h)
        if t in ("am", "pm") and t not in [x[0] for x in turnos_config]:
            turnos_config.append((t, h))
    tipos_presentes = [x[0] for x in turnos_config]
    if "am" not in tipos_presentes:
        turnos_config.insert(0, ("am", "09:00"))
    if "pm" not in tipos_presentes:
        turnos_config.append(("pm", "18:00"))
    turnos_config.sort(key=lambda x: 0 if x[0] == "am" else 1)
    turnos_config = turnos_config[:2]

    # ===== Tabla =====
    fila1 = [
        Paragraph("<b>Día</b>", estilo_head),
        Paragraph("<b>TURNO AM</b>", estilo_head_grupo),
        "", "", "",
        Paragraph("<b>TURNO PM</b>", estilo_head_grupo),
        "", "", "",
    ]
    subencabezados = ["Hora", "Temp °C", "% HR", "Registró"]
    fila2 = [Paragraph("", estilo_head)]
    for t, h in turnos_config:
        for sub in subencabezados:
            fila2.append(Paragraph(f"<b>{sub}</b>", estilo_head))

    data = [fila1, fila2]
    for d in range(1, dias + 1):
        fila = [Paragraph(str(d), estilo_centrado)]
        for t, h in turnos_config:
            r = por_dia.get((d, t))
            if r:
                hora_txt = r["fecha"][11:16]
                temp_txt = f"{r['temperatura']:.1f}"
                hum_txt = f"{r['humedad']:.0f}" if r["humedad"] is not None else ""
                user_txt = (r["usuario_nombre"] or "")[:12]
            else:
                hora_txt = temp_txt = hum_txt = user_txt = ""
            fila += [
                Paragraph(hora_txt, estilo_centrado),
                Paragraph(temp_txt, estilo_centrado),
                Paragraph(hum_txt, estilo_centrado),
                Paragraph(user_txt, estilo_centrado),
            ]
        data.append(fila)

    n_turnos = len(turnos_config)
    ancho_util = 19.5 * cm
    ancho_dia = 1.0 * cm
    ancho_cols = (ancho_util - ancho_dia) / (4 * n_turnos)
    col_widths = [ancho_dia] + [ancho_cols] * (4 * n_turnos)

    tabla = Table(data, colWidths=col_widths, repeatRows=2)
    estilos_tabla = [
        ("BACKGROUND", (0, 0), (0, 1), colors.HexColor("#dbe6ef")),
        ("BACKGROUND", (1, 0), (4, 0), colors.HexColor("#0a6ebd")),
        ("BACKGROUND", (5, 0), (8, 0), colors.HexColor("#0a6ebd")),
        ("SPAN", (0, 0), (0, 1)),
        ("SPAN", (1, 0), (4, 0)),
        ("SPAN", (5, 0), (8, 0)),
        ("BACKGROUND", (1, 1), (-1, 1), colors.HexColor("#dbe6ef")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8c4cd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("BACKGROUND", (5, 2), (8, -1), colors.HexColor("#f4f7f9")),
    ]
    tabla.setStyle(TableStyle(estilos_tabla))
    elementos.append(tabla)

    # ===== Bloque final =====
    elementos.append(Spacer(1, 8))
    regente = config.get("regente_nombre") or ""
    tarjeta = config.get("regente_tarjeta") or ""

    elementos.append(Paragraph(
        "<b>Observaciones del mes:</b> ______________________________________________<br/>"
        "______________________________________________________________________",
        estilo_celda,
    ))
    elementos.append(Spacer(1, 12))
    elementos.append(Paragraph(
        "<b>Verificado por:</b><br/><br/>"
        "_______________________________________<br/>"
        f"<b>{regente}</b><br/>"
        f"Director Técnico — Tarjeta profesional {tarjeta or '—'}",
        estilo_celda,
    ))

    doc.build(elementos)
    buffer.seek(0)
    nombre = f"temperaturas_{zona['nombre']}_{anio}_{mes:02d}.pdf".replace(" ", "_")
    return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                     download_name=nombre)