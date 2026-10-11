"""
PRUEBAS DE GESTIÓN DOCUMENTAL (Fase 4.1, app/documentos.py).

Se prueba: listado sugerido, crear, subir versiones (borrador y vigente),
aprobar, control de cambios, revisión sin cambios, obsoleto, archivos
aceptados/rechazados, permisos, aviso en el Inicio y el PDF del listado.
"""
import io
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import BaseFase1

HOY = date.today()
PDF = lambda: (io.BytesIO(b"%PDF-1.4 documento de prueba"), "procedimiento.pdf")
DOCX = lambda: (io.BytesIO(b"PK\x03\x04 word de prueba"), "procedimiento.docx")


class BaseDocumentos(BaseFase1):
    def tearDown(self):
        # Borra los archivos que las pruebas guardaron en static/uploads/documentos
        con = self.db()
        for f in con.execute("SELECT archivo FROM documento_versiones WHERE archivo IS NOT NULL"):
            (Path(self.app.static_folder) / f["archivo"]).unlink(missing_ok=True)
        con.close()
        super().tearDown()

    def crear(self, codigo="PR-03", nombre="Recepción técnica", frecuencia="12"):
        return self.post(self.c, "/documentos/nuevo", {"codigo": codigo, "nombre": nombre,
                                                       "tipo": "procedimiento", "frecuencia_meses": frecuencia})

    def subir(self, doc_id=1, archivo=None, **datos):
        base = {"version": "01", "estado": "vigente", "aprobo": "Fernando", "elaboro": "Fernando",
                "fecha": HOY.isoformat(), "archivo": archivo or PDF()}
        base.update(datos)
        return self.post(self.c, f"/documentos/{doc_id}/version", base, content_type="multipart/form-data")

    def doc(self, doc_id=1):
        return self.uno("SELECT * FROM documentos WHERE id = ?", doc_id)

    def cuantas(self, sql="SELECT COUNT(*) n FROM documento_versiones"):
        return self.uno(sql)["n"]


