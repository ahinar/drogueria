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
    4. Abre la VENTANA del programa, maximizada, con Microsoft Edge (o
       Google Chrome) en "modo aplicación": sin barra de direcciones ni
       pestañas, como un programa normal. Se imprime y se abren las
       tirillas igual que en el navegador.
    5. Cuando se cierra la ventana, se apaga todo.

    Si no encuentra Edge ni Chrome, abre el navegador que haya y el
    programa queda prendido (hasta apagar el computador).

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

URL = f"http://127.0.0.1:{config.PORT}"


def preparar_registro():
    """Los mensajes y errores van a un archivo (no hay pantalla negra donde verlos)."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    manejador = logging.handlers.RotatingFileHandler(config.LOG_DIR / "fervifarma.log", maxBytes=2_000_000,
                                                     backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[manejador],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def ya_esta_prendido():
    """True si el programa ya está corriendo en este computador."""
    try:
        with urllib.request.urlopen(URL + "/salud", timeout=1.5) as resp:
            return resp.read().decode("utf-8", "ignore").startswith("fervifarma")
    except OSError:
        return False


def prender_servidor():
    """Prende el programa (Flask + Waitress) en un hilo y espera a que conteste."""
    from waitress import serve

    from app import create_app
    from app.backup_utils import iniciar_reloj_de_respaldos

    app = create_app()
    iniciar_reloj_de_respaldos(app)
    hilo = threading.Thread(target=serve, args=(app,),
                            kwargs={"host": config.HOST, "port": config.PORT, "threads": 6},
                            name="servidor", daemon=True)
    hilo.start()
    for _ in range(100):                           # hasta 20 segundos
        if ya_esta_prendido():
            return True
        time.sleep(0.2)
    logging.error("El servidor no contestó a tiempo")
    return False


def buscar_navegador():
    """Ruta de Microsoft Edge o Google Chrome (los dos sirven para el modo aplicación)."""
    candidatos = []
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidatos += [Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                           Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"]
    return next((str(c) for c in candidatos if c.exists()), None)


def abrir_ventana(esperar=True):
    """Abre la ventana del programa. Si esperar=True, no vuelve hasta que la cierren."""
    navegador = buscar_navegador()
    if not navegador:
        logging.warning("No se encontró Edge ni Chrome: se abre el navegador predeterminado")
        webbrowser.open(URL)
        return False
    perfil = config.DATA_DIR / "ventana"           # perfil propio: no se mezcla con el navegador de uso diario
    orden = [navegador, f"--app={URL}", "--start-maximized", f"--user-data-dir={perfil}",
             "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]
    proceso = subprocess.Popen(orden)
    if esperar:
        proceso.wait()                             # aquí se queda mientras la ventana esté abierta
    return True


def main():
    preparar_registro()
    logging.info("Abriendo Fervifarma (datos en %s)", config.DATA_DIR)
    # "Fervifarma.exe --solo-servidor": prende el programa sin abrir ventana
    # (para revisar que el instalador funciona, o para abrirlo desde otro lado)
    if "--solo-servidor" in sys.argv:
        if ya_esta_prendido() or prender_servidor():
            while True:
                time.sleep(3600)
        return
    if ya_esta_prendido():
        abrir_ventana(esperar=False)               # ya está prendido: solo otra ventana
        return
    if not prender_servidor():
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, f"No se pudo abrir el programa. Revisa el archivo de errores en:\n{config.LOG_DIR}",
                "Fervifarma", 0x10)
        return
    if abrir_ventana(esperar=True):
        # Se cerró la ventana. Si quedó otra abierta (por ejemplo una tirilla),
        # se espera a que el perfil quede libre antes de apagar.
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
