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

CORRECCIÓN 1.1.2 (por qué el cajón no abría):
    Antes se escribía  ctypes.windll.winspool  y Windows buscaba un archivo
    "winspool.dll"... que NO existe: el archivo de verdad se llama
    "winspool.drv" (.drv = "driver"). Como no lo encontraba, Python fallaba
    antes de hablarle a la impresora y el POS solo mostraba
    "Cajón: error de conexión". Ahora se carga por su nombre completo
    (ver _winspool() más abajo) y, si algo falla, se explica qué pasó.

DÓNDE SE CONFIGURA: Administración → Configuración → Impresora de tirillas:
    - nombre de la impresora (vacío = la impresora predeterminada de Windows)
    - cuándo abrir el cajón al cobrar: nunca, solo en efectivo, o siempre
"""
import sys

# ESC p 0 25 250 (pin 2) y ESC p 1 25 250 (pin 5): se mandan los dos para
# que funcione con cualquier cajón (el que no esté conectado no hace nada).
ORDEN_ABRIR = bytes([27, 112, 0, 25, 250]) + bytes([27, 112, 1, 25, 250])

# VERSIÓN 1.1.3: no todas las impresoras entienden la orden igual.
# Se puede escoger en Configuración cuál mandar y probarlas una por una:
#   - estandar:    la de arriba (impresoras Epson y la mayoría).
#   - largo:       la misma, pero dándole corriente más tiempo (200 ms en vez
#                  de 50 ms): para cajones con el seguro duro o de 24 V.
#   - tiempo_real: otra orden, DLE DC4 (bytes 16 20 1 m t), que muchas
#                  impresoras chinas (SAT, Xprinter, 3nStar…) obedecen al
#                  instante aunque estén ocupadas. t = 5 → 500 ms.
# Todas empiezan con ESC @ (27 64) = "reiniciar la impresora", por si tenía
# algo a medias en su memoria que le impidiera entender la orden.
REINICIAR = bytes([27, 64])
ORDENES = {
    "estandar": ("Estándar (la mayoría de impresoras)",
                 REINICIAR + ORDEN_ABRIR),
    "largo": ("Pulso largo (cajón duro de abrir)",
              REINICIAR + bytes([27, 112, 0, 100, 250]) + bytes([27, 112, 1, 100, 250])),
    "tiempo_real": ("Tiempo real · DLE DC4 (impresoras SAT, Xprinter y similares)",
                    REINICIAR + bytes([16, 20, 1, 0, 5]) + bytes([16, 20, 1, 1, 5])),
}

MODOS = {
    "no": "Nunca (lo abro con el botón)",
    "efectivo": "Al cobrar en efectivo",
    "siempre": "En todos los cobros",
}


def disponible():
    """El cajón solo se puede abrir desde Windows (ahí está la impresora)."""
    return sys.platform == "win32"


_WINSPOOL = None   # aquí se guarda la librería ya cargada (se carga una sola vez)


def _winspool():
    """Carga la librería de impresoras de Windows: winspool.DRV (no .dll).

    Además se le dice a Python qué recibe y qué devuelve cada función
    (argtypes / restype). Sin eso, en Windows de 64 bits Python puede
    "recortar" la manija (handle) de la impresora y la orden se pierde.
    """
    global _WINSPOOL
    if _WINSPOOL is None:
        import ctypes
        from ctypes import wintypes
        w = ctypes.WinDLL("winspool.drv")          # <-- el nombre completo, con .drv
        P = ctypes.c_void_p                        # "puntero a algo" (direcciones de memoria)
        w.GetDefaultPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        w.GetDefaultPrinterW.restype = wintypes.BOOL
        w.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), P]
        w.OpenPrinterW.restype = wintypes.BOOL
        w.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, P]
        w.StartDocPrinterW.restype = wintypes.DWORD      # número del trabajo (0 = falló)
        w.StartPagePrinter.argtypes = [wintypes.HANDLE]
        w.StartPagePrinter.restype = wintypes.BOOL
        w.WritePrinter.argtypes = [wintypes.HANDLE, P, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        w.WritePrinter.restype = wintypes.BOOL
        w.EndPagePrinter.argtypes = [wintypes.HANDLE]
        w.EndPagePrinter.restype = wintypes.BOOL
        w.EndDocPrinter.argtypes = [wintypes.HANDLE]
        w.EndDocPrinter.restype = wintypes.BOOL
        w.ClosePrinter.argtypes = [wintypes.HANDLE]
        w.ClosePrinter.restype = wintypes.BOOL
        _WINSPOOL = w
    return _WINSPOOL


def _impresora_predeterminada():
    """Nombre de la impresora predeterminada de Windows (o '' si no hay)."""
    import ctypes
    from ctypes import wintypes
    tam = wintypes.DWORD(0)
    _winspool().GetDefaultPrinterW(None, ctypes.byref(tam))      # primero pregunta el tamaño
    if not tam.value:
        return ""
    nombre = ctypes.create_unicode_buffer(tam.value)
    if _winspool().GetDefaultPrinterW(nombre, ctypes.byref(tam)):
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


def abrir(nombre_impresora="", orden="estandar"):
    """Manda la orden de abrir el cajón. Devuelve (True, '') o (False, 'qué pasó').

    orden = cuál de las ORDENES mandar (se escoge en Configuración).
    """
    if not disponible():
        return False, "El cajón solo se puede abrir desde el computador del local (Windows) con la impresora conectada."
    datos = ORDENES.get(orden, ORDENES["estandar"])[1]
    return enviar_crudo(nombre_impresora, datos, "Abrir cajón")


def impresora_usada(nombre_impresora=""):
    """A qué impresora le llega la orden de verdad: la escrita en Configuración
    o, si está vacía, la predeterminada de Windows.

    Sirve para que el mensaje diga "Orden enviada a «SAT Q150»": si sale el
    nombre de OTRA impresora (por ejemplo "Microsoft Print to PDF"), ahí está
    el problema: hay que escribir el nombre correcto en Configuración.
    """
    nombre = (nombre_impresora or "").strip()
    if nombre or not disponible():
        return nombre
    try:
        return _impresora_predeterminada()
    except Exception:                              # noqa: BLE001
        return ""


def enviar_crudo(nombre_impresora, datos: bytes, titulo="Fervifarma"):
    """Manda bytes "tal cual" (RAW) a una impresora de Windows.

    La usan el cajón (solo la orden de abrir) y la tirilla directa
    (app/tirilla_directa.py: el texto de la venta en el idioma ESC/POS).
    Devuelve (True, '') o (False, 'qué pasó').
    """
    if not disponible():
        return False, "Solo se puede imprimir directo desde el computador del local (Windows)."
    # Si algo inesperado falla al hablar con Windows, se devuelve un mensaje
    # claro (y queda anotado en el registro) en vez de un "error 500".
    try:
        return _enviar_crudo_windows(nombre_impresora, datos, titulo)
    except Exception as error:                     # noqa: BLE001 (queremos atrapar cualquier cosa)
        import logging
        logging.exception("No se pudo mandar la orden a la impresora")
        return False, f"Windows no dejó hablar con la impresora ({error})."


def _enviar_crudo_windows(nombre_impresora, datos: bytes, titulo):
    """La parte que de verdad le habla a Windows (la llama enviar_crudo)."""
    import ctypes
    from ctypes import wintypes

    nombre = (nombre_impresora or "").strip() or _impresora_predeterminada()
    if not nombre:
        return False, "No hay impresora predeterminada. Escribe el nombre de la impresora de tirillas en Configuración."

    # Estructura que pide Windows para empezar un "documento" (DOC_INFO_1)
    class DOC_INFO_1(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR), ("pDatatype", wintypes.LPWSTR)]

    winspool = _winspool()
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
