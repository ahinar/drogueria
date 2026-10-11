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
