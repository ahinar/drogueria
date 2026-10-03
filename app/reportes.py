"""Reportes: historial de temperaturas con gráfico y PDF, y otros por venir."""
from datetime import datetime
from io import BytesIO

from flask import (Blueprint, make_response, render_template, request,
                   send_file, url_for)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .auth import login_required
from .configuracion import obtener_config
from .db import get_db

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

    # Datos para el gráfico: [{fecha, zona, temperatura, humedad, en_rango}, ...]
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
        filas=filas[-500:],   # solo mostramos las últimas 500 en pantalla
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

    # --- Construcción del PDF ---
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title="Historial de temperaturas",
        author=config.get("razon_social") or "Droguería",
    )

    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle(
        "Titulo", parent=estilos["Title"], fontSize=16, textColor=colors.HexColor("#0a4f8a"),
    )
    estilo_sub = ParagraphStyle(
        "Sub", parent=estilos["Normal"], fontSize=9, textColor=colors.HexColor("#555555"),
    )
    estilo_celda = ParagraphStyle("Celda", parent=estilos["Normal"], fontSize=8)
    estilo_celda_chica = ParagraphStyle("CeldaChica", parent=estilos["Normal"], fontSize=7.5)

    # --- Encabezado ---
    elementos = []
    elementos.append(Paragraph(config.get("razon_social") or "Droguería", estilo_titulo))
    nit = config.get("nit") or ""
    direccion = config.get("direccion") or ""
    ciudad = config.get("ciudad") or ""
    telefono = config.get("telefono") or ""
    linea2 = " · ".join([x for x in [f"NIT {nit}", direccion, ciudad, telefono] if x])
    if linea2:
        elementos.append(Paragraph(linea2, estilo_sub))
    elementos.append(Spacer(1, 6))
    elementos.append(Paragraph("<b>Reporte de temperatura y humedad</b>", estilos["Heading2"]))
    elementos.append(Spacer(1, 4))

    # --- Filtros aplicados ---
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

    # --- Tabla ---
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
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0a4f8a")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c4cd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7f9")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elementos.append(tabla)

    # --- Firma ---
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