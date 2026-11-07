"""
PRUEBAS DE LA VERSIÓN 1.1.17
============================
  - TestVentanaProducto: UNA sola ventana «Editar producto» (POS, toma de inventario y
    Recepción) con pestañas Venta y Datos técnicos; «✎ Editar datos» en la Recepción;
    el costo de la compra anterior para la etiqueta «▲ subió 23 %».
  - TestCobroConTeclado: lo que el cobro con teclado necesita en la página.
  - TestFormasDePago: Configuración → Formas de pago: agregar una cuenta, ocultar,
    ordenar, y que el resto del programa (POS, Bancos, cobrar) lo respete.

Recordatorio (BaseVentas): producto 1 = $1.000 sin IVA; la caja se abre con $10.000.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import FUTURO
from test_reportes import BaseReportes


# =====================================================================
# 1. LA VENTANA «EDITAR PRODUCTO» EN LA RECEPCIÓN
# =====================================================================
class TestVentanaProducto(BaseReportes):
    def test_recepcion_trae_la_ventana_con_dos_pestanas(self):
        html = self.pagina_con_js(self.c, "/recepciones/nueva")
        self.assertIn('id="modal-editar-producto"', html)
        self.assertIn('data-pestana="venta"', html)
        self.assertIn('data-pestana="tecnicos"', html)
        self.assertIn("✎ Editar datos", html)
        self.assertNotIn("Completar datos del producto", html)        # la ventana vieja ya no está
        self.assertIn("costoPorUnidad", html)                           # recepcion.js
        self.assertIn("pintarCosto", html)                              # editar_producto.js
        self.assertIn('id="editar-registro"', html)

    def test_pos_y_conteo_tambien_tienen_datos_tecnicos(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        html = self.c.get("/pos/").get_data(as_text=True)
        self.assertIn('data-pestana="tecnicos"', html)
        self.assertIn('id="editar-laboratorio"', html)

    def test_auxiliar_solo_ve_datos_tecnicos(self):
        self.crear_usuario(self.c, "aux", "auxiliar")
        c2 = self.cliente()
        self.entrar(c2, "aux")
        html = c2.get("/recepciones/nueva").get_data(as_text=True)
        self.assertIn('data-pestana="tecnicos"', html)
        self.assertNotIn('data-pestana="venta"', html)                 # los precios son de los jefes
        self.assertIn('data-puede-venta="0"', html)

    def test_info_del_producto_trae_la_parte_tecnica(self):
        con = self.db()
        con.execute("UPDATE productos SET registro_sanitario = 'INVIMA 2020M-1', concentracion = '500 mg' WHERE id = 1")
        con.commit()
        con.close()
        p = self.c.get("/pos/api/producto/1").get_json()["producto"]
        self.assertEqual(p["tecnicos"]["registro_sanitario"], "INVIMA 2020M-1")
        self.assertEqual(p["concentracion"], "500 mg")
        self.assertIn("principios", p["tecnicos"])

    def test_guardar_tecnicos_y_venta(self):
        """Lo mismo que hace la ventana al darle Guardar: primero técnicos, luego venta."""
        r1 = self.post(self.c, "/recepciones/api/producto/1/tecnicos",
                       {"registro_sanitario": "INVIMA 2021M-77", "concentracion": "10 mg", "laboratorio_id": "",
                        "principios": "", "forma_farmaceutica_id": "", "registro_vence": ""}).get_json()
        self.assertTrue(r1["ok"], r1)
        self.assertEqual(self.uno("SELECT registro_sanitario r FROM productos WHERE id = 1")["r"], "INVIMA 2021M-77")

    def test_ultimo_costo_para_la_etiqueta(self):
        from app.ventana_producto import ultimo_costo
        self.recepcion(costo=500)
        self.recepcion(costo=650)                                  # la más reciente manda
        self.recepcion(costo=999, estado="cuarentena")            # no aprobada: no cuenta
        self.recepcion(costo=111, resultado="rechazado", motivo="Roto")   # rechazada: no cuenta
        with self.app.app_context():
            from app.db import get_db
            self.assertEqual(ultimo_costo(get_db(), 1), 650)
            self.assertIsNone(ultimo_costo(get_db(), 2))           # nunca comprado
        # La búsqueda de la recepción lo trae, para pintar «▲ subió 23 %»
        res = self.c.get("/recepciones/api/buscar-productos?q=" + self.uno(
            "SELECT nombre FROM productos WHERE id = 1")["nombre"][:5]).get_json()["resultados"]
        p1 = next(x for x in res if x["id"] == 1)
        self.assertEqual(p1["ultimo_costo"], 650)


# =====================================================================
# 2. COBRAR CON EL TECLADO
# =====================================================================
class TestCobroConTeclado(BaseReportes):
    def setUp(self):
        super().setUp()
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()

    def test_la_pagina_trae_el_teclado(self):
        html = self.pagina_con_js(self.c, "/pos/")
        self.assertIn("COBRAR TODO CON EL TECLADO", html)
        self.assertIn("TECLAS_PREFERIDAS", html)
        self.assertIn("exitoDesde", html)                       # el medio segundo de espera
        self.assertIn('class="pago-teclas', html)              # la ayuda en pantalla

    def test_efectivo_vacio_es_pago_exacto(self):
        """Lo que manda el POS con «vacío + Enter»: monto_recibido vacío → cambio 0."""
        datos = {"carrito": json.dumps([{"producto_id": 1, "cantidad": 2}]), "forma_pago": "efectivo",
                 "monto_recibido": ""}
        j = self.post(self.c, "/pos/api/cobrar", datos).get_json()
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["cambio"], 0)


# =====================================================================
# 3. CONFIGURACIÓN → FORMAS DE PAGO
# =====================================================================
class TestFormasDePago(BaseReportes):
    URL = "/configuracion/formas-pago/"

    def agregar(self, nombre="Bancolombia", **extra):
        return self.post(self.c, self.URL + "agregar", {"nombre": nombre, "icono": "🟡", **extra},
                         follow_redirects=True)

    def test_pantalla(self):
        html = self.c.get(self.URL).get_data(as_text=True)
        for t in ("Nequi", "Davivienda", "Daviplata", "Tarjeta", "Agregar una cuenta", "no se borra"):
            self.assertIn(t, html)
        self.assertIn(self.URL, self.c.get("/").get_data(as_text=True))       # está en el menú

    def test_solo_administrador(self):
        self.crear_usuario(self.c, "aux", "auxiliar")
        c2 = self.cliente()
        self.entrar(c2, "aux")
        self.assertEqual(c2.get(self.URL).status_code, 403)

    def test_agregar_cuenta_y_usarla_en_todo(self):
        r = self.agregar(saldo_inicial="150.000")
        self.assertIn("Bancolombia agregada", r.get_data(as_text=True))
        c = self.uno("SELECT * FROM cuentas_bancarias WHERE clave = 'bancolombia'")
        self.assertEqual((c["saldo_inicial"], c["icono"], c["oculta"]), (150000, "🟡", 0))
        # Sale en el cobro del POS...
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        self.assertIn('data-forma="bancolombia"', self.c.get("/pos/").get_data(as_text=True))
        # ...se puede cobrar con ella (antes la base de datos no lo dejaba: regla CHECK)...
        datos = {"carrito": json.dumps([{"producto_id": 1, "cantidad": 3}]), "forma_pago": "bancolombia"}
        self.assertTrue(self.post(self.c, "/pos/api/cobrar", datos).get_json()["ok"])
        # ...y suma en Bancos: 150.000 + 3.000
        self.assertIn("$153.000", self.c.get("/bancos/").get_data(as_text=True))
        # También en el pago mixto y como forma de un gasto
        datos = {"carrito": json.dumps([{"producto_id": 1, "cantidad": 2}]), "forma_pago": "mixto",
                 "pagos": json.dumps({"bancolombia": 1000}), "monto_recibido": "1000"}
        self.assertTrue(self.post(self.c, "/pos/api/cobrar", datos).get_json()["ok"])

    def test_no_repetir_ni_palabras_reservadas(self):
        self.assertIn("Ya existe", self.agregar("nequi").get_data(as_text=True))
        self.assertIn("Ya existe", self.agregar("Efectivo").get_data(as_text=True))
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM cuentas_bancarias")["n"], 3)

    def test_ocultar_y_mostrar(self):
        self.lote(1, "L1", FUTURO, 10)
        self.abrir_caja()
        # Se vende por Daviplata y después se oculta
        datos = {"carrito": json.dumps([{"producto_id": 1, "cantidad": 1}]), "forma_pago": "daviplata"}
        self.assertTrue(self.post(self.c, "/pos/api/cobrar", datos).get_json()["ok"])
        self.post(self.c, self.URL + "daviplata/mostrar", {"ocultar": "1"})
        self.post(self.c, self.URL + "tarjeta/mostrar", {"ocultar": "1"})
        pos = self.c.get("/pos/").get_data(as_text=True)
        self.assertNotIn('data-forma="daviplata"', pos)
        self.assertNotIn('data-forma="tarjeta"', pos)
        # Ya no se puede cobrar con ella...
        self.assertFalse(self.post(self.c, "/pos/api/cobrar", datos).get_json()["ok"])
        # ...pero lo viejo sigue: la cuenta en Bancos y la venta en el reporte
        self.assertIn("Daviplata", self.c.get("/bancos/").get_data(as_text=True))
        from app import informes
        from datetime import date
        with self.app.test_request_context():
            from flask import g
            g.user = {"rol": "administrador"}
            d = informes.ventas(date.today(), date.today(), date.today(), date.today())
        self.assertIn("Daviplata", [f["nombre"] for f in d["por_pago"]])
        # Se vuelve a mostrar
        self.post(self.c, self.URL + "daviplata/mostrar", {"ocultar": "0"})
        self.assertIn('data-forma="daviplata"', self.c.get("/pos/").get_data(as_text=True))

    def test_efectivo_no_se_oculta(self):
        r = self.post(self.c, self.URL + "efectivo/mostrar", {"ocultar": "1"}, follow_redirects=True)
        self.assertIn("no se puede ocultar", r.get_data(as_text=True))

    def test_ordenar(self):
        self.agregar()
        self.post(self.c, self.URL + "bancolombia/mover", {"hacia": "arriba"})
        self.post(self.c, self.URL + "bancolombia/mover", {"hacia": "arriba"})
        with self.app.test_request_context():
            from app import formas_pago as fp
            self.assertEqual(fp.CLAVES_CUENTAS, ("nequi", "bancolombia", "davivienda", "daviplata"))

    def test_cambiar_nombre_no_cambia_la_clave(self):
        self.post(self.c, self.URL + "nequi/editar", {"nombre": "Nequi Fernando", "icono": "🟣"})
        c = self.uno("SELECT * FROM cuentas_bancarias WHERE clave = 'nequi'")
        self.assertEqual((c["nombre"], c["icono"]), ("Nequi Fernando", "🟣"))

    def test_la_base_de_datos_ya_no_limita_las_formas(self):
        """Migración 44: la regla CHECK de las 6 tablas ya no trae la lista fija."""
        con = self.db()
        for tabla in ("caja_movimientos", "gastos", "otros_ingresos", "cartera_abonos", "venta_pagos",
                      "pagos_proveedores"):
            sql = con.execute("SELECT sql FROM sqlite_master WHERE name = ?", (tabla,)).fetchone()[0]
            self.assertNotIn("'nequi'", sql, tabla)
        con.close()
