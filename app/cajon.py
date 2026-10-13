"""
CAJÓN MONEDERO
==============

PARA QUÉ (para aprender):
    El cajón monedero casi siempre va CONECTADO A LA IMPRESORA de tirillas
    (con un cable tipo teléfono, RJ11). No tiene "driver" propio: se abre
    cuando la impresora recibe una orden especial. Esa orden es un comando
    ESC/POS (el "idioma" de las impresoras térmicas):

        ESC  p   m   t1  t2      ->  bytes 27 112 m t1 t2
        m  = qué pin del conector (0 = pin 2, 1 = pin 5; según el cajón)
        t1 = cuánto tiempo se le da corriente (×2 ms) para soltar el seguro
        t2 = cuánto tiempo se espera después (×2 ms)

    Esa orden NO imprime nada ni gasta papel: solo abre el cajón.

    ¿Por qué lo hace Python y no el navegador? El navegador no puede mandar
    bytes "crudos" a una impresora (solo imprime páginas). Pero el programa
    corre en el MISMO computador que la impresora, así que Python sí puede,
    usando las funciones de Windows para imprimir (winspool.drv) en modo
    "RAW" (crudo: los bytes van tal cual, sin convertirlos en página).

    Se usa ctypes (viene con Python) para llamar esas funciones de Windows;
    así no hay que instalar nada más.

DÓNDE SE CONFIGURA: Administración → Configuración → Impresora de tirillas:
    - nombre de la impresora (vacío = la impresora predeterminada de Windows)
    - cuándo abrir el cajón al cobrar: nunca, solo en efectivo, o siempre
"""
import sys

# ESC p 0 25 250 (pin 2) y ESC p 1 25 250 (pin 5): se mandan los dos para
# que funcione con cualquier cajón (el que no esté conectado no hace nada).
ORDEN_ABRIR = bytes([27, 112, 0, 25, 250]) + bytes([27, 112, 1, 25, 250])

MODOS = {
    "no": "Nunca (lo abro con el botón)",
    "efectivo": "Al cobrar en efectivo",
    "siempre": "En todos los cobros",
}


def disponible():
    """El cajón solo se puede abrir desde Windows (ahí está la impresora)."""
    return sys.platform == "win32"


def _impresora_predeterminada():
    """Nombre de la impresora predeterminada de Windows (o '' si no hay)."""
    import ctypes
    from ctypes import wintypes
    tam = wintypes.DWORD(0)
    ctypes.windll.winspool.GetDefaultPrinterW(None, ctypes.byref(tam))      # primero pregunta el tamaño
    if not tam.value:
        return ""
    nombre = ctypes.create_unicode_buffer(tam.value)
    if ctypes.windll.winspool.GetDefaultPrinterW(nombre, ctypes.byref(tam)):
        return nombre.value
    return ""


def impresoras():
    """Lista de impresoras instaladas en Windows (para escoger en Configuración)."""
    if not disponible():
        return []
    import subprocess
    try:
        salida = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Printer | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=10, creationflags=0x08000000)   # 0x08000000 = sin ventana negra
        return [linea.strip() for linea in salida.stdout.splitlines() if linea.strip()]
    except Exception:
        return []


def abrir(nombre_impresora=""):
    """Manda la orden de abrir el cajón. Devuelve (True, '') o (False, 'qué pasó')."""
    if not disponible():
        return False, "El cajón solo se puede abrir desde el computador del local (Windows) con la impresora conectada."
    return enviar_crudo(nombre_impresora, ORDEN_ABRIR, "Abrir cajón")


def enviar_crudo(nombre_impresora, datos: bytes, titulo="Fervifarma"):
    """Manda bytes "tal cual" (RAW) a una impresora de Windows.

    La usan el cajón (solo la orden de abrir) y la tirilla directa
    (app/tirilla_directa.py: el texto de la venta en el idioma ESC/POS).
    Devuelve (True, '') o (False, 'qué pasó').
    """
    if not disponible():
        return False, "Solo se puede imprimir directo desde el computador del local (Windows)."
    import ctypes
    from ctypes import wintypes

    nombre = (nombre_impresora or "").strip() or _impresora_predeterminada()
    if not nombre:
        return False, "No hay impresora predeterminada. Escribe el nombre de la impresora de tirillas en Configuración."

    # Estructura que pide Windows para empezar un "documento" (DOC_INFO_1)
    class DOC_INFO_1(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR), ("pDatatype", wintypes.LPWSTR)]

    winspool = ctypes.windll.winspool
    manija = wintypes.HANDLE()
    if not winspool.OpenPrinterW(nombre, ctypes.byref(manija), None):
        return False, f"No se encontró la impresora «{nombre}». Revisa el nombre en Configuración."
    ok, escritos = False, wintypes.DWORD(0)
    try:
        info = DOC_INFO_1(titulo, None, "RAW")                 # RAW = mandar los bytes tal cual
        if not winspool.StartDocPrinterW(manija, 1, ctypes.byref(info)):
            return False, "La impresora no aceptó la orden (¿está apagada o sin conexión?)."
        try:
            winspool.StartPagePrinter(manija)
            buffer = ctypes.create_string_buffer(datos, len(datos))
            ok = winspool.WritePrinter(manija, buffer, len(datos), ctypes.byref(escritos))
            winspool.EndPagePrinter(manija)
        finally:
            winspool.EndDocPrinter(manija)
    finally:
        winspool.ClosePrinter(manija)
    if not ok or escritos.value != len(datos):
        return False, "No se pudo mandar la orden a la impresora."
    return True, ""