class TestDocumentos(BaseDocumentos):
    def test_listado_sugerido_se_crea_una_sola_vez(self):
        self.post(self.c, "/documentos/sugerido")
        from app.documentos import LISTADO_SUGERIDO
        total = self.uno("SELECT COUNT(*) n FROM documentos")["n"]
        self.assertEqual(total, len(LISTADO_SUGERIDO))
        self.assertEqual(self.uno("SELECT estado FROM documentos WHERE codigo = 'PR-03'")["estado"], "por_hacer")
        self.post(self.c, "/documentos/sugerido")              # repetir no duplica
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM documentos")["n"], total)

    def test_crear_y_validar(self):
        self.crear()
        self.assertEqual(self.doc()["codigo"], "PR-03")
        self.crear(codigo="pr-03", nombre="Otro")              # código repetido (sin importar mayúsculas)
        self.crear(codigo="", nombre="Sin código")
        self.crear(codigo="PR-99", nombre="X", frecuencia="0")
        self.assertEqual(self.uno("SELECT COUNT(*) n FROM documentos")["n"], 1)

    def test_primera_version_vigente_calcula_la_proxima_revision(self):
        self.crear(frecuencia="12")
        self.subir(fecha="2026-01-31")
        d = self.doc()
        self.assertEqual((d["estado"], d["version"], d["fecha_aprobacion"], d["proxima_revision"]),
                         ("vigente", "01", "2026-01-31", "2027-01-31"))
        self.assertTrue(d["archivo"].startswith("uploads/documentos/"))
        v = self.uno("SELECT * FROM documento_versiones")
        self.assertEqual((v["cambio"], v["estado"]), ("Emisión inicial", "vigente"))  # sin texto = emisión inicial
        self.assertIsNotNone(self.uno("SELECT 1 FROM bitacora WHERE accion = 'documento_version'"))

    def test_segunda_version_exige_el_cambio_y_reemplaza_la_anterior(self):
        self.crear()
        self.subir()
        self.subir(version="02")                                # sin decir qué cambió: se rechaza
        self.assertEqual(self.cuantas(), 1)
        self.subir(version="01", cambio="x")                    # versión repetida: se rechaza
        self.assertEqual(self.cuantas(), 1)
        self.subir(version="02", cambio="Se agregó verificar el INVIMA", archivo=DOCX())
        self.assertEqual(self.doc()["version"], "02")
        estados = [f["estado"] for f in self.db().execute(
            "SELECT estado FROM documento_versiones ORDER BY id")]
        self.assertEqual(estados, ["reemplazada", "vigente"])   # la vieja NO se borra
        self.assertTrue(self.doc()["archivo"].endswith(".docx"))

    def test_borrador_y_luego_aprobar(self):
        self.crear()
        self.subir(estado="borrador", aprobo="")
        self.assertEqual(self.doc()["estado"], "borrador")
        self.assertIsNone(self.doc()["version"])                # todavía no hay versión vigente
        self.post(self.c, "/documentos/1/version/1/aprobar", {"aprobo": "", "fecha": HOY.isoformat()})
        self.assertEqual(self.doc()["estado"], "borrador")      # sin quién aprobó: no se aprueba
        self.post(self.c, "/documentos/1/version/1/aprobar", {"aprobo": "Fernando", "fecha": HOY.isoformat()})
        d = self.doc()
        self.assertEqual((d["estado"], d["version"], d["aprobo"]), ("vigente", "01", "Fernando"))

    def test_vigente_exige_quien_aprobo(self):
        self.crear()
        self.subir(aprobo="")
        self.assertEqual(self.cuantas(), 0)
        self.assertEqual(self.doc()["estado"], "por_hacer")

    def test_archivos_rechazados(self):
        self.crear()
        self.subir(archivo=(io.BytesIO(b"MZ programa"), "virus.exe"))          # tipo no permitido
        self.subir(archivo=(io.BytesIO(b"esto no es word"), "falso.docx"))     # firma interna falsa
        self.subir(archivo=(io.BytesIO(b"MZ no es pdf"), "falso.pdf"))
        self.assertEqual(self.cuantas(), 0)

    def test_revision_sin_cambios_corre_la_fecha(self):
        self.crear(frecuencia="6")
        self.subir(fecha=(HOY - timedelta(days=200)).isoformat())
        self.post(self.c, "/documentos/1/revisar", {"reviso": "Fernando", "fecha": HOY.isoformat()})
        from app.equipos import sumar_meses
        self.assertEqual(self.doc()["proxima_revision"], sumar_meses(HOY, 6).isoformat())
        rev = self.uno("SELECT * FROM documento_versiones WHERE tipo = 'revision'")
        self.assertEqual((rev["version"], rev["aprobo"]), ("01", "Fernando"))
        self.assertEqual(self.doc()["version"], "01")           # la versión no cambia

    def test_obsoleto_y_reactivar(self):
        self.crear()
        self.subir()
        self.post(self.c, "/documentos/1/obsoleto")
        self.assertEqual(self.doc()["estado"], "obsoleto")
        self.subir(version="02", cambio="x")                     # obsoleto: no recibe versiones
        self.assertEqual(self.cuantas(), 1)
        self.post(self.c, "/documentos/1/obsoleto")
        self.assertEqual(self.doc()["estado"], "vigente")

    def test_auxiliar_ve_pero_no_modifica(self):
        self.crear()
        self.subir()
        self.crear_usuario(self.c, "aux1", "auxiliar")
        aux = self.cliente()
        self.entrar(aux, "aux1")
        self.assertEqual(aux.get("/documentos/").status_code, 200)
        self.assertEqual(aux.get("/documentos/1").status_code, 200)
        self.assertEqual(self.post(aux, "/documentos/nuevo", {"codigo": "X", "nombre": "X"}).status_code, 403)
        self.assertEqual(self.post(aux, "/documentos/1/obsoleto").status_code, 403)

    def test_aviso_en_inicio_cuando_toca_revisar(self):
        self.crear()
        self.subir()
        claves = lambda: re.findall(r'data-clave="([a-z_]+)"', self.c.get("/").get_data(as_text=True))
        self.assertNotIn("documentos_por_revisar", claves())
        con = self.db()
        con.execute("UPDATE documentos SET proxima_revision = ?", ((HOY + timedelta(days=10)).isoformat(),))
        con.commit()
        con.close()
        self.assertIn("documentos_por_revisar", claves())

    def test_pantallas_y_pdf(self):
        self.post(self.c, "/documentos/sugerido")
        self.subir(doc_id=6)
        r = self.c.get("/documentos/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("PR-03", r.get_data(as_text=True))
        self.assertEqual(self.c.get("/documentos/?filtro=por_hacer").status_code, 200)
        self.assertEqual(self.c.get("/documentos/6").status_code, 200)
        self.assertEqual(self.c.get("/documentos/6/editar").status_code, 200)
        pdf = self.c.get("/documentos/listado.pdf")
        self.assertEqual(pdf.mimetype, "application/pdf")
        self.assertTrue(pdf.data.startswith(b"%PDF"))
