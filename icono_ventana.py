"""
ÍCONO PROPIO EN LA BARRA DE TAREAS DE WINDOWS (versión 1.1.6)
============================================================

PARA QUÉ (para aprender):
    La ventana de Fervifarma es Google Chrome (o Edge) en "modo aplicación"
    (ver escritorio.py). Windows agrupa los botones de la barra de tareas por
    "identidad de programa" (se llama AppUserModelID). Como la ventana la abre
    Chrome, Windows creía que ERA Chrome y mostraba el ícono de Chrome.

    Aquí, apenas aparece la ventana, le decimos a Windows:
        - "esta ventana es Fervifarma"   → identidad propia ("Fervifarma.Programa")
        - "su ícono es la cruz verde"    → el mismo ícono del instalador
        - "si la anclan, se abre con Fervifarma.exe"
    El instalador le pone la MISMA identidad al acceso directo del escritorio
    (instalador/fervifarma.iss), así Windows junta la ventana con ese acceso
    directo y muestra el ícono de Fervifarma.

    No cambia nada de lo que pasa DENTRO de la ventana (imprimir, tirillas,
    cajón): solo cómo la dibuja Windows en la barra de tareas.

CÓMO RECONOCE LA VENTANA:
    Las ventanas de Chrome/Edge son de la clase "Chrome_WidgetWin_1". Las de
    Fervifarma tienen en el título "· Fervifarma" (ver <title> en base.html), o
    son las tirillas que se abren aparte ("Comprobante V-0001", "Recibo ...").
    Las del Chrome de uso diario terminan en "- Google Chrome" o "- Microsoft Edge"
    y esas NO se tocan.

    Todo va dentro de try/except: si algo falla, el programa sigue igual que
    antes (solo se anota en el archivo de errores).
"""
import logging
import sys
import threading
import time
from pathlib import Path

ID_APP = "Fervifarma.Programa"     # la misma identidad que pone el instalador (AppUserModelID)
NOMBRE = "Fervifarma"

# Títulos de las ventanitas que se abren aparte para imprimir (no llevan "· Fervifarma")
_TITULOS_IMPRESION = ("Comprobante ", "Recibo ", "Cotización ")


def es_ventana_del_programa(clase, titulo):
    """True si una ventana de Windows es una ventana de Fervifarma (y no del Chrome de uso diario)."""
    if clase != "Chrome_WidgetWin_1" or not titulo:
        return False
    if "Google Chrome" in titulo or "Microsoft" in titulo or titulo.endswith("Edge"):
        return False                                   # pestaña del navegador normal: no se toca
    return "· Fervifarma" in titulo or titulo.startswith(_TITULOS_IMPRESION)


def ruta_del_icono():
    """De dónde sacar el ícono: el propio Fervifarma.exe (instalado) o el .ico (programando)."""
    if getattr(sys, "frozen", False):                   # instalado con PyInstaller
        return sys.executable
    return str(Path(__file__).resolve().parent / "instalador" / "fervifarma.ico")


def orden_para_reabrir():
    """Lo que Windows corre si anclan el botón y le dan clic: abrir Fervifarma."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{Path(__file__).resolve().parent / "escritorio.py"}"'


def identidad_del_proceso():
    """Le pone la identidad Fervifarma a ESTE proceso (sus mensajes de error, por ejemplo)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ID_APP)
    except Exception:                                   # nunca debe impedir que abra el programa
        logging.exception("No se pudo poner la identidad de Fervifarma al proceso")


def vigilar(segundos=None):
    """Arranca un "vigilante" (hilo por detrás) que le pone el ícono a cada ventana de Fervifarma.

    segundos=None: vigila mientras el programa esté abierto (ventana principal).
    segundos=20:   vigila solo 20 segundos (cuando se abre una ventana más y el lanzador termina).
    Devuelve el hilo (o None fuera de Windows).
    """
    if sys.platform != "win32":
        return None
    hilo = threading.Thread(target=_vigilar, args=(segundos,), name="icono-ventana", daemon=True)
    hilo.start()
    return hilo


# ---------------------------------------------------------------------------
# De aquí para abajo: hablar con Windows (solo funciona en Windows).
# ctypes es la forma de Python de llamar funciones de Windows directamente.
# ---------------------------------------------------------------------------
def _vigilar(segundos):
    try:
        windows = _Windows()
    except Exception:
        logging.exception("No se pudo preparar el ícono de la barra de tareas")
        return
    fin = None if segundos is None else time.monotonic() + segundos
    while fin is None or time.monotonic() < fin:
        try:
            windows.revisar_ventanas()
        except Exception:
            logging.exception("Error poniendo el ícono de la barra de tareas")
            return
        time.sleep(1.5)                                 # revisar cada segundo y medio es suficiente


