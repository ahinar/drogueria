"""Configuración del negocio: datos que van en informes, PDFs y reportes."""
from flask import (Blueprint, flash, redirect, render_template, request, url_for)

from .audit import registrar
from .auth import roles_required
from .db import get_db
from .utils_imagenes import guardar_imagen, eliminar_imagen

bp = Blueprint("configuracion", __name__, url_prefix="/configuracion")

CAMPOS = [
    ("nit",                    "NIT",                             "text"),
    ("razon_social",           "Razón social",                    "text"),
    ("nombre_comercial",       "Nombre comercial",                "text"),
    ("direccion",              "Dirección",                       "text"),
    ("ciudad",                 "Ciudad",                          "text"),
    ("departamento",           "Departamento",                    "text"),
    ("telefono",               "Teléfono",                        "text"),
    ("celular",                "Celular / WhatsApp",              "text"),
    ("correo",                 "Correo electrónico",              "text"),
    ("sitio_web",              "Sitio web",                       "text"),
    ("regente_nombre",         "Director Técnico — Nombre",       "text"),
    ("regente_documento",      "Director Técnico — Documento",    "text"),
    ("regente_tarjeta",        "Director Técnico — Tarjeta profesional", "text"),
    ("horario",                "Horario de atención",             "text"),
]

DEFAULTS = {
    "nit": "",
    "razon_social": "",
    "nombre_comercial": "",
    "direccion": "",
    "ciudad": "",
    "departamento": "",
    "telefono": "",
    "celular": "",
    "correo": "",
    "sitio_web": "",
    "regente_nombre": "",
    "regente_documento": "",
    "regente_tarjeta": "",
    "horario": "",
    "pie_pagina": "Comprobante interno, no válido como factura.",
    "logo_ruta": "",
    # Ancho del papel de la impresora de tirillas (comprobante y recibos): "58" u "80" mm
    "ancho_tirilla": "80",
    # Cajón monedero (ver app/cajon.py): "no", "efectivo" o "siempre"
    "cajon_modo": "no",
    # Qué orden se le manda a la impresora para abrir el cajón (ver cajon.ORDENES)
    "cajon_orden": "estandar",
    # Nombre de la impresora de tirillas en Windows (vacío = la predeterminada)
    "impresora_tirillas": "",
    # Cómo se imprime el comprobante del POS (ver app/tirilla_directa.py):
    #   "navegador" = se abre la página y se imprime desde ella (en el PC donde se vende)
    #   "directa"   = el programa la manda a la impresora del PC principal (sirve desde el portátil)
    "tirilla_modo": "navegador",
    # Tirilla directa: "si" = con tildes y ñ; "no" = sin tildes (si la impresora las imprime raras)
    "tirilla_tildes": "si",
    # ¿La droguería declara IVA ante la DIAN? (versión 1.1.6)
    #   "no" = el IVA de las compras es parte del COSTO (la utilidad usa el costo con IVA)
    #   "si" = el IVA de las compras se descuenta (la utilidad usa el costo sin IVA)
    "declara_iva": "no",
    # Versión 1.1.11: margen para ESTIMAR el costo en la toma de inventario cuando el
    # producto no tiene ninguno (inventario inicial). costo ≈ precio de venta × (1 − margen)
    "margen_costo_estimado": "30",
    # Versión 1.1.16: alertas al celular por Telegram (ver app/telegram.py)
    "telegram_token": "",          # la clave del bot que entrega @BotFather
    "telegram_chat_id": "",        # a quién le escribe el bot (se busca con «Buscar mi chat»)
    "telegram_cierre_caja": "si",  # mini resumen al cerrar cada caja
    "telegram_temperatura": "si",  # lectura de temperatura/humedad fuera de rango
}

MODOS_TIRILLA = {
    "navegador": "Por el navegador (en el computador donde se vende)",
    "directa": "Directa a la impresora del PC principal (recomendada; sirve desde el portátil)",
}


def obtener_config() -> dict:
    """Devuelve la configuración actual (combinando con los valores por defecto)."""
    filas = get_db().execute("SELECT clave, valor FROM config").fetchall()
    valores = dict(DEFAULTS)
    for fila in filas:
        valores[fila["clave"]] = fila["valor"] or ""
    return valores


def guardar_config(valores: dict) -> None:
    db = get_db()
    for clave, valor in valores.items():
        db.execute(
            "INSERT INTO config (clave, valor) VALUES (?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (clave, valor),
        )
    db.commit()


