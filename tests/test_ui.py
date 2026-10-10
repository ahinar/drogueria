"""
PRUEBAS DE LA PARTE VISUAL COMÚN (rediseño parte 4):
mensajes tipo toast, fechas dd/mm/aaaa, ventanas propias en vez de
prompt() y comprobante en tirilla de 80 mm.

Lo que pasa DENTRO del navegador (el calendario, la ventana que pide el
cliente) lo hace JavaScript y se probó a mano con un navegador real.
Aquí revisamos lo que manda el servidor.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas, FUTURO

RAIZ = Path(__file__).resolve().parent.parent


class TestToastsYFechas(BaseVentas):
    def test_base_carga_ui_js(self):
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn("js/ui.js", html)
        self.assertIn('id="toasts"', html)

    def test_mensaje_del_servidor_sale_como_toast_con_x(self):
        self.abrir_caja()     # deja un mensaje "Caja ... abierta"
        html = self.c.get("/pos/").get_data(as_text=True)
        self.assertIn('class="aviso toast ok"', html)
        self.assertIn('class="toast-cerrar"', html)

    def test_el_servidor_sigue_recibiendo_aaaa_mm_dd(self):
        # El campo de fecha original se queda en la página (ui.js lo
        # esconde y pone el visible dd/mm/aaaa al lado).
        html = self.c.get("/contabilidad/gastos/nuevo").get_data(as_text=True)
        self.assertIn('type="date" name="fecha"', html)

    def test_ya_no_hay_prompt_ni_alert_del_navegador(self):
        for archivo in list((RAIZ / "static/js").glob("*.js")) + list((RAIZ / "app/templates").rglob("*.html")):
            texto = archivo.read_text(encoding="utf-8")
            for feo in ("prompt(", " alert("):
                lineas = [l for l in texto.splitlines() if feo in l and not l.strip().startswith("//")]
                self.assertEqual(lineas, [], f"{archivo.name} todavía usa {feo}")


class TestTirilla80mm(BaseVentas):
    def test_comprobante_80mm_con_formato_colombiano(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 2}], recibido="5000")
        html = self.c.get("/pos/venta/1").get_data(as_text=True)
        self.assertIn("css/tirilla.css", html)       # estilo de tirilla compartido
        css = (RAIZ / "static/css/tirilla.css").read_text(encoding="utf-8")
        self.assertIn("size: 80mm auto", css)        # papel de 80 mm
        self.assertIn("$2.000", html)                # punto de miles, como en Colombia
        self.assertIn("$3.000", html)                # el cambio
        self.assertIn("no es factura", html)

    def test_filtro_fecha_hora(self):
        f = self.app.jinja_env.filters["fecha_hora"]
        self.assertEqual(f("2026-10-10 07:15:33"), "10/10/2026 07:15")
        self.assertEqual(f("2026-10-10"), "10/10/2026")
        self.assertEqual(f(None), "")
