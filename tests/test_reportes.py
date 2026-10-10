"""
PRUEBAS DE LOS REPORTES R1 (Ventas), R3 (Top), R4 (Ventas vs compras),
R5 (Gastos), R7 (Recepciones) y R8 (Vencimientos).
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import FECHA
from test_utilidades import BaseUtilidades
from test_fase2_ventas import FUTURO

HOY = date.today()
INICIO_MES = HOY.replace(day=1)


class BaseReportes(BaseUtilidades):
    def ctx(self):
        return self.app.test_request_context()

    def recepcion(self, estado="aprobada", resultado="aceptado", costo=500, cantidad=10, motivo=None):
        con = self.db()
        n = con.execute("SELECT COUNT(*) FROM recepciones").fetchone()[0] + 1
        rec = con.execute("INSERT INTO recepciones (numero, fecha, proveedor_id, estado, creado_en) "
                          "VALUES (?,?,1,?,?)", (f"REC-{n:04d}", HOY.isoformat() + " 09:00:00", estado, FECHA)).lastrowid
        con.execute("INSERT INTO recepcion_lineas (recepcion_id, producto_id, lote, cantidad_facturada, cantidad_recibida, "
                    "costo_unitario, resultado, motivo_rechazo) VALUES (?,1,'X1',?,?,?,?,?)",
                    (rec, cantidad, cantidad, costo, resultado, motivo))
        con.commit(); con.close()


class TestVentas(BaseReportes):
    def test_totales_por_pago_y_vendedor(self):
        from app import informes
        self.lote(1, "L1", FUTURO, 100)
        self.lote(2, "L2", FUTURO, 10)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 2}])                       # $2.000 efectivo
        self.cobrar([{"producto_id": 2, "cantidad": 1}], forma="nequi")        # $11.900 Nequi
        self.cobrar([{"producto_id": 1, "cantidad": 1}])
        self.post(self.c, "/pos/venta/3/anular", {"motivo": "Error"})          # no cuenta
        with self.ctx():
            d = informes.ventas(INICIO_MES, HOY, INICIO_MES - timedelta(days=30), INICIO_MES - timedelta(days=1))
        self.assertEqual((d["actual"]["n"], d["actual"]["con_iva"], d["actual"]["sin_iva"]), (2, 13900, 12000))
        self.assertEqual(d["actual"]["ticket"], 6950)
        self.assertEqual(d["anuladas"]["n"], 1)
        self.assertEqual({f["nombre"]: f["total"] for f in d["por_pago"]}, {"Nequi": 11900, "Efectivo": 2000})
        self.assertEqual(d["por_vendedor"][0]["nombre"], "Fernando")
        self.assertEqual(len(d["por_dia"]), (HOY - INICIO_MES).days + 1)    # todos los días, aunque estén en 0
        self.assertEqual(sum(f["total"] for f in d["por_dia"]), 13900)
        self.assertEqual(sum(h["n"] for h in d["por_hora"]), 2)

    def test_pantalla(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 2}])
        html = self.c.get("/reportes/ventas").get_data(as_text=True)
        self.assertIn("grafico-ventas", html)
        self.assertIn("$2.000", html)
        self.assertIn('class="activo">🛒 Ventas', html)        # el menú marca el reporte actual
        self.assertIn("No hay ventas", self.c.get("/reportes/ventas?mes=2020-01").get_data(as_text=True))


class TestTop(BaseReportes):
    def test_orden_por_dinero_unidades_y_utilidad(self):
        from app import informes
        self.lote(1, "L1", FUTURO, 100)     # $1.000, costo $100
        self.lote(2, "L2", FUTURO, 10)      # $11.900, costo $100
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 5}])     # 5 und, $5.000
        self.cobrar([{"producto_id": 2, "cantidad": 1}])     # 1 und, $11.900
        with self.ctx():
            por_dinero = informes.top_productos(INICIO_MES, HOY, 10, "dinero")
            por_unidades = informes.top_productos(INICIO_MES, HOY, 10, "unidades")
            uno = informes.top_productos(INICIO_MES, HOY, 1, "dinero")
        self.assertEqual([p["id"] for p in por_dinero["top"]], [2, 1])
        self.assertEqual([p["id"] for p in por_unidades["top"]], [1, 2])
        acet = [p for p in por_dinero["top"] if p["id"] == 1][0]
        self.assertEqual((acet["unidades"], acet["utilidad"]), (5, 5000 - 500))
        self.assertEqual(len(uno["top"]), 1)
        self.assertEqual(uno["total_productos"], 2)

    def test_pantalla(self):
        self.assertEqual(self.c.get("/reportes/top?orden=unidades&cuantos=5").status_code, 200)
        self.assertEqual(self.c.get("/reportes/top?orden=raro&cuantos=99").status_code, 200)


class TestVentasVsCompras(BaseReportes):
    def test_mes_actual(self):
        from app import informes
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 3}])        # vendido sin IVA 3.000
        self.recepcion(costo=500, cantidad=10)                   # comprado 5.000
        self.recepcion(estado="cuarentena", costo=999)           # no cuenta (no aprobada)
        self.recepcion(resultado="rechazado", costo=999)         # no cuenta (rechazado)
        with self.ctx():
            d = informes.ventas_vs_compras()
        self.assertEqual(len(d["filas"]), 12)
        ultimo = d["filas"][-1]
        self.assertEqual((ultimo["vendido"], ultimo["comprado"], ultimo["diferencia"]), (3000, 5000, -2000))
        self.assertEqual(self.c.get("/reportes/ventas-vs-compras").status_code, 200)


class TestGastos(BaseReportes):
    def test_por_categoria_y_comparacion(self):
        from app import informes
        self.gasto("Arriendo", 1000)
        self.gasto("Domicilios", 300)
        self.gasto("Arriendo", 800, fecha=(INICIO_MES - timedelta(days=1)).replace(day=1).isoformat())
        with self.ctx():
            ant_h = INICIO_MES - timedelta(days=1)
            d = informes.gastos(INICIO_MES, HOY, ant_h.replace(day=1), ant_h)
        self.assertEqual(d["total"], 1300)
        self.assertEqual(d["total_anterior"], 800)
        arriendo = d["categorias"][0]
        self.assertEqual((arriendo["categoria"], arriendo["total"], arriendo["anterior"]), ("Arriendo", 1000, 800))
        html = self.c.get("/reportes/gastos").get_data(as_text=True)
        self.assertIn("Domicilios", html)


class TestRecepciones(BaseReportes):
    def test_por_proveedor_y_rechazos(self):
        from app import informes
        self.recepcion(costo=500, cantidad=10)
        self.recepcion(resultado="rechazado", motivo="Empaque roto")
        with self.ctx():
            d = informes.recepciones(INICIO_MES, HOY)
        prov = d["por_proveedor"][0]
        self.assertEqual((prov["recepciones"], prov["lineas_rechazadas"], prov["valor"]), (2, 1, 5000))
        self.assertEqual(d["rechazos"][0]["motivo_rechazo"], "Empaque roto")

    def test_auxiliar_puede_ver_recepciones_y_vencimientos_pero_no_ventas(self):
        self.crear_usuario(self.c, "aux", "auxiliar")
        c = self.cliente()
        self.entrar(c, "aux")
        self.assertEqual(c.get("/reportes/recepciones").status_code, 200)
        self.assertEqual(c.get("/reportes/vencimientos").status_code, 200)
        self.assertIn(c.get("/reportes/ventas").status_code, (302, 403))
        menu = c.get("/reportes/").get_data(as_text=True)
        self.assertNotIn("/reportes/ventas", menu)
        self.assertIn("/reportes/recepciones", menu)


class TestVencimientos(BaseReportes):
    def test_pantalla_y_pdf(self):
        self.lote(1, "VIEJO", (HOY - timedelta(days=3)).isoformat(), 4)
        self.lote(1, "PRONTO", (HOY + timedelta(days=10)).isoformat(), 4)
        html = self.c.get("/reportes/vencimientos").get_data(as_text=True)
        self.assertIn("VIEJO", html)
        self.assertIn("PRONTO", html)
        r = self.c.get("/reportes/vencimientos/pdf")
        self.assertEqual(r.mimetype, "application/pdf")
        self.assertTrue(r.data.startswith(b"%PDF"))
        # La pantalla de Inventario sigue funcionando con la misma agrupación
        self.assertIn("VIEJO", self.c.get("/inventario/vencimientos").get_data(as_text=True))


class TestMenuReportes(BaseReportes):
    def test_todos_los_reportes_abren(self):
        for url in ("/reportes/", "/reportes/ventas", "/reportes/utilidades", "/reportes/top",
                    "/reportes/ventas-vs-compras", "/reportes/gastos", "/reportes/sugerido",
                    "/reportes/recepciones", "/reportes/vencimientos", "/reportes/temperaturas"):
            self.assertEqual(self.c.get(url).status_code, 200, url)
