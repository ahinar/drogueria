"""
PRUEBAS DE LA VERSIÓN 1.1.12 (el proveedor más barato está en test_sugerido.py)
==============================================================================
  - TestEliminarFoto: el botón «Eliminar» de la foto en la ficha del producto.
  - TestAgotadosEntendido: «Entendido» en la alerta de agotados del Inicio.
  - TestEditarComoSeVende: la ventana "Editar producto" (POS y conteo) con la
    sección "Cómo se vende" (unidad, presentaciones, por defecto).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import FUTURO
from test_unidades import BaseUnidades


class TestEliminarFoto(BaseUnidades):
    def test_el_formulario_trae_el_campo_y_se_borra_al_guardar(self):
        con = self.db()
        con.execute("UPDATE productos SET imagen = 'uploads/productos/vieja.jpg' WHERE id = 1")
        con.commit()
        con.close()
        html = self.c.get("/productos/1/editar").get_data(as_text=True)
        self.assertIn('name="_imagen_accion"', html)        # antes faltaba: el botón no hacía nada
        self.assertIn('id="btn-eliminar-imagen"', html)
        self.ficha(_imagen_accion="eliminar")
        self.assertIsNone(self.uno("SELECT imagen FROM productos WHERE id = 1")["imagen"])


class TestAgotadosEntendido(BaseUnidades):
    def alerta_agotados(self):
        from app.alertas import calcular_alertas
        with self.app.test_request_context():
            from flask import g
            g.user = {"rol": "administrador", "id": 1, "nombre": "x"}
            a = [x for x in calcular_alertas("administrador") if x["clave"] == "agotados"]
        return [i["texto"] for i in a[0]["items"]] if a else []

    def test_entendido_lo_quita_hasta_que_vuelva_a_agotarse(self):
        con = self.db()
        con.execute("UPDATE productos SET stock_minimo = 5 WHERE id = 1")
        con.commit()
        con.close()
        self.assertEqual(len(self.alerta_agotados()), 1)
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn("Entendido", html)
        self.post(self.c, "/alertas/entendido", {"clave": "agotados", "producto_id": "1"})
        self.assertEqual(self.alerta_agotados(), [])                     # ya no sale en Inicio
        self.assertIn(1, [i["id"] for i in self.reporte_bajo_minimo()])   # el reporte sigue igual
        # Llega mercancía: la marca se borra sola...
        self.lote(1, "L1", FUTURO, 10)
        self.assertEqual(self.alerta_agotados(), [])                      # tiene stock: no está agotado
        # ...y si se vuelve a agotar, sale otra vez
        con = self.db()
        con.execute("UPDATE lotes SET cantidad_disponible = 0, estado = 'agotado'")
        con.commit()
        con.close()
        self.assertEqual(len(self.alerta_agotados()), 1)

    def reporte_bajo_minimo(self):
        from app import sugerido
        with self.app.test_request_context():
            return sugerido.calcular()["bajo_minimo"]


class TestEditarComoSeVende(BaseUnidades):
    def editar(self, **extra):
        datos = {"formato": "presentaciones", "nombre": "Acetaminofén 500 mg", "iva_tipo": "excluido",
                 "precio_unidad": "200", "vende_suelto": "1", "venta_defecto": str(self.u["Sobre x 10"]),
                 "pres_unidad_id": [str(self.u["Sobre x 10"]), str(self.u["Caja x 100"])],
                 "pres_factor": ["10", "100"], "pres_precio": ["1800", "15000"],
                 "pres_maximo": ["", ""], "pres_barras": ["", "7701234567890"]}
        datos.update(extra)
        return self.post(self.c, "/pos/api/producto/1/editar", datos).get_json()

    def test_la_info_trae_suelto_y_unidad(self):
        p = self.c.get("/pos/api/producto/1").get_json()["producto"]
        self.assertEqual((p["vende_suelto"], p["unidad_venta_id"]), (True, self.u["Tableta"]))

    def test_cambiar_precios_codigo_de_caja_y_por_defecto(self):
        j = self.editar(pres_precio=["1900", "16000"])
        self.assertTrue(j["ok"], j)
        filas = {f["factor"]: f for f in self.db().execute(
            "SELECT * FROM producto_presentaciones WHERE producto_id = 1").fetchall()}
        self.assertEqual((filas[10]["precio_venta"], filas[100]["precio_venta"]), (1900, 16000))
        self.assertEqual(filas[100]["codigo_barras"], "7701234567890")
        p = self.uno("SELECT precio_venta, vende_suelto, venta_defecto_unidad_id FROM productos WHERE id = 1")
        self.assertEqual((p["precio_venta"], p["vende_suelto"], p["venta_defecto_unidad_id"]),
                         (200, 1, self.u["Sobre x 10"]))

    def test_agregar_y_quitar_presentacion(self):
        # Se quita la caja y se queda solo el sobre
        j = self.editar(pres_unidad_id=[str(self.u["Sobre x 10"])], pres_factor=["10"],
                        pres_precio=["1800"], pres_maximo=[""], pres_barras=[""])
        self.assertTrue(j["ok"], j)
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM producto_presentaciones WHERE producto_id = 1")["n"], 1)

    def test_no_se_vende_suelta_precio_sale_del_sobre(self):
        j = self.editar(vende_suelto="", precio_unidad="")      # la casilla apagada no se envía
        self.assertTrue(j["ok"], j)
        p = self.uno("SELECT precio_venta, vende_suelto FROM productos WHERE id = 1")
        self.assertEqual((p["precio_venta"], p["vende_suelto"]), (180, 0))   # $1.800 ÷ 10

    def test_errores_de_presentacion(self):
        j = self.editar(pres_factor=["1", "100"])
        self.assertFalse(j["ok"])
        self.assertIn("mayor que 1", j["error"])
        j = self.editar(vende_suelto="", pres_unidad_id=[], pres_factor=[], pres_precio=[], pres_maximo=[],
                        pres_barras=[])
        self.assertIn("no se vende suelta", j["error"])

    def test_la_ventana_esta_en_el_pos_y_en_el_conteo(self):
        self.abrir_caja()
        pos = self.c.get("/pos/").get_data(as_text=True)
        self.assertIn('name="pres_unidad_id"', pos)
        # editar_producto.js tiene que cargar ANTES que pos_carrito.js (que lo usa)
        self.assertLess(pos.index("js/editar_producto.js"), pos.index("js/pos_carrito.js"))
        r = self.post(self.c, "/inventario/conteos/nuevo", {"alcance": "todo"}, follow_redirects=True)
        conteo = r.get_data(as_text=True)
        self.assertIn('id="modal-editar-producto"', conteo)
        self.assertIn("editar_producto.js", conteo)
