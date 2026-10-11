"""
PRUEBAS DE CAPACITACIONES (Fase 4.3, app/capacitaciones.py):
personal, plan sugerido, programar, registrar como realizada (asistentes y
notas), cancelar, permisos, aviso de atrasadas y PDFs.
"""
import io
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import BaseFase1

HOY = date.today()


class BaseCapacitaciones(BaseFase1):
    def tearDown(self):
        con = self.db()
        for f in con.execute("SELECT archivo FROM capacitaciones WHERE archivo IS NOT NULL"):
            (Path(self.app.static_folder) / f["archivo"]).unlink(missing_ok=True)
        con.close()
        super().tearDown()

    def persona(self, nombre="Ana Pérez", ocasional=False):
        datos = {"nombre": nombre, "cargo": "Auxiliar de droguería"}
        if ocasional:
            datos["ocasional"] = "1"
        return self.post(self.c, "/capacitaciones/personal", datos)

    def programar(self, tema="Recepción técnica", fecha=None, tipo="interna"):
        return self.post(self.c, "/capacitaciones/nueva", {"tema": tema, "tipo": tipo, "duracion_horas": "1",
                                                           "evaluacion": "1",
                                                           "fecha_programada": (fecha or HOY).isoformat()})

    def realizar(self, cap_id=1, **datos):
        base = {"fecha_realizada": HOY.isoformat(), "duracion_horas": "1,5", "personal_id": ["1"]}
        base.update(datos)
        return self.post(self.c, f"/capacitaciones/{cap_id}/realizar", base, content_type="multipart/form-data")

    def cap(self, cap_id=1):
        return self.uno("SELECT * FROM capacitaciones WHERE id = ?", cap_id)

    def n(self, sql):
        return self.uno(sql)["n"]


