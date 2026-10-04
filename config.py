"""Configuración del sistema. Los valores se pueden cambiar con variables de entorno. config.py"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "db"
DB_PATH = Path(os.environ.get("DROGUERIA_DB", DB_DIR / "drogueria.db"))
SECRET_KEY_FILE = DB_DIR / "secret.key"

BACKUP_DIR = Path(os.environ.get("DROGUERIA_BACKUPS", BASE_DIR / "backups"))
# Carpeta adicional opcional (memoria USB, carpeta sincronizada con la nube, etc.)
BACKUP_EXTRA_DIR = os.environ.get("DROGUERIA_BACKUP_EXTRA") or None
BACKUP_KEEP = int(os.environ.get("DROGUERIA_BACKUP_KEEP", "30"))  # cuántos respaldos conservar

PDF_DIR = BASE_DIR / "pdfs"
STATIC_DIR = BASE_DIR / "static"

HOST = os.environ.get("DROGUERIA_HOST", "0.0.0.0")  # 0.0.0.0 = visible en la red local
PORT = int(os.environ.get("DROGUERIA_PORT", "5000"))
SESSION_HORAS = int(os.environ.get("DROGUERIA_SESION_HORAS", "10"))

UPLOADS_DIR = BASE_DIR / "static" / "uploads"