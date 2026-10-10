"""
PRUEBAS DE DEVOLUCIONES (de cliente y a proveedor).

Montaje: producto 1 a $1.000 (sin IVA), producto 2 a $11.900 (IVA 19 %).
Los lotes de prueba cuestan $100 la unidad.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas, FUTURO, FUTURO_CERCA

HOY = date.today()


class BaseDevoluciones(BaseVentas):
    def devolver(self, venta="V-0001", forma="efectivo", motivo="Producto equivocado", **cantidades):
        """cantidades: cant_<linea>=..., destino_<linea>=..."""
        datos = {"venta": venta, "forma_reembolso": forma, "motivo": motivo}
        datos.update(cantidades)
        return self.post(self.c, "/devoluciones/cliente", datos)

    def stock_lote(self, nombre):
        return self.uno("SELECT cantidad_disponible n FROM lotes WHERE lote = ?", nombre)["n"]

    def estado(self):
        from app import utilidades
        with self.app.test_request_context():
            return utilidades.estado_de_resultados()["actual"]


class TestDevolucionCliente(BaseDevoluciones):
    def vender(self, cantidad=3, producto=1):
        self.lote(1, "L1", FUTURO, 100)
        self.lote(2, "L2", FUTURO, 10)
        self.abrir_caja()
        self.cobrar([{"producto_id": producto, "cantidad": cantidad, "descuento_pct": 10}])   # 10 % de descuento

    def test_reingreso_devuelve_al_lote_y_saca_plata_de_la_caja(self):
        self.vender(3)                           # 3 x $1.000 - 10 % = $2.700
        self.devolver(cant_1="1", destino_1="reingreso")
        dev = self.uno("SELECT * FROM devoluciones")
        self.assertEqual((dev["numero"], dev["tipo"], dev["total"]), ("DC-0001", "cliente", 900))   # 1/3 de $2.700
        self.assertEqual(self.stock_lote("L1"), 98)                     # 97 + 1
        mov = self.uno("SELECT * FROM caja_movimientos WHERE tipo = 'salida'")
        self.assertEqual((mov["monto"], mov["forma_pago"]), (900, "efectivo"))
        kardex = self.uno("SELECT * FROM movimientos_inventario WHERE tipo = 'devolucion'")
        self.assertEqual(kardex["cantidad"], 1)
        self.assertIsNotNone(self.uno("SELECT 1 FROM bitacora WHERE accion = 'devolucion_cliente'"))

    def test_baja_no_vuelve_al_inventario(self):
        self.vender(3)
        self.devolver(cant_1="2", destino_1="baja")
        self.assertEqual(self.stock_lote("L1"), 97)
        self.assertEqual(self.uno("SELECT total FROM devoluciones")["total"], 1800)

    def test_no_se_devuelve_mas_de_lo_comprado_ni_dos_veces(self):
        self.vender(3)
        self.devolver(cant_1="4")
        self.assertIsNone(self.uno("SELECT 1 FROM devoluciones"))
        self.devolver(cant_1="2")
        self.devolver(cant_1="2")                                       # solo queda 1
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM devoluciones")["n"], 1)
        self.devolver(cant_1="1")
        self.assertEqual(self.uno("SELECT SUM(cantidad) n FROM devolucion_lineas")["n"], 3)
        self.assertEqual(self.stock_lote("L1"), 100)                    # todo volvió

    def test_validaciones(self):
        self.vender(3)
        self.devolver(cant_1="1", motivo="")                            # sin motivo
        self.devolver(cant_1="1", forma="bitcoin")                      # forma inválida
        self.devolver(cant_1="0")                                       # nada
        self.devolver(cant_1="abc")                                     # inválida
        self.devolver(venta="V-0099", cant_1="1")                       # no existe
        self.assertIsNone(self.uno("SELECT 1 FROM devoluciones"))

    def test_sin_caja_abierta_no_se_puede(self):
        self.vender(3)
        con = self.db(); con.execute("UPDATE cajas SET estado = 'cerrada'"); con.commit(); con.close()
        self.devolver(cant_1="1")
        self.assertIsNone(self.uno("SELECT 1 FROM devoluciones"))

    def test_venta_anulada_no_se_devuelve_y_con_devolucion_no_se_anula(self):
        self.vender(3)
        self.devolver(cant_1="1")
        self.post(self.c, "/pos/venta/1/anular", {"motivo": "Error"})
        self.assertEqual(self.uno("SELECT estado FROM ventas")["estado"], "completada")
        self.cobrar([{"producto_id": 1, "cantidad": 1}])
        self.post(self.c, "/pos/venta/2/anular", {"motivo": "Error"})
        self.devolver(venta="V-0002", cant_1="1")
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM devoluciones")["n"], 1)

    def test_vuelve_a_los_lotes_de_donde_salio(self):
        self.lote(1, "LARGO", FUTURO, 10)
        self.lote(1, "CORTO", FUTURO_CERCA, 2)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 5}])      # 2 del CORTO + 3 del LARGO
        self.devolver(cant_1="4")                             # vuelven 3 al LARGO (último) y 1 al CORTO
        self.assertEqual((self.stock_lote("CORTO"), self.stock_lote("LARGO")), (1, 10))
        self.devolver(cant_1="1")                             # el último vuelve al CORTO
        self.assertEqual((self.stock_lote("CORTO"), self.stock_lote("LARGO")), (2, 10))

    def test_utilidades_restan_la_devolucion(self):
        self.vender(3)                                        # ventas sin IVA $2.700, costo $300
        self.devolver(cant_1="1", destino_1="reingreso")      # -$900 de ventas, -$100 de costo
        a = self.estado()
        self.assertEqual((a["ventas"], a["devoluciones"], a["costo"]), (2700, 900, 200))
        self.assertEqual(a["utilidad_bruta"], 2700 - 900 - 200)

    def test_utilidades_con_baja_el_costo_se_queda(self):
        self.vender(3)
        self.devolver(cant_1="1", destino_1="baja")
        a = self.estado()
        self.assertEqual((a["devoluciones"], a["costo"]), (900, 300))

    def test_cierre_de_caja_descuenta_el_reembolso(self):
        self.vender(3)
        self.devolver(cant_1="1")
        efectivo = self.c.get("/pos/api/resumen-caja").get_json()["resumen"]["efectivo"]
        self.assertEqual(efectivo["salidas"], 900)
        self.assertEqual(efectivo["esperado"], 10000 + 2700 - 900)   # base + venta - reembolso

    def test_pantallas(self):
        self.vender(3)
        html = self.c.get("/devoluciones/cliente?venta=1").get_data(as_text=True)   # "1" -> V-0001
        self.assertIn('name="cant_1"', html)
        self.devolver(cant_1="1")
        self.assertIn("DC-0001", self.c.get("/devoluciones/").get_data(as_text=True))
        self.assertIn("Volvió al inventario", self.c.get("/devoluciones/1").get_data(as_text=True))
        pdf = self.c.get("/devoluciones/1/pdf")
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        self.assertIn("devoluciones/cliente?venta=V-0001", self.c.get("/pos/ventas").get_data(as_text=True))


class TestDevolucionProveedor(BaseDevoluciones):
    def test_con_nota_credito_no_es_perdida(self):
        self.lote(1, "VENCIDO", (HOY - timedelta(days=2)).isoformat(), 10)
        self.post(self.c, "/devoluciones/proveedor", {"proveedor_id": "1", "motivo": "Producto vencido",
                                                       "con_credito": "1", "nota_credito": "NC-55", "cant_1": "10"})
        dev = self.uno("SELECT * FROM devoluciones")
        self.assertEqual((dev["numero"], dev["total"], dev["con_credito"]), ("DP-0001", 1000, 1))
        lote = self.uno("SELECT * FROM lotes")
        self.assertEqual(lote["cantidad_disponible"], 0)
        mov = self.uno("SELECT * FROM movimientos_inventario")
        self.assertEqual((mov["tipo"], mov["cantidad"]), ("devolucion", -10))
        self.assertEqual(self.estado()["total_perdidas"], 0)

    def test_sin_credito_es_perdida(self):
        self.lote(1, "AVERIADO", FUTURO, 10)
        self.post(self.c, "/devoluciones/proveedor", {"proveedor_id": "1", "motivo": "Averiado / empaque dañado",
                                                       "cant_1": "4"})
        self.assertEqual(self.uno("SELECT tipo FROM movimientos_inventario")["tipo"], "baja")
        self.assertEqual(self.estado()["bajas"], 400)
        self.assertEqual(self.stock_lote("AVERIADO"), 6)

    def test_validaciones(self):
        self.lote(1, "L1", FUTURO, 10)
        for datos in ({"proveedor_id": "1", "motivo": "Producto vencido", "cant_1": "11"},   # más de lo que hay
                      {"proveedor_id": "", "motivo": "Producto vencido", "cant_1": "1"},     # sin proveedor
                      {"proveedor_id": "1", "motivo": "Inventado", "cant_1": "1"},           # motivo inválido
                      {"proveedor_id": "1", "motivo": "Otro", "cant_1": "1"},                # "Otro" sin detalle
                      {"proveedor_id": "1", "motivo": "Producto vencido"}):                  # sin cantidades
            self.post(self.c, "/devoluciones/proveedor", datos)
        self.assertIsNone(self.uno("SELECT 1 FROM devoluciones"))
        self.assertEqual(self.stock_lote("L1"), 10)

    def test_resta_en_ventas_vs_compras(self):
        from app import informes
        self.lote(1, "L1", FUTURO, 10)
        self.post(self.c, "/devoluciones/proveedor", {"proveedor_id": "1", "motivo": "Error en el pedido",
                                                       "con_credito": "1", "cant_1": "3"})
        with self.app.test_request_context():
            self.assertEqual(informes.ventas_vs_compras()["filas"][-1]["comprado"], -300)

    def test_pantalla_y_pdf(self):
        self.lote(1, "VIEJO", (HOY - timedelta(days=2)).isoformat(), 10)
        html = self.c.get("/devoluciones/proveedor").get_data(as_text=True)
        self.assertIn("VIEJO", html)                       # por defecto muestra los vencidos
        self.assertIn("VIEJO", self.c.get("/devoluciones/proveedor?lote=1").get_data(as_text=True))
        self.post(self.c, "/devoluciones/proveedor", {"proveedor_id": "1", "motivo": "Producto vencido",
                                                       "con_credito": "1", "cant_1": "10"})
        self.assertTrue(self.c.get("/devoluciones/1/pdf").data.startswith(b"%PDF"))

    def test_auxiliar_no_entra(self):
        self.crear_usuario(self.c, "aux", "auxiliar")
        c = self.cliente()
        self.entrar(c, "aux")
        self.assertIn(c.get("/devoluciones/").status_code, (302, 403))
        self.assertIn(c.get("/devoluciones/cliente").status_code, (302, 403))
