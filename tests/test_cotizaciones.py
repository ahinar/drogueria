"""
PRUEBAS DE COTIZACIONES: guardar el carrito como cotización, verla/imprimirla
con WhatsApp, cargarla en el POS y cobrarla (queda "convertida").
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase2_ventas import BaseVentas, FUTURO


class TestCotizaciones(BaseVentas):
    def setUp(self):
        super().setUp()
        self.lote(1, "L1", FUTURO, 100)          # producto 1: $1.000 c/u

    def cotizar(self, **extra):
        datos = {"carrito": json.dumps([{"producto_id": 1, "presentacion_id": 0, "cantidad": 3, "precio": 900},
                                        {"libre": 1, "descripcion": "Inyectología", "precio": 5000, "cantidad": 1}]),
                 "cliente_nombre": "Ana", "cliente_telefono": "300 123 4567", "validez_dias": "8"}
        datos.update(extra)
        return self.post(self.c, "/cotizaciones/api/crear", datos).get_json()

    def test_crear_ver_y_whatsapp(self):
        j = self.cotizar()
        self.assertTrue(j["ok"], j)
        self.assertEqual((j["numero"], j["total"]), ("COT-0001", 2700 + 5000))
        html = self.c.get(j["url"]).get_data(as_text=True)
        self.assertIn("COTIZACIÓN", html)
        self.assertIn("wa.me/573001234567", html)              # celular con indicativo de Colombia
        self.assertIn("$7.700", html)
        self.assertEqual(self.stock(1), 100)                    # no toca el inventario
        lista = self.c.get("/cotizaciones/").get_data(as_text=True)
        self.assertIn("COT-0001", lista)
        self.assertIn("Vigente", lista)

    def test_cargar_en_el_pos_y_cobrar_la_convierte(self):
        j = self.cotizar()
        api = self.c.get(f"/cotizaciones/api/{j['id']}").get_json()
        self.assertTrue(api["vigente"])
        self.assertEqual(api["lineas"][0]["precio"], 900)
        # El POS manda el precio cotizado con motivo "Cotización COT-0001"
        self.abrir_caja()
        r = self.post(self.c, "/pos/api/cobrar", {
            "carrito": json.dumps([{"producto_id": 1, "presentacion_id": 0, "cantidad": 3,
                                    "precio_nuevo": 900, "motivo_precio": "Cotización COT-0001"}]),
            "forma_pago": "efectivo", "cotizacion_id": str(j["id"])}).get_json()
        self.assertTrue(r["ok"], r)
        c = self.uno("SELECT * FROM cotizaciones WHERE id = ?", j["id"])
        self.assertEqual(c["estado"], "convertida")
        self.assertEqual(self.uno("SELECT cotizacion_id FROM ventas WHERE id = ?", c["venta_id"])[0], j["id"])
        self.assertEqual(self.c.get(f"/cotizaciones/api/{j['id']}").get_json()["estado"], "convertida")

    def test_vencida_y_anular(self):
        j = self.cotizar()
        con = self.db()
        con.execute("UPDATE cotizaciones SET fecha = ? WHERE id = ?",
                    ((date.today() - timedelta(days=20)).isoformat() + " 10:00:00", j["id"]))
        con.commit()
        con.close()
        self.assertFalse(self.c.get(f"/cotizaciones/api/{j['id']}").get_json()["vigente"])
        self.post(self.c, f"/cotizaciones/{j['id']}/anular", {"motivo": "No volvió"})
        self.assertEqual(self.uno("SELECT estado FROM cotizaciones WHERE id = ?", j["id"])[0], "anulada")

    def test_carrito_vacio_no(self):
        self.assertFalse(self.cotizar(carrito="[]")["ok"])

    def test_buscar_productos_por_ids(self):
        r = self.c.get("/pos/api/productos?ids=1").get_json()
        self.assertEqual([p["id"] for p in r["productos"]], [1])
