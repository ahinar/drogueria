"""Respaldos de la base de datos usando la API de respaldo de SQLite (segura con la base en uso)."""
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

PREFIJO = "drogueria_"


def listar_respaldos(carpeta):
    carpeta = Path(carpeta)
    if not carpeta.exists():
        return []
    return sorted(carpeta.glob(f"{PREFIJO}*.db"), reverse=True)


def hacer_respaldo(db_path, carpeta, extra=None, conservar=30):
    """Crea un respaldo con fecha, verifica su integridad y limpia los más antiguos.

    Devuelve (ruta_respaldo, avisos). Si la copia adicional falla, no se pierde el respaldo principal.
    """
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{PREFIJO}{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    origen = sqlite3.connect(str(db_path))
    copia = sqlite3.connect(str(destino))
    try:
        origen.backup(copia)
        resultado = copia.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        copia.close()
        origen.close()
    if resultado != "ok":
        destino.unlink(missing_ok=True)
        raise RuntimeError(f"El respaldo no pasó la verificación de integridad: {resultado}")

    avisos = []
    if extra:
        try:
            Path(extra).mkdir(parents=True, exist_ok=True)
            shutil.copy2(destino, Path(extra) / destino.name)
        except OSError as error:
            avisos.append(f"No se pudo copiar a la carpeta adicional: {error}")

    for viejo in listar_respaldos(carpeta)[conservar:]:
        viejo.unlink(missing_ok=True)
    return destino, avisos


def hacer_respaldo_si_toca(db_path, carpeta, extra=None, conservar=30, horas=24):
    """Hace un respaldo solo si el último tiene más de `horas` horas (o no hay ninguno)."""
    existentes = listar_respaldos(carpeta)
    if existentes:
        ultimo = datetime.fromtimestamp(existentes[0].stat().st_mtime)
        if datetime.now() - ultimo < timedelta(hours=horas):
            return None
    return hacer_respaldo(db_path, carpeta, extra, conservar)[0]
