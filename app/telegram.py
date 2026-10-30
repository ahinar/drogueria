"""ALERTAS AL CELULAR POR TELEGRAM (versión 1.1.16).

PARA QUÉ (pedido de Fernando)
-----------------------------
Enterarse sin estar frente al computador de lo importante que pasa en la droguería:
  - Cierre de caja, con un mini resumen (ventas por forma de pago, contado,
    diferencia, gastos y retiros del turno).
  - Temperatura o humedad FUERA DE RANGO al registrar una lectura.
  - (Botón «Probar» en Configuración, para saber que quedó bien.)

CÓMO FUNCIONA (en palabras sencillas)
-------------------------------------
Telegram deja crear «bots» gratis: una cuenta automática que manda mensajes.
  1. En Telegram se habla con @BotFather, se escribe /newbot y él entrega un
     TOKEN (una clave larga como 123456:ABC-DEF...).
  2. Se le escribe cualquier cosa al bot nuevo desde el celular de Fernando.
  3. En Configuración → Alertas al celular se pega el token y se toca «Buscar mi
     chat»: el programa le pregunta a Telegram quién le escribió al bot y guarda
     ese número de chat (chat_id).
  4. Desde ahí, el programa le manda los mensajes a ese chat.

El envío va en un HILO APARTE («en segundo plano»): si no hay internet o Telegram
tarda, la caja se cierra igual y nadie espera. Si falla, queda en fervifarma.log.
Para las pruebas automáticas, enviar_ahora() se puede reemplazar (mock).

Dónde se guarda (tabla config):
  telegram_token, telegram_chat_id
  telegram_cierre_caja = 'si'/'no'     telegram_temperatura = 'si'/'no'
"""
import json
import logging
import threading
import urllib.parse
import urllib.request

log = logging.getLogger("drogueria")

API = "https://api.telegram.org/bot{token}/{metodo}"
ESPERA = 10            # segundos máximo esperando a Telegram


def _config():
    from .configuracion import obtener_config
    return obtener_config()


def configurado(config=None):
    """¿Hay token y chat? (sin eso no se manda nada)."""
    c = config or _config()
    return bool((c.get("telegram_token") or "").strip() and (c.get("telegram_chat_id") or "").strip())


def activo(aviso, config=None):
    """¿Está prendido este aviso? aviso = 'cierre_caja' o 'temperatura'. Por defecto, sí."""
    c = config or _config()
    return configurado(c) and (c.get(f"telegram_{aviso}") or "si") == "si"


def _llamar(token, metodo, datos=None):
    """Llama a la API de Telegram y devuelve la respuesta (diccionario). Puede lanzar error."""
    url = API.format(token=token.strip(), metodo=metodo)
    cuerpo = urllib.parse.urlencode(datos or {}).encode("utf-8") if datos else None
    with urllib.request.urlopen(urllib.request.Request(url, data=cuerpo), timeout=ESPERA) as r:
        return json.loads(r.read().decode("utf-8"))


def enviar_ahora(texto, token, chat_id):
    """Manda el mensaje YA y espera la respuesta. Devuelve (True, '') o (False, por qué)."""
    try:
        r = _llamar(token, "sendMessage", {"chat_id": chat_id, "text": texto, "parse_mode": "HTML",
                                           "disable_web_page_preview": "true"})
        return (True, "") if r.get("ok") else (False, r.get("description") or "Telegram no aceptó el mensaje.")
    except Exception as e:                       # sin internet, token malo, Telegram caído...
        return False, str(e)


def enviar(texto, aviso=None):
    """Manda el mensaje EN SEGUNDO PLANO (no hace esperar a nadie). No lanza errores.

    aviso: 'cierre_caja' o 'temperatura' (se respeta si está apagado en Configuración).
    """
    c = _config()
    if not (activo(aviso, c) if aviso else configurado(c)):
        return False
    token, chat = c["telegram_token"], c["telegram_chat_id"]

    def tarea():
        ok, error = enviar_ahora(texto, token, chat)
        if not ok:
            log.warning("Telegram: no se pudo mandar el aviso (%s): %s", aviso or "general", error)

    threading.Thread(target=tarea, daemon=True, name="telegram").start()
    return True


def buscar_chat(token):
    """Pregunta a Telegram quién le escribió al bot. Devuelve (chat_id, nombre) o (None, por qué)."""
    try:
        r = _llamar(token, "getUpdates")
    except Exception as e:
        return None, f"No se pudo hablar con Telegram: {e}"
    if not r.get("ok"):
        return None, r.get("description") or "Telegram no aceptó el token."
    for u in reversed(r.get("result") or []):
        chat = (u.get("message") or u.get("edited_message") or {}).get("chat")
        if chat:
            nombre = chat.get("first_name") or chat.get("title") or chat.get("username") or ""
            return str(chat["id"]), nombre
    return None, "El bot todavía no tiene mensajes: escríbale cualquier cosa desde su celular y vuelva a intentar."


