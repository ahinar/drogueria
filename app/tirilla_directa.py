"""
TIRILLA DIRECTA A LA IMPRESORA (ESC/POS)
========================================

PARA QUÉ (para aprender):
    Hay dos maneras de imprimir el comprobante de una venta:

    1. POR EL NAVEGADOR (la de siempre): se abre la página del comprobante
       (pos/comprobante.html) y se le da "Imprimir". Imprime en la impresora
       del computador donde está abierta la ventana, y Windows convierte la
       página en una imagen: por eso a veces las letras salen pálidas.

    2. DIRECTA (este archivo): el programa arma la tirilla como TEXTO en el
       idioma de las impresoras térmicas (ESC/POS) y se la manda "cruda" a la
       impresora del PC principal (con cajon.enviar_crudo). Ventajas:
         - Sale con la letra propia de la impresora: negra y nítida.
         - Sale SIEMPRE por la impresora del mostrador, aunque la venta se
           haga desde el portátil (incluso desde la casa).
         - Es más rápida y no muestra ventanas de "Imprimir".
       Desventaja: no lleva el logo (la imagen); solo texto.

    Se escoge en Administración → Configuración → Impresora de tirillas.

CÓMO FUNCIONA ESC/POS (lo básico):
    La impresora recibe letras normales y, mezcladas, unas "órdenes" que
    empiezan con el byte ESC (27) o GS (29). Por ejemplo:
        ESC @        -> borrar todo y empezar limpio
        ESC a 1      -> centrar         (ESC a 0 = a la izquierda)
        ESC E 1      -> negrilla        (ESC E 0 = quitarla)
        GS ! 0x11    -> letra doble de alto y de ancho (GS ! 0 = normal)
        GS V 66 3    -> avanzar un poco el papel y cortarlo
    Las letras van una por renglón con un "salto de línea" (byte 10) al final.

    ¿Cuántas letras caben por renglón? Con la letra normal:
        papel de 80 mm -> 48 letras      papel de 58 mm -> 32 letras

TILDES: cada impresora trae varias "tablas de letras". Se pide la PC850
    (la de español en casi todas). Si en alguna impresora las tildes salen
    raras, en Configuración se escoge "sin tildes" y se imprimen sin ellas
    (á -> a, ñ -> n).
"""
import unicodedata

from .formato import pesos

# ---- Órdenes ESC/POS (bytes) ----
ESC, GS = b"\x1b", b"\x1d"
INICIAR = ESC + b"@"
TABLA_PC850 = ESC + b"t\x02"          # tabla de letras con tildes y ñ
CENTRO = ESC + b"a\x01"
IZQUIERDA = ESC + b"a\x00"
NEGRILLA = ESC + b"E\x01"
SIN_NEGRILLA = ESC + b"E\x00"
GRANDE = GS + b"!\x11"                # doble alto y doble ancho
ALTA = GS + b"!\x01"                  # solo doble alto (cabe el mismo ancho de letras)
NORMAL = GS + b"!\x00"
CORTAR = GS + b"V\x42\x03"            # avanza 3 puntos y corta (si la impresora no corta, no pasa nada)
SALTO = b"\n"

LETRAS_POR_ANCHO = {"80": 48, "58": 32}