@bp.route("/", methods=["GET", "POST"])
@roles_required("administrador")
def ver():
    if request.method == "POST":
        accion = request.form.get("_accion", "guardar")

        # ===== Eliminar logo =====
        if accion == "eliminar_logo":
            actual = obtener_config()
            if actual.get("logo_ruta"):
                eliminar_imagen(actual["logo_ruta"])
            guardar_config({"logo_ruta": ""})
            registrar("configuracion_logo_eliminado", "config")
            flash("Logo eliminado.", "ok")
            return redirect(url_for("configuracion.ver"))

        # ===== Guardar todo =====
        nuevos = {}
        for clave, _titulo, _tipo in CAMPOS:
            nuevos[clave] = request.form.get(clave, "").strip()
        nuevos["pie_pagina"] = request.form.get("pie_pagina", "").strip()
        # Solo se aceptan los dos anchos que existen en el mercado
        nuevos["ancho_tirilla"] = "58" if request.form.get("ancho_tirilla") == "58" else "80"
        # Cajón monedero: cuándo se abre solo y en qué impresora (ver app/cajon.py)
        from .cajon import MODOS, ORDENES
        nuevos["cajon_modo"] = request.form.get("cajon_modo") if request.form.get("cajon_modo") in MODOS else "no"
        nuevos["cajon_orden"] = request.form.get("cajon_orden") if request.form.get("cajon_orden") in ORDENES else "estandar"
        nuevos["impresora_tirillas"] = (request.form.get("impresora_tirillas") or "").strip()
        # Tirilla del POS: por el navegador o directa (app/tirilla_directa.py)
        nuevos["tirilla_modo"] = "directa" if request.form.get("tirilla_modo") == "directa" else "navegador"
        nuevos["tirilla_tildes"] = "no" if request.form.get("tirilla_tildes") == "no" else "si"
        nuevos["declara_iva"] = "si" if request.form.get("declara_iva") == "si" else "no"
        # Margen para estimar costos del inventario inicial (0 a 90 %; si escriben algo raro, 30)
        try:
            margen = float((request.form.get("margen_costo_estimado") or "30").replace(",", "."))
        except ValueError:
            margen = 30.0
        nuevos["margen_costo_estimado"] = f"{min(90.0, max(0.0, margen)):g}"
        # Alertas por Telegram (1.1.16). Las casillas que no se marcan no llegan en el formulario → "no"
        nuevos.update(_telegram_del_formulario())
        nuevos["telegram_cierre_caja"] = "si" if request.form.get("telegram_cierre_caja") else "no"
        nuevos["telegram_temperatura"] = "si" if request.form.get("telegram_temperatura") else "no"

        # Manejar subida de logo
        archivo_logo = request.files.get("logo")
        if archivo_logo and archivo_logo.filename:
            ruta, error = guardar_imagen(
                archivo_logo, "logos", max_px=800, max_bytes=2 * 1024 * 1024,
                nombre_fijo="logo",
            )
            if error:
                flash(f"Error con el logo: {error}", "error")
                return redirect(url_for("configuracion.ver"))
            # Eliminar el logo anterior si existía y era distinto
            anterior = obtener_config().get("logo_ruta")
            if anterior and anterior != ruta:
                eliminar_imagen(anterior)
            nuevos["logo_ruta"] = ruta

        if not nuevos["razon_social"]:
            flash("La razón social es obligatoria.", "error")
        elif not nuevos["nit"]:
            flash("El NIT es obligatorio.", "error")
        else:
            guardar_config(nuevos)
            registrar("configuracion_actualizada", "config",
                      detalle=f"NIT={nuevos['nit']} razón={nuevos['razon_social']}")
            flash("Configuración guardada.", "ok")
            return redirect(url_for("configuracion.ver"))

    from . import cajon
    valores = obtener_config()
    return render_template("configuracion.html", campos=CAMPOS, valores=valores,
                           modos_cajon=cajon.MODOS, ordenes_cajon=cajon.ORDENES, impresoras=cajon.impresoras(),
                           modos_tirilla=MODOS_TIRILLA,
                           cajon_disponible=cajon.disponible())


@bp.route("/probar-cajon", methods=["POST"])
@roles_required("administrador")
def probar_cajon():
    """Botón "Probar cajón" de la configuración: lo abre sin imprimir nada.

    Usa lo que está escrito en la pantalla AHORA (impresora y tipo de orden),
    aunque todavía no se haya guardado: así se pueden probar las órdenes una
    por una y guardar la que sí abra.
    """
    from . import cajon
    cfg = obtener_config()
    impresora = request.form.get("impresora_tirillas") or cfg.get("impresora_tirillas")
    orden = request.form.get("cajon_orden") or cfg.get("cajon_orden") or "estandar"
    ok, error = cajon.abrir(impresora, orden)
    usada = cajon.impresora_usada(impresora)
    registrar("cajon_prueba", "config", detalle=(f"ok impresora={usada} orden={orden}" if ok else error))
    if ok:
        flash(f"Se mandó la orden «{cajon.ORDENES.get(orden, cajon.ORDENES['estandar'])[0]}» a la impresora "
              f"«{usada or '¿?'}». Si el cajón no abrió, prueba con otro tipo de orden.", "ok")
    else:
        flash(error, "error")
    return redirect(url_for("configuracion.ver"))

