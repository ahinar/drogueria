"""
INSTALAR FERVIFARMA COMO APLICACIÓN DESDE CHROME (o Edge)
=========================================================

PARA QUÉ (para aprender):
    Chrome muestra en la barra de direcciones un botoncito de "Instalar"
    (una pantalla con una flecha) cuando la página es una "aplicación web
    instalable" (en inglés: PWA, Progressive Web App). Al instalarla queda
    con su propio ícono en el escritorio y en el menú Inicio, y abre en una
    ventana sin pestañas, como un programa normal.

    Para que Chrome muestre ese botón, la página necesita tres cosas:

      1. Un MANIFIESTO (/manifest.webmanifest): una "ficha" en formato JSON
         con el nombre, los colores, los íconos y la página de inicio.
         Cada página lo anuncia con  <link rel="manifest" ...>  (base.html
         y login.html).
      2. Un SERVICE WORKER (/sw.js): un pequeño JavaScript que el navegador
         deja "instalado" para la página. Aquí NO guarda nada en caché:
         el programa siempre necesita los datos frescos del PC principal.
      3. Una dirección SEGURA. Chrome solo ofrece instalar en:
           - https://...                      (con candado)
           - http://localhost o http://127.0.0.1  (este mismo computador)
         Por eso el botón SÍ sale en el PC del mostrador
         (http://localhost:8765) y NO sale si se entra por
         http://192.168.x.x:8765 o por la dirección de Tailscale 100.x.x.x.
         Ver LEEME.md → "Instalar como aplicación" para esos casos.

    ¿Por qué el service worker va en /sw.js y no en /static/js/sw.js?
    Porque un service worker solo "maneja" las páginas que están en su
    carpeta o más adentro. En /static/js/ solo manejaría /static/js/...,
    y en la raíz (/) maneja todo el programa.

    Estas dos direcciones NO piden usuario y contraseña: el navegador las
    lee solo, y no tienen ningún dato de la droguería.
"""
from flask import Blueprint, jsonify, make_response, url_for

bp = Blueprint("instalable", __name__)


@bp.route("/manifest.webmanifest")
def manifiesto():
    """La "ficha" de la aplicación que lee Chrome para poder instalarla."""
    datos = {
        "name": "Fervifarma",                  # nombre completo (ventana de instalar)
        "short_name": "Fervifarma",            # nombre corto (debajo del ícono)
        "description": "Calidad y punto de venta de la droguería",
        "lang": "es-CO",
        "start_url": "/",                      # dónde abre: la página de Inicio
        "scope": "/",                          # todo el programa es parte de la aplicación
        "display": "standalone",               # ventana propia, sin barra de direcciones
        "background_color": "#ffffff",         # color mientras carga
        "theme_color": "#0f766e",              # color de la barra de título (verde Fervifarma)
        "icons": [
            {"src": url_for("static", filename="img/app-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="img/app-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": url_for("static", filename="img/app-512.png"), "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},           # versión que el sistema puede recortar redonda
        ],
    }
    respuesta = jsonify(datos)
    respuesta.mimetype = "application/manifest+json"
    return respuesta


@bp.route("/sw.js")
def service_worker():
    """Service worker mínimo: hace instalable el programa, no guarda nada en caché."""
    codigo = """// Fervifarma: service worker (ver app/instalable.py)
// Solo existe para que Chrome deje instalar el programa como aplicación.
// No guarda páginas en caché: todo se pide siempre al PC principal.
self.addEventListener('install', () => self.skipWaiting());          // activarse de una vez
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
"""
    respuesta = make_response(codigo)
    respuesta.mimetype = "application/javascript"
    respuesta.headers["Cache-Control"] = "no-cache"     # que el navegador revise si cambió
    return respuesta

