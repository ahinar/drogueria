"""
PRUEBAS DE LA VERSIÓN 1.1.18
============================
Lo que encontró Fernando con POND REJUVENESS: el producto traía una presentación
«SELLO X 10» con precio $0 (venía del programa anterior). Al guardar en la ventana
«Editar producto» se guardaban los datos técnicos pero NO los precios, y la línea
de la recepción seguía diciendo «SIN registro INVIMA».
  - La ventana primero REVISA la parte de venta (_solo_revisar=1) sin guardar nada.
  - El error dice CUÁL presentación no tiene precio.
  - Aviso en Inicio: «Presentaciones sin precio».
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_reportes import BaseReportes


class TestPresentacionSinPrecio(BaseReportes):
    def setUp(self):
        super().setUp()
        con = self.db()
        self.nombre_sello = "SELLO X 10"
        self.sello = con.execute("INSERT INTO unidades_medida (nombre, cantidad, activo, creado_en) "
                                 "VALUES ('SELLO X 10', 10, 1, '2026-01-01')").lastrowid
        con.execute("INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, creado_en) "
                    "VALUES (1, ?, 10, 0, '2026-01-01')", (self.sello,))
        con.commit()
        con.close()

    def datos_venta(self, **extra):
        """Lo que manda la pestaña «Venta» con la presentación tal como está (precio 0)."""
        p = self.uno("SELECT * FROM productos WHERE id = 1")
        datos = {"nombre": p["nombre"], "codigo_barras": "", "precio_unidad": "1000", "vende_suelto": "1",
                 "venta_defecto": "", "iva_tipo": "excluido", "maneja_vencimiento": "1",
                 "pres_unidad_id": str(self.sello), "pres_factor": "10", "pres_precio": "0",
                 "pres_maximo": "", "pres_barras": "", "formato": "presentaciones"}
        datos.update(extra)
        return datos

    def test_error_dice_cual_presentacion(self):
        j = self.post(self.c, "/pos/api/producto/1/editar", self.datos_venta()).get_json()
        self.assertFalse(j["ok"])
        self.assertIn(self.nombre_sello, j["error"])
        self.assertIn("no tiene precio", j["error"])

    def test_solo_revisar_no_guarda(self):
        j = self.post(self.c, "/pos/api/producto/1/editar",
                      self.datos_venta(pres_precio="9000", nombre="NOMBRE NUEVO", _solo_revisar="1")).get_json()
        self.assertTrue(j["ok"], j)
        self.assertTrue(j.get("revisado"))
        self.assertNotEqual(self.uno("SELECT nombre FROM productos WHERE id = 1")["nombre"], "NOMBRE NUEVO")

    def test_control_especial_con_registro_que_se_esta_escribiendo(self):
        datos = self.datos_venta(pres_precio="9000", control_especial="1", _solo_revisar="1")
        self.assertFalse(self.post(self.c, "/pos/api/producto/1/editar", datos).get_json()["ok"])
        datos["_registro_nuevo"] = "INVIMA 2020M-1"
        self.assertTrue(self.post(self.c, "/pos/api/producto/1/editar", datos).get_json()["ok"])

    def test_aviso_en_inicio(self):
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn("Presentaciones sin precio", html)
        self.assertIn(self.nombre_sello, html)

    def test_la_ventana_revisa_antes_de_guardar(self):
        html = self.pagina_con_js(self.c, "/recepciones/nueva")
        self.assertIn("_solo_revisar", html)
        self.assertIn("marcarFilasSinPrecio", html)
