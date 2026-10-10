"""
CARGA INICIAL: EXISTENCIAS POR LOTE Y FOTOS
===========================================

Lo usa el importador de productos (app/importador.py) cuando se sube, junto
con el archivo de productos, un archivo de LOTES (exportado del programa
anterior). En un solo paso quedan:
    1. los productos (con su foto, si el archivo la trae), y
    2. el inventario inicial: cada lote con su vencimiento y su cantidad.

Reglas (las mismas de todo el programa):
    - Las cantidades del programa anterior vienen en la unidad de medida del
      producto (ej. 22,5 SELLO X 10). Aquí se guardan en UNIDADES: 225.
    - Cantidades en 0 o negativas NO se cargan: se listan para revisarlas.
    - Si queda una fracción de unidad (ej. 37,67) se redondea.
    - Un lote que ya existe en el programa no se repite (subir dos veces el
      mismo archivo no duplica el inventario).
    - Productos SIN lote (cepillos, dulces...): su cantidad sale del archivo de
      productos ("Cantidad a la mano") y entra como "sin lote".
    - El costo de cada lote es el costo de 1 unidad de la ficha del producto.
    - En el kardex queda un movimiento "ajuste" con referencia "Carga inicial".
"""
import base64
import binascii
import io
import re
import unicodedata
from datetime import datetime

from PIL import Image
from werkzeug.datastructures import FileStorage

from .db import ahora
from . import presentaciones as pres
from .utils_imagenes import guardar_imagen

REFERENCIA = "Carga inicial"

# Nombres con que puede venir cada columna del archivo de lotes
COLUMNAS_LOTES = {
    "producto": ["producto", "nombre en pantalla", "nombre", "articulo"],
    "lote": ["numero de serie/lote", "lote/numero de serie", "numero de lote/serie", "lote", "numero de lote"],
    "vence": ["fecha de caducidad", "numero de serie/lote/fecha de caducidad", "lote/numero de serie/fecha de caducidad",
              "lote/fecha de caducidad", "vencimiento", "fecha de vencimiento", "vence"],
    "cantidad": ["cantidad a la mano", "cantidad", "cantidad contada", "existencias", "a la mano"],
}


