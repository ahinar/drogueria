"""
PRUEBAS DE R2 · UTILIDADES / ESTADO DE RESULTADOS.

Montaje: producto 1 a $1.000 (sin IVA) y producto 2 a $11.900 (IVA 19 %).
Los lotes de prueba cuestan $100 la unidad (ver BaseVentas.lote).
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import FECHA
from test_fase2_ventas import BaseVentas, FUTURO

HOY = date.today()


class BaseUtilidades(BaseVentas):
    def gasto(self, categoria, monto, fecha=None, descripcion="Gasto de prueba"):
        con = self.db()
        cat = con.execute("SELECT id FROM catalogos WHERE tipo='categoria_gasto' AND nombre=?",
                          (categoria,)).fetchone()[0]
        con.execute("INSERT INTO gastos (fecha, categoria_id, descripcion, monto, creado_en) "
                    "VALUES (?,?,?,?,?)", (fecha or HOY.isoformat(), cat, descripcion, monto, FECHA))
        con.commit(); con.close()

    def estado(self, **params):
        """Calcula el estado de resultados dentro de la app (como lo hace la pantalla)."""
        from app import utilidades
        with self.app.test_request_context():
            from app.db import get_db  # noqa: F401  (usa la base de pruebas)
            return utilidades.estado_de_resultados(**params)


class TestPeriodos(BaseUtilidades):
    def per(self, **kw):
        from app.utilidades import periodos
        return periodos(**kw)

    def test_mes_en_curso_se_compara_con_los_mismos_dias(self):
        p = self.per(hoy=date(2026, 10, 9))
        self.assertEqual((p["actual"]["desde"], p["actual"]["hasta"]), (date(2026, 10, 1), date(2026, 10, 9)))
        self.assertEqual((p["anterior"]["desde"], p["anterior"]["hasta"]), (date(2026, 9, 1), date(2026, 9, 9)))
        self.assertEqual(p["actual"]["texto"], "1 al 9 de octubre de 2026")

    def test_mes_cerrado_se_compara_con_el_mes_anterior_completo(self):
        p = self.per(mes="2026-09", hoy=date(2026, 10, 9))
        self.assertEqual(p["actual"]["hasta"], date(2026, 9, 30))
        self.assertEqual((p["anterior"]["desde"], p["anterior"]["hasta"]), (date(2026, 8, 1), date(2026, 8, 31)))
        self.assertEqual(p["actual"]["texto"], "septiembre de 2026")

    def test_31_de_marzo_compara_con_febrero_completo(self):
        p = self.per(hoy=date(2027, 3, 31))
        self.assertEqual(p["anterior"]["hasta"], date(2027, 2, 28))

    def test_rango_libre_compara_con_el_rango_anterior_de_igual_duracion(self):
        p = self.per(desde="2026-10-05", hasta="2026-10-11", hoy=date(2026, 10, 20))
        self.assertEqual(p["modo"], "rango")
        self.assertEqual((p["anterior"]["desde"], p["anterior"]["hasta"]), (date(2026, 9, 28), date(2026, 10, 4)))

    def test_mes_invalido_usa_el_actual(self):
        p = self.per(mes="hola", hoy=date(2026, 10, 9))
        self.assertEqual(p["actual"]["desde"], date(2026, 10, 1))


class TestCalculo(BaseUtilidades):
    def test_ventas_costo_y_utilidad_bruta(self):
        self.lote(1, "L1", FUTURO, 100)          # costo $100 c/u
        self.lote(2, "L2", FUTURO, 10)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 3}])        # $3.000, costo $300
        self.cobrar([{"producto_id": 2, "cantidad": 1}])        # $11.900 con IVA = $10.000 sin IVA, costo $100
        a = self.estado()["actual"]
        self.assertEqual(a["ventas"], 13000)
        self.assertEqual(a["iva"], 1900)
        self.assertEqual(a["costo"], 400)
        self.assertEqual(a["utilidad_bruta"], 12600)
        self.assertEqual(a["n_ventas"], 2)

    def test_venta_anulada_no_cuenta(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 3}])
        self.post(self.c, "/pos/venta/1/anular", {"motivo": "Error"})
        a = self.estado()["actual"]
        self.assertEqual((a["ventas"], a["costo"], a["n_ventas"]), (0, 0, 0))

    def test_costo_es_el_real_de_cada_lote(self):
        con = self.db()
        con.execute("INSERT INTO lotes (producto_id, lote, vencimiento, cantidad_inicial, cantidad_disponible, "
                    "costo_unitario, estado, creado_en) VALUES (1,'BARATO',?,2,2,50,'disponible',?)",
                    ((HOY + timedelta(days=30)).isoformat(), FECHA))
        con.commit(); con.close()
        self.lote(1, "CARO", FUTURO, 10)                        # $100
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 3}])        # 2 x $50 (vence antes) + 1 x $100
        self.assertEqual(self.estado()["actual"]["costo"], 200)

    def test_gastos_por_categoria_y_utilidad_neta(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 10}])       # ventas 10.000, costo 1.000
        self.gasto("Arriendo", 3000)
        self.gasto("Sueldo del dueño", 2000)
        self.gasto("Arriendo", 500)
        a = self.estado()["actual"]
        self.assertEqual(a["total_gastos"], 5500)
        self.assertEqual([(c["categoria"], c["total"]) for c in a["gastos"]],
                         [("Arriendo", 3500), ("Sueldo del dueño", 2000)])
        self.assertEqual(a["utilidad_neta"], 10000 - 1000 - 5500)

    def test_gasto_anulado_no_cuenta(self):
        self.gasto("Arriendo", 3000)
        con = self.db(); con.execute("UPDATE gastos SET activo = 0"); con.commit(); con.close()
        self.assertEqual(self.estado()["actual"]["total_gastos"], 0)

    def test_perdidas_por_baja_y_no_cuentan_sobrantes(self):
        self.lote(1, "L1", FUTURO, 100)
        self.post(self.c, "/inventario/lotes/1/ajustar", {"cantidad": "90", "motivo": "Vencidos"})   # -10
        self.post(self.c, "/inventario/lotes/1/ajustar", {"cantidad": "95", "motivo": "Apareció"})   # +5
        a = self.estado()["actual"]
        self.assertEqual(a["bajas"], 1000)            # 10 x $100
        self.assertEqual(a["total_perdidas"], 1000)   # el sobrante no resta ni suma
        self.assertEqual(a["utilidad_neta"], -1000)

    def test_faltantes_del_conteo_van_aparte(self):
        self.lote(1, "L1", FUTURO, 20)
        self.post(self.c, "/inventario/conteos/nuevo", {})
        lote_id = self.uno("SELECT id FROM lotes")["id"]
        self.post(self.c, "/inventario/conteos/1/api/contar", {"lote_id": lote_id, "cantidad": "17"})
        self.post(self.c, "/inventario/conteos/1/aplicar", {})
        a = self.estado()["actual"]
        self.assertEqual(a["faltantes_conteo"], 300)  # 3 x $100
        self.assertEqual(a["bajas"], 0)

    def test_retiro_del_dueno_es_informativo(self):
        self.post(self.c, "/caja-menor/aporte", {"monto": "50000", "motivo": "Fondo"})
        self.post(self.c, "/caja-menor/retiro", {"monto": "10000", "motivo": "Mi ganancia", "retiro_dueno": "1"})
        self.post(self.c, "/caja-menor/retiro", {"monto": "7000", "motivo": "Consignación"})   # no es del dueño
        a = self.estado()["actual"]
        self.assertEqual(a["retiros_dueno"], 10000)
        self.assertEqual(a["utilidad_neta"], 0)       # el retiro NO es gasto
        self.assertEqual(a["queda"], -10000)

    def test_avisa_ventas_de_lotes_sin_costo(self):
        con = self.db()
        con.execute("INSERT INTO lotes (producto_id, lote, vencimiento, cantidad_inicial, cantidad_disponible, "
                    "costo_unitario, estado, creado_en) VALUES (1,'GRATIS',?,5,5,0,'disponible',?)", (FUTURO, FECHA))
        con.commit(); con.close()
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 1}])
        self.assertEqual(self.estado()["actual"]["lineas_sin_costo"], 1)

    def test_comparacion_con_el_periodo_anterior(self):
        self.gasto("Arriendo", 1000, fecha=(HOY.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat())
        self.gasto("Arriendo", 1500)
        r = self.estado()
        fila = [f for f in r["filas_gastos"] if f["categoria"] == "Arriendo"][0]
        self.assertEqual((fila["actual"], fila["anterior"]), (1500, 1000))
        from app.utilidades import variacion
        self.assertEqual(variacion(1500, 1000), 50)
        self.assertIsNone(variacion(1500, 0))


class TestPantalla(BaseUtilidades):
    def test_pantalla_y_pdf(self):
        self.lote(1, "L1", FUTURO, 100)
        self.abrir_caja()
        self.cobrar([{"producto_id": 1, "cantidad": 2}])
        self.gasto("Arriendo", 800, descripcion="Arriendo octubre")
        html = self.c.get("/reportes/utilidades").get_data(as_text=True)
        self.assertIn("Utilidad neta", html)
        self.assertIn("Arriendo octubre", html)          # detalle del gasto
        self.assertIn("$2.000", html)
        r = self.c.get("/reportes/utilidades/pdf")
        self.assertEqual(r.mimetype, "application/pdf")
        self.assertTrue(r.data.startswith(b"%PDF"))
        self.assertEqual(self.c.get("/reportes/utilidades?mes=2026-01").status_code, 200)
        self.assertEqual(self.c.get("/reportes/utilidades?desde=2026-01-01&hasta=2026-01-31").status_code, 200)

    def test_auxiliar_no_entra(self):
        self.crear_usuario(self.c, "aux", "auxiliar")
        c = self.cliente()
        self.entrar(c, "aux")
        self.assertNotEqual(self.c.get("/reportes/utilidades").status_code, 403)
        self.assertIn(c.get("/reportes/utilidades").status_code, (302, 403))
        self.assertNotIn("reportes/utilidades", c.get("/reportes/").get_data(as_text=True))

    def test_existe_la_categoria_sueldo_del_dueno(self):
        self.assertIsNotNone(self.uno("SELECT 1 FROM catalogos WHERE tipo='categoria_gasto' "
                                      "AND nombre='Sueldo del dueño'"))
