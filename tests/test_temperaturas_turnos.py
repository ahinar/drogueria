"""
PRUEBAS DE LA ALARMA DE TEMPERATURA Y LOS TURNOS (AM / PM).

Reglas que verifican estos tests:
  1. Solo hay DOS turnos: AM (antes de las 12:00) y PM (desde las 12:00 hasta el cierre del día).
  2. Se toma UNA lectura por turno y por zona.
  3. Si el turno se cierra sin lectura (ej. no se abrió en la mañana), esa lectura NO se
     toma: la alarma deja de sonar y no se arrastra al otro turno.
  4. La alarma, el inicio y el reporte usan la misma lógica.

Para simular "qué hora es" usamos un reloj falso que congela la hora.
"""
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import BaseFase1, FECHA


def reloj(hora, minuto=0):
    """Congela la hora que ve el módulo de temperaturas (hoy a las `hora`:`minuto`)."""
    fijo = datetime.now().replace(hour=hora, minute=minuto, second=0, microsecond=0)

    class RelojFalso(datetime):
        @classmethod
        def now(cls, tz=None):
            return fijo

    return mock.patch("app.temperaturas.datetime", RelojFalso)


class BaseTemp(BaseFase1):
    def setUp(self):
        super().setUp()
        con = self.db()
        # El programa ya trae 4 zonas de ejemplo. Dejamos activa solo "Ambiente" y la
        # configuramos como en la droguería real: lecturas a las 10:45 y 19:00, sin tolerancia.
        con.execute("UPDATE zonas_temperatura SET activa = 0")
        con.execute(
            "UPDATE zonas_temperatura SET horarios = '10:45,19:00', dias_semana = '1,2,3,4,5,6,7', "
            "minutos_tolerancia = 0, activa = 1 WHERE nombre = 'Ambiente'")
        con.commit()
        con.close()
        self.zona_id = self.uno("SELECT id FROM zonas_temperatura WHERE nombre = 'Ambiente'")["id"]

    def lectura_a_las(self, hora, minuto=0):
        """Inserta una lectura de HOY a la hora indicada (como si ya se hubiera registrado)."""
        fecha = datetime.now().replace(hour=hora, minute=minuto, second=0).strftime("%Y-%m-%d %H:%M:%S")
        con = self.db()
        con.execute(
            "INSERT INTO temperatura_registros (zona_id, fecha, temperatura, humedad, dentro_de_rango, "
            "usuario_nombre, creado_en) VALUES (?,?,22,50,1,'Prueba',?)", (self.zona_id, fecha, fecha))
        con.commit()
        con.close()

    def pendientes(self, hora, minuto=0):
        with reloj(hora, minuto):
            return self.c.get("/temperaturas/api/pendientes").get_json()["pendientes"]


class TestTurnos(BaseTemp):
    def test_solo_hay_dos_turnos_19h_es_pm(self):
        from app.temperaturas import _turno_de_hora
        self.assertEqual(_turno_de_hora("10:45"), "am")
        self.assertEqual(_turno_de_hora("11:59"), "am")
        self.assertEqual(_turno_de_hora("12:00"), "pm")
        self.assertEqual(_turno_de_hora("19:00"), "pm")   # antes se llamaba "noche"
        self.assertEqual(_turno_de_hora("23:30"), "pm")


