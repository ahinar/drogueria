"""
PRUEBAS DEL CAJÓN MONEDERO (app/cajon.py) Y DE LA TIRILLA.

Aquí no hay impresora ni Windows, así que se prueba:
  - que la orden ESC/POS sea la correcta
  - que en un computador sin Windows avise (sin romper nada)
  - que, si "abrir" funciona (simulado), el POS lo registre en la bitácora
  - la configuración (cuándo abrirlo) y que el POS la reciba
  - que el enlace "Ver comprobante" deje a la tirilla cerrarse al volver
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas


class TestCajon(BaseVentas):
    def test_orden_escpos(self):
        from app.cajon import ORDEN_ABRIR
        # ESC p 0 25 250 (pin 2) + ESC p 1 25 250 (pin 5)
        self.assertEqual(ORDEN_ABRIR, b"\x1bp\x00\x19\xfa\x1bp\x01\x19\xfa")

    def test_sin_windows_avisa(self):
        from app import cajon
        with mock.patch.object(cajon, "disponible", return_value=False):
            ok, error = cajon.abrir("POS-58")
        self.assertFalse(ok)
        self.assertIn("Windows", error)

    def test_api_necesita_caja_abierta_y_queda_en_bitacora(self):
        r = self.post(self.c, "/pos/api/abrir-cajon", {"motivo": "manual"})
        self.assertFalse(r.get_json()["ok"])                    # sin caja abierta
        self.abrir_caja()
        with mock.patch("app.cajon.abrir", return_value=(True, "")) as abrir:
            r = self.post(self.c, "/pos/api/abrir-cajon", {"motivo": "cobro"})
        self.assertTrue(r.get_json()["ok"])
        abrir.assert_called_once()
        bit = self.uno("SELECT detalle FROM bitacora WHERE accion = 'cajon_abierto'")
        self.assertEqual(bit["detalle"], "motivo=cobro")

    def test_configuracion_y_pos(self):
        self.post(self.c, "/configuracion/", {"razon_social": "Fervifarma", "nit": "1", "ancho_tirilla": "58",
                                              "cajon_modo": "efectivo", "impresora_tirillas": "POS-58"})
        from app.configuracion import obtener_config
        with self.app.app_context():
            cfg = obtener_config()
        self.assertEqual((cfg["cajon_modo"], cfg["impresora_tirillas"]), ("efectivo", "POS-58"))
        self.post(self.c, "/configuracion/", {"razon_social": "Fervifarma", "nit": "1", "cajon_modo": "cohete"})
        with self.app.app_context():
            self.assertEqual(obtener_config()["cajon_modo"], "no")          # valor raro -> "no"
        self.abrir_caja()
        html = self.c.get("/pos/").get_data(as_text=True)
        self.assertIn('id="cfg-cajon" value="no"', html)
        self.assertIn('data-accion="abrir-cajon"', html)
        # "Ver comprobante" abre la tirilla CON acceso a la ventana del POS (rel="opener"),
        # así "Volver al POS" la cierra en vez de abrir otro POS
        self.assertIn('id="exito-comprobante" href="#" target="_blank" rel="opener"', html)


class TestCorreccion112(BaseVentas):
    """Versión 1.1.2: el cajón no abría porque se cargaba "winspool" (.dll) en vez de winspool.drv."""

    def test_carga_winspool_drv(self):
        # Se revisa el código: en ningún lado debe quedar la forma vieja ctypes.windll.winspool.X
        from app import cajon
        codigo = Path(cajon.__file__).read_text(encoding="utf-8")
        self.assertIn('WinDLL("winspool.drv")', codigo)
        self.assertNotIn("windll.winspool.", codigo)

    def test_si_windows_falla_avisa_sin_romper(self):
        # Si Windows lanza un error raro, se devuelve un mensaje (no un "error 500")
        from app import cajon
        with mock.patch.object(cajon, "disponible", return_value=True), \
             mock.patch.object(cajon, "_enviar_crudo_windows", side_effect=OSError("prueba")):
            ok, error = cajon.abrir("POS-58")
        self.assertFalse(ok)
        self.assertIn("prueba", error)


class TestInstalable(BaseVentas):
    """Versión 1.1.2: el programa se puede instalar como aplicación desde Chrome."""

    def test_manifiesto_y_service_worker_sin_contraseña(self):
        anonimo = self.app.test_client()                     # sin iniciar sesión
        r = anonimo.get("/manifest.webmanifest")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/manifest+json")
        datos = r.get_json(force=True)
        self.assertEqual(datos["display"], "standalone")
        tamaños = {i["sizes"] for i in datos["icons"]}
        self.assertTrue({"192x192", "512x512"} <= tamaños)    # Chrome exige estos dos
        for icono in datos["icons"]:
            self.assertEqual(anonimo.get(icono["src"]).status_code, 200)
        r = anonimo.get("/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/javascript")

    def test_paginas_anuncian_el_manifiesto(self):
        anonimo = self.app.test_client()
        self.assertIn('rel="manifest"', anonimo.get("/login").get_data(as_text=True))
        self.assertIn('rel="manifest"', self.c.get("/").get_data(as_text=True))


class TestOrdenesCajon113(BaseVentas):
    """Versión 1.1.3: se puede escoger qué orden mandar para abrir el cajón."""

    def test_ordenes(self):
        from app import cajon
        self.assertEqual(set(cajon.ORDENES), {"estandar", "largo", "tiempo_real"})
        for _nombre, datos in cajon.ORDENES.values():
            self.assertTrue(datos.startswith(b"\x1b@"))           # todas reinician primero
        self.assertIn(b"\x10\x14\x01\x00\x05", cajon.ORDENES["tiempo_real"][1])   # DLE DC4

    def test_se_guarda_y_el_pos_la_usa(self):
        self.post(self.c, "/configuracion/", {"razon_social": "Fervifarma", "nit": "1",
                                              "cajon_orden": "tiempo_real", "impresora_tirillas": "SAT Q150"})
        from app.configuracion import obtener_config
        with self.app.app_context():
            self.assertEqual(obtener_config()["cajon_orden"], "tiempo_real")
        self.abrir_caja()
        with mock.patch("app.cajon.abrir", return_value=(True, "")) as abrir:
            j = self.post(self.c, "/pos/api/abrir-cajon", {"motivo": "manual"}).get_json()
        abrir.assert_called_once_with("SAT Q150", "tiempo_real")
        self.assertEqual(j["impresora"], "SAT Q150")              # el POS dice a cuál impresora llegó

    def test_valor_raro_queda_estandar(self):
        self.post(self.c, "/configuracion/", {"razon_social": "Fervifarma", "nit": "1", "cajon_orden": "cohete"})
        from app.configuracion import obtener_config
        with self.app.app_context():
            self.assertEqual(obtener_config()["cajon_orden"], "estandar")


class TestRecepcionBarras113(BaseVentas):
    def test_modal_tiene_codigo_de_barras(self):
        html = self.c.get("/recepciones/nueva").get_data(as_text=True)
        self.assertIn('id="np-barras"', html)
        self.assertIn("codigo_barras", html)
        self.assertIn("beforeunload", html)                       # avisa antes de salir sin guardar
