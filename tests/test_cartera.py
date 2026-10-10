"""
PRUEBAS DE CARTERA (cuentas por cobrar): ventas a crédito, cupo, abonos,
estado de cuenta, devoluciones de ventas a crédito y alerta de deuda vieja.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas, FUTURO

MES = date.today().isoformat()[:7]


class BaseCartera(BaseVentas):
    def setUp(self):
        super().setUp()
        self.lote(1, "L1", FUTURO, 100)     # producto 1: $1.000 c/u, costo $100

    def nuevo_cliente(self, nombre="Ana Pérez", documento="1020", cupo=""):
        self.post(self.c, "/cartera/clientes/nuevo",
                  {"nombre": nombre, "documento": documento, "telefono": "300", "cupo": cupo})
        return self.uno("SELECT * FROM clientes WHERE nombre = ?", nombre)

    def fiar(self, cliente_id, cantidad=1):
        return self.post(self.c, "/pos/api/cobrar", {
            "carrito": f'[{{"producto_id": 1, "cantidad": {cantidad}}}]',
            "forma_pago": "credito", "cliente_id": cliente_id}).get_json()

    def abonar(self, cliente_id, monto, forma="efectivo"):
        return self.post(self.c, "/cartera/api/abono",
                         {"cliente_id": cliente_id, "monto": monto, "forma_pago": forma}).get_json()

    def saldo(self, cliente_id):
        from app import cartera
        with self.app.test_request_context():
            return cartera.saldo(cliente_id)


class TestClientes(BaseCartera):
    def test_crear_y_validar(self):
        c = self.nuevo_cliente(cupo="50.000")
        self.assertEqual(c["cupo"], 50000)
        self.nuevo_cliente(nombre="Otro con mismo doc", documento="1020")   # documento repetido
        self.nuevo_cliente(nombre="Cupo malo", documento="9", cupo="-5")
        self.nuevo_cliente(nombre="ab", documento="8")
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM clientes")["n"], 1)

    def test_sin_cupo_es_sin_limite(self):
        self.assertIsNone(self.nuevo_cliente()["cupo"])

    def test_auxiliar_no_entra_a_cartera_pero_puede_buscar_desde_el_pos(self):
        self.nuevo_cliente()
        self.crear_usuario(self.c, "aux", "auxiliar")
        c = self.cliente()
        self.entrar(c, "aux")
        self.assertEqual(c.get("/cartera/").status_code, 403)
        self.assertEqual(c.get("/cartera/api/clientes?q=ana").get_json()["clientes"][0]["nombre"], "Ana Pérez")


class TestVentaACredito(BaseCartera):
    def test_fiar_deja_la_deuda_y_no_toca_la_caja(self):
        c = self.nuevo_cliente()
        self.abrir_caja("10000")
        j = self.fiar(c["id"], 3)
        self.assertTrue(j["ok"], j)
        v = self.uno("SELECT * FROM ventas")
        self.assertEqual((v["forma_pago"], v["cliente_id"], v["cliente_nombre"], v["monto_recibido"]),
                         ("credito", c["id"], "Ana Pérez", 0))
        self.assertEqual(self.saldo(c["id"]), 3000)
        r = self.c.get("/pos/api/resumen-caja").get_json()["resumen"]
        self.assertEqual(r["efectivo"]["esperado"], 10000)          # no entró plata
        self.assertEqual(r["credito"]["ventas"], 3000)              # pero se informa
        self.assertEqual(self.stock(1), 97)                         # el producto sí sale

    def test_sin_cliente_o_inactivo_no_se_puede(self):
        self.abrir_caja()
        self.assertFalse(self.fiar(999)["ok"])
        c = self.nuevo_cliente()
        self.post(self.c, f"/cartera/clientes/{c['id']}/editar", {"nombre": "Ana Pérez", "activo": "0"})
        self.assertFalse(self.fiar(c["id"])["ok"])

    def test_cupo(self):
        c = self.nuevo_cliente(cupo="5000")
        self.abrir_caja()
        self.assertTrue(self.fiar(c["id"], 4)["ok"])                # debe 4.000
        j = self.fiar(c["id"], 2)                                    # 6.000 > 5.000
        self.assertFalse(j["ok"])
        self.assertIn("cupo", j["error"])
        self.assertTrue(self.fiar(c["id"], 1)["ok"])                # justo 5.000

    def test_comprobante_dice_credito_y_saldo(self):
        c = self.nuevo_cliente()
        self.abrir_caja()
        self.fiar(c["id"], 2)
        html = self.c.get("/pos/venta/1").get_data(as_text=True)
        self.assertIn("VENTA A CRÉDITO", html)
        self.assertIn("Firma del cliente", html)
        self.assertIn("$2.000", html)

    def test_anular_la_venta_borra_la_deuda(self):
        c = self.nuevo_cliente()
        self.abrir_caja()
        self.fiar(c["id"], 2)
        self.post(self.c, "/pos/venta/1/anular", {"motivo": "Error"})
        self.assertEqual(self.saldo(c["id"]), 0)


class TestAbonos(BaseCartera):
    def test_abono_en_efectivo_entra_a_la_caja(self):
        c = self.nuevo_cliente()
        self.abrir_caja("10000")
        self.fiar(c["id"], 5)
        j = self.abonar(c["id"], 2000)
        self.assertTrue(j["ok"], j)
        self.assertEqual((j["numero"], j["saldo"]), ("AB-0001", 3000))
        r = self.c.get("/pos/api/resumen-caja").get_json()["resumen"]
        self.assertEqual(r["efectivo"]["esperado"], 12000)
        recibo = self.c.get(j["url_recibo"]).get_data(as_text=True)
        self.assertIn("RECIBO DE ABONO", recibo)
        self.assertIn("$3.000", recibo)                              # saldo pendiente

    def test_limites(self):
        c = self.nuevo_cliente()
        self.assertIn("no tiene deuda", self.abonar(c["id"], 100)["error"])
        self.abrir_caja()
        self.fiar(c["id"], 2)
        self.assertIn("solo debe", self.abonar(c["id"], 5000)["error"])
        self.assertFalse(self.abonar(c["id"], 0)["ok"])

    def test_efectivo_necesita_caja_abierta_pero_transferencia_no(self):
        c = self.nuevo_cliente()
        self.abrir_caja()
        self.fiar(c["id"], 2)
        self.post(self.c, "/pos/api/cerrar-caja", {"efectivo_contado": "10000"})
        self.assertIn("abre la caja", self.abonar(c["id"], 500)["error"].lower())
        self.assertTrue(self.abonar(c["id"], 500, "transferencia")["ok"])
        self.assertEqual(self.saldo(c["id"]), 1500)

    def test_anular_abono_devuelve_la_deuda_y_saca_la_plata(self):
        c = self.nuevo_cliente()
        self.abrir_caja("10000")
        self.fiar(c["id"], 3)
        self.abonar(c["id"], 3000)
        self.assertEqual(self.saldo(c["id"]), 0)
        self.post(self.c, "/cartera/abonos/1/anular", {"motivo": "Se registró dos veces"})
        self.assertEqual(self.saldo(c["id"]), 3000)
        r = self.c.get("/pos/api/resumen-caja").get_json()["resumen"]
        self.assertEqual(r["efectivo"]["esperado"], 10000)           # entró y salió

    def test_abono_desde_la_pantalla_de_cartera(self):
        c = self.nuevo_cliente()
        self.abrir_caja()
        self.fiar(c["id"], 2)
        r = self.post(self.c, f"/cartera/clientes/{c['id']}/abonar", {"monto": "1000", "forma_pago": "nequi"})
        self.assertIn("/recibo", r.headers["Location"])
        self.assertEqual(self.saldo(c["id"]), 1000)


class TestEstadoDeCuenta(BaseCartera):
    def test_fifo_y_antiguedad(self):
        from app import cartera
        c = self.nuevo_cliente()
        self.abrir_caja()
        self.fiar(c["id"], 2)          # V-0001: 2.000
        self.fiar(c["id"], 3)          # V-0002: 3.000
        con = self.db()                # V-0001 fue hace 45 días
        con.execute("UPDATE ventas SET fecha = ? WHERE id = 1",
                    ((date.today() - timedelta(days=45)).isoformat() + " 10:00:00",))
        con.commit()
        con.close()
        self.abonar(c["id"], 2500)     # paga toda la V-0001 y 500 de la V-0002
        with self.app.test_request_context():
            e = cartera.estado_de_cuenta(c["id"])
            r = cartera.resumen()
        self.assertEqual(e["saldo"], 2500)
        self.assertEqual([p["consecutivo"] for p in e["pendientes"]], ["V-0002"])
        self.assertEqual(e["pendientes"][0]["pendiente"], 2500)
        self.assertEqual(e["dias_mayor"], 0)                         # la vieja ya se pagó
        self.assertEqual(r["total"], 2500)
        self.assertEqual(r["rangos"][0]["total"], 2500)              # 0 a 30 días

    def test_pantallas(self):
        c = self.nuevo_cliente()
        self.abrir_caja()
        self.fiar(c["id"], 2)
        self.abonar(c["id"], 500)
        lista = self.c.get("/cartera/").get_data(as_text=True)
        self.assertIn("Ana Pérez", lista)
        self.assertIn("$1.500", lista)
        estado = self.c.get(f"/cartera/clientes/{c['id']}").get_data(as_text=True)
        self.assertIn("Venta a crédito", estado)
        self.assertIn("AB-0001", estado)
        self.assertIn("Registrar abono", estado)

    def test_alerta_de_deuda_vieja_en_inicio(self):
        c = self.nuevo_cliente()
        self.abrir_caja()
        self.fiar(c["id"], 2)
        self.assertNotIn("Clientes con deuda de más de 30 días", self.c.get("/").get_data(as_text=True))
        con = self.db()
        con.execute("UPDATE ventas SET fecha = ?", ((date.today() - timedelta(days=40)).isoformat() + " 10:00:00",))
        con.commit()
        con.close()
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn("Clientes con deuda de más de 30 días", html)
        self.assertIn("desde hace 40 días", html)

    def test_reporte_de_ventas_muestra_credito(self):
        c = self.nuevo_cliente()
        self.abrir_caja()
        self.fiar(c["id"], 2)
        self.assertIn("Crédito (cartera)", self.c.get(f"/reportes/ventas?mes={MES}").get_data(as_text=True))


class TestDevolucionDeVentaACredito(BaseCartera):
    def test_se_descuenta_de_la_deuda(self):
        c = self.nuevo_cliente()
        self.abrir_caja("10000")
        self.fiar(c["id"], 4)                                         # debe 4.000
        html = self.c.get("/devoluciones/cliente?venta=V-0001").get_data(as_text=True)
        self.assertIn('value="credito"', html)
        self.assertNotIn('value="efectivo"', html)                    # no se devuelve plata
        linea = self.uno("SELECT id FROM venta_lineas")["id"]
        self.post(self.c, "/devoluciones/cliente", {"venta": "V-0001", f"cant_{linea}": "1",
                                                    f"destino_{linea}": "reingreso", "motivo": "No lo necesitó",
                                                    "forma_reembolso": "credito"})
        self.assertEqual(self.saldo(c["id"]), 3000)
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM caja_movimientos")["n"], 0)

    def test_no_se_puede_devolver_plata_de_una_venta_fiada(self):
        c = self.nuevo_cliente()
        self.abrir_caja()
        self.fiar(c["id"], 2)
        linea = self.uno("SELECT id FROM venta_lineas")["id"]
        self.post(self.c, "/devoluciones/cliente", {"venta": "V-0001", f"cant_{linea}": "1",
                                                    f"destino_{linea}": "reingreso", "motivo": "Prueba",
                                                    "forma_reembolso": "efectivo"})
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM devoluciones")["n"], 0)