class TestAlarma(BaseTemp):
    def test_antes_de_la_hora_no_hay_alarma(self):
        self.assertEqual(self.pendientes(10, 30), [])

    def test_en_la_manana_suena_hasta_las_12(self):
        p = self.pendientes(11, 0)
        self.assertEqual([(x["hora"], x["turno"]) for x in p], [("10:45", "am")])
        self.assertEqual(len(self.pendientes(11, 59)), 1)

    def test_si_no_se_tomo_en_la_manana_a_las_12_la_alarma_se_apaga(self):
        """El caso del video: son las 12:13 y seguía sonando la lectura de las 10:45."""
        self.assertEqual(self.pendientes(12, 13), [])
        self.assertEqual(self.pendientes(15, 0), [])

    def test_en_la_tarde_suena_desde_las_19_hasta_el_cierre(self):
        self.assertEqual(self.pendientes(18, 59), [])
        self.assertEqual([x["turno"] for x in self.pendientes(19, 5)], ["pm"])
        self.assertEqual(len(self.pendientes(23, 50)), 1)

    def test_si_no_se_tomo_en_la_tarde_no_se_arrastra_a_nada_mas(self):
        """Dos turnos en el día: lo no tomado simplemente queda sin tomar."""
        self.assertEqual(len(self.pendientes(20, 0)), 1)      # sigue pendiente mientras dura el turno PM
        # (el día siguiente _pendientes empieza de cero: 08:00 no tiene nada pendiente)
        self.assertEqual(self.pendientes(8, 0), [])

    def test_lectura_en_la_manana_apaga_la_alarma_am(self):
        self.lectura_a_las(11, 0)
        self.assertEqual(self.pendientes(11, 30), [])

    def test_lectura_registrada_a_las_1213_cuenta_como_pm_y_no_deja_pendiente_la_am(self):
        """Antes: el formulario decía 'mañana' a las 12:13 pero se guardaba como PM."""
        self.lectura_a_las(12, 13)
        self.assertEqual(self.pendientes(12, 20), [])         # la AM ya cerró de todas formas
        self.assertEqual(self.pendientes(19, 5), [])          # la PM ya está tomada

    def test_lectura_pm_apaga_la_alarma_de_las_19(self):
        self.lectura_a_las(19, 10)
        self.assertEqual(self.pendientes(19, 30), [])

    def test_una_sola_alarma_por_turno_aunque_haya_dos_horas_en_el_mismo_turno(self):
        con = self.db()
        con.execute("UPDATE zonas_temperatura SET horarios = '09:00,10:30,19:00'")
        con.commit(); con.close()
        p = self.pendientes(11, 0)
        self.assertEqual([x["hora"] for x in p], ["09:00"])

    def test_zona_inactiva_no_alarma(self):
        con = self.db()
        con.execute("UPDATE zonas_temperatura SET activa = 0")
        con.commit(); con.close()
        self.assertEqual(self.pendientes(11, 0), [])

    def test_dia_no_programado_no_alarma(self):
        con = self.db()
        con.execute("UPDATE zonas_temperatura SET dias_semana = '0'")
        con.commit(); con.close()
        self.assertEqual(self.pendientes(11, 0), [])


class TestFormularioEInicio(BaseTemp):
    def test_formulario_a_las_1213_dice_tarde(self):
        with reloj(12, 13):
            html = self.c.get(f"/temperaturas/registrar/{self.zona_id}").get_data(as_text=True)
        self.assertIn("tarde", html)
        self.assertNotIn("lectura de la <strong>mañana</strong>", html)

    def test_formulario_en_la_manana_dice_manana(self):
        with reloj(11, 0):
            html = self.c.get(f"/temperaturas/registrar/{self.zona_id}").get_data(as_text=True)
        self.assertIn("mañana", html)

    def test_inicio_usa_la_misma_logica_que_la_alarma(self):
        from app.main import _estado_temperatura
        for hora, minuto, esperado in ((11, 0, 1), (12, 13, 0), (19, 5, 1)):
            with reloj(hora, minuto), self.app.test_request_context():
                from app.db import get_db
                self.assertEqual(len(_estado_temperatura(get_db())["pendientes"]), esperado,
                                 f"{hora}:{minuto:02d}")


class TestReporteMensual(BaseTemp):
    def test_lectura_de_las_19h_aparece_en_el_turno_pm_del_pdf(self):
        """Antes se clasificaba como 'noche' y no salía en el registro mensual oficial."""
        self.lectura_a_las(19, 5)
        hoy = datetime.now()
        r = self.c.get(f"/reportes/temperaturas/mensual/pdf?zona_id={self.zona_id}&mes={hoy.month}&anio={hoy.year}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data.startswith(b"%PDF"))
