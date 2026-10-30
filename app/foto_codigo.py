"""FOTO DEL PRODUCTO POR CÓDIGO DE BARRAS (versión 1.1.16).

PARA QUÉ
--------
En la ficha del producto, el botón «🔎 Buscar foto» toma el código de barras y
busca una foto en internet, para no tener que tomarla con el celular.

DÓNDE BUSCA
-----------
En las bases de datos ABIERTAS y gratuitas de «Open Facts» (las arma la gente,
como Wikipedia, y no piden clave):
  - Open Food Facts      → alimentos, dulces, bebidas, suplementos
  - Open Beauty Facts    → cremas, champú, desodorantes, cuidado personal
  - Open Products Facts  → otros productos (pañales, aseo...)

OJO (para no crear falsas esperanzas): los MEDICAMENTOS casi nunca están ahí.
Funciona sobre todo con la parte de miscelánea, dulcería y cuidado personal.
Si no encuentra nada, se sigue subiendo la foto a mano como siempre.

CÓMO LLEGA LA FOTO AL PRODUCTO
------------------------------
El servidor baja la foto y se la entrega a la página; la página la pone en el
campo «Cambiar imagen» como si la hubieran escogido a mano. Así se GUARDA con
el botón Guardar de siempre (misma revisión y mismo tamaño que una foto normal),
y si no le gusta, simplemente no guarda.
"""
import json
import re
import urllib.error
import urllib.request

FUENTES = [
    ("Open Food Facts", "https://world.openfoodfacts.org/api/v2/product/{codigo}.json"),
    ("Open Beauty Facts", "https://world.openbeautyfacts.org/api/v2/product/{codigo}.json"),
    ("Open Products Facts", "https://world.openproductsfacts.org/api/v2/product/{codigo}.json"),
]
ESPERA = 8                       # segundos máximo por consulta
PESO_MAXIMO = 5 * 1024 * 1024    # no bajar fotos de más de 5 MB
# Open Facts pide que cada programa se identifique (es de buena educación con un servicio gratis)
CABECERAS = {"User-Agent": "Fervifarma-POS/1.1 (drogueria; foto por codigo de barras)"}


def codigo_valido(codigo):
    """Solo números, de 8 a 14 cifras (EAN-8, UPC, EAN-13, GTIN-14)."""
    return bool(re.fullmatch(r"\d{8,14}", codigo or ""))


def _bajar(url, maximo=PESO_MAXIMO):
    """Baja una dirección de internet y devuelve los bytes (lanza error si falla)."""
    with urllib.request.urlopen(urllib.request.Request(url, headers=CABECERAS), timeout=ESPERA) as r:
        datos = r.read(maximo + 1)
    if len(datos) > maximo:
        raise ValueError("la foto pesa demasiado")
    return datos


def _url_foto(producto):
    """De la ficha de Open Facts, la mejor foto: la del frente (en español si hay)."""
    for clave in ("image_front_url", "image_url"):
        if producto.get(clave):
            return producto[clave]
    fotos = (producto.get("selected_images") or {}).get("front", {}).get("display", {})
    return fotos.get("es") or next(iter(fotos.values()), None)


def buscar_foto(codigo):
    """Busca la foto en las 3 fuentes, en orden.

    Devuelve un diccionario:
      encontrada: {"ok": True, "foto": bytes, "fuente": "Open Food Facts", "nombre": "Galletas..."}
      no:         {"ok": False, "error": "por qué"}
    """
    codigo = (codigo or "").strip()
    if not codigo_valido(codigo):
        return {"ok": False, "error": "El código de barras debe tener solo números (de 8 a 14)."}
    hubo_conexion = False
    for fuente, plantilla in FUENTES:
        try:
            ficha = json.loads(_bajar(plantilla.format(codigo=codigo)).decode("utf-8"))
            hubo_conexion = True
        except urllib.error.HTTPError:                # respondió «no lo tengo» (404): sí hay internet
            hubo_conexion = True
            continue
        except Exception:
            continue                                  # esta fuente falló: se prueba la siguiente
        producto = ficha.get("product") or {}         # (si no lo tiene, viene vacío o con status 0)
        url = _url_foto(producto) if producto else None
        if not url:
            continue
        try:
            foto = _bajar(url)
        except Exception:
            continue
        nombre = producto.get("product_name_es") or producto.get("product_name") or ""
        return {"ok": True, "foto": foto, "fuente": fuente, "nombre": nombre}
    if not hubo_conexion:
        return {"ok": False, "error": "No se pudo conectar a internet para buscar la foto."}
    return {"ok": False, "error": "No se encontró foto para ese código. Los medicamentos casi nunca están en "
                                  "estas bases; tome la foto con el celular y súbala como siempre."}
