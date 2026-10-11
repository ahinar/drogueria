"""
PRUEBAS DE QUEJAS (PQRS, app/pqrs.py), FARMACOVIGILANCIA (app/farmacovigilancia.py)
Y DE LOS FESTIVOS / DÍAS HÁBILES (app/festivos.py).
"""
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import BaseFase1

HOY = date.today()


class TestFestivos(BaseFase1):
    def test_festivos_2026(self):
        from app.festivos import festivos
        esperados = {(1, 1), (1, 12), (3, 23), (4, 2), (4, 3), (5, 1), (5, 18), (6, 8), (6, 15), (6, 29),
                     (7, 20), (8, 7), (8, 17), (10, 12), (11, 2), (11, 16), (12, 8), (12, 25)}
        self.assertEqual({(d.month, d.day) for d in festivos(2026)}, esperados)

    def test_dias_habiles(self):
        from app.festivos import dias_habiles_entre, sumar_dias_habiles
        # Viernes 9 oct 2026 + 15 hábiles: salta fines de semana, el 12 oct y el 2 nov -> martes 3 nov
        self.assertEqual(sumar_dias_habiles(date(2026, 10, 9), 15), date(2026, 11, 3))
        self.assertEqual(dias_habiles_entre(date(2026, 10, 9), date(2026, 11, 3)), 15)
        self.assertEqual(dias_habiles_entre(date(2026, 11, 3), date(2026, 10, 9)), -15)


class TestPqrs(BaseFase1):
    def registrar(self, c=None, **datos):
        base = {"tipo": "queja", "canal": "presencial", "fecha": HOY.isoformat(), "descripcion": "Me cobraron de más"}
        base.update(datos)
        return self.post(c or self.c, "/quejas/nueva", base)

    def test_registrar_calcula_numero_y_fecha_limite(self):
        from app.festivos import sumar_dias_habiles
        self.registrar()
        self.registrar(tipo="sugerencia")
        filas = self.db().execute("SELECT * FROM pqrs ORDER BY id").fetchall()
        self.assertEqual([f["numero"] for f in filas], ["PQ-0001", "PQ-0002"])
        self.assertEqual(filas[0]["fecha_limite"], sumar_dias_habiles(HOY, 15).isoformat())
        self.registrar(descripcion="")                          # sin descripción: no
        self.registrar(fecha=(HOY + timedelta(days=1)).isoformat())   # futura: no
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM pqrs")["n"], 2)

    def test_responder_cierra_y_reabrir(self):
        self.registrar()
        self.post(self.c, "/quejas/1/responder", {"respuesta": "", "fecha_respuesta": HOY.isoformat()})
        self.assertEqual(self.uno("SELECT estado FROM pqrs")["estado"], "abierta")
        self.post(self.c, "/quejas/1/responder", {"respuesta": "Se le devolvió la diferencia",
                                                  "accion_mejora": "Revisar precios en el POS",
                                                  "fecha_respuesta": HOY.isoformat(), "satisfecho": "si"})
        p = self.uno("SELECT * FROM pqrs")
        self.assertEqual((p["estado"], p["satisfecho"]), ("cerrada", "si"))
        self.post(self.c, "/quejas/1/reabrir")
        self.assertEqual(self.uno("SELECT estado FROM pqrs")["estado"], "abierta")

    def test_auxiliar_registra_pero_no_responde(self):
        self.crear_usuario(self.c, "aux1", "auxiliar")
        aux = self.cliente()
        self.entrar(aux, "aux1")
        self.registrar(aux)
        self.assertEqual(self.uno("SELECT usuario_nombre FROM pqrs")["usuario_nombre"], "Aux1")
        r = self.post(aux, "/quejas/1/responder", {"respuesta": "x", "fecha_respuesta": HOY.isoformat()})
        self.assertEqual(r.status_code, 403)

    def test_avisos_de_plazo(self):
        claves = lambda: re.findall(r'data-clave="([a-z_]+)"', self.c.get("/").get_data(as_text=True))
        self.registrar()
        self.assertNotIn("pqrs_vencidas", claves())
        con = self.db()
        con.execute("UPDATE pqrs SET fecha_limite = ?", ((HOY - timedelta(days=1)).isoformat(),))
        con.commit()
        con.close()
        self.assertIn("pqrs_vencidas", claves())

    def test_pantallas_y_pdf(self):
        self.registrar()
        for url in ("/quejas/", "/quejas/?filtro=todas", "/quejas/nueva", "/quejas/1"):
            self.assertEqual(self.c.get(url).status_code, 200, url)
        r = self.c.get("/quejas/1/pdf")
        self.assertTrue(r.data.startswith(b"%PDF"))


