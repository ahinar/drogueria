"""
IMPORTAR FOTOS DE PRODUCTOS DESDE ODOO
======================================

Odoo puede exportar la foto de cada producto dentro del archivo, como un
texto largo (la imagen "codificada en base64": letras y números que
representan los puntos de la foto). Aquí se lee ese texto, se vuelve a
convertir en imagen y se le pone a su producto.

Archivo: en Odoo, Inventario → Productos (vista lista) → seleccionar todos →
Exportar en formato CSV con: Nombre, Código de barras e Imagen 512.
(En Excel no sirve: Excel corta los textos de más de 32.767 letras.)

Cada producto se busca por código de barras y, si no tiene, por nombre.
Por defecto solo se pone foto a los productos que NO tienen; con la casilla
"Reemplazar" también se cambian las que ya estaban.
"""
import base64
import binascii
import csv
import io
import sys

from flask import Blueprint, flash, redirect, render_template, request, url_for
from PIL import Image
from werkzeug.datastructures import FileStorage

from .audit import registrar
from .auth import roles_required
from .db import get_db
from .importador import _abrir_archivo
from .importador_existencias import _BuscadorProductos, _normal
from .utils_imagenes import eliminar_imagen, guardar_imagen

bp = Blueprint("imagenes", __name__, url_prefix="/productos/importar/imagenes")

# Una foto en base64 es un texto muy largo: se sube el límite del lector de CSV
csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))


def _columna(encabezados, opciones):
    normales = {_normal(e): e for e in encabezados}
    return next((normales[o] for o in opciones if o in normales), None)


@bp.route("/", methods=["GET", "POST"])
@roles_required("administrador", "director_tecnico")
def inicio():
    if request.method == "GET":
        return render_template("importador/imagenes.html")
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Escoge el archivo.", "error")
        return redirect(url_for("imagenes.inicio"))
    filas, error = _abrir_archivo(archivo.filename, archivo.read())
    if error or not filas:
        flash(error or "El archivo no tiene filas.", "error")
        return redirect(url_for("imagenes.inicio"))
    encabezados = list(filas[0].keys())
    col_img = _columna(encabezados, ["imagen 512", "imagen 1024", "imagen", "imagen 1920", "imagen 256",
                                     "imagen 128", "image", "foto"])
    col_nombre = _columna(encabezados, ["nombre", "producto", "nombre en pantalla"])
    col_barras = _columna(encabezados, ["codigo de barras", "barras", "ean"])
    if not col_img or not (col_nombre or col_barras):
        flash("El archivo debe traer la columna de la imagen y el Nombre o el Código de barras.", "error")
        return redirect(url_for("imagenes.inicio"))

    reemplazar = bool(request.form.get("reemplazar"))
    db = get_db()
    buscador = _BuscadorProductos(db)
    puestas, sin_foto, no_encontrados, ya_tenian, danadas = 0, 0, [], 0, []
    for f in filas:
        texto = (f.get(col_img) or "").strip()
        if not texto or texto in ("False", "0"):
            sin_foto += 1
            continue
        barras = (f.get(col_barras) or "").strip() if col_barras else ""
        nombre = (f.get(col_nombre) or "").strip() if col_nombre else ""
        pid = (buscador.por_barras.get(barras) if barras else None) or (buscador.buscar(nombre) if nombre else None)
        if not pid:
            no_encontrados.append(nombre or barras)
            continue
        prod = db.execute("SELECT id, imagen FROM productos WHERE id = ?", (pid,)).fetchone()
        if prod["imagen"] and not reemplazar:
            ya_tenian += 1
            continue
        # Texto -> bytes de la imagen. Se averigua el formato real (png, jpg, webp...)
        try:
            datos = base64.b64decode(texto, validate=False)
            formato = (Image.open(io.BytesIO(datos)).format or "PNG").lower()
        except (binascii.Error, ValueError, OSError):
            danadas.append(nombre or barras)
            continue
        extension = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif"}.get(formato, ".png")
        foto = FileStorage(stream=io.BytesIO(datos), filename="odoo" + extension)
        ruta, error = guardar_imagen(foto, "productos", max_px=600, max_bytes=10 * 1024 * 1024)
        if not ruta:
            danadas.append(f"{nombre or barras} ({error})")
            continue
        if prod["imagen"]:
            eliminar_imagen(prod["imagen"])
        db.execute("UPDATE productos SET imagen = ? WHERE id = ?", (ruta, pid))
        puestas += 1
    db.commit()
    registrar("imagenes_importadas", "productos", None,
              f"puestas={puestas} ya_tenian={ya_tenian} no_encontrados={len(no_encontrados)} danadas={len(danadas)}")
    return render_template("importador/imagenes.html", resultado={
        "puestas": puestas, "sin_foto": sin_foto, "ya_tenian": ya_tenian,
        "no_encontrados": no_encontrados, "danadas": danadas})
