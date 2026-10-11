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


# ======================================================================
# RESPALDO DE LOS ARCHIVOS (fotos, certificados, actas, documentos)
# ----------------------------------------------------------------------
# La base de datos guarda el NOMBRE de cada foto o documento, pero el
# archivo vive aparte, en la carpeta "uploads". Una vez por semana se
# guarda todo eso en un ZIP (se conservan los 4 últimos).
# ======================================================================
PREFIJO_ARCHIVOS = "archivos_"


def listar_respaldos_archivos(carpeta):
    carpeta = Path(carpeta)
    if not carpeta.exists():
        return []
    return sorted(carpeta.glob(f"{PREFIJO_ARCHIVOS}*.zip"), reverse=True)


def respaldar_archivos(uploads_dir, carpeta, extra=None, conservar=4):
    """ZIP de la carpeta de archivos subidos. Devuelve la ruta del ZIP (o None si no hay nada)."""
    uploads_dir = Path(uploads_dir)
    if not uploads_dir.exists() or not any(uploads_dir.rglob("*")):
        return None
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    base = carpeta / f"{PREFIJO_ARCHIVOS}{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    destino = Path(shutil.make_archive(str(base), "zip", root_dir=str(uploads_dir)))
    if extra:
        try:
            Path(extra).mkdir(parents=True, exist_ok=True)
            shutil.copy2(destino, Path(extra) / destino.name)
        except OSError:
            pass
    for viejo in listar_respaldos_archivos(carpeta)[conservar:]:
        viejo.unlink(missing_ok=True)
    return destino


def respaldar_archivos_si_toca(uploads_dir, carpeta, extra=None, dias=7):
    """Hace el ZIP de los archivos si el último tiene más de `dias` días (o no hay ninguno)."""
    existentes = listar_respaldos_archivos(carpeta)
    if existentes:
        ultimo = datetime.fromtimestamp(existentes[0].stat().st_mtime)
        if datetime.now() - ultimo < timedelta(days=dias):
            return None
    return respaldar_archivos(uploads_dir, carpeta, extra)


# ======================================================================
# RELOJ DE RESPALDOS
# ----------------------------------------------------------------------
# Antes el respaldo solo se hacía al ABRIR el programa. Si el computador
# del local queda prendido varios días, no se respaldaba nada. Ahora un
# "hilo" (un trabajito que corre por debajo, sin estorbar) revisa cada
# hora: si el último respaldo tiene más de 24 horas, hace uno nuevo; y una
# vez por semana guarda también las fotos y documentos.
# ======================================================================
def carpeta_extra(app):
    """Carpeta adicional (USB, Drive...): la escogida en Respaldos o la de config.py."""
    try:
        import sqlite3 as _sqlite
        con = _sqlite.connect(app.config["DB_PATH"])
        fila = con.execute("SELECT valor FROM config WHERE clave = 'respaldo_carpeta_extra'").fetchone()
        con.close()
        if fila and (fila[0] or "").strip():
            return fila[0].strip()
    except Exception:
        pass
    return app.config.get("BACKUP_EXTRA_DIR")


def revisar_respaldos(app):
    """Hace los respaldos que toquen (base de datos cada 24 h, archivos cada 7 días)."""
    import logging
    log = logging.getLogger("drogueria")
    extra = carpeta_extra(app)
    try:
        nuevo = hacer_respaldo_si_toca(app.config["DB_PATH"], app.config["BACKUP_DIR"], extra,
                                       app.config["BACKUP_KEEP"])
        if nuevo:
            log.info("Respaldo automático creado: %s", nuevo)
    except Exception:
        log.exception("No se pudo hacer el respaldo automático de la base de datos")
    try:
        zip_ = respaldar_archivos_si_toca(app.config["UPLOADS_DIR"], app.config["BACKUP_DIR"], extra)
        if zip_:
            log.info("Respaldo de archivos creado: %s", zip_)
    except Exception:
        log.exception("No se pudo hacer el respaldo de las fotos y documentos")


def iniciar_reloj_de_respaldos(app, cada_segundos=3600):
    """Arranca el reloj (una sola vez). Lo llaman run.py y escritorio.py."""
    import threading
    import time

    def trabajar():
        while True:
            revisar_respaldos(app)
            time.sleep(cada_segundos)

    hilo = threading.Thread(target=trabajar, name="respaldos", daemon=True)   # daemon: se apaga con el programa
    hilo.start()
    return hilo
