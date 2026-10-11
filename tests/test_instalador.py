"""
PRUEBAS DE LO QUE NECESITA EL PROGRAMA INSTALADO (Fase 7):
  - las fotos y documentos se guardan y se sirven desde la carpeta de DATOS
    (no desde la del programa, que se reemplaza al actualizar)
  - /salud contesta "fervifarma <versión>" (lo usa el lanzador escritorio.py)
  - respaldo de fotos y documentos en ZIP, y carpeta adicional (USB/Drive)
"""
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase0 import Base, TOKEN  # noqa: F401

from app import create_app, auth


class BaseDatosAparte(Base):
    """Igual que Base, pero con la carpeta de archivos (UPLOADS_DIR) en un temporal, como instalado."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "prueba.db")
        self.backups = os.path.join(self.tmp, "respaldos")
        self.uploads = os.path.join(self.tmp, "uploads")
        self.app = create_app({"TESTING": True, "SECRET_KEY": "x", "DB_PATH": self.db_path,
                               "BACKUP_DIR": self.backups, "BACKUP_KEEP": 3, "UPLOADS_DIR": self.uploads})
        auth.reiniciar_limites()
        self.c = self.admin_logueado()


class TestDatosAparte(BaseDatosAparte):
    def test_salud(self):
        from app.version import VERSION
        r = self.cliente().get("/salud")
        self.assertEqual(r.get_data(as_text=True), f"fervifarma {VERSION}")

    def test_logo_se_guarda_en_la_carpeta_de_datos_y_se_ve(self):
        from PIL import Image
        imagen = io.BytesIO()
        Image.new("RGB", (40, 40), "teal").save(imagen, "PNG")
        imagen.seek(0)
        self.post(self.c, "/configuracion/", {"nit": "1", "razon_social": "Fervifarma", "logo": (imagen, "logo.png")},
                  content_type="multipart/form-data")
        self.assertTrue((Path(self.uploads) / "logos" / "logo.png").exists())          # en DATOS
        r = self.c.get("/static/uploads/logos/logo.png")                                 # y se ve en la misma dirección
        self.assertEqual(r.status_code, 200)
        r.close()
        # Los estilos del programa siguen saliendo de la carpeta del programa
        r = self.c.get("/static/css/app.css")
        self.assertEqual(r.status_code, 200)
        r.close()

    def test_respaldo_de_archivos_y_carpeta_extra(self):
        (Path(self.uploads) / "documentos").mkdir(parents=True)
        (Path(self.uploads) / "documentos" / "pr03.pdf").write_bytes(b"%PDF-1.4 x")
        extra = os.path.join(self.tmp, "usb")
        self.post(self.c, "/admin/respaldos", {"accion": "carpeta_extra", "carpeta_extra": extra})
        self.post(self.c, "/admin/respaldos", {"accion": "respaldar"})
        zips = list(Path(self.backups).glob("archivos_*.zip"))
        self.assertEqual(len(zips), 1)
        with zipfile.ZipFile(zips[0]) as z:
            self.assertIn("documentos/pr03.pdf", z.namelist())
        # Copias en la carpeta adicional (la "USB")
        self.assertEqual(len(list(Path(extra).glob("drogueria_*.db"))), 1)
        self.assertEqual(len(list(Path(extra).glob("archivos_*.zip"))), 1)
        self.assertEqual(self.c.get("/admin/respaldos").status_code, 200)

    def test_revisar_respaldos_no_repite_el_mismo_dia(self):
        from app.backup_utils import listar_respaldos, revisar_respaldos
        revisar_respaldos(self.app)
        revisar_respaldos(self.app)
        self.assertEqual(len(listar_respaldos(self.backups)), 1)
