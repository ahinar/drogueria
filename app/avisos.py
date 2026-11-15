"""AVISOS AL CELULAR: por TELEGRAM, por WHATSAPP o por los dos (versión 1.1.20).

PARA QUÉ (pedido de Fernando)
-----------------------------
En la 1.1.16 los avisos (cierre de caja con mini resumen, temperatura fuera de
rango) llegaban solo por Telegram (app/telegram.py). Fernando pidió poder
escoger también WhatsApp, o los dos a la vez.

CÓMO SE MANDA POR WHATSAPP (CallMeBot)
--------------------------------------
WhatsApp no deja que un programa mande mensajes gratis. La opción oficial (de
Meta) pide cuenta de empresa, un número aparte, plantillas aprobadas y cobra
por mensaje. Por eso se usa CallMeBot: un servicio GRATIS para mandarse
mensajes a UNO MISMO.
  1. Se agrega a los contactos el número de CallMeBot (está en callmebot.com).
  2. Desde WhatsApp se le escribe: "I allow callmebot to send me messages".
  3. Responde con una clave (APIKEY). Esa clave y el número del celular se
     ponen en Configuración → Alertas al celular.
  4. El programa abre una dirección como
        https://api.callmebot.com/whatsapp.php?phone=+573001234567&text=Hola&apikey=123456
     y CallMeBot le manda el mensaje.
OJO: es un servicio de terceros; a veces se demora o falla por ratos. Por eso
se pueden dejar prendidos los dos canales: si uno falla, llega por el otro.

CÓMO FUNCIONA AQUÍ
------------------
  - avisos.activo('cierre_caja')  → ¿hay que avisar eso? (casilla prendida y al
    menos un canal listo).
  - avisos.enviar(texto, 'cierre_caja') → lo manda por cada canal escogido, cada uno
    en un HILO APARTE (segundo plano): la caja se cierra igual aunque no haya
    internet. Si falla, queda anotado en fervifarma.log.
  - El texto se escribe una vez, con el formato de Telegram (<b>negrita</b>); para
    WhatsApp se convierte a su formato (*negrita*) con a_whatsapp().

Dónde se guarda (tabla config):
  aviso_telegram = 'si'/'no'     aviso_whatsapp = 'si'/'no'     (por dónde)
  telegram_cierre_caja, telegram_temperatura = 'si'/'no'         (qué avisar; los
      nombres vienen de la 1.1.16 y sirven para los dos canales)
  whatsapp_numero (ej. +573001234567), whatsapp_apikey
"""
import html
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import telegram

log = logging.getLogger("drogueria")

URL_CALLMEBOT = "https://api.callmebot.com/whatsapp.php"
ESPERA = 15                      # segundos máximo esperando a CallMeBot (a veces es lento)


def _config():
    from .configuracion import obtener_config
    return obtener_config()


# ---------------------------------------------------------------------
# WhatsApp (CallMeBot)
# ---------------------------------------------------------------------

def numero_whatsapp(texto):
    """Deja el número como lo pide CallMeBot: +57 y los 10 dígitos.

    '300 123 4567' → '+573001234567' (si no trae país, se asume Colombia)
    '+57 300-123-4567' → '+573001234567'
    """
    digitos = re.sub(r"\D", "", texto or "")
    if not digitos:
        return ""
    if len(digitos) == 10 and digitos.startswith("3"):      # celular de Colombia sin el 57
        digitos = "57" + digitos
    return "+" + digitos


def whatsapp_configurado(c=None):
    c = c or _config()
    return bool(numero_whatsapp(c.get("whatsapp_numero")) and (c.get("whatsapp_apikey") or "").strip())


def a_whatsapp(texto):
    """Pasa el texto del formato de Telegram (HTML) al de WhatsApp.

    <b>Caja cerrada</b> → *Caja cerrada*   ·   &amp; → &   ·   se quitan las demás etiquetas.
    """
    texto = re.sub(r"</?b>", "*", texto or "")
    texto = re.sub(r"<[^>]+>", "", texto)
    return html.unescape(texto)


def whatsapp_enviar_ahora(texto, numero, apikey):
    """Manda el mensaje YA por CallMeBot. Devuelve (True, '') o (False, por qué)."""
    numero = numero_whatsapp(numero)
    if not numero or not (apikey or "").strip():
        return False, "Falta el número o la clave (apikey) de CallMeBot."
    url = URL_CALLMEBOT + "?" + urllib.parse.urlencode(
        {"phone": numero, "text": a_whatsapp(texto), "apikey": apikey.strip()})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Fervifarma"}),
                                    timeout=ESPERA) as r:
            respuesta = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:                     # CallMeBot respondió con error (clave mala...)
        respuesta = e.read().decode("utf-8", "replace") if e.fp else str(e)
        return False, _explicar(respuesta) or f"CallMeBot respondió con error {e.code}."
    except Exception as e:                                   # sin internet, CallMeBot caído...
        return False, f"No se pudo conectar con CallMeBot: {e}"
    # CallMeBot contesta con una pagina corta; si el mensaje quedó en cola, dice «queued» o «sent»
    if re.search(r"queued|sent|enviado", respuesta, re.I) and not re.search(r"error|invalid", respuesta, re.I):
        return True, ""
    return False, _explicar(respuesta) or "CallMeBot no aceptó el mensaje."


def _explicar(respuesta):
    """El texto de la respuesta de CallMeBot, sin etiquetas, para mostrarlo (máximo 200 letras)."""
    limpio = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", respuesta or "")).split())
    if re.search(r"apikey", limpio, re.I) and re.search(r"invalid|wrong|incorrect", limpio, re.I):
        return "La clave (apikey) no es válida para ese número. Revise el número y la clave que le mandó CallMeBot."
    return limpio[:200]


# ---------------------------------------------------------------------
# Los canales y el envío
# ---------------------------------------------------------------------

def canales(c=None):
    """Los canales escogidos Y listos: ['telegram'], ['whatsapp'], los dos o ninguno."""
    c = c or _config()
    lista = []
    if (c.get("aviso_telegram") or "si") == "si" and telegram.configurado(c):
        lista.append("telegram")
    if (c.get("aviso_whatsapp") or "no") == "si" and whatsapp_configurado(c):
        lista.append("whatsapp")
    return lista


def activo(aviso, c=None):
    """¿Hay que mandar este aviso? aviso = 'cierre_caja' o 'temperatura'."""
    c = c or _config()
    return bool(canales(c)) and (c.get(f"telegram_{aviso}") or "si") == "si"


def enviar_por(canal, texto, c):
    """Manda YA por un canal. Devuelve (True, '') o (False, por qué)."""
    if canal == "telegram":
        return telegram.enviar_ahora(texto, c["telegram_token"], c["telegram_chat_id"])
    return whatsapp_enviar_ahora(texto, c.get("whatsapp_numero"), c.get("whatsapp_apikey"))


def enviar(texto, aviso=None):
    """Manda el aviso por cada canal escogido, EN SEGUNDO PLANO. No lanza errores.

    Cada canal va en su propio hilo: si WhatsApp se demora o falla, Telegram llega igual.
    """
    c = _config()
    if aviso and not activo(aviso, c):
        return []
    usados = canales(c)
    for canal in usados:
        def tarea(canal=canal):
            ok, error = enviar_por(canal, texto, c)
            if not ok:
                log.warning("Aviso por %s no enviado (%s): %s", canal, aviso or "general", error)
        threading.Thread(target=tarea, daemon=True, name=f"aviso-{canal}").start()
    return usados
