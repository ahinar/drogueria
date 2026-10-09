"""
PRUEBAS DEL SCRIPT DE DEMOSTRACIÓN (scripts/crear_demo.py), usado en Codespaces.
Lo más importante: que NUNCA escriba en la base real.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "scripts" / "crear_demo.py"


def correr(db=None):
    entorno = {k: v for k, v in os.environ.items() if k != "DROGUERIA_DB"}
    if db is not None:
        entorno["DROGUERIA_DB"] = str(db)
    return subprocess.run([sys.executable, str(SCRIPT)], env=entorno, capture_output=True,
                          text=True, cwd=str(RAIZ), timeout=120)


class TestDemo(unittest.TestCase):
    def test_crea_la_demo_y_no_la_duplica(self):
        with tempfile.TemporaryDirectory() as carpeta:
            db = Path(carpeta) / "demo.db"
            self.assertEqual(correr(db).returncode, 0)
            con = sqlite3.connect(db)
            usuarios = [r[0] for r in con.execute("SELECT usuario FROM usuarios ORDER BY usuario")]
            productos = con.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
            lotes = con.execute("SELECT COUNT(*) FROM lotes").fetchone()[0]
            con.close()
            self.assertEqual(usuarios, ["admin", "aux", "dt"])
            self.assertEqual((productos, lotes), (12, 13))
            salida = correr(db)                       # segunda vez: no cambia nada
            self.assertIn("ya existe", salida.stdout)
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM productos").fetchone()[0], 12)
            con.close()

    def test_sin_variable_no_hace_nada(self):
        salida = correr(None)
        self.assertIn("no se hace nada", salida.stdout)

    def test_se_niega_a_tocar_la_base_real(self):
        salida = correr(RAIZ / "db" / "drogueria.db")
        self.assertIn("base REAL", salida.stdout)
