"""
PRUEBAS DE LOS TEMAS (Apariencia): cada usuario elige cómo se ve el programa.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fase1 import BaseFase1


class TestTemas(BaseFase1):
    def test_por_defecto_es_verde_con_el_diseno_nuevo(self):
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn('data-tema="verde" class="moderno"', html)
        self.assertIn("css/moderno.css", html)
        self.assertIn('class="ico-svg"', html)        # íconos de línea en el menú

    def test_cambiar_a_clasico_y_volver(self):
        self.post(self.c, "/cuenta/apariencia", {"tema": "clasico"})
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn('data-tema="clasico"', html)
        self.assertNotIn('class="moderno"', html)       # sin el diseño nuevo: se ve como antes
        self.assertEqual(self.uno("SELECT tema FROM usuarios")["tema"], "clasico")
        self.post(self.c, "/cuenta/apariencia", {"tema": "azul"})
        self.assertIn('data-tema="azul" class="moderno"', self.c.get("/").get_data(as_text=True))

    def test_tema_invalido_no_se_guarda(self):
        self.post(self.c, "/cuenta/apariencia", {"tema": "rosado"})
        self.assertEqual(self.uno("SELECT tema FROM usuarios")["tema"], "verde")

    def test_cada_usuario_tiene_su_tema(self):
        self.crear_usuario(self.c, "aux", "auxiliar")
        self.post(self.c, "/cuenta/apariencia", {"tema": "clasico"})
        c = self.cliente()
        self.entrar(c, "aux")
        self.assertIn('data-tema="verde"', c.get("/").get_data(as_text=True))

    def test_pantalla_y_barra_superior(self):
        html = self.c.get("/cuenta/apariencia").get_data(as_text=True)
        self.assertIn("Verde salud", html)
        self.assertIn("Clásico", html)
        self.assertIn("Caja cerrada", self.c.get("/productos/").get_data(as_text=True))

    def test_inicio_sin_accesos_rapidos(self):
        self.assertNotIn("Accesos rápidos", self.c.get("/").get_data(as_text=True))


class TestPaginasSueltas(BaseFase1):
    """El login no usa base.html: si no carga temas.css, el botón 'Entrar'
    queda blanco sobre blanco (esto le pasó a Fernando en el celular)."""

    def test_login_carga_los_colores_del_tema(self):
        html = self.app.test_client().get("/login").get_data(as_text=True)
        self.assertIn("css/temas.css", html)
        self.assertIn("Entrar", html)

    def test_app_css_trae_los_colores_por_si_acaso(self):
        css = (Path(__file__).resolve().parent.parent / "static/css/app.css").read_text(encoding="utf-8")
        self.assertIn('@import url("temas.css")', css)


class TestMenuApariencia(BaseFase1):
    """En el celular el pie del menú (iniciales) se oculta: por eso los temas
    deben tener su propia opción visible en el menú, para cualquier rol."""

    def test_menu_tiene_opcion_apariencia(self):
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn("Apariencia (temas)", html)
        self.assertIn('href="/cuenta/apariencia"', html)