def normal(texto):
    """'Número de serie/Lote ' -> 'numero de serie/lote' (sin tildes, minúsculas, espacios simples)."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().replace("*", "").split())


def fecha(valor):
    """'2026-12-31 05:00:00', '31/12/2026', '2026-12-31' -> '2026-12-31'. Vacío -> None."""
    t = str(valor or "").strip()
    if not t or t in ("0", "False", "None"):
        return None
    for formato, largo in (("%Y-%m-%d", 10), ("%d/%m/%Y", 10), ("%d-%m-%Y", 10)):
        try:
            return datetime.strptime(t[:largo], formato).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _numero(valor):
    from .importador import _num
    return _num(valor, 0)


class BuscadorProductos:
    """Encuentra un producto por código de barras, código o nombre.

    El programa anterior escribe el producto así: "[7702027440106] DOLEX GRIPA"
    (lo de los corchetes es la referencia, a veces el código de barras) o solo
    con el nombre.
    """
    def __init__(self, db):
        self.por_barras, self.por_codigo, self.por_nombre = {}, {}, {}
        for p in db.execute("SELECT id, codigo, codigo_barras, nombre FROM productos"):
            if p["codigo_barras"]:
                self.por_barras[p["codigo_barras"].strip()] = p["id"]
            self.por_codigo[p["codigo"].strip().lower()] = p["id"]
            self.por_nombre.setdefault(normal(p["nombre"]), p["id"])
        for pp in db.execute("SELECT producto_id, codigo_barras FROM producto_presentaciones "
                             "WHERE codigo_barras IS NOT NULL"):
            self.por_barras.setdefault(pp["codigo_barras"].strip(), pp["producto_id"])

    def buscar(self, texto, barras=None):
        if barras and barras.strip() in self.por_barras:
            return self.por_barras[barras.strip()]
        texto = str(texto or "").strip()
        m = re.match(r"^\[(.+?)\]\s*(.*)$", texto)
        ref, nombre = (m.group(1).strip(), m.group(2)) if m else ("", texto)
        for intento in (self.por_barras.get(ref), self.por_codigo.get(ref.lower()),
                        self.por_nombre.get(normal(nombre)), self.por_nombre.get(normal(texto))):
            if intento:
                return intento
        return None


def leer_lotes(filas):
    """Filas del archivo de lotes -> [{fila, producto, lote, vence, cantidad}].

    Las filas sin producto (títulos de grupo, ej. "WH/EXISTENCIAS (203)") se saltan.
    Devuelve (lotes, error).
    """
    if not filas:
        return [], None
    normales = {normal(e): e for e in filas[0].keys()}
    mapa = {}
    for dato, opciones in COLUMNAS_LOTES.items():
        for o in opciones:
            if o in normales and normales[o] not in mapa.values():
                mapa[dato] = normales[o]
                break
    if "producto" not in mapa or "cantidad" not in mapa:
        return None, ("El archivo de lotes debe traer las columnas 'Producto' y 'Cantidad a la mano'. "
                      f"Trae: {', '.join(list(filas[0].keys())[:8])}")
    lotes = []
    for i, f in enumerate(filas, 2):                     # fila 1 = encabezados
        producto = (f.get(mapa["producto"]) or "").strip()
        if not producto:
            continue
        lote = str(f.get(mapa.get("lote", ""), "") or "").strip().upper() or None
        if lote in ("0", "FALSE", "NONE"):
            lote = None
        lotes.append({"fila": i, "producto": producto, "lote": lote,
                      "vence": fecha(f.get(mapa.get("vence", ""), "")),
                      "cantidad": _numero(f.get(mapa["cantidad"]))})
    return lotes, None


def resumen_lotes(lotes):
    """Para la previsualización: cuántos lotes traen cantidad y cuáles se omiten."""
    con = [l for l in lotes if l["cantidad"] > 0]
    negativos = [l for l in lotes if l["cantidad"] < 0]
    return {"total": len(lotes), "con_cantidad": len(con),
            "productos": len({normal(l["producto"]) for l in con}),
            "en_cero": sum(1 for l in lotes if l["cantidad"] == 0), "negativos": negativos}


def guardar_foto(texto):
    """Foto escrita como texto (base64, así la exporta el programa anterior) -> archivo.

    Devuelve (ruta, error). Se averigua el formato real (webp, png, jpg) y se
    guarda reducida a 600 px para que el POS cargue rápido.
    """
    texto = str(texto or "").strip()
    if not texto or texto in ("False", "0", "None"):
        return None, None
    if " " in texto:
        # No es una foto sino un mensaje: Excel no deja guardar textos de más de
        # 32.767 letras, y el programa anterior pone un aviso en vez de la foto.
        return None, "grande"
    try:
        datos = base64.b64decode(texto, validate=False)
        formato = (Image.open(io.BytesIO(datos)).format or "PNG").lower()
    except (binascii.Error, ValueError, OSError):
        return None, "la foto está dañada o incompleta"
    extension = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif"}.get(formato, ".png")
    return guardar_imagen(FileStorage(stream=io.BytesIO(datos), filename="foto" + extension),
                          "productos", max_px=600, max_bytes=10 * 1024 * 1024)


def cargar_existencias(db, lotes, cantidades_producto, usuario, lotes_subidos=True):
    """Crea los lotes del inventario inicial.

    lotes               -> lo que devuelve leer_lotes()
    cantidades_producto -> [{nombre, barras, cantidad}] del archivo de productos
                           ("Cantidad a la mano", en la unidad de medida del producto)
    lotes_subidos       -> si se subió el archivo de lotes. Si no, solo se cargan
                           los productos que no manejan lote.
    Devuelve un resumen {lotes, unidades, repetidos, problemas}.
    """
    buscador = BuscadorProductos(db)
    productos = {p["id"]: p for p in db.execute("SELECT * FROM productos")}
    opciones = pres.presentaciones_de(list(productos))

    def factor(pid):
        """Las cantidades vienen en la unidad de medida del producto, que al
        importar quedó como su unidad de venta (ej. SELLO X 10 -> 10)."""
        ops = opciones.get(pid, [])
        defecto = pres.id_por_defecto(ops, productos[pid]["venta_defecto_unidad_id"])
        return next((o["factor"] for o in ops if o["id"] == defecto), 1.0)

    grupos, problemas, suma_lotes = {}, [], {}
    for l in lotes:
        pid = buscador.buscar(l["producto"])
        if not pid:
            if l["cantidad"] > 0:
                problemas.append(f"Lote {l['lote'] or '-'} de «{l['producto']}»: el producto no existe")
            continue
        if l["cantidad"] < 0:
            problemas.append(f"«{productos[pid]['nombre']}» lote {l['lote'] or '-'}: cantidad {l['cantidad']:g} (negativa)")
        if l["cantidad"] <= 0:
            continue
        g = grupos.setdefault((pid, l["lote"]), {"cantidad": 0.0, "vence": l["vence"]})
        g["cantidad"] += l["cantidad"]
        g["vence"] = g["vence"] or l["vence"]
        suma_lotes[pid] = suma_lotes.get(pid, 0) + l["cantidad"]

    # Lo que el producto tiene y no está en ningún lote -> "sin lote"
    sin_lote_pendientes = 0
    for c in cantidades_producto:
        pid = buscador.buscar(c["nombre"], c.get("barras"))
        if not pid:
            continue
        if c["cantidad"] < 0:
            problemas.append(f"«{productos[pid]['nombre']}»: cantidad {c['cantidad']:g} (negativa)")
            continue
        resto = round(c["cantidad"] - suma_lotes.get(pid, 0), 4)
        if resto <= 0:
            continue
        if productos[pid]["maneja_vencimiento"] and not lotes_subidos:
            sin_lote_pendientes += 1           # maneja lote: hay que subir el archivo de lotes o contarlo
            continue
        g = grupos.setdefault((pid, None), {"cantidad": 0.0, "vence": None})
        g["cantidad"] += resto

    creados, unidades, repetidos = 0, 0, 0
    for (pid, lote), g in grupos.items():
        cant = round(g["cantidad"] * factor(pid))
        if cant <= 0:
            continue
        if db.execute("SELECT 1 FROM lotes WHERE producto_id = ? AND UPPER(TRIM(COALESCE(lote, ''))) = ? "
                      "AND estado <> 'rechazado'", (pid, lote or "")).fetchone():
            repetidos += 1
            continue
        costo = float(productos[pid]["precio_compra"] or 0)
        cur = db.execute(
            "INSERT INTO lotes (producto_id, lote, vencimiento, cantidad_inicial, cantidad_disponible, "
            "costo_unitario, estado, creado_en) VALUES (?,?,?,?,?,?, 'disponible', ?)",
            (pid, lote, g["vence"], cant, cant, costo, ahora()))
        db.execute(
            "INSERT INTO movimientos_inventario (fecha, lote_id, producto_id, tipo, cantidad, referencia, "
            "usuario_id, usuario_nombre, creado_en) VALUES (?,?,?, 'ajuste', ?, ?, ?, ?, ?)",
            (ahora(), cur.lastrowid, pid, cant, REFERENCIA, usuario["id"], usuario["nombre"], ahora()))
        creados += 1
        unidades += cant
    return {"lotes": creados, "unidades": unidades, "repetidos": repetidos,
            "problemas": problemas, "sin_lote_pendientes": sin_lote_pendientes}
