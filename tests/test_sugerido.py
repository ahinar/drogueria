"""
PRUEBAS DE R6 · SUGERIDO DE COMPRA.

Montaje: productos 1 (Acetaminofén) y 2 (Jeringa), proveedor 1.
Se venden unidades por el POS para crear "historial de ventas".
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import FECHA
from test_fase2_ventas import BaseVentas, FUTURO

HOY = date.today()


class BaseSugerido(BaseVentas):
    def calcular(self, **kw):
        from app import sugerido
        with self.app.test_request_context():
            return sugerido.calcular(**kw)

    def compra(self, producto_id, costo, proveedor_id=1, hace_dias=10):
        """Una recepción aprobada (para saber a quién se le compra y a qué costo)."""
        fecha = (HOY - timedelta(days=hace_dias)).isoformat() + " 10:00:00"
        con = self.db()
        n = con.execute("SELECT COUNT(*) FROM recepciones").fetchone()[0] + 1
        rec = con.execute("INSERT INTO recepciones (numero, fecha, proveedor_id, estado, creado_en) "
                          "VALUES (?,?,?, 'aprobada', ?)", (f"REC-{n:04d}", fecha, proveedor_id, fecha)).lastrowid
        con.execute("INSERT INTO recepcion_lineas (recepcion_id, producto_id, cantidad_facturada, cantidad_recibida, "
                    "costo_unitario, resultado) VALUES (?,?,10,10,?, 'aceptado')", (rec, producto_id, costo))
        con.commit(); con.close()

    def sql(self, consulta, *args):
        con = self.db(); con.execute(consulta, args); con.commit(); con.close()

    def item(self, lista, producto_id):
        return next((i for i in lista if i["id"] == producto_id), None)


class TestCalculo(BaseSugerido):
    def test_sin_ventas_se_guia_por_el_stock_minimo(self):
        self.sql("UPDATE productos SET stock_minimo = 20 WHERE id = 1")
        self.lote(1, "L1", FUTURO, 5)
        d = self.calcular()
        i = self.item(d["pedido"][0]["items"], 1)
        self.assertEqual(i["sugerido"], 15)          # quiere 20, tiene 5
        self.assertEqual(i["motivo"], "mínimo")
        self.assertFalse(d["hay_ventas"])

    def test_con_ventas_calcula_para_la_cobertura(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 60}])    # 60 en 30 días = 2 al día; quedan 40
        d = self.calcular(cobertura=30)                       # quiere 2 x 30 = 60, tiene 40 -> 20
        i = self.item(d["pedido"][0]["items"], 1)
        self.assertAlmostEqual(i["diaria"], 2)
        self.assertEqual(i["dias_alcanza"], 20)
        self.assertEqual(i["sugerido"], 20)
        self.assertEqual(i["motivo"], "ventas")
        # Con 15 días de cobertura quiere 30 y tiene 40: no se pide
        self.assertIsNone(self.item(sum((g["items"] for g in self.calcular(cobertura=15)["pedido"]), []), 1))

    def test_ventas_por_caja_cuentan_unidades(self):
        con = self.db()
        uid = con.execute("INSERT INTO unidades_medida (nombre, cantidad, activo, creado_en) "
                          "VALUES ('Caja x 10', 10, 1, ?)", (FECHA,)).lastrowid
        pid = con.execute("INSERT INTO producto_presentaciones (producto_id, unidad_id, factor, precio_venta, "
                          "creado_en) VALUES (1, ?, 10, 9000, ?)", (uid, FECHA)).lastrowid
        con.commit(); con.close()
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "presentacion_id": pid, "cantidad": 3}])   # 30 unidades
        self.sql("UPDATE productos SET stock_minimo = 100 WHERE id = 1")   # para que salga en el pedido
        i = self.item(self.calcular()["pedido"][0]["items"], 1)
        self.assertAlmostEqual(i["diaria"], 1)        # 30 unidades / 30 días
        self.assertEqual(i["stock"], 70)
        self.assertEqual(i["en_presentacion"], "≈ 3 Caja x 10")   # pide 30 = 3 cajas

    def test_ventas_anuladas_y_viejas_no_cuentan(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 30}])
        self.post(self.c, "/pos/venta/1/anular", {"motivo": "Error"})
        self.cobrar([{"producto_id": 1, "cantidad": 30}])
        self.sql("UPDATE ventas SET fecha = ? WHERE id = 2", (HOY - timedelta(days=45)).isoformat() + " 10:00:00")
        d = self.calcular()
        self.assertFalse(d["hay_ventas"])

    def test_agrupa_por_el_proveedor_de_la_ultima_compra(self):
        self.sql("INSERT INTO proveedores (nit, razon_social, telefono, creado_en) "
                 "VALUES ('800', 'Otro Proveedor', '300 123 4567', ?)", FECHA)
        self.sql("UPDATE productos SET stock_minimo = 5 WHERE id IN (1, 2)")
        self.compra(1, 900, proveedor_id=1, hace_dias=40)
        self.compra(1, 950, proveedor_id=2, hace_dias=5)    # la más reciente manda
        d = self.calcular()
        nombres = {g["proveedor"]: [i["id"] for i in g["items"]] for g in d["pedido"]}
        self.assertEqual(nombres["Otro Proveedor"], [1])
        self.assertIn(2, nombres["Sin proveedor (nunca se ha comprado)"])
        grupo = [g for g in d["pedido"] if g["proveedor"] == "Otro Proveedor"][0]
        self.assertEqual(grupo["items"][0]["costo"], 950)
        self.assertEqual(grupo["total"], 5 * 950)
        self.assertEqual(d["pedido"][-1]["proveedor_id"], 0)    # "sin proveedor" al final

    def test_stock_vencido_o_en_cuarentena_no_cuenta(self):
        self.sql("UPDATE productos SET stock_minimo = 10 WHERE id = 1")
        self.lote(1, "VIEJO", (HOY - timedelta(days=1)).isoformat(), 50)
        self.lote(1, "CUAR", FUTURO, 50, estado="cuarentena")
        i = self.item(self.calcular()["bajo_minimo"], 1)
        self.assertEqual((i["stock"], i["sugerido"]), (0, 10))

    def test_se_agota_en_menos_de_7_dias(self):
        self.lote(1, "L1", FUTURO, 70)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 60}])    # 2 al día, quedan 10 -> 5 días
        d = self.calcular()
        self.assertEqual(self.item(d["se_agota"], 1)["dias_alcanza"], 5)

    def test_sin_rotacion(self):
        self.lote(1, "L1", FUTURO, 10)          # costo $100 -> $1.000 quietos
        self.lote(2, "L2", FUTURO, 10)
        self.abrir_caja()
        self.cobrar([{"producto_id": 2, "cantidad": 1}])
        d = self.calcular()
        self.assertEqual([i["id"] for i in d["sin_rotacion"]], [1])
        self.assertEqual(d["valor_sin_rotacion"], 1000)

    def test_telefono_para_whatsapp(self):
        from app.sugerido import telefono_whatsapp
        self.assertEqual(telefono_whatsapp("300 123 4567"), "573001234567")
        self.assertEqual(telefono_whatsapp("+57 300-123-4567"), "573001234567")
        self.assertEqual(telefono_whatsapp("6041234567"), "")       # fijo: no sirve para WhatsApp
        self.assertEqual(telefono_whatsapp(None), "")


class TestPantalla(BaseSugerido):
    def test_pantalla(self):
        self.sql("UPDATE productos SET stock_minimo = 8 WHERE id = 1")
        self.sql("UPDATE proveedores SET telefono = '3001234567'")
        self.compra(1, 900)
        html = self.c.get("/reportes/sugerido?cobertura=30&rotacion=90").get_data(as_text=True)
        self.assertIn("Proveedor Prueba SAS", html)
        self.assertIn('data-whatsapp="573001234567"', html)
        self.assertIn('value="8"', html)
        self.assertIn("$7.200", html)                          # 8 x $900
        self.assertEqual(self.c.get("/reportes/sugerido?cobertura=999").status_code, 200)   # valor raro -> 15

    def test_auxiliar_no_entra(self):
        self.crear_usuario(self.c, "aux", "auxiliar")
        c = self.cliente()
        self.entrar(c, "aux")
        self.assertIn(c.get("/reportes/sugerido").status_code, (302, 403))
