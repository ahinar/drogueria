# -*- mode: python ; coding: utf-8 -*-
"""
RECETA DE EMPAQUETADO (PyInstaller) — convierte el programa en "Fervifarma.exe"
==============================================================================

PARA QUÉ (para aprender):
    En el computador del local no hace falta instalar Python: PyInstaller
    mete en una carpeta el programa, Python y las librerías (Flask, Waitress,
    ReportLab, OpenPyXL, Pillow). Después Inno Setup (fervifarma.iss) arma
    con esa carpeta el instalador "Fervifarma-Instalador-x.y.z.exe".

    Se ejecuta desde la carpeta del proyecto:
        pyinstaller instalador/fervifarma.spec --noconfirm
    y deja el resultado en  dist/Fervifarma/

    Lo que se mete además del código Python:
      - app/templates  (las páginas)
      - static         (estilos, JavaScript, íconos) SIN static/uploads:
                       las fotos y documentos son datos de cada droguería
                       y viven en la carpeta de datos (ver config.py).
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

RAIZ = Path(SPECPATH).parent          # carpeta del proyecto (SPECPATH = carpeta de este archivo)


def carpeta(origen, destino, saltar=()):
    """Lista (archivo, carpeta_destino) de todos los archivos de una carpeta, menos las que se saltan."""
    datos = []
    for actual, carpetas, archivos in os.walk(RAIZ / origen):
        carpetas[:] = [c for c in carpetas if c not in saltar and c != "__pycache__"]
        rel = Path(actual).relative_to(RAIZ / origen)
        for archivo in archivos:
            datos.append((str(Path(actual) / archivo), str(Path(destino) / rel)))
    return datos


datos = (carpeta("app/templates", "app/templates")
         + carpeta("static", "static", saltar=("uploads",))
         + collect_data_files("reportlab"))          # fuentes y métricas que usan los PDF

a = Analysis(
    [str(RAIZ / "escritorio.py")],
    pathex=[str(RAIZ)],
    datas=datos,
    # Los módulos del programa se importan a veces "por dentro" de las funciones:
    # se incluyen todos para que no falte ninguno.
    hiddenimports=collect_submodules("app") + ["waitress", "openpyxl", "PIL.Image"],
    # Lo que no usa el programa (si está instalado en el computador que empaqueta, no se mete)
    excludes=["tests", "pytest", "tkinter", "playwright", "numpy", "scipy", "pandas", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Fervifarma",
    icon=str(RAIZ / "instalador" / "fervifarma.ico"),
    console=False,          # sin pantalla negra
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Fervifarma", upx=False)
