"""Utilidades para generar encabezados de PDFs con logo y datos del negocio."""
from pathlib import Path

from flask import current_app
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, Table, TableStyle


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
        textColor=colors.HexColor("#0a4f8a"), spaceAfter=2,
        alignment=1,
    )
    sub_style = ParagraphStyle(
        "sub_emp", fontSize=8.5,
        textColor=colors.HexColor("#555555"),
        alignment=1,
    )
    doc_style = ParagraphStyle(
        "doc_titulo", fontSize=12,
        textColor=colors.HexColor("#1a2733"),
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

    # Título del documento
    elementos.append(Paragraph(titulo_pdf, doc_style))
    if subtitulo_extra:
        elementos.append(Paragraph(subtitulo_extra, sub_style))

    return elementos