"""
PRUEBAS DEL ANCHO DE LA TIRILLA: 58 mm u 80 mm (Configuración), y los
botones 58 / 80 de cada tirilla para imprimir una vez en el otro ancho.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas, FUTURO


class TestAnchoTirilla(BaseVentas):
    def setUp(self):
        super().setUp()
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 1}])

    def configurar(self, ancho):
        self.post(self.c, "/configuracion/", {"_accion": "guardar", "ancho_tirilla": ancho,
                                              "nombre_comercial": "Fervifarma", "razon_social": "Fervifarma S.A.S.",
                                              "nit": "900.000.000-1"})

    def test_por_defecto_80(self):
        html = self.c.get("/pos/venta/1").get_data(as_text=True)
        self.assertIn('class="papel-80"', html)
        self.assertIn("js/tirilla.js", html)          # pone el tamaño exacto del papel

    def test_configurar_58(self):
        self.configurar("58")
        self.assertIn('class="papel-58"', self.c.get("/pos/venta/1").get_data(as_text=True))
        self.assertIn('value="58" selected', self.c.get("/configuracion/").get_data(as_text=True))

    def test_valor_raro_queda_en_80(self):
        self.configurar("100")
        self.assertIn('class="papel-80"', self.c.get("/pos/venta/1").get_data(as_text=True))

    def test_boton_para_imprimir_una_vez_en_el_otro_ancho(self):
        self.configurar("58")
        html = self.c.get("/pos/venta/1?papel=80").get_data(as_text=True)
        self.assertIn('class="papel-80"', html)
        self.assertIn('href="?papel=58"', html)
