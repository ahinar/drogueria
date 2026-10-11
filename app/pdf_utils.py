"""Utilidades para generar encabezados de PDFs con logo y datos del negocio."""
from pathlib import Path

from flask import current_app
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, Table, TableStyle


# =====================================================================
# MISMO ASPECTO EN TODOS LOS PDF (actas, reportes, inventario...)
#   - encabezado_pdf(): logo, datos del negocio y título (arriba)
#   - pie_de_pagina():  "Página N · impreso el ... por ..." (abajo, en todas las hojas)
#   - estilo_tabla():   tablas con el mismo encabezado de color y rayado
# Los colores son los del tema "Verde salud" (static/css/temas.css).
# =====================================================================
COLOR_MARCA = colors.HexColor("#0F766E")        # --acento
COLOR_MARCA_FUERTE = colors.HexColor("#115E59")  # --acento-fuerte
COLOR_MARCA_SUAVE = colors.HexColor("#E6F3F1")   # --acento-suave
COLOR_TEXTO = colors.HexColor("#13201D")         # --texto
COLOR_SUAVE = colors.HexColor("#5B6B66")         # --texto-suave
COLOR_BORDE = colors.HexColor("#D5DEDB")
COLOR_RAYADO = colors.HexColor("#F7FAF9")


def estilo_tabla(extra=None, cabecera=True):
    """Estilo común de las tablas de los PDF. `extra` = reglas propias de esa tabla."""
    reglas = [
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, COLOR_BORDE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1 if cabecera else 0), (-1, -1), [colors.white, COLOR_RAYADO]),
    ]
    if cabecera:
        reglas += [("BACKGROUND", (0, 0), (-1, 0), COLOR_MARCA_SUAVE),
                   ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_MARCA_FUERTE),
                   ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    return TableStyle(reglas + list(extra or []))


def pie_de_pagina(canvas, doc):
    """Pie de TODAS las hojas: nombre del negocio, quién y cuándo imprimió, y número de página.

    Se usa así:  doc.build(elementos, onFirstPage=pie_de_pagina, onLaterPages=pie_de_pagina)
    """
    from datetime import datetime
    from flask import g, has_request_context
    from .configuracion import obtener_config
    try:
        config = obtener_config()
        negocio = config.get("nombre_comercial") or config.get("razon_social") or "Droguería"
    except Exception:
        negocio = "Droguería"
    usuario = ""
    if has_request_context() and getattr(g, "user", None):
        usuario = f" por {g.user['nombre']}"
    ancho, _alto = doc.pagesize
    canvas.saveState()
    canvas.setStrokeColor(COLOR_BORDE)
    canvas.setLineWidth(0.5)
    y = doc.bottomMargin - 0.35 * cm
    canvas.line(doc.leftMargin, y + 0.3 * cm, ancho - doc.rightMargin, y + 0.3 * cm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(COLOR_SUAVE)
    canvas.drawString(doc.leftMargin, y, negocio)
    canvas.drawCentredString(ancho / 2, y, f"Impreso el {datetime.now():%d/%m/%Y %H:%M}{usuario}")
    canvas.drawRightString(ancho - doc.rightMargin, y, f"Página {doc.page}")
    canvas.restoreState()


def encabezado_pdf(config, titulo_pdf, subtitulo_extra=None):
    """Devuelve una lista de flowables para el encabezado del PDF.

    Uso:
        elementos = []
        elementos.extend(encabezado_pdf(config, "ACTA DE RECEPCIÓN TÉCNICA N° REC-0001"))
        ...
    """
    elementos = []

    # Estilos
    titulo_style = ParagraphStyle(
        "titulo_emp", fontSize=13,
        textColor=COLOR_MARCA, spaceAfter=2,
        alignment=1,
    )
    sub_style = ParagraphStyle(
        "sub_emp", fontSize=8.5,
        textColor=COLOR_SUAVE,
        alignment=1,
    )
    doc_style = ParagraphStyle(
        "doc_titulo", fontSize=12,
        textColor=COLOR_TEXTO,
        alignment=1, spaceBefore=6, spaceAfter=3,
    )

    # Datos empresa
    razon = config.get("razon_social") or "Droguería"
    partes = []
    if config.get("nit"): partes.append(f"NIT {config['nit']}")
    if config.get("direccion"): partes.append(config["direccion"])
    if config.get("ciudad"): partes.append(config["ciudad"])
    if config.get("telefono"): partes.append(f"Tel. {config['telefono']}")

    # ¿Hay logo?
    logo_ruta = config.get("logo_ruta")
    logo_path = None
    if logo_ruta:
        ruta_fisica = Path(current_app.static_folder) / logo_ruta
        if ruta_fisica.exists():
            logo_path = str(ruta_fisica)

    if logo_path:
        # Tabla: logo a la izquierda, datos de empresa al centro
        logo_img = Image(logo_path, width=2.2 * cm, height=2.2 * cm, kind="proportional")
        logo_img.hAlign = "LEFT"

        texto_empresa = [
            Paragraph(razon, titulo_style),
        ]
        if partes:
            texto_empresa.append(Paragraph(" · ".join(partes), sub_style))

        tabla = Table(
            [[logo_img, texto_empresa]],
            colWidths=[3 * cm, None],
        )
        tabla.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        elementos.append(tabla)
    else:
        # Sin logo: solo texto centrado (comportamiento anterior)
        elementos.append(Paragraph(razon, titulo_style))
        if partes:
            elementos.append(Paragraph(" · ".join(partes), sub_style))

    # Línea de color y título del documento
    from reportlab.platypus import HRFlowable
    elementos.append(HRFlowable(width="100%", thickness=1.2, color=COLOR_MARCA, spaceBefore=4, spaceAfter=2))
    elementos.append(Paragraph(f"<b>{titulo_pdf}</b>", doc_style))
    if subtitulo_extra:
        elementos.append(Paragraph(subtitulo_extra, sub_style))

    return elementos