class TestCapacitaciones(BaseCapacitaciones):
    def test_plan_sugerido_12_temas_una_vez(self):
        self.post(self.c, "/capacitaciones/sugerido", {"anio": "2027"})
        self.assertEqual(self.n("SELECT COUNT(*) n FROM capacitaciones"), 12)
        meses = [f["fecha_programada"] for f in self.db().execute("SELECT fecha_programada FROM capacitaciones ORDER BY id")]
        self.assertEqual(meses[0], "2027-01-15")
        self.assertEqual(meses[-1], "2027-12-15")
        self.post(self.c, "/capacitaciones/sugerido", {"anio": "2027"})          # repetir no duplica
        self.assertEqual(self.n("SELECT COUNT(*) n FROM capacitaciones"), 12)
        # Si se borra un tema y se completa, vuelve a SU mes (marzo), no al primero
        con = self.db()
        con.execute("DELETE FROM capacitaciones WHERE tema LIKE 'Manejo de residuos%'")
        con.commit()
        con.close()
        self.post(self.c, "/capacitaciones/sugerido", {"anio": "2027"})
        residuos = self.uno("SELECT * FROM capacitaciones WHERE tema LIKE 'Manejo de residuos%'")
        self.assertEqual(residuos["fecha_programada"], "2027-03-15")
        self.assertEqual(residuos["estado"], "programada")

    def test_plan_del_anio_en_curso_no_queda_atrasado(self):
        from app.capacitaciones import fechas_del_plan
        # Año futuro: el 15 de cada mes
        self.assertEqual(fechas_del_plan(2030, range(1, 13), hoy=date(2026, 10, 11))[2], date(2030, 3, 15))
        # Año en curso, en octubre: todo entre el 18/10 y el 15/12, en orden
        f = fechas_del_plan(2026, range(1, 13), hoy=date(2026, 10, 11))
        self.assertEqual((f[0], f[-1]), (date(2026, 10, 18), date(2026, 12, 15)))
        self.assertEqual(f, sorted(f))
        # Año en curso, en enero (antes del 15): normal, uno por mes
        self.assertEqual(fechas_del_plan(2026, range(1, 13), hoy=date(2026, 1, 3))[0], date(2026, 1, 15))
        # Cargar el plan de este año no deja ninguna atrasada
        self.post(self.c, "/capacitaciones/sugerido", {"anio": str(HOY.year)})
        self.assertEqual(self.n(f"SELECT COUNT(*) n FROM capacitaciones WHERE fecha_programada < '{HOY.isoformat()}'"), 0)

    def test_programar_y_validar(self):
        self.programar()
        self.assertEqual(self.cap()["estado"], "programada")
        self.post(self.c, "/capacitaciones/nueva", {"tema": "", "fecha_programada": HOY.isoformat()})
        self.post(self.c, "/capacitaciones/nueva", {"tema": "X", "fecha_programada": ""})
        self.assertEqual(self.n("SELECT COUNT(*) n FROM capacitaciones"), 1)

    def test_realizar_con_asistentes_notas_y_acta(self):
        self.persona("Ana Pérez")
        self.persona("Luis Gómez", ocasional=True)
        self.programar()
        self.realizar(personal_id=["1", "2"], nota_1="4,5", nota_2="",
                      archivo=(io.BytesIO(b"%PDF-1.4 acta"), "acta.pdf"))
        c = self.cap()
        self.assertEqual((c["estado"], c["fecha_realizada"], c["duracion_horas"]), ("realizada", HOY.isoformat(), 1.5))
        self.assertTrue(c["archivo"].startswith("uploads/capacitaciones/"))
        notas = {f["personal_id"]: f["nota"] for f in self.db().execute("SELECT * FROM capacitacion_asistentes")}
        self.assertEqual(notas, {1: 4.5, 2: None})
        # Corregir la asistencia reemplaza la anterior (no duplica) y conserva el acta
        self.realizar(personal_id=["1"], nota_1="5")
        self.assertEqual(self.n("SELECT COUNT(*) n FROM capacitacion_asistentes"), 1)
        self.assertIsNotNone(self.cap()["archivo"])
        self.assertIsNotNone(self.uno("SELECT 1 FROM bitacora WHERE accion = 'capacitacion_realizada'"))

    def test_realizar_validaciones(self):
        self.persona()
        self.programar()
        self.realizar(personal_id=[])                                     # sin asistentes
        self.realizar(fecha_realizada=(HOY + timedelta(days=2)).isoformat())   # fecha futura
        self.realizar(duracion_horas="")                                  # sin horas
        self.realizar(nota_1="9")                                         # nota fuera de 0 a 5
        self.assertEqual(self.cap()["estado"], "programada")
        self.assertEqual(self.n("SELECT COUNT(*) n FROM capacitacion_asistentes"), 0)

    def test_cancelar_y_reprogramar(self):
        self.programar()
        self.post(self.c, "/capacitaciones/1/cancelar")
        self.assertEqual(self.cap()["estado"], "cancelada")
        self.persona()
        self.realizar()                                                   # cancelada: no se registra
        self.assertEqual(self.cap()["estado"], "cancelada")
        self.post(self.c, "/capacitaciones/1/cancelar")
        self.assertEqual(self.cap()["estado"], "programada")

    def test_aviso_de_atrasadas(self):
        claves = lambda: re.findall(r'data-clave="([a-z_]+)"', self.c.get("/").get_data(as_text=True))
        self.programar(fecha=HOY + timedelta(days=5))
        self.assertNotIn("capacitaciones_atrasadas", claves())
        self.programar(tema="Atrasada", fecha=HOY - timedelta(days=5))
        self.assertIn("capacitaciones_atrasadas", claves())

    def test_personal_editar_retirar_e_induccion(self):
        self.persona()
        self.post(self.c, "/capacitaciones/personal/1", {"nombre": "Ana María Pérez", "cargo": "Auxiliar"})
        self.assertEqual(self.uno("SELECT nombre FROM personal")["nombre"], "Ana María Pérez")
        self.programar(tema="Inducción de Ana", tipo="induccion")
        self.realizar()
        html = self.c.get("/capacitaciones/personal").get_data(as_text=True)
        self.assertIn("Hecha", html)                                      # ya tuvo inducción
        self.post(self.c, "/capacitaciones/personal/1", {"accion": "activar"})
        self.assertEqual(self.uno("SELECT activo FROM personal")["activo"], 0)

    def test_auxiliar_ve_pero_no_modifica(self):
        self.programar()
        self.crear_usuario(self.c, "aux1", "auxiliar")
        aux = self.cliente()
        self.entrar(aux, "aux1")
        self.assertEqual(aux.get("/capacitaciones/").status_code, 200)
        self.assertEqual(aux.get("/capacitaciones/1").status_code, 200)
        self.assertEqual(self.post(aux, "/capacitaciones/nueva", {"tema": "X"}).status_code, 403)
        self.assertEqual(self.post(aux, "/capacitaciones/personal", {"nombre": "X"}).status_code, 403)
        self.assertEqual(self.post(aux, "/capacitaciones/1/realizar").status_code, 403)

    def test_pantallas_y_pdfs(self):
        self.persona()
        self.post(self.c, "/capacitaciones/sugerido", {"anio": str(HOY.year)})
        self.realizar()
        for url in ("/capacitaciones/", f"/capacitaciones/?anio={HOY.year + 1}", "/capacitaciones/1",
                    "/capacitaciones/1/editar", "/capacitaciones/nueva", "/capacitaciones/personal",
                    "/capacitaciones/personal/1"):
            self.assertEqual(self.c.get(url).status_code, 200, url)
        for url in ("/capacitaciones/1/acta.pdf", "/capacitaciones/2/acta.pdf", "/capacitaciones/plan.pdf"):
            r = self.c.get(url)
            self.assertEqual(r.mimetype, "application/pdf", url)
            self.assertTrue(r.data.startswith(b"%PDF"))