class _Windows:
    """Las llamadas a Windows que se necesitan, preparadas una sola vez."""

    WM_GETICON, WM_SETICON = 0x007F, 0x0080
    ICON_SMALL, ICON_BIG = 0, 1

    def __init__(self):
        import ctypes
        import uuid
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        # Copias PROPIAS de las librerías de Windows (WinDLL): los tipos que se declaran abajo
        # no afectan a otras partes del programa (el cajón, los mensajes de error...)
        self.user32, self.shell32 = ctypes.WinDLL("user32"), ctypes.WinDLL("shell32")
        ctypes.WinDLL("ole32").CoInitialize(None)          # Windows pide esto antes de usar el "property store"

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        class PROPERTYKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

        class PROPVARIANT(ctypes.Structure):           # solo el caso "texto" (VT_LPWSTR = 31)
            _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.WORD), ("r2", wintypes.WORD),
                        ("r3", wintypes.WORD), ("texto", ctypes.c_wchar_p), ("relleno", ctypes.c_void_p)]

        def guid(texto):
            u = uuid.UUID(texto)
            g = GUID(u.fields[0], u.fields[1], u.fields[2])
            for i, b in enumerate(u.bytes[8:]):
                g.Data4[i] = b
            return g

        self.PROPERTYKEY, self.PROPVARIANT = PROPERTYKEY, PROPVARIANT

        # Le decimos a Python qué tipo de dato recibe cada función de Windows. Sin esto,
        # en Windows de 64 bits los "handles" (números de ventana o de ícono) se podrían cortar.
        W, u, s = wintypes, self.user32, self.shell32
        self.ENUMERAR = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        u.EnumWindows.argtypes = [self.ENUMERAR, W.LPARAM]
        u.IsWindowVisible.argtypes = [W.HWND]
        u.GetWindow.argtypes, u.GetWindow.restype = [W.HWND, W.UINT], W.HWND
        u.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
        u.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        u.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT,
                                          ctypes.POINTER(ctypes.c_size_t)]
        u.PrivateExtractIconsW.argtypes = [W.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           ctypes.POINTER(W.HICON), ctypes.POINTER(W.UINT), W.UINT, W.UINT]
        s.SHGetPropertyStoreForWindow.argtypes = [W.HWND, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        s.SHGetPropertyStoreForWindow.restype = ctypes.c_long
        self.iid_store = guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")       # IPropertyStore
        grupo = guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3")               # propiedades "AppUserModel"
        # Orden: primero cómo reabrir, ícono y nombre; la identidad (ID) de última, como pide Windows
        self.propiedades = [
            (PROPERTYKEY(grupo, 2), orden_para_reabrir()),              # RelaunchCommand
            (PROPERTYKEY(grupo, 3), ruta_del_icono() + ",0"),           # RelaunchIconResource
            (PROPERTYKEY(grupo, 4), NOMBRE),                            # RelaunchDisplayNameResource
            (PROPERTYKEY(grupo, 5), ID_APP),                            # ID
        ]
        # Los dos tamaños del ícono (grande para la barra de tareas, pequeño para el título)
        self.icono_grande = self._cargar_icono(self.user32.GetSystemMetrics(11) * 2)   # SM_CXICON
        self.icono_chico = self._cargar_icono(self.user32.GetSystemMetrics(49))        # SM_CXSMICON
        self.listas = set()                              # ventanas a las que ya se les puso la identidad

    def _cargar_icono(self, lado):
        icono = self.wintypes.HICON()
        self.user32.PrivateExtractIconsW(ruta_del_icono(), 0, lado, lado, self.ctypes.byref(icono), None, 1, 0)
        return icono.value

    def revisar_ventanas(self):
        """Busca las ventanas de Fervifarma y les pone identidad e ícono."""
        ctypes = self.ctypes
        encontradas = []

        def cada_ventana(hwnd, _):
            if self.user32.IsWindowVisible(hwnd) and not self.user32.GetWindow(hwnd, 4):   # 4 = GW_OWNER
                clase = ctypes.create_unicode_buffer(64)
                titulo = ctypes.create_unicode_buffer(256)
                self.user32.GetClassNameW(hwnd, clase, 64)
                self.user32.GetWindowTextW(hwnd, titulo, 256)
                if es_ventana_del_programa(clase.value, titulo.value):
                    encontradas.append(hwnd)
            return True

        self.user32.EnumWindows(self.ENUMERAR(cada_ventana), 0)
        self.listas &= set(encontradas)                 # olvidar las ventanas que ya se cerraron
        for hwnd in encontradas:
            if hwnd not in self.listas:
                self._poner_identidad(hwnd)
                self.listas.add(hwnd)
            self._poner_icono(hwnd)

    def _poner_identidad(self, hwnd):
        ctypes = self.ctypes
        tienda = ctypes.c_void_p()
        self.shell32.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(self.iid_store), ctypes.byref(tienda))
        if not tienda.value:
            return
        # Las funciones del "property store" se llaman por su posición en la tabla del objeto (COM):
        # 2 = Release, 6 = SetValue, 7 = Commit
        tabla = ctypes.cast(tienda, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        HRESULT = ctypes.c_long
        set_value = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(self.PROPERTYKEY),
                                       ctypes.POINTER(self.PROPVARIANT))(tabla[6])
        commit = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p)(tabla[7])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(tabla[2])
        try:
            for llave, texto in self.propiedades:
                valor = self.PROPVARIANT(31, 0, 0, 0, texto, None)   # 31 = VT_LPWSTR (texto)
                set_value(tienda, ctypes.byref(llave), ctypes.byref(valor))
            commit(tienda)
        finally:
            release(tienda)

    def _poner_icono(self, hwnd):
        """Pone el ícono. Si Chrome lo cambió (al navegar pone el de la página), lo vuelve a poner."""
        actual = self.ctypes.c_size_t()
        self.user32.SendMessageTimeoutW(hwnd, self.WM_GETICON, self.ICON_BIG, 0, 0x2, 300,
                                        self.ctypes.byref(actual))                   # 0x2 = no esperar si está colgada
        if self.icono_grande and actual.value != self.icono_grande:
            self.user32.PostMessageW(hwnd, self.WM_SETICON, self.ICON_BIG, self.icono_grande)
            if self.icono_chico:
                self.user32.PostMessageW(hwnd, self.WM_SETICON, self.ICON_SMALL, self.icono_chico)
