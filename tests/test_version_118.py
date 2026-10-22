"""
PRUEBAS DE LA VERSIÓN 1.1.8
===========================
  - TestFotosJfif: las fotos ".jfif" (fotos JPG con otro nombre) ya se aceptan.
  - TestPdfRecepcion: el Acta de recepción en PDF trae al menos 20 productos por hoja.
  - TestRecepcionEnEspera: guardar una recepción a medias y terminarla otro día.
  - TestFotoDesdeRecepcion: poner, cambiar y quitar la foto del producto desde la recepción.
  - TestCamposYConteo: el 0 que desaparece al dar clic y el conteo de efectivo que no se borra.

Se corren con:   python -m pytest tests/test_version_118.py -q
"""
import io
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import BaseFase1

RAIZ = Path(__file__).resolve().parent.parent


def foto_jpg():
    """Una foto JPG chiquita hecha en memoria (como si fuera un archivo del computador)."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(buf, "JPEG")
    buf.seek(0)
    return buf


class Base118(BaseFase1):
    def setUp(self):
        super().setUp()
        # Las fotos de las pruebas van a una carpeta temporal (no a static/uploads del proyecto)
        self.uploads = os.path.join(self.tmp, "uploads")
        self.app.config["UPLOADS_DIR"] = self.uploads

    def linea(self, n, producto=1):
        return {"producto_id": producto, "lote": f"LOTE-{n:02d}", "vencimiento": "2028-05-01",
                "cantidad_recibida": 10, "costo": 300}

    def datos_recepcion(self, lineas, factura="F-200"):
        datos = {"proveedor_id": "1", "factura_numero": factura}
        for campo in ("producto_id", "lote", "vencimiento", "cantidad_recibida", "costo"):
            datos["linea_" + campo] = [str(l[campo]) for l in lineas]
        datos["linea_presentacion"] = ["0"] * len(lineas)
        datos["linea_iva"] = ["0"] * len(lineas)
        datos["linea_resultado"] = ["aceptado"] * len(lineas)
        return datos

    def contar(self, tabla):
        return self.uno(f"SELECT COUNT(*) n FROM {tabla}")["n"]


class TestFotosJfif(Base118):
    def test_guardar_imagen_acepta_jfif_y_la_deja_en_jpg(self):
        from werkzeug.datastructures import FileStorage
        from app.utils_imagenes import guardar_imagen
        with self.app.app_context():
            archivo = FileStorage(stream=foto_jpg(), filename="foto del producto.jfif")
            ruta, error = guardar_imagen(archivo, "productos")
        self.assertIsNone(error)
        self.assertTrue(ruta.endswith(".jpg"), ruta)
        self.assertTrue(os.path.exists(os.path.join(self.uploads, "productos", os.path.basename(ruta))))

    def test_otro_formato_sigue_saliendo_el_aviso(self):
        from werkzeug.datastructures import FileStorage
        from app.utils_imagenes import guardar_imagen
        with self.app.app_context():
            _, error = guardar_imagen(FileStorage(stream=io.BytesIO(b"x"), filename="a.exe"), "productos")
        self.assertIn("Formato no soportado", error)

    def test_selectores_de_archivo_ofrecen_jfif(self):
        for plantilla in ("productos/form.html", "pos/_modal_editar_producto.html", "recepciones/form.html"):
            self.assertIn(".jfif", (RAIZ / "app" / "templates" / plantilla).read_text(encoding="utf-8"), plantilla)


class TestPdfRecepcion(Base118):
    def test_al_menos_20_productos_por_hoja(self):
        # 45 productos con nombres largos y laboratorio: el caso más apretado
        con = self.db()
        con.execute("INSERT INTO catalogos (tipo, nombre, activo, creado_en) "
                    "VALUES ('laboratorio', 'Laboratorios Genfar S.A.', 1, '2026-10-01')")
        lab = con.execute("SELECT id FROM catalogos WHERE tipo = 'laboratorio'").fetchone()[0]
        con.execute("UPDATE productos SET nombre = 'Acetaminofén tabletas recubiertas', "
                    "concentracion = '500 mg', laboratorio_id = ?, registro_sanitario = 'INVIMA 2019M-0012345' "
                    "WHERE id = 1", (lab,))
        con.commit()
        con.close()
        self.post(self.c, "/recepciones/nueva", self.datos_recepcion([self.linea(n) for n in range(1, 46)]))
        rec = self.uno("SELECT id FROM recepciones")
        self.assertIsNotNone(rec)
        r = self.c.get(f"/recepciones/{rec['id']}/pdf")
        self.assertEqual(r.status_code, 200)

        from pypdf import PdfReader
        hojas = PdfReader(io.BytesIO(r.data)).pages
        por_hoja = [len(re.findall(r"LOTE-\d\d", h.extract_text())) for h in hojas]
        self.assertEqual(sum(por_hoja), 45, por_hoja)
        # Todas las hojas que no son la última traen al menos 20 productos (también la primera)
        for n in por_hoja[:-1]:
            self.assertGreaterEqual(n, 20, por_hoja)
        self.assertGreaterEqual(por_hoja[0], 20, por_hoja)


class TestRecepcionEnEspera(Base118):
    def guardar_en_espera(self, lineas, **extra):
        datos = self.datos_recepcion(lineas)
        datos["accion"] = "espera"
        datos.update(extra)
        return self.post(self.c, "/recepciones/nueva", datos)

    def test_en_espera_no_crea_recepcion_ni_toca_inventario(self):
        r = self.guardar_en_espera([self.linea(1), self.linea(2)])
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.contar("recepciones"), 0)
        self.assertEqual(self.contar("lotes"), 0)
        e = self.uno("SELECT * FROM recepciones_espera")
        self.assertEqual((e["total_lineas"], e["factura_numero"], e["proveedor_id"]), (2, "F-200", 1))
        self.assertIn("LOTE-02", e["datos"])
        self.assertNotIn("_csrf", e["datos"])          # la clave de seguridad no se guarda

    def test_en_espera_guarda_aunque_falten_datos(self):
        # Una línea a medias (sin costo ni lote): igual se guarda, sin revisar nada
        lineas = [{"producto_id": 1, "lote": "", "vencimiento": "", "cantidad_recibida": "", "costo": ""}]
        self.guardar_en_espera(lineas)
        self.assertEqual(self.contar("recepciones_espera"), 1)

    def test_en_espera_vacia_no_guarda(self):
        r = self.post(self.c, "/recepciones/nueva", {"accion": "espera", "linea_producto_id": [""]},
                      follow_redirects=True)
        self.assertEqual(self.contar("recepciones_espera"), 0)
        self.assertIn("No hay nada escrito", r.get_data(as_text=True))

    def test_lista_muestra_en_espera_y_continuar_repinta_todo(self):
        self.guardar_en_espera([self.linea(1), self.linea(2)], observaciones="faltan 30 líneas")
        e = self.uno("SELECT id FROM recepciones_espera")
        html = self.c.get("/recepciones/").get_data(as_text=True)
        self.assertIn("En espera", html)
        self.assertIn(f"/recepciones/nueva?espera={e['id']}", html)
        html = self.c.get(f"/recepciones/nueva?espera={e['id']}").get_data(as_text=True)
        for texto in ("LOTE-01", "LOTE-02", "faltan 30 líneas", 'value="F-200"',
                      f'name="espera_id" value="{e["id"]}"', "Continuando una recepción"):
            self.assertIn(texto, html)

    def test_seguir_en_espera_actualiza_la_misma(self):
        self.guardar_en_espera([self.linea(1)])
        e = self.uno("SELECT id FROM recepciones_espera")
        self.guardar_en_espera([self.linea(1), self.linea(2), self.linea(3)], espera_id=str(e["id"]))
        self.assertEqual(self.contar("recepciones_espera"), 1)
        self.assertEqual(self.uno("SELECT total_lineas n FROM recepciones_espera")["n"], 3)

    def test_terminar_crea_la_recepcion_y_borra_la_espera(self):
        self.guardar_en_espera([self.linea(1)])
        e = self.uno("SELECT id FROM recepciones_espera")
        datos = self.datos_recepcion([self.linea(1), self.linea(2)])
        datos["espera_id"] = str(e["id"])
        r = self.post(self.c, "/recepciones/nueva", datos)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.contar("recepciones"), 1)
        self.assertEqual(self.contar("recepcion_lineas"), 2)
        self.assertEqual(self.contar("recepciones_espera"), 0)
        self.assertEqual(self.uno("SELECT estado FROM recepciones")["estado"], "cuarentena")

    def test_si_al_terminar_hay_error_la_espera_no_se_pierde(self):
        self.guardar_en_espera([self.linea(1)])
        e = self.uno("SELECT id FROM recepciones_espera")
        malo = self.linea(1)
        malo["costo"] = "0"                                  # costo en 0: no deja guardar
        datos = self.datos_recepcion([malo])
        datos["espera_id"] = str(e["id"])
        html = self.post(self.c, "/recepciones/nueva", datos).get_data(as_text=True)
        self.assertEqual(self.contar("recepciones"), 0)
        self.assertEqual(self.contar("recepciones_espera"), 1)
        self.assertIn(f'name="espera_id" value="{e["id"]}"', html)   # sigue siendo la misma espera

    def test_numero_ocupado_mientras_estaba_en_espera(self):
        self.guardar_en_espera([self.linea(1)], numero="REC-0001")
        self.post(self.c, "/recepciones/nueva", self.datos_recepcion([self.linea(5)], factura="OTRA"))
        e = self.uno("SELECT id FROM recepciones_espera")
        html = self.c.get(f"/recepciones/nueva?espera={e['id']}").get_data(as_text=True)
        self.assertIn('value="REC-0002"', html)              # REC-0001 ya lo tiene la otra

    def test_descartar(self):
        self.guardar_en_espera([self.linea(1)])
        e = self.uno("SELECT id FROM recepciones_espera")
        self.post(self.c, f"/recepciones/espera/{e['id']}/descartar")
        self.assertEqual(self.contar("recepciones_espera"), 0)
        r = self.c.get(f"/recepciones/nueva?espera={e['id']}")
        self.assertEqual(r.status_code, 302)                 # ya no existe: vuelve a la lista

    def test_alerta_en_inicio(self):
        self.guardar_en_espera([self.linea(1)])
        from app.alertas import calcular_alertas
        with self.app.test_request_context():
            claves = [a["clave"] for a in calcular_alertas("administrador")]
        self.assertIn("recepciones_espera", claves)

    def test_boton_guardar_en_espera_no_exige_campos(self):
        html = self.c.get("/recepciones/nueva").get_data(as_text=True)
        boton = re.search(r'<button[^>]*value="espera"[^>]*>', html).group(0)
        self.assertIn("formnovalidate", boton)


class TestFotoDesdeRecepcion(Base118):
    def test_nuevo_producto_con_foto_jfif(self):
        r = self.post(self.c, "/recepciones/api/crear-producto",
                      {"nombre": "Ibuprofeno", "unidad_venta_id": "1",
                       "imagen": (foto_jpg(), "ibuprofeno.jfif")},
                      content_type="multipart/form-data")
        j = r.get_json()
        self.assertTrue(j["ok"], j)
        self.assertIsNone(j["aviso"])
        imagen = self.uno("SELECT imagen FROM productos WHERE id = ?", j["id"])["imagen"]
        self.assertTrue(imagen.startswith("uploads/productos/") and imagen.endswith(".jpg"), imagen)

    def test_foto_mala_no_impide_crear_el_producto(self):
        r = self.post(self.c, "/recepciones/api/crear-producto",
                      {"nombre": "Gasa", "unidad_venta_id": "1",
                       "imagen": (io.BytesIO(b"no soy una foto"), "gasa.jpg")},
                      content_type="multipart/form-data")
        j = r.get_json()
        self.assertTrue(j["ok"])
        self.assertIn("la foto no", j["aviso"])
        self.assertIsNone(self.uno("SELECT imagen FROM productos WHERE id = ?", j["id"])["imagen"])

    def test_completar_datos_pone_cambia_y_quita_la_foto(self):
        url = "/recepciones/api/producto/1/tecnicos"
        self.assertEqual(self.c.get(url).get_json()["producto"]["imagen_url"], "")
        self.post(self.c, url, {"imagen": (foto_jpg(), "a.jpg")}, content_type="multipart/form-data")
        primera = self.uno("SELECT imagen FROM productos WHERE id = 1")["imagen"]
        self.assertTrue(primera)
        self.assertIn(primera, self.c.get(url).get_json()["producto"]["imagen_url"])
        # Cambiar: la foto vieja se borra del disco
        self.post(self.c, url, {"imagen": (foto_jpg(), "b.jfif")}, content_type="multipart/form-data")
        segunda = self.uno("SELECT imagen FROM productos WHERE id = 1")["imagen"]
        self.assertNotEqual(primera, segunda)
        self.assertFalse(os.path.exists(os.path.join(self.uploads, "productos", os.path.basename(primera))))
        # Quitar
        self.post(self.c, url, {"imagen_accion": "eliminar"})
        self.assertIsNone(self.uno("SELECT imagen FROM productos WHERE id = 1")["imagen"])

    def test_ventanas_tienen_el_cuadro_de_foto(self):
        html = self.c.get("/recepciones/nueva").get_data(as_text=True)
        self.assertIn('id="np-foto"', html)
        self.assertIn('id="dt-foto"', html)


class TestCamposYConteo(Base118):
    def test_el_cero_desaparece_al_dar_clic(self):
        ui = (RAIZ / "static" / "js" / "ui.js").read_text(encoding="utf-8")
        self.assertIn("EL 0 DESAPARECE AL DAR CLIC", ui)
        self.assertIn("campo-num-activo", ui)
        css = (RAIZ / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn("input.campo-num-activo:focus", css)

    def test_el_conteo_de_efectivo_ya_no_se_pone_en_cero_al_abrir(self):
        pos = (RAIZ / "static" / "js" / "pos.js").read_text(encoding="utf-8")
        apertura = (RAIZ / "app" / "templates" / "pos" / "abrir_caja.html").read_text(encoding="utf-8")
        for codigo in (pos, apertura):
            self.assertNotIn(".conteo-input').forEach(i => i.value = 0)", codigo)
        self.assertIn("conteoEfectivo.usar(claveCierre)", pos)
        self.assertIn("conteoEfectivo.limpiar(claveCierre)", pos)       # se borra al cerrar la caja
        self.assertIn("conteoEfectivo.usar('apertura')", apertura)

    def test_ventana_de_conteo_tiene_limpiar(self):
        html = self.c.get("/pos/abrir-caja").get_data(as_text=True)     # pantalla de abrir caja
        self.assertIn('id="conteo-limpiar"', html)
        self.assertIn("window.conteoEfectivo", html)

    def test_version(self):
        from app.version import VERSION
        self.assertEqual(VERSION, "1.1.8")
