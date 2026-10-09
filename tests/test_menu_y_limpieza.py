"""
PRUEBAS DE LA LIMPIEZA: menú por roles, catálogo retirado y tabla muerta borrada.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase0 import Base


class TestMenuPorRoles(Base):
    def menu_de(self, rol):
        """Entra con un usuario del rol pedido y devuelve el HTML del inicio."""
        c = self.admin_logueado()
        if rol == "administrador":
            return c.get("/").get_data(as_text=True)
        self.crear_usuario(c, "otro", rol)
        c2 = self.cliente()
        self.entrar(c2, "otro")
        return c2.get("/").get_data(as_text=True)

    def test_auxiliar_solo_ve_lo_suyo(self):
        html = self.menu_de("auxiliar")
        for visible in ("Vender (POS)", "Recepciones", "Temperaturas", "Inventario", "Reportes"):
            self.assertIn(visible, html)
        for oculto in ("Proveedores", "Contabilidad", "Caja menor", "Catálogos", "Usuarios"):
            self.assertNotIn('title="' + oculto + '"', html)
        # Tampoco en los accesos rápidos del inicio
        self.assertNotIn("/proveedores/", html)

    def test_director_tecnico_ve_dinero_pero_no_usuarios(self):
        html = self.menu_de("director_tecnico")
        for visible in ("Contabilidad", "Caja menor", "Proveedores", "Catálogos", "Bitácora"):
            self.assertIn('title="' + visible + '"', html)
        for oculto in ("Usuarios", "Configuración", "Respaldos"):
            self.assertNotIn('title="' + oculto + '"', html)

    def test_administrador_ve_todo(self):
        html = self.menu_de("administrador")
        for visible in ("Contabilidad", "Usuarios", "Configuración", "Respaldos"):
            self.assertIn('title="' + visible + '"', html)

    def test_ya_no_hay_enlace_clientes_deshabilitado(self):
        self.assertNotIn("Clientes", self.menu_de("administrador"))


class TestLimpieza(Base):
    def test_catalogo_tipos_de_pago_retirado(self):
        c = self.admin_logueado()
        self.assertEqual(c.get("/admin/catalogos/tipo_pago/").status_code, 404)
        self.assertNotIn("Tipos de pago", c.get("/admin/catalogos/").get_data(as_text=True))

    def test_usos_ahora_se_llaman_usos_y_sintomas(self):
        c = self.admin_logueado()
        self.assertIn("Usos y síntomas", c.get("/admin/catalogos/").get_data(as_text=True))

    def test_tabla_presentaciones_borrada(self):
        con = sqlite3.connect(self.db_path)
        hay = con.execute("SELECT 1 FROM sqlite_master WHERE name = 'presentaciones_producto'").fetchone()
        con.close()
        self.assertIsNone(hay)
