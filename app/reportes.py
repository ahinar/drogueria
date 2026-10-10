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

from .auth import login_required, roles_required
from .configuracion import obtener_config
from .db import get_db
from .pdf_utils import encabezado_pdf
from .temperaturas import _turno_de_hora, turno_de_hh
from . import utilidades

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
        turno = turno_de_hh(hora)   # mismos dos turnos que usa la alarma (AM / PM)
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

# ============================================================
# R2 · UTILIDADES / ESTADO DE RESULTADOS
# ============================================================
# Los cálculos están en app/utilidades.py. Aquí solo se arman las filas
# de la tabla (las mismas para la pantalla y para el PDF).

def _filas_estado(r):
    """Filas de la tabla del estado de resultados.

    Cada fila: texto, valor actual, valor anterior, tipo y si "subir es bueno"
    (para pintar el cambio en verde o rojo: más ventas = bueno, más gastos = malo).
    tipo: 'linea' (normal), 'resta' (se descuenta), 'total' (resultado), 'info' (solo informativo)
    """
    a, b = r["actual"], r["anterior"]
    filas = [
        {"texto": "Ventas (sin IVA)", "a": a["ventas"], "b": b["ventas"], "tipo": "linea", "sube_bueno": True},
        {"texto": "− Costo de lo vendido", "a": a["costo"], "b": b["costo"], "tipo": "resta", "sube_bueno": False},
        {"texto": "= Utilidad bruta", "a": a["utilidad_bruta"], "b": b["utilidad_bruta"], "tipo": "total",
         "sube_bueno": True, "margen_a": a["margen_bruto"], "margen_b": b["margen_bruto"]},
    ]
    for g_ in r["filas_gastos"]:
        filas.append({"texto": f"− {g_['categoria']}", "a": g_["actual"], "b": g_["anterior"],
                      "tipo": "resta", "sube_bueno": False, "detalle": g_["detalle"], "gasto": True})
    filas.append({"texto": "Total gastos", "a": a["total_gastos"], "b": b["total_gastos"],
                  "tipo": "subtotal", "sube_bueno": False})
    filas += [
        {"texto": "− Pérdidas: vencidos, averías y bajas", "a": a["bajas"], "b": b["bajas"],
         "tipo": "resta", "sube_bueno": False},
        {"texto": "− Pérdidas: faltantes del conteo", "a": a["faltantes_conteo"], "b": b["faltantes_conteo"],
         "tipo": "resta", "sube_bueno": False},
        {"texto": "= Utilidad neta", "a": a["utilidad_neta"], "b": b["utilidad_neta"], "tipo": "total",
         "sube_bueno": True, "margen_a": a["margen_neto"], "margen_b": b["margen_neto"], "final": True},
        {"texto": "Retiros del dueño (no es gasto)", "a": a["retiros_dueno"], "b": b["retiros_dueno"],
         "tipo": "info", "sube_bueno": None},
        {"texto": "Queda en el negocio", "a": a["queda"], "b": b["queda"], "tipo": "info", "sube_bueno": True},
    ]
    for f in filas:
        f["cambio"] = utilidades.variacion(f["a"], f["b"])
    return filas


def _leer_periodo():
    return utilidades.estado_de_resultados(
        mes=request.args.get("mes"), desde=request.args.get("desde"), hasta=request.args.get("hasta"))


@bp.route("/utilidades")
@login_required
@roles_required("administrador", "director_tecnico")
def utilidades_ver():
    r = _leer_periodo()
    return render_template("reportes/utilidades.html", r=r, filas=_filas_estado(r),
                           meses=utilidades.meses_disponibles(),
                           args=request.args)


def _pesos(n):
    """1234567.8 -> '$1.234.568' ; negativos con signo: '-$5.000'"""
    texto = f"${abs(n):,.0f}".replace(",", ".")
    return f"-{texto}" if n < -0.5 else texto


@bp.route("/utilidades/pdf")
@login_required
@roles_required("administrador", "director_tecnico")
def utilidades_pdf():
    """El mismo estado de resultados en PDF (para el contador o el archivo)."""
    r = _leer_periodo()
    filas = _filas_estado(r)
    per = r["periodo"]
    config = obtener_config()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                            title="Estado de resultados",
                            author=config.get("razon_social") or "Droguería")
    estilos = getSampleStyleSheet()
    sub = ParagraphStyle("Sub", parent=estilos["Normal"], fontSize=9, textColor=colors.HexColor("#555555"))
    celda = ParagraphStyle("Celda", parent=estilos["Normal"], fontSize=9)
    celda_der = ParagraphStyle("CeldaDer", parent=celda, alignment=2)   # 2 = derecha

    elementos = list(encabezado_pdf(config, "ESTADO DE RESULTADOS"))
    elementos.append(Spacer(1, 6))
    elementos.append(Paragraph(
        f"Período: <b>{per['actual']['texto']}</b> · Comparado con: {per['anterior']['texto']}<br/>"
        f"Ventas registradas: {r['actual']['n_ventas']} · Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        sub))
    elementos.append(Spacer(1, 10))

    data = [[Paragraph("<b>Concepto</b>", celda), Paragraph("<b>Período</b>", celda_der),
             Paragraph("<b>Anterior</b>", celda_der), Paragraph("<b>Cambio</b>", celda_der)]]
    estilos_tabla = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe6ef")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#c8d2da")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, f in enumerate(filas, start=1):
        texto = f["texto"]
        if f.get("margen_a") is not None:
            texto += f"  ({f['margen_a']:.1f} % de las ventas)"
        negrita = f["tipo"] in ("total", "subtotal")
        cambio = "—" if f["cambio"] is None else f"{f['cambio']:+.1f} %"
        fmt = (lambda t: f"<b>{t}</b>") if negrita else (lambda t: t)
        data.append([Paragraph(fmt(texto), celda), Paragraph(fmt(_pesos(f["a"])), celda_der),
                     Paragraph(_pesos(f["b"]), celda_der), Paragraph(cambio, celda_der)])
        if f["tipo"] == "total":
            estilos_tabla.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#eef4f9")))
        if f["tipo"] == "info":
            estilos_tabla.append(("TEXTCOLOR", (0, i), (-1, i), colors.HexColor("#555555")))
    tabla = Table(data, colWidths=[8.2 * cm, 3.0 * cm, 3.0 * cm, 2.2 * cm], repeatRows=1)
    tabla.setStyle(TableStyle(estilos_tabla))
    elementos.append(tabla)

    elementos.append(Spacer(1, 10))
    notas = [
        f"Ventas con IVA: {_pesos(r['actual']['total_con_iva'])} · IVA cobrado: {_pesos(r['actual']['iva'])} · "
        f"Descuentos dados: {_pesos(r['actual']['descuentos'])}.",
        "Costo de lo vendido = costo real de compra de cada lote vendido.",
        "Los retiros del dueño no son gasto: se muestran solo para saber cuánto queda en el negocio.",
    ]
    if r["actual"]["lineas_sin_costo"]:
        notas.append(f"<b>Atención:</b> {r['actual']['lineas_sin_costo']} línea(s) de venta salieron de lotes "
                     "con costo $0; la utilidad real es menor que la mostrada.")
    for n in notas:
        elementos.append(Paragraph(n, sub))

    pie = config.get("pie_pagina") or ""
    if pie:
        elementos.append(Spacer(1, 10))
        elementos.append(Paragraph(f"<i>{pie}</i>", sub))

    doc.build(elementos)
    buffer.seek(0)
    nombre = f"estado_resultados_{per['actual']['desde'].isoformat()}_{per['actual']['hasta'].isoformat()}.pdf"
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=nombre)
