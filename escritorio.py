"""
LANZADOR DEL PROGRAMA INSTALADO (el ícono "Fervifarma" del escritorio)
=====================================================================

PARA QUÉ (para aprender):
    Programando, se abre con "python run.py" y una pantalla negra. Instalado,
    nadie debería ver eso. Este archivo es lo que corre al dar doble clic:

    1. ¿Ya está prendido? (por ejemplo, se le dio doble clic dos veces)
       Pregunta a http://127.0.0.1:8765/salud. Si contesta "fervifarma",
       solo abre otra ventana y termina.
    2. Si no: prende el servidor (Waitress) por debajo, en un "hilo".
    3. Arranca el reloj de respaldos (uno al abrir y cada 24 horas).
    4. Abre la VENTANA del programa, maximizada, con Google Chrome (o
       Microsoft Edge si no hay Chrome) en "modo aplicación": sin barra de direcciones ni
       pestañas, como un programa normal. Se imprime y se abren las
       tirillas igual que en el navegador.
    5. Cuando se cierra la ventana, se apaga todo.

    Si no encuentra Edge ni Chrome, abre el navegador que haya y el
    programa queda prendido (hasta apagar el computador).

    VARIOS COMPUTADORES (versión 1.1.0, ver config.py y app/equipo.py):
    - PC principal que COMPARTE: al cerrar la ventana el programa NO se
      apaga, porque el portátil puede estar trabajando. Sigue por detrás
      hasta que se apague el computador.
    - PC CONECTADO (portátil): no prende ningún servidor ni tiene datos.
      Solo revisa que el PC principal conteste y abre la ventana apuntando
      a él. Si no contesta, muestra un mensaje con "Reintentar".

    ÍCONO EN LA BARRA DE TAREAS (versión 1.1.6, ver icono_ventana.py):
    - Antes salía el ícono de Chrome, porque la ventana la abre Chrome. Ahora un
      "vigilante" le dice a Windows que esa ventana es Fervifarma y le pone su ícono.

    Los errores quedan escritos en  <datos>/logs/fervifarma.log  (ver config.py).
"""
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import config
import icono_ventana

URL = f"http://127.0.0.1:{config.PORT}"


def url_del_principal(equipo, puerto):
    """En un PC conectado, la dirección del PC principal: "mostrador" -> "http://mostrador:8765".

    Si escribieron "http://..." o ya le pusieron el puerto, se respeta. En un PC
    principal (o sin dirección) devuelve None.
    """
    servidor = (equipo.get("servidor") or "").strip().rstrip("/")
    if equipo.get("modo") != "conectado" or not servidor:
        return None
    if not servidor.startswith(("http://", "https://")):
        servidor = "http://" + servidor
    if servidor.count(":") < 2:                    # "http://mostrador" -> le falta el puerto
        servidor += f":{puerto}"
    return servidor


URL_PRINCIPAL = url_del_principal(config.EQUIPO, config.PORT)