class Tirilla:
    """Arma la tirilla renglón por renglón y al final da los bytes para la impresora."""

    def __init__(self, ancho="80", tildes=True):
        self.columnas = LETRAS_POR_ANCHO.get(str(ancho), 48)
        self.tildes = tildes
        self.datos = bytearray(INICIAR + (TABLA_PC850 if tildes else b""))

    # ---------- convertir texto a bytes ----------
    def _bytes(self, texto) -> bytes:
        texto = str(texto or "")
        if not self.tildes:
            # "Quitar tildes": se separa la letra de su tilde (á = a + ´) y se bota la tilde
            texto = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
        # cp850 = la tabla PC850; lo que no exista en ella sale como "?"
        return texto.encode("cp850", errors="replace")

    def orden(self, *ordenes):
        """Agrega órdenes ESC/POS (centrar, negrilla...)."""
        for o in ordenes:
            self.datos += o
        return self

    # ---------- renglones ----------
    def linea(self, texto=""):
        """Un texto; si es más largo que el papel, se parte en varios renglones por palabras."""
        for renglon in partir(str(texto or ""), self.columnas) or [""]:
            self.datos += self._bytes(renglon) + SALTO
        return self

    def dos_columnas(self, izquierda, derecha, columnas=None):
        """Texto a la izquierda y valor pegado a la derecha:  "TOTAL ........ $12.000"."""
        columnas = columnas or self.columnas
        derecha = str(derecha)
        espacio = columnas - len(derecha) - 1
        partes = partir(str(izquierda), max(espacio, 8)) or [""]
        for renglon in partes[:-1]:
            self.datos += self._bytes(renglon) + SALTO
        ultimo = partes[-1]
        self.datos += self._bytes(ultimo + " " * max(columnas - len(ultimo) - len(derecha), 1) + derecha) + SALTO
        return self

    def separador(self, caracter="-"):
        self.datos += self._bytes(caracter * self.columnas) + SALTO
        return self

    def terminar(self) -> bytes:
        """Deja espacio para arrancar el papel, corta y devuelve todo."""
        self.datos += SALTO * 4 + CORTAR
        return bytes(self.datos)


def partir(texto: str, columnas: int) -> list:
    """Parte un texto en renglones de máximo `columnas` letras, sin cortar palabras (si se puede)."""
    renglones, actual = [], ""
    for palabra in texto.split():
        while len(palabra) > columnas:                 # palabra larguísima: se corta a la fuerza
            if actual:
                renglones.append(actual)
                actual = ""
            renglones.append(palabra[:columnas])
            palabra = palabra[columnas:]
        if not actual:
            actual = palabra
        elif len(actual) + 1 + len(palabra) <= columnas:
            actual += " " + palabra
        else:
            renglones.append(actual)
            actual = palabra
    if actual:
        renglones.append(actual)
    return renglones


def _fecha_hora(t):
    """'2026-10-10 07:15:00' -> '10/10/2026 07:15' (igual que en las páginas)."""
    t = t or ""
    if len(t) < 10:
        return t
    return f"{t[8:10]}/{t[5:7]}/{t[0:4]}" + (f" {t[11:16]}" if len(t) >= 16 else "")


def _cantidad(valor):
    """2.0 -> '2' ; 1.5 -> '1.5' (como el '%g' de la página)."""
    return "%g" % (valor or 0)


