"""
PRUEBAS DE LA VERSIÓN 1.1.11 (además del costo estimado, que está en test_conteos.py)
=====================================================================================
Pasó en el mostrador: al cobrar, el POS mostró "Unexpected token '<' ... is not valid JSON".
El programa había contestado una PÁGINA WEB (la de Ingresar o la de error) en vez de datos.
Ahora las direcciones /api/ contestan SIEMPRE en JSON, con un mensaje claro, y si la
clave de seguridad de la página quedó vieja, se manda la nueva para reintentar.
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import FUTURO, BaseVentas


class TestErroresEnJSON(BaseVentas):
    def carrito(self):
        return {"carrito": '[{"producto_id": 1, "cantidad": 1}]', "forma_pago": "efectivo"}

    def test_sesion_cerrada_contesta_json(self):
        with self.c.session_transaction() as s:
            s.pop("user_id", None)                        # como si se hubiera vencido la sesión
        r = self.post(self.c, "/pos/api/cobrar", self.carrito())
        self.assertEqual(r.status_code, 401)
        j = r.get_json()
        self.assertEqual((j["ok"], j["sesion"]), (False, True))
        self.assertIn("F5", j["error"])

    def test_clave_vieja_manda_la_nueva_y_no_cobra(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        r = self.c.post("/pos/api/cobrar", data=dict(self.carrito(), _csrf="clave-vieja"))
        self.assertEqual(r.status_code, 400)
        j = r.get_json()
        with self.c.session_transaction() as s:
            self.assertEqual(j["csrf_nuevo"], s["_csrf"])   # la clave que sí vale
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM ventas")["n"], 0)   # no se cobró nada
        # Con la clave nueva (lo que hace la pantalla sola) ya cobra
        r2 = self.c.post("/pos/api/cobrar", data=dict(self.carrito(), _csrf=j["csrf_nuevo"]))
        self.assertTrue(r2.get_json()["ok"])

    def test_error_interno_contesta_json(self):
        self.app.config["PROPAGATE_EXCEPTIONS"] = False   # como en la droguería (no en modo pruebas)
        self.abrir_caja()
        # Versión 1.1.15: cobrar está en app/pos_ventas.py (el POS se partió en tres archivos)
        with mock.patch("app.pos_ventas._caja_abierta", side_effect=RuntimeError("falla de prueba")):
            r = self.post(self.c, "/pos/api/cobrar", self.carrito())
        self.assertEqual(r.status_code, 500)
        self.assertFalse(r.get_json()["ok"])
        self.assertIn("revisa si quedó", r.get_json()["error"])

    def test_paginas_normales_siguen_igual(self):
        r = self.c.post("/proveedores/nuevo", data={"_csrf": "mala"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("text/html", r.content_type)        # una página normal sigue mostrando la pantalla de error

    def test_la_pantalla_trae_el_reintento(self):
        self.abrir_caja()                                  # sin caja abierta, /pos/ lleva a «Abrir caja»
        html = self.pagina_con_js(self.c, "/pos/")
        self.assertIn("csrf_nuevo", html)
        # Versión 1.1.15: el reintento está en static/js/pagina_inicio.js, que carga en el <head>,
        # antes que los scripts del POS
        self.assertLess(html.index("js/pagina_inicio.js"), html.index("js/pos_carrito.js"))


class TestBuscarLoMasParecidoPrimero(BaseVentas):
    """Al escribir "TAM", TAMPONES va antes que aceTAMinofen (pedido de Fernando)."""

    def setUp(self):
        super().setUp()
        con = self.db()
        # 45 acetaminofenes (más que los 40 que muestra el POS) y los tampones
        for i in range(45):
            con.execute("INSERT INTO productos (codigo, nombre, precio_venta, creado_en) VALUES (?,?,1000,?)",
                        (f"A{i:03d}", f"ACETAMINOFEN {i} MG", "2026-10-24"))
        con.execute("INSERT INTO productos (codigo, nombre, precio_venta, creado_en) "
                    "VALUES ('T1', 'TOALLAS TAMAÑO GRANDE', 5000, '2026-10-24')")
        con.execute("INSERT INTO productos (codigo, nombre, precio_venta, creado_en) "
                    "VALUES ('T2', 'TAMPONES OB X 10', 9000, '2026-10-24')")
        con.commit()
        con.close()

    def nombres_pos(self, q):
        return [p["nombre"] for p in self.c.get(f"/pos/api/productos?q={q}").get_json()["productos"]]

    def test_pos_tampones_de_primero(self):
        nombres = self.nombres_pos("tam")
        self.assertEqual(nombres[:2], ["TAMPONES OB X 10", "TOALLAS TAMAÑO GRANDE"])
        self.assertTrue(nombres[2].startswith("ACETAMINOFEN"))

    def test_pos_codigo_exacto_gana(self):
        self.assertEqual(self.nombres_pos("T1")[0], "TOALLAS TAMAÑO GRANDE")

    def test_recepcion_tambien(self):
        r = self.c.get("/recepciones/api/buscar-productos?q=tam").get_json()
        self.assertEqual(r["resultados"][0]["nombre"], "TAMPONES OB X 10")

    def test_lista_de_productos_tambien(self):
        html = self.c.get("/productos/?q=tam").get_data(as_text=True)
        self.assertLess(html.index("TAMPONES OB X 10"), html.index("ACETAMINOFEN 0 MG"))