# ---------------------------------------------------------------------
# Alertas al celular por Telegram (versión 1.1.16, ver app/telegram.py)
# ---------------------------------------------------------------------

def _telegram_del_formulario():
    """Token y chat escritos en la pantalla (sin espacios). Si vienen vacíos, los guardados."""
    cfg = obtener_config()
    token = (request.form.get("telegram_token") or "").strip().replace(" ", "")
    chat = (request.form.get("telegram_chat_id") or "").strip().replace(" ", "")
    if "telegram_token" not in request.form:          # (el formulario no traía la parte de Telegram)
        token, chat = cfg.get("telegram_token", ""), cfg.get("telegram_chat_id", "")
    return {"telegram_token": token, "telegram_chat_id": chat}


@bp.route("/telegram/buscar-chat", methods=["POST"])
@roles_required("administrador")
def telegram_buscar_chat():
    """Botón «Buscar mi chat»: pregunta a Telegram quién le escribió al bot y lo guarda.

    Guarda SOLO el token y el chat (no el resto del formulario), para que funcione
    aunque falte la razón social o el NIT.
    """
    from . import telegram
    token = _telegram_del_formulario()["telegram_token"]
    if not token:
        flash("Primero pega el token que te dio @BotFather.", "error")
        return redirect(url_for("configuracion.ver") + "#telegram")
    chat, nombre = telegram.buscar_chat(token)
    if not chat:
        flash(nombre, "error")          # (cuando no hay chat, «nombre» trae el porqué)
        return redirect(url_for("configuracion.ver") + "#telegram")
    guardar_config({"telegram_token": token, "telegram_chat_id": chat})
    registrar("telegram_configurado", "config", detalle=f"chat={chat}")
    flash(f"Listo: el bot le escribirá a {nombre or 'tu chat'} (chat {chat}). Toca «Mandar prueba» para verificar.", "ok")
    return redirect(url_for("configuracion.ver") + "#telegram")


@bp.route("/telegram/probar", methods=["POST"])
@roles_required("administrador")
def telegram_probar():
    """Botón «Mandar prueba»: manda un mensaje YA y dice si llegó bien a Telegram."""
    from . import telegram
    datos = _telegram_del_formulario()
    if not (datos["telegram_token"] and datos["telegram_chat_id"]):
        flash("Falta el token o el chat. Pega el token y toca «Buscar mi chat».", "error")
        return redirect(url_for("configuracion.ver") + "#telegram")
    negocio = telegram.escapar(obtener_config().get("nombre_comercial") or "La droguería")
    ok, error = telegram.enviar_ahora(f"✅ <b>{negocio}</b>: las alertas al celular quedaron funcionando.",
                                      datos["telegram_token"], datos["telegram_chat_id"])
    registrar("telegram_prueba", "config", detalle="ok" if ok else error)
    if ok:
        flash("Mensaje de prueba enviado: revisa Telegram en tu celular.", "ok")
    else:
        flash(f"No se pudo mandar: {error}", "error")
    return redirect(url_for("configuracion.ver") + "#telegram")


@bp.route("/probar-tirilla", methods=["POST"])
@roles_required("administrador")
def probar_tirilla():
    """Botón "Imprimir prueba": manda una tirilla corta directa a la impresora (app/tirilla_directa.py)."""
    from . import cajon
    from .tirilla_directa import Tirilla, CENTRO, NEGRILLA, SIN_NEGRILLA, IZQUIERDA
    valores = obtener_config()
    ancho = "58" if request.form.get("ancho_tirilla") == "58" else (valores.get("ancho_tirilla") or "80")
    tildes = (request.form.get("tirilla_tildes") or valores.get("tirilla_tildes")) != "no"
    t = Tirilla(ancho, tildes=tildes)
    t.orden(CENTRO, NEGRILLA).linea("PRUEBA DE IMPRESIÓN").orden(SIN_NEGRILLA)
    t.linea(valores.get("nombre_comercial") or valores.get("razon_social") or "Droguería")
    t.orden(IZQUIERDA).separador()
    t.linea("Tildes y eñe: á é í ó ú ñ Ñ ¡ ¿")
    t.dos_columnas("Acetaminofén 500 mg x 10", "$2.500")
    t.separador().linea("Si las tildes salen raras, escoge «sin tildes» en Configuración.")
    impresora = request.form.get("impresora_tirillas") or valores.get("impresora_tirillas")
    ok, error = cajon.enviar_crudo(impresora, t.terminar(), "Prueba Fervifarma")
    registrar("tirilla_prueba", "config", detalle="ok" if ok else error)
    flash("Listo: se mandó la tirilla de prueba." if ok else error, "ok" if ok else "error")
    return redirect(url_for("configuracion.ver"))
