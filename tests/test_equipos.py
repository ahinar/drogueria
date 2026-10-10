"""
PRUEBAS DE EQUIPOS Y CALIBRACIONES.
"""
import io
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import BaseFase1

HOY = date.today()
dias = lambda n: (HOY + timedelta(days=n)).isoformat()


class BaseEquipos(BaseFase1):
    def crear(self, nombre="Termohigrómetro bodega", tipo="termohigrometro", zona_id="", frecuencia="12"):
        return self.post(self.c, "/equipos/nuevo", {"nombre": nombre, "tipo": tipo, "zona_id": zona_id,
                                                    "frecuencia_meses": frecuencia})

    def calibrar(self, equipo_id=1, **datos):
        base = {"fecha": HOY.isoformat(), "empresa": "Metrología SAS", "certificado_numero": "C-123"}
        base.update(datos)
        return self.post(self.c, f"/equipos/{equipo_id}/calibrar", base, content_type="multipart/form-data")

    def equipo(self, equipo_id=1):
        return self.uno("SELECT * FROM equipos WHERE id = ?", equipo_id)

    def claves_inicio(self):
        return re.findall(r'data-clave="([a-z_]+)"', self.c.get("/").get_data(as_text=True))


class TestEquipos(BaseEquipos):
    def test_crear_y_validar(self):
        self.crear()
        self.assertEqual(self.equipo()["nombre"], "Termohigrómetro bodega")
        self.crear(nombre="")                          # sin nombre
        self.crear(nombre="X", tipo="cohete")          # tipo inválido
        self.crear(nombre="Y", frecuencia="0")         # frecuencia inválida
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM equipos")["n"], 1)

    def test_tipos_nuevos_aceptados_por_la_base(self):
        """La migración 22 amplió los tipos (antes solo 3)."""
        self.crear(nombre="Balanza", tipo="balanza")
        self.assertEqual(self.equipo()["tipo"], "balanza")

    def test_calibrar_calcula_la_proxima_con_la_frecuencia(self):
        self.crear(frecuencia="6")
        self.calibrar(fecha="2026-01-31")
        e = self.equipo()
        self.assertEqual((e["fecha_calibracion"], e["proxima_calibracion"]), ("2026-01-31", "2026-07-31"))
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM calibraciones")["n"], 1)
        self.assertIsNotNone(self.uno("SELECT 1 FROM bitacora WHERE accion = 'equipo_calibrado'"))

    def test_sumar_meses_fin_de_mes(self):
        from app.equipos import sumar_meses
        self.assertEqual(sumar_meses(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(sumar_meses(date(2027, 11, 15), 3), date(2028, 2, 15))

    def test_validaciones_de_calibracion(self):
        self.crear()
        self.calibrar(fecha=dias(5))                                   # futura
        self.calibrar(fecha=HOY.isoformat(), proxima=dias(-1))        # próxima antes de la fecha
        self.calibrar(fecha="")                                        # sin fecha
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM calibraciones")["n"], 0)

    def test_una_calibracion_vieja_no_pisa_la_mas_reciente(self):
        self.crear()
        self.calibrar(fecha=HOY.isoformat(), proxima=dias(365))
        self.calibrar(fecha=dias(-400), proxima=dias(-35))
        self.assertEqual(self.equipo()["proxima_calibracion"], dias(365))

    def test_certificado_pdf_y_archivo_falso(self):
        self.crear()
        r = self.calibrar(certificado=(io.BytesIO(b"%PDF-1.4 prueba"), "cert.pdf"))
        archivo = self.uno("SELECT archivo FROM calibraciones")["archivo"]
        self.assertTrue(archivo.startswith("uploads/certificados/") and archivo.endswith(".pdf"))
        ruta = Path(self.app.static_folder) / archivo
        self.assertTrue(ruta.exists())
        ruta.unlink()                                     # no dejar basura de las pruebas
        # Un "PDF" que no es PDF se rechaza y no se guarda la calibración
        self.calibrar(certificado=(io.BytesIO(b"MZ esto no es pdf"), "virus.pdf"))
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM calibraciones")["n"], 1)

    def test_lecturas_de_temperatura_quedan_ligadas_al_equipo(self):
        zona = self.uno("SELECT id FROM zonas_temperatura WHERE nombre = 'Ambiente'")["id"]
        self.crear(zona_id=str(zona))
        self.post(self.c, f"/temperaturas/registrar/{zona}", {"temperatura": "22", "humedad": "55"})
        fila = self.uno("SELECT equipo_id FROM temperatura_registros ORDER BY id DESC")
        self.assertIsNotNone(fila, "no se guardó la lectura")
        self.assertEqual(fila["equipo_id"], 1)

    def test_dar_de_baja(self):
        self.crear()
        self.post(self.c, "/equipos/1/activar", {})
        self.assertEqual(self.equipo()["activo"], 0)

    def test_pantallas(self):
        self.crear()
        self.calibrar()
        self.assertIn("Metrología SAS", self.c.get("/equipos/1").get_data(as_text=True))
        lista = self.c.get("/equipos/").get_data(as_text=True)
        self.assertIn("Al día", lista)
        self.assertIn("Zonas de temperatura sin equipo", lista)
        self.assertEqual(self.c.get("/equipos/99").status_code, 404)

    def test_auxiliar_ve_pero_no_edita(self):
        self.crear()
        self.crear_usuario(self.c, "aux", "auxiliar")
        c = self.cliente()
        self.entrar(c, "aux")
        self.assertEqual(c.get("/equipos/").status_code, 200)
        self.assertNotIn("Registrar calibración", c.get("/equipos/1").get_data(as_text=True))
        self.assertIn(self.post(c, "/equipos/1/calibrar", {"fecha": HOY.isoformat()}).status_code, (302, 403))
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM calibraciones")["n"], 0)


class TestAlertasDeCalibracion(BaseEquipos):
    def test_sin_calibracion_por_vencer_y_vencida(self):
        self.crear()
        self.assertIn("calibracion_por_vencer", self.claves_inicio())      # sin calibración
        self.calibrar(fecha=dias(-300), proxima=dias(10))
        self.assertIn("calibracion_por_vencer", self.claves_inicio())      # vence en 10 días
        self.calibrar(fecha=dias(-200), proxima=dias(-1))
        # La más reciente sigue siendo la de hace 200 días (vencida ayer)
        self.assertIn("calibracion_vencida", self.claves_inicio())

    def test_no_conforme_es_roja_aunque_la_fecha_este_vigente(self):
        self.crear()
        self.calibrar(resultado="no_conforme")
        self.assertIn("calibracion_vencida", self.claves_inicio())
        self.assertIn("No conforme", self.c.get("/equipos/").get_data(as_text=True))

    def test_al_dia_no_alerta_y_dado_de_baja_tampoco(self):
        self.crear()
        self.calibrar()
        self.assertNotIn("calibracion_vencida", self.claves_inicio())
        self.assertNotIn("calibracion_por_vencer", self.claves_inicio())
        self.crear(nombre="Viejo")
        self.post(self.c, "/equipos/2/activar", {})
        self.assertNotIn("calibracion_por_vencer", self.claves_inicio())