def escapar(texto):
    """Telegram (modo HTML) no acepta < > & sueltos: se cambian por su código."""
    return str(texto or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------
# Los mensajes
# ---------------------------------------------------------------------

def mensaje_cierre_caja(db, caja_id):
    """Mini resumen del turno que se acaba de cerrar (texto para Telegram)."""
    from .formato import pesos
    from .pos import _resumen_caja
    from . import formas_pago as fp
    caja = db.execute("SELECT * FROM cajas WHERE id = ?", (caja_id,)).fetchone()
    r = _resumen_caja(caja)
    negocio = escapar(_config().get("nombre_comercial") or "La droguería")
    lineas = [f"🔒 <b>{negocio}: caja #{caja['numero']} cerrada</b>",
              f"Cerró {escapar(caja['cerrada_por_nombre'] or '—')} · {(caja['cerrada_en'] or '')[11:16]}",
              "",
              f"🛒 Ventas: <b>{pesos(r['total_ventas'])}</b> ({r['n_ventas']} venta{'s' if r['n_ventas'] != 1 else ''})"]
    # Una línea por cada forma de pago que tuvo ventas
    for forma in ("efectivo",) + fp.CLAVES_CUENTAS + ("tarjeta", "credito"):
        valor = r.get(f"ventas_{forma}") or 0
        if valor:
            lineas.append(f"   • {fp.nombre(forma) if forma != 'credito' else 'Fiado (crédito)'}: {pesos(valor)}")
    # Efectivo contado y diferencia
    contado = caja["efectivo_contado"] or 0
    dif = round(float(caja["diferencia"] or 0))
    if abs(dif) < 1:
        estado = "✅ cuadró"
    elif dif < 0:
        estado = f"🔴 faltaron {pesos(-dif)}"
    else:
        estado = f"🟢 sobraron {pesos(dif)}"
    lineas += ["", f"💵 Efectivo contado: {pesos(contado)} · {estado}"]
    # Gastos y retiros del dueño hechos desde esta caja
    # (el «Faltante de caja» que el programa anota solo al cerrar NO se suma: ya se ve en la diferencia)
    gastos = db.execute("SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE caja_id = ? AND activo = 1 "
                        "AND id IS NOT ?", (caja_id, caja["diferencia_gasto_id"])).fetchone()[0]
    retiros = db.execute("SELECT COALESCE(SUM(monto), 0) FROM caja_movimientos WHERE caja_id = ? "
                         "AND tipo = 'salida' AND lugar = 'dueno'", (caja_id,)).fetchone()[0]
    if gastos:
        lineas.append(f"🧾 Gastos del turno: {pesos(gastos)}")
    if retiros:
        lineas.append(f"👤 Retiros del dueño: {pesos(retiros)}")
    if caja["observaciones_cierre"]:
        lineas.append(f"📝 {escapar(caja['observaciones_cierre'])}")
    return "\n".join(lineas)


def _num(n):
    """23.5 → '23,5' (con coma, como se escribe en Colombia)."""
    return f"{n:g}".replace(".", ",")


def mensaje_temperatura(zona, temp, humedad, accion, quien):
    """Aviso de una lectura fuera de rango (puede ser la temperatura o la humedad)."""
    temp_mal = temp < zona["temp_min"] or temp > zona["temp_max"]
    partes = [f"🌡️ <b>Fuera de rango: {escapar(zona['nombre'])}</b>",
              f"Temperatura: <b>{_num(temp)} °C</b>{' ⚠️' if temp_mal else ''} "
              f"(rango {_num(zona['temp_min'])} a {_num(zona['temp_max'])} °C)"]
    if humedad is not None:
        h_min, h_max = zona["humedad_min"], zona["humedad_max"]
        h_mal = (h_min is not None and humedad < h_min) or (h_max is not None and humedad > h_max)
        rango = f" (rango {_num(h_min)} a {_num(h_max)} %)" if h_min is not None and h_max is not None else ""
        partes.append(f"Humedad: <b>{_num(humedad)} %</b>{' ⚠️' if h_mal else ''}{rango}")
    partes += [f"Acción correctiva: {escapar(accion or '—')}", f"Registró: {escapar(quien)}"]
    return "\n".join(partes)
