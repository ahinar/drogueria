"""RECEPCIÓN · ACTA EN PDF (la que se imprime y se firma).

Versión 1.1.15: esto estaba en app/recepciones.py (casi 1.500 líneas). Ahora la recepción
está en tres archivos, por tema, con las mismas direcciones (/recepciones/...):
    recepciones.py           -> la recepción: lista, nueva, guardar a medias, ver, aprobar
    recepciones_productos.py -> buscar y crear productos sin salir de la recepción
    recepciones_acta.py      -> (este) el acta de recepción técnica en PDF
Las rutas se registran en el mismo blueprint "recepciones" (bp).
"""
from io import BytesIO

from flask import send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .auth import login_required
from .configuracion import obtener_config
from .db import get_db
# Lo que comparte con la recepción (está en app/recepciones.py)
from .recepciones import EMPAQUES, ESTADOS, RESULTADOS, _lineas_de, _obtener, bp


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
    subtit = ParagraphStyle("st", parent=estilos["Normal"], fontSize=9,
                            textColor=colors.HexColor("#555"))
    celda = ParagraphStyle("c", parent=estilos["Normal"], fontSize=6.8, leading=8.2)
    celda_chica = ParagraphStyle("cc", parent=estilos["Normal"], fontSize=6.3, leading=7.5)
    celda_head = ParagraphStyle("ch", parent=estilos["Normal"], fontSize=6.5,
                                leading=7.5, textColor=colors.HexColor("#0F766E"))
    seccion = ParagraphStyle("s", parent=estilos["Heading3"], fontSize=9,
                             textColor=colors.HexColor("#0F766E"), spaceBefore=6, spaceAfter=3)

    elementos = []

    # ===== ENCABEZADO con logo =====
    from .pdf_utils import encabezado_pdf, pie_de_pagina
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

    # Versión 1.1.8: los datos generales van en 2 filas (antes 4) para que quepan
    # más productos en la primera hoja. Cada fila tiene 4 parejas "Etiqueta: dato".
    datos_gen = [
        ["Fecha:", fecha_dt, "Proveedor:", proveedor["razon_social"] if proveedor else "—",
         "NIT:", proveedor["nit"] if proveedor else "—", "Estado:", estado_txt],
        ["Factura N°:", rec["factura_numero"] or "—", "Remisión N°:", rec["remision_numero"] or "—",
         "T° llegada:", temp_llegada, "Recibido por:", recibido],
    ]
    tabla_gen = Table(datos_gen, colWidths=[1.8 * cm, 3.6 * cm, 2.0 * cm, 8.1 * cm,
                                            1.6 * cm, 3.0 * cm, 2.2 * cm, 4.8 * cm])
    tabla_gen.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        # Las etiquetas (columnas 0, 2, 4 y 6) en gris
        *[("TEXTCOLOR", (c, 0), (c, -1), colors.HexColor("#555")) for c in (0, 2, 4, 6)],
    ]))
    elementos.append(tabla_gen)
    elementos.append(Spacer(1, 4))

    # ===== TABLA DE LÍNEAS =====
    elementos.append(Paragraph("DETALLE DE PRODUCTOS RECIBIDOS", seccion))

    encabezados = [
        "#", "Producto / Concentración", "Principio activo (DCI)",
        "Forma / Presentación", "Reg. INVIMA", "Lote",
        "Vence", "Vida útil", "Cant.", "Empaque",
        "Cond. especiales", "Resultado"
    ]
    data = [[Paragraph(f"<b>{h}</b>", celda_head) for h in encabezados]]

    # ---- Versión 1.1.8: AL MENOS 20 PRODUCTOS POR HOJA (pedido de Fernando) ----
    # Antes cada producto ocupaba 3 renglones (nombre / concentración / laboratorio,
    # uno debajo del otro) y cabían unos 13 por hoja. Ahora todo va SEGUIDO en el
    # mismo renglón, separado por " · ", y la columna del producto es más ancha.
    # Así cada producto ocupa 1 renglón (2 si el nombre es muy largo).
    hoy = _dt.now().date()
    for i, l in enumerate(lineas, 1):
        producto_txt = f"<b>{l['producto_nombre']}</b>"
        if l["concentracion"]:
            producto_txt += f" {l['concentracion']}"
        if l["lab_nombre"]:
            producto_txt += f" · <i>{l['lab_nombre']}</i>"

        forma_txt = l["forma_nombre"] or "—"
        if l["unidad_nombre"]:
            forma_txt += f" · <i>{l['unidad_nombre']}</i>"

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
                    vida_txt = f'<font color="{color}"><b>{pct:.0f}%</b></font> {dias} d'
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
        cond_txt = " ".join(conds) if conds else "—"       # seguidas, en un solo renglón

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

    # Anchos de las 12 columnas (la hoja acostada deja 27,1 cm). La del producto
    # pasó de 4,2 a 6,8 cm para que el nombre, la concentración y el laboratorio
    # quepan en un solo renglón; la del registro INVIMA, de 2,4 a 3,2 cm, para
    # que el número no se parta en dos renglones.
    tabla = Table(
        data,
        colWidths=[0.6 * cm, 6.8 * cm, 2.7 * cm, 2.6 * cm, 3.2 * cm, 1.8 * cm,
                   1.6 * cm, 1.5 * cm, 1.2 * cm, 1.4 * cm, 2.0 * cm, 1.6 * cm],
        repeatRows=1,          # el encabezado de la tabla se repite en cada hoja
    )
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe6ef")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8c4cd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7f9")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        # Menos espacio arriba y abajo de cada renglón (antes 2,5): caben más por hoja
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
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

    doc.build(elementos, onFirstPage=pie_de_pagina, onLaterPages=pie_de_pagina)
    buffer.seek(0)
    nombre = f"Acta_recepcion_{rec['numero']}.pdf"
    return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                     download_name=nombre)