def armar_venta(venta, lineas, cfg, saldo_cliente=None) -> bytes:
    """Bytes ESC/POS del comprobante de una venta (el mismo contenido de pos/comprobante.html).

    venta, lineas = filas de las tablas ventas y venta_lineas
    cfg           = configuración del negocio (obtener_config())
    saldo_cliente = en ventas a crédito, cuánto debe en total el cliente
    """
    t = Tirilla(cfg.get("ancho_tirilla") or "80", tildes=cfg.get("tirilla_tildes", "si") != "no")

    # ---------- Encabezado: datos del negocio, centrado ----------
    t.orden(CENTRO, NEGRILLA, ALTA)
    t.linea(cfg.get("nombre_comercial") or cfg.get("razon_social") or "Droguería")
    t.orden(NORMAL, SIN_NEGRILLA)
    if cfg.get("razon_social") and cfg.get("nombre_comercial"):
        t.linea(cfg["razon_social"])
    if cfg.get("nit"):
        t.linea(f"NIT {cfg['nit']}")
    if cfg.get("direccion"):
        t.linea(cfg["direccion"] + (f" - {cfg['ciudad']}" if cfg.get("ciudad") else ""))
    if cfg.get("telefono") or cfg.get("celular"):
        t.linea(f"Tel. {cfg.get('telefono') or cfg.get('celular')}")
    t.orden(IZQUIERDA).separador()

    if venta["estado"] == "anulada":
        t.orden(CENTRO, NEGRILLA).linea("*** ANULADA ***").orden(SIN_NEGRILLA, IZQUIERDA)

    # ---------- Datos de la venta ----------
    t.orden(NEGRILLA).dos_columnas("Venta", venta["consecutivo"]).orden(SIN_NEGRILLA)
    t.dos_columnas("Fecha", _fecha_hora(venta["fecha"]))
    t.dos_columnas("Atendió", venta["usuario_nombre"] or "")
    t.linea("Cliente: " + (venta["cliente_nombre"] or "")
            + (f" - {venta['cliente_documento']}" if venta["cliente_documento"] else ""))
    t.separador()

    # ---------- Productos: nombre en un renglón; cantidad x precio = total en otro ----------
    for l in lineas:
        nombre = l["producto_nombre"]
        if l["factor"] and l["factor"] != 1:
            nombre += f" - {l['presentacion']}"
        t.orden(NEGRILLA).linea(nombre).orden(SIN_NEGRILLA)
        t.dos_columnas(f"  {_cantidad(l['cantidad'])} x {pesos(l['precio_unitario'])}", pesos(l["total"]))
        if l["descuento_linea"]:
            t.linea(f"  desc. -{pesos(l['descuento_linea'])}")
    t.separador()

    # ---------- Totales ----------
    t.dos_columnas("Subtotal (sin IVA)", pesos(venta["subtotal"]))
    if venta["descuento"]:
        t.dos_columnas("Descuentos", "-" + pesos(venta["descuento"]))
    t.dos_columnas("IVA incluido", pesos(venta["iva"]))
    # TOTAL en letra alta y negrilla para que se vea de lejos
    t.orden(NEGRILLA, ALTA).dos_columnas("TOTAL", pesos(venta["total"])).orden(NORMAL, SIN_NEGRILLA)
    if venta["forma_pago"] != "credito":
        t.dos_columnas(f"Pago ({venta['forma_pago']})", pesos(venta["monto_recibido"] or venta["total"]))
        if venta["cambio"]:
            t.dos_columnas("Cambio", pesos(venta["cambio"]))

    # ---------- Crédito: queda debiendo y firma ----------
    if venta["forma_pago"] == "credito":
        t.linea().orden(CENTRO, NEGRILLA).linea("VENTA A CRÉDITO").orden(SIN_NEGRILLA, IZQUIERDA)
        if saldo_cliente is not None:
            t.dos_columnas("Saldo total del cliente", pesos(saldo_cliente))
        t.linea().linea().linea("_" * min(t.columnas, 32)).linea("Firma del cliente")

    if venta["observaciones"]:
        t.separador().linea(f"Nota: {venta['observaciones']}")

    # ---------- Pie ----------
    t.separador().orden(CENTRO, NEGRILLA).linea("¡Gracias por su compra!").orden(SIN_NEGRILLA)
    if cfg.get("pie_pagina"):
        t.linea(cfg["pie_pagina"])
    t.linea("Documento interno - no es factura").orden(IZQUIERDA)
    return t.terminar()


def imprimir_venta(venta_id: int):
    """Imprime el comprobante de una venta en la impresora de tirillas del PC principal.

    Devuelve (True, '') o (False, 'qué pasó').
    """
    from . import cajon
    from .configuracion import obtener_config
    from .db import get_db

    db = get_db()
    venta = db.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
    if venta is None:
        return False, "La venta no existe."
    lineas = db.execute("SELECT * FROM venta_lineas WHERE venta_id = ? ORDER BY id", (venta_id,)).fetchall()
    saldo_cliente = None
    if venta["forma_pago"] == "credito" and venta["cliente_id"]:
        from . import cartera
        saldo_cliente = cartera.saldo(venta["cliente_id"])
    cfg = obtener_config()
    datos = armar_venta(venta, lineas, cfg, saldo_cliente)
    return cajon.enviar_crudo(cfg.get("impresora_tirillas"), datos, f"Venta {venta['consecutivo']}")