def preparar_registro():
    """Los mensajes y errores van a un archivo (no hay pantalla negra donde verlos)."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    manejador = logging.handlers.RotatingFileHandler(config.LOG_DIR / "fervifarma.log", maxBytes=2_000_000,
                                                     backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[manejador],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def ya_esta_prendido(url=URL, espera=3):
    """True si el programa contesta en esa dirección (por defecto: en este computador)."""
    try:
        with urllib.request.urlopen(url + "/salud", timeout=espera) as resp:
            return resp.read().decode("utf-8", "ignore").startswith("fervifarma")
    except OSError:
        return False


def puerto_ocupado():
    """True si ALGUIEN ya está usando el puerto del programa en este computador.

    Por qué (corrección de la versión 1.1.1): si el programa estaba muy ocupado,
    no alcanzaba a contestar "/salud" a tiempo, y al darle doble clic al ícono se
    creía apagado y prendía OTRO programa encima del primero. Ahora, además de
    preguntar, se revisa si el puerto está tomado: si lo está, ya hay uno
    prendido y solo se abre la ventana.
    """
    import socket
    prueba = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        prueba.bind((config.HOST, config.PORT))     # si se puede "tomar", está libre
        return False
    except OSError:
        return True
    finally:
        prueba.close()


def prender_servidor():
    """Prende el programa (Flask + Waitress) en un hilo y espera a que conteste."""
    from waitress import serve

    from app import create_app
    from app.backup_utils import iniciar_reloj_de_respaldos

    app = create_app()
    iniciar_reloj_de_respaldos(app)
    hilo = threading.Thread(target=serve, args=(app,),
                            kwargs={"host": config.HOST, "port": config.PORT, "threads": 12},
                            name="servidor", daemon=True)
    hilo.start()
    for _ in range(100):                           # hasta 20 segundos
        if ya_esta_prendido():
            return True
        time.sleep(0.2)
    logging.error("El servidor no contestó a tiempo")
    return False


def buscar_navegador():
    """Ruta de Google Chrome o, si no está, de Microsoft Edge.

    Los dos sirven para el "modo aplicación" (ventana sin barra de direcciones).
    Desde la versión 1.1.2 se busca PRIMERO Chrome (antes era Edge, y como
    Edge viene en todos los Windows, siempre ganaba). Edge queda de respaldo
    por si el computador no tiene Chrome.
    """
    bases = [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")]
    bases = [b for b in bases if b]
    # Primero todas las carpetas donde puede estar Chrome, después las de Edge
    candidatos = [Path(b) / "Google" / "Chrome" / "Application" / "chrome.exe" for b in bases]
    candidatos += [Path(b) / "Microsoft" / "Edge" / "Application" / "msedge.exe" for b in bases]
    return next((str(c) for c in candidatos if c.exists()), None)


def abrir_ventana(esperar=True, url=URL):
    """Abre la ventana del programa. Si esperar=True, no vuelve hasta que la cierren."""
    navegador = buscar_navegador()
    if not navegador:
        logging.warning("No se encontró Edge ni Chrome: se abre el navegador predeterminado")
        webbrowser.open(url)
        return False
    perfil = config.DATA_DIR / "ventana"           # perfil propio: no se mezcla con el navegador de uso diario
    orden = [navegador, f"--app={url}", "--start-maximized", f"--user-data-dir={perfil}",
             "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]
    proceso = subprocess.Popen(orden)
    if esperar:
        icono_ventana.vigilar()                    # ícono de Fervifarma mientras la ventana esté abierta
        proceso.wait()                             # aquí se queda mientras la ventana esté abierta
    else:
        # Este lanzador se va a cerrar enseguida: se queda 20 segundos poniéndole
        # el ícono a la ventana nueva y después termina
        vigilante = icono_ventana.vigilar(segundos=20)
        if vigilante:
            vigilante.join()
    return True


def mensaje(texto, botones=0x10):
    """Ventanita de Windows con un mensaje. 0x10 = ícono de error y botón Aceptar.
    Devuelve el botón que tocaron (4 = Reintentar). Fuera de Windows solo lo anota."""
    logging.warning(texto.replace("\n", " "))
    if sys.platform != "win32":
        return 0
    import ctypes
    return ctypes.windll.user32.MessageBoxW(None, texto, "Fervifarma", botones)


def abrir_conectado():
    """PC CONECTADO (portátil): abre la ventana del programa del PC principal."""
    logging.info("PC conectado: se abre %s", URL_PRINCIPAL)
    while True:
        # Al prender el portátil, Tailscale puede tardar unos segundos en conectar:
        # se pregunta varias veces antes de rendirse (hasta ~15 segundos)
        for _ in range(5):
            if ya_esta_prendido(URL_PRINCIPAL, espera=3):
                abrir_ventana(esperar=False, url=URL_PRINCIPAL)
                return
            time.sleep(0.5)
        boton = mensaje(
            f"No se pudo conectar con el PC principal ({URL_PRINCIPAL}).\n\n"
            "Revisa que:\n"
            "  • el PC del mostrador esté prendido y con Fervifarma abierto,\n"
            "  • Tailscale esté conectado en los dos computadores,\n"
            "  • este portátil tenga internet (o esté en el WiFi del local).\n\n"
            "Para cambiar la dirección, vuelve a correr el instalador.",
            0x5 | 0x30)                              # 0x5 = Reintentar/Cancelar, 0x30 = ícono de advertencia
        if boton != 4:                               # 4 = tocaron "Reintentar"
            return


def main():
    preparar_registro()
    icono_ventana.identidad_del_proceso()          # este proceso también es "Fervifarma" para Windows
    logging.info("Abriendo Fervifarma (datos en %s, modo %s)", config.DATA_DIR, config.EQUIPO["modo"])
    if URL_PRINCIPAL:
        abrir_conectado()
        return
    # "Fervifarma.exe --solo-servidor": prende el programa sin abrir ventana
    # (para revisar que el instalador funciona, o para abrirlo desde otro lado)
    if "--solo-servidor" in sys.argv:
        if ya_esta_prendido() or prender_servidor():
            while True:
                time.sleep(3600)
        return
    if ya_esta_prendido() or puerto_ocupado():
        # Ya está prendido (quizás ocupado): se le da hasta un minuto para contestar
        # y se abre solo otra ventana. NUNCA se prende un segundo programa.
        for _ in range(20):
            if ya_esta_prendido():
                break
        abrir_ventana(esperar=False)
        return
    if not prender_servidor():
        mensaje(f"No se pudo abrir el programa. Revisa el archivo de errores en:\n{config.LOG_DIR}")
        return
    if abrir_ventana(esperar=True):
        if config.EQUIPO["compartir"]:
            # Comparte con el portátil: aunque cierren la ventana, sigue por detrás
            logging.info("Ventana cerrada: el programa sigue prendido para los otros equipos")
            while True:
                time.sleep(3600)
        logging.info("Ventana cerrada: se apaga el programa")
    else:
        # Sin Edge/Chrome no se sabe cuándo cierran el navegador: queda prendido
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Error al abrir el programa")
        raise
    sys.exit(0)
