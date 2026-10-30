"""AYUDAS QUE USAN MUCHOS MÓDULOS (versión 1.1.15).

PARA QUÉ (para aprender)
------------------------
Antes cada módulo escribía su propia versión de estas tres cosas, y no todas
hacían lo mismo (por ejemplo, en el conteo "6.420" era seis mil cuatrocientos
veinte y en capacitaciones era seis coma cuarenta y dos). Ahora viven aquí y
todos las usan:

  leer_numero("1.500")         -> 1500.0   (lo que escribe el usuario, a la colombiana)
  obtener_o_404("pqrs", 7)     -> la fila 7 de la tabla pqrs, o la página «no existe»
  siguiente_numero(db, "cotizaciones", "COT") -> "COT-0013" (el consecutivo que sigue)
"""
import re

from flask import abort

from .db import get_db

# "1.500", "12.345.678" (puntos de miles en grupos de 3), con o sin decimales con coma
_MILES = re.compile(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$")


def leer_numero(texto, vacio=None, malo=None):
    """Convierte lo que escribe una persona en un número (float), como se escribe en Colombia.

        "1500" -> 1500      "1.500" -> 1500       "1.500,75" -> 1500.75
        "2,5"  -> 2.5       "2.5"   -> 2.5        "$ 3.000"  -> 3000
        ""     -> vacio     "abc"   -> malo

    Regla: la COMA es la de los decimales. El punto es de miles cuando va en grupos de
    3 cifras ("1.500"); si no ("2.5"), se toma como decimal (así escribe el teclado
    numérico del computador). vacio y malo son lo que se devuelve en esos casos (por
    defecto None); hay pantallas que usan malo="error" para avisar.
    """
    t = str(texto if texto is not None else "").strip().replace("$", "").replace(" ", "")
    if not t:
        return vacio
    if "," in t:                         # 1.500,75 -> 1500.75   ;   2,5 -> 2.5
        t = t.replace(".", "").replace(",", ".")
    elif _MILES.match(t):                # 1.500 -> 1500
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return malo


def obtener_o_404(tabla, registro_id):
    """La fila con ese id de la tabla, o la página «no existe» (error 404).

    tabla es siempre un nombre escrito en el código (nunca algo que mande el usuario):
    por eso se puede poner directo en el SQL.
    """
    fila = get_db().execute(f"SELECT * FROM {tabla} WHERE id = ?", (registro_id,)).fetchone()
    if fila is None:
        abort(404)
    return fila


def siguiente_numero(db, tabla, prefijo, columna="numero"):
    """El consecutivo que sigue: "COT-0012" -> "COT-0013". El primero es "COT-0001".

    Busca el número MÁS ALTO que empiece por el prefijo (no el último guardado), así un
    número escrito a mano o borrado no hace que se repita uno.
    """
    largo = len(prefijo) + 2                      # "COT-" -> la cifra empieza en la posición 5
    fila = db.execute(
        f"SELECT MAX(CAST(SUBSTR({columna}, ?) AS INTEGER)) AS n FROM {tabla} "
        f"WHERE {columna} LIKE ? AND SUBSTR({columna}, ?) GLOB '[0-9]*'",
        (largo, prefijo + "-%", largo)).fetchone()
    return f"{prefijo}-{(fila['n'] or 0) + 1:04d}"