class TestFarmacovigilancia(BaseFase1):
    def registrar(self, c=None, **datos):
        base = {"tipo": "ram", "grave": "0", "fecha_conocimiento": HOY.isoformat(),
                "medicamento": "P00001 · Acetaminofén 500 mg", "lote": "l1",
                "descripcion": "Brote en la piel", "paciente_iniciales": "jpg"}
        base.update(datos)
        return self.post(c or self.c, "/farmacovigilancia/nuevo", base)

    def test_plazos(self):
        from app.farmacovigilancia import plazo_reporte
        self.assertEqual(plazo_reporte(date(2026, 10, 11), True), date(2026, 10, 14))     # 72 horas
        self.assertEqual(plazo_reporte(date(2026, 10, 11), False), date(2026, 11, 5))     # día 5 del mes siguiente
        self.assertEqual(plazo_reporte(date(2026, 12, 31), False), date(2027, 1, 5))

    def test_registrar_enlaza_el_producto(self):
        self.registrar()
        c = self.uno("SELECT * FROM farmacovigilancia")
        self.assertEqual((c["numero"], c["producto_id"], c["medicamento"], c["lote"], c["paciente_iniciales"]),
                         ("FV-0001", 1, "Acetaminofén 500 mg", "L1", "JPG"))
        self.registrar(medicamento="Un jarabe que no está en el programa")
        self.assertIsNone(self.uno("SELECT producto_id FROM farmacovigilancia WHERE id = 2")["producto_id"])
        self.registrar(descripcion="")                          # sin descripción: no
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM farmacovigilancia")["n"], 2)

    def test_marcar_reportado_y_avisos(self):
        claves = lambda: re.findall(r'data-clave="([a-z_]+)"', self.c.get("/").get_data(as_text=True))
        self.registrar(grave="1")
        self.assertIn("farmacovigilancia_graves", claves())
        self.post(self.c, "/farmacovigilancia/1/reportado", {"fecha_reporte": HOY.isoformat(), "medio_reporte": ""})
        self.assertEqual(self.uno("SELECT reportado FROM farmacovigilancia")["reportado"], 0)
        self.post(self.c, "/farmacovigilancia/1/reportado", {"fecha_reporte": HOY.isoformat(),
                                                             "medio_reporte": "eReporting INVIMA", "numero_reporte": "123"})
        c = self.uno("SELECT * FROM farmacovigilancia")
        self.assertEqual((c["reportado"], c["numero_reporte"]), (1, "123"))
        self.assertNotIn("farmacovigilancia_graves", claves())

    def test_auxiliar_registra_pero_no_reporta(self):
        self.crear_usuario(self.c, "aux1", "auxiliar")
        aux = self.cliente()
        self.entrar(aux, "aux1")
        self.registrar(aux)
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM farmacovigilancia")["n"], 1)
        self.assertEqual(self.post(aux, "/farmacovigilancia/1/reportado", {}).status_code, 403)
        self.assertEqual(aux.get("/farmacovigilancia/1/editar").status_code, 403)

    def test_pantallas_y_pdf(self):
        self.registrar()
        self.post(self.c, "/farmacovigilancia/1/editar", {"tipo": "calidad", "grave": "0",
                                                          "fecha_conocimiento": HOY.isoformat(),
                                                          "medicamento": "Acetaminofén 500 mg", "descripcion": "Tabletas partidas"})
        self.assertEqual(self.uno("SELECT tipo FROM farmacovigilancia")["tipo"], "calidad")
        for url in ("/farmacovigilancia/", "/farmacovigilancia/?filtro=pendientes", "/farmacovigilancia/nuevo",
                    "/farmacovigilancia/1", "/farmacovigilancia/1/editar"):
            self.assertEqual(self.c.get(url).status_code, 200, url)
        self.assertTrue(self.c.get("/farmacovigilancia/1/pdf").data.startswith(b"%PDF"))
