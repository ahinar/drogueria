"""Respaldo manual o programado: python backup.py"""
import sys

import config
from app.backup_utils import hacer_respaldo

if __name__ == "__main__":
    if not config.DB_PATH.exists():
        print("No existe la base de datos todavía. Inicia el sistema una vez primero.")
        sys.exit(1)
    destino, avisos = hacer_respaldo(config.DB_PATH, config.BACKUP_DIR, config.BACKUP_EXTRA_DIR, config.BACKUP_KEEP)
    print(f"Respaldo creado y verificado: {destino}")
    for aviso in avisos:
        print(f"AVISO: {aviso}")
