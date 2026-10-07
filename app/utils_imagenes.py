"""Utilidades para procesar y guardar imágenes con cualquier formato."""
import os
import uuid
from pathlib import Path

from flask import current_app
from PIL import Image, UnidentifiedImageError

# Extensiones aceptadas (se guardan tal cual)
EXT_DIRECTAS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Extensiones que se convierten a PNG automáticamente
EXT_CONVERTIR = {".tif", ".tiff", ".bmp", ".heic", ".heif"}

EXT_ACEPTADAS = EXT_DIRECTAS | EXT_CONVERTIR


def es_extension_valida(nombre_archivo):
    ext = Path(nombre_archivo).suffix.lower()
    return ext in EXT_ACEPTADAS


def guardar_imagen(archivo, subcarpeta, max_px=1200, max_bytes=5 * 1024 * 1024,
                   nombre_fijo=None, forzar_extension=None):
    """Guarda una imagen validada y optimizada.

    Devuelve (ruta_relativa, error).
    - ruta_relativa: 'uploads/<subcarpeta>/<archivo>' para guardar en BD.
    - error: None si fue bien, o string con el motivo.

    Parámetros:
    - archivo: FileStorage de Flask (request.files['...'])
    - subcarpeta: 'logos', 'productos', 'recepciones', etc.
    - max_px: lado máximo (ancho o alto) al que se redimensiona.
    - max_bytes: peso máximo permitido al subir.
    - nombre_fijo: si se especifica, se guarda con ese nombre base (ej. 'logo').
    - forzar_extension: fuerza la extensión de salida (ej. '.png').
    """
    if not archivo or not archivo.filename:
        return None, "No se recibió ningún archivo."

    ext_original = Path(archivo.filename).suffix.lower()
    if ext_original not in EXT_ACEPTADAS:
        return None, f"Formato no soportado: {ext_original}. Usa JPG, PNG, WEBP, GIF o TIFF."

    # Verificar tamaño
    archivo.seek(0, os.SEEK_END)
    peso = archivo.tell()
    archivo.seek(0)
    if peso > max_bytes:
        mb_max = max_bytes / (1024 * 1024)
        return None, f"El archivo pesa {peso/1024/1024:.1f} MB. Máximo permitido: {mb_max:.1f} MB."

    # Abrir la imagen
    try:
        img = Image.open(archivo.stream)
        img.load()
    except UnidentifiedImageError:
        return None, "El archivo no es una imagen válida."
    except Exception as e:
        return None, f"No se pudo abrir la imagen: {e}"

    # Determinar formato de salida
    if forzar_extension:
        ext_salida = forzar_extension.lower()
    elif ext_original in EXT_CONVERTIR:
        ext_salida = ".png"
    else:
        ext_salida = ext_original

    # Aplanar imágenes con canal alfa para JPG
    if ext_salida in (".jpg", ".jpeg"):
        if img.mode in ("RGBA", "LA", "P"):
            fondo = Image.new("RGB", img.size, (255, 255, 255))
            img = img.convert("RGBA")
            fondo.paste(img, mask=img.split()[-1])
            img = fondo
        elif img.mode != "RGB":
            img = img.convert("RGB")

    # Redimensionar si excede el tamaño
    if max(img.size) > max_px:
        img.thumbnail((max_px, max_px), Image.LANCZOS)

    # Nombre del archivo
    if nombre_fijo:
        base = nombre_fijo
    else:
        base = uuid.uuid4().hex
    nombre = f"{base}{ext_salida}"

    # Crear carpeta
    carpeta = Path(current_app.static_folder) / "uploads" / subcarpeta
    carpeta.mkdir(parents=True, exist_ok=True)

    # Guardar
    ruta_fisica = carpeta / nombre
    try:
        if ext_salida == ".gif":
            # GIF se guarda tal cual (no perder animación)
            archivo.seek(0)
            with open(ruta_fisica, "wb") as f:
                f.write(archivo.read())
        elif ext_salida == ".webp":
            img.save(ruta_fisica, "WEBP", quality=85, method=6)
        elif ext_salida in (".jpg", ".jpeg"):
            img.save(ruta_fisica, "JPEG", quality=85, optimize=True)
        else:
            # PNG por defecto
            img.save(ruta_fisica, "PNG", optimize=True)
    except Exception as e:
        return None, f"No se pudo guardar la imagen: {e}"

    ruta_relativa = f"uploads/{subcarpeta}/{nombre}"
    return ruta_relativa, None


def eliminar_imagen(ruta_relativa):
    """Elimina un archivo de imagen del disco (silenciosamente si no existe)."""
    if not ruta_relativa:
        return
    ruta_fisica = Path(current_app.static_folder) / ruta_relativa
    try:
        ruta_fisica.unlink(missing_ok=True)
    except OSError:
        pass