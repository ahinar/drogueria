"""
PRUEBA DE LAS VENTANAS (MODALES) DE TODO EL PROGRAMA.

Cada ventana es un <div id="modal-..." class="modal-oculto"> que el JavaScript
muestra quitándole "modal-oculto". Para que se vea FLOTANDO encima de la página
necesita su regla en el CSS (#modal-... { position: fixed; ... }). Si falta,
la ventana queda pegada al final de la página y parece que el botón no hace
nada (así pasó con "Registrar aporte" de Caja menor). Esta prueba revisa que
ninguna ventana se quede sin su estilo.
"""
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# Plantillas que existen pero no se usan en ninguna página (versión 1.1.14: se borró
# _modal_cobro.html, que llevaba tiempo sin usarse; ya no queda ninguna)
SIN_USAR = set()


class TestModales(unittest.TestCase):
    def test_toda_ventana_tiene_su_estilo(self):
        css = "\n".join(p.read_text(encoding="utf-8") for p in (RAIZ / "static" / "css").glob("*.css"))
        faltan = []
        for plantilla in (RAIZ / "app" / "templates").rglob("*.html"):
            texto = plantilla.read_text(encoding="utf-8")
            for ident in re.findall(r'<div id="(modal-[\w-]+)" class="modal-oculto"', texto):
                if ident not in SIN_USAR and not re.search(r"#" + re.escape(ident) + r"\b", css):
                    faltan.append(f"{ident} ({plantilla.relative_to(RAIZ)})")
        self.assertEqual(faltan, [], "Ventanas sin estilo de ventana flotante en el CSS")
