"""
PRUEBAS DE LA VERSIÓN 1.1.9
===========================
  - TestRecepcionAbierta: la recepción queda ABIERTA y se guarda sola (como el
    conteo de inventario) hasta que se le da «Confirmar recepción».
  - TestFotoArriba: el cuadro de la foto va arriba en «Nuevo producto» y «Completar datos».
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_version_118 import Base118


class TestRecepcionAbierta(Base118):
    def borrador(self, datos):
        return self.post(self.c, "/recepciones/api/borrador", datos).get_json()

    def test_pantalla_dice_confirmar_y_trae_clave(self):
        html = self.c.get("/recepciones/nueva").get_data(as_text=True)
        self.assertIn("Confirmar recepción", html)
        self.assertIn("Guardar y seguir después", html)
        self.assertNotIn("Guardar recepción", html)
        self.assertIn('name="borrador_token"', html)

    def test_guardado_automatico_crea_y_luego_actualiza_la_misma(self):
        datos = self.datos_recepcion([self.linea(1)])
        datos["borrador_token"] = "clave-1"
        j = self.borrador(datos)
        self.assertTrue(j["ok"])
        self.assertEqual(j["lineas"], 1)
        # Segundo guardado SIN el número (como si la respuesta del primero no hubiera llegado):
        # la clave de la pantalla hace que se actualice la misma, no que se cree otra
        datos = self.datos_recepcion([self.linea(1), self.linea(2)])
        datos["borrador_token"] = "clave-1"
        j2 = self.borrador(datos)
        self.assertEqual((j2["espera_id"], j2["lineas"]), (j["espera_id"], 2))
        self.assertEqual(self.contar("recepciones_espera"), 1)
        self.assertEqual(self.contar("recepciones"), 0)            # nada entra hasta confirmar

    def test_vacia_no_guarda(self):
        j = self.borrador({"borrador_token": "x", "linea_producto_id": [""]})
        self.assertTrue(j.get("vacia"))
        self.assertEqual(self.contar("recepciones_espera"), 0)

    def test_confirmar_cierra_la_abierta_y_no_se_repite(self):
        datos = self.datos_recepcion([self.linea(1)])
        datos["borrador_token"] = "clave-2"
        self.borrador(datos)
        # Confirmar sin espera_id (el guardado automático no alcanzó a avisar el número)
        r = self.post(self.c, "/recepciones/nueva", datos, follow_redirects=True)
        self.assertIn("CONFIRMADA", r.get_data(as_text=True))
        self.assertEqual((self.contar("recepciones"), self.contar("recepciones_espera")), (1, 0))
        # Un guardado automático que llega tarde no crea otra abierta
        self.assertTrue(self.borrador(datos).get("confirmada"))
        self.assertEqual(self.contar("recepciones_espera"), 0)
        # Darle Confirmar otra vez (doble clic / atrás) no crea una segunda recepción
        self.post(self.c, "/recepciones/nueva", datos)
        self.assertEqual(self.contar("recepciones"), 1)

    def test_continuar_recibiendo_le_pone_clave_a_las_viejas(self):
        datos = self.datos_recepcion([self.linea(1)])
        datos["accion"] = "espera"
        self.post(self.c, "/recepciones/nueva", datos)            # sin clave, como en la 1.1.8
        e = self.uno("SELECT id, token FROM recepciones_espera")
        self.assertIsNone(e["token"])
        html = self.c.get(f"/recepciones/nueva?espera={e['id']}").get_data(as_text=True)
        self.assertIn("continuar recibiendo", html)
        self.assertIsNotNone(self.uno("SELECT token FROM recepciones_espera")["token"])


class TestFotoArriba(Base118):
    def test_foto_va_arriba_en_las_dos_ventanas(self):
        html = self.c.get("/recepciones/nueva").get_data(as_text=True)
        self.assertEqual(html.count("modal-con-foto"), 2)
        # En «Nuevo producto» la foto va antes del laboratorio (arriba), no al final
        self.assertLess(html.index('id="np-foto"'), html.index('id="np-laboratorio"'))
