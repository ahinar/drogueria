"""Configuración del sistema. Los valores se pueden cambiar con variables de entorno. config.py

DÓNDE QUEDA CADA COSA (para aprender):
    Hay dos carpetas distintas:

    1. La carpeta del PROGRAMA (BASE_DIR): el código, las plantillas, los
       estilos. Cuando se instala una actualización, esta carpeta se REEMPLAZA.

    2. La carpeta de DATOS (DATA_DIR): la base de datos, las fotos de los
       productos, los certificados, los documentos y los respaldos. Esta NUNCA
       se toca al actualizar: así no se pierde nada.

    - Programando (python run.py): las dos son la carpeta del proyecto, como
      siempre (db/, backups/, static/uploads/).
    - Instalado en Windows (el .exe): el programa queda en "Archivos de
      programa" y los datos en  C:\\Users\\<usuario>\\AppData\\Local\\Fervifarma
      (la variable de Windows %LOCALAPPDATA%). Se puede cambiar con la
      variable de entorno FERVIFARMA_DATOS.
"""
import os
import sys
from pathlib import Path

# ¿Corre como programa instalado (empaquetado con PyInstaller)? En ese caso
# sys.frozen existe y los archivos del programa están en sys._MEIPASS.
INSTALADO = bool(getattr(sys, "frozen", False))

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

if os.environ.get("FERVIFARMA_DATOS"):
    DATA_DIR = Path(os.environ["FERVIFARMA_DATOS"])
elif INSTALADO:
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Fervifarma"
else:
    DATA_DIR = Path(__file__).resolve().parent

DB_DIR = DATA_DIR / "db"
DB_PATH = Path(os.environ.get("DROGUERIA_DB", DB_DIR / "drogueria.db"))
SECRET_KEY_FILE = DB_DIR / "secret.key"

BACKUP_DIR = Path(os.environ.get("DROGUERIA_BACKUPS", DATA_DIR / ("respaldos" if INSTALADO else "backups")))
# Carpeta adicional opcional (memoria USB, carpeta sincronizada con la nube, etc.).
# También se puede escoger en el programa: Administración → Respaldos.
BACKUP_EXTRA_DIR = os.environ.get("DROGUERIA_BACKUP_EXTRA") or None
BACKUP_KEEP = int(os.environ.get("DROGUERIA_BACKUP_KEEP", "30"))  # cuántos respaldos conservar

PDF_DIR = DATA_DIR / "pdfs"
STATIC_DIR = BASE_DIR / "static"
# Fotos, certificados, actas y documentos que sube la droguería
UPLOADS_DIR = DATA_DIR / "uploads" if INSTALADO else BASE_DIR / "static" / "uploads"
# Registro de lo que pasa (errores), sobre todo para el programa instalado
LOG_DIR = DATA_DIR / "logs"

# Instalado, el programa solo se ve en ESTE computador (127.0.0.1) y usa el
# puerto 8765 para no chocar con otros programas. Programando: toda la red, 5000.
HOST = os.environ.get("DROGUERIA_HOST", "127.0.0.1" if INSTALADO else "0.0.0.0")
PORT = int(os.environ.get("DROGUERIA_PORT", "8765" if INSTALADO else "5000"))
SESSION_HORAS = int(os.environ.get("DROGUERIA_SESION_HORAS", "10"))
