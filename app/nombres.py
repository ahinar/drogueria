"""
NOMBRES: COMPARAR Y ORDENAR EN ESPAÑOL (versión 1.1.6)
=====================================================

PARA QUÉ (para aprender):
    Dos problemas que tenían los catálogos (laboratorios, principios activos,
    formas, categorías...) y las unidades de medida:

    1. SE COLABAN REPETIDOS. La base de datos solo bloqueaba nombres idénticos
       letra por letra, así que dejaba crear "SAN FER", "san fer" y "SANFER"
       como si fueran tres laboratorios distintos.
       → clave(nombre) convierte el nombre en una "huella" sin mayúsculas,
         sin tildes, sin espacios ni signos. Si dos nombres tienen la misma
         huella, son el MISMO:
             clave("SAN FER")       = "sanfer"
             clave("Sanfer.")       = "sanfer"
             clave("Acetaminofén")  = "acetaminofen"
             clave("Caja x12")      = "cajax12"   = clave("CAJA X 12")

    2. LAS TILDES SE ORDENABAN MAL. SQLite (la base de datos) ordena letra por
       letra según su código, y la "Á" queda después de la "Z": "Ácido fólico"
       salía al final, después de "Zinc".
       → orden(nombre) da la forma de ordenar como en un diccionario, y
         registrar_en(conexion) le enseña a SQLite un orden nuevo llamado "ES":
             ... ORDER BY nombre COLLATE ES
         (COLLATE = "con qué regla comparar". "ES" = español, sin tildes.)

    3. LAS UNIDADES: "Unidad" primero y después por tamaño (pedido de
       Fernando): Unidad, Sello x 4, Sello x 7, Caja x 10, Sello x 10, Caja x 12...
       → orden_unidades(lista) las ordena así, leyendo el número del nombre
         cuando la unidad quedó guardada con cantidad 1 (ej. "CAJA X 12").
"""
import re
import unicodedata


def sin_tildes(texto):
    """'Acetaminofén Ñ' -> 'Acetaminofen N'. (Separa la letra de su tilde y bota la tilde.)"""
    descompuesto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def clave(nombre):
    """Huella para saber si dos nombres son el MISMO (ver punto 1 arriba)."""
    texto = sin_tildes(nombre).lower()
    return re.sub(r"[^a-z0-9]", "", texto)        # solo letras y números, nada más


def orden(nombre):
    """Forma de ordenar como en el diccionario: sin tildes y sin importar mayúsculas."""
    return re.sub(r"\s+", " ", sin_tildes(nombre).lower()).strip()


def _comparar(a, b):
    """Regla "ES" para SQLite: devuelve -1, 0 o 1 (a va antes, igual, o después de b)."""
    oa, ob = orden(a), orden(b)
    return (oa > ob) - (oa < ob)


def plano(texto):
    """'Codeína ' -> 'codeina' : para BUSCAR sin que importen tildes ni mayúsculas."""
    return sin_tildes(texto if isinstance(texto, str) else ("" if texto is None else str(texto))).lower()


def registrar_en(conexion):
    """Le enseña a una conexión de SQLite:
      - el orden "ES"          (ORDER BY nombre COLLATE ES)
      - la función PLANO(x)    (WHERE PLANO(nombre) LIKE '%codeina%' encuentra "Codeína")
    Se llama cada vez que se abre la base (db.conectar)."""
    conexion.create_collation("ES", _comparar)
    conexion.create_function("PLANO", 1, plano, deterministic=True)


def buscar_igual(filas, nombre, campo="nombre", excepto_id=None):
    """De una lista de filas (de la base), la que tenga el MISMO nombre según clave().

    excepto_id: para no compararse consigo misma al editar.
    Devuelve la fila o None.
    """
    huella = clave(nombre)
    if not huella:
        return None
    for fila in filas:
        if excepto_id is not None and fila["id"] == excepto_id:
            continue
        if clave(fila[campo]) == huella:
            return fila
    return None


def catalogo_igual(db, tipo, nombre, excepto_id=None):
    """¿Ya existe en el catálogo `tipo` un registro con el mismo nombre? (activo o no)"""
    filas = db.execute("SELECT * FROM catalogos WHERE tipo = ?", (tipo,)).fetchall()
    return buscar_igual(filas, nombre, excepto_id=excepto_id)


def unidad_igual(db, nombre, excepto_id=None):
    """¿Ya existe una unidad de medida con el mismo nombre? (activa o no)"""
    filas = db.execute("SELECT * FROM unidades_medida").fetchall()
    return buscar_igual(filas, nombre, excepto_id=excepto_id)


def cantidad_unidad(nombre, cantidad):
    """Cuántas trae una unidad: su cantidad, o si quedó en 1, el número del nombre.

    "CAJA X 12" con cantidad 1 -> 12. (Igual que presentaciones.cantidad_efectiva.)
    """
    try:
        cantidad = float(cantidad or 1)
    except (TypeError, ValueError):
        cantidad = 1.0
    if cantidad <= 1:
        m = re.search(r"x\s*(\d+(?:[.,]\d+)?)\s*$", nombre or "", re.IGNORECASE)
        if m:
            return float(m.group(1).replace(",", "."))
    return cantidad


def llave_unidad(nombre, cantidad):
    """Llave para ordenar unidades: "Unidad" primero, luego por tamaño, luego por nombre."""
    return (0 if clave(nombre) == "unidad" else 1, cantidad_unidad(nombre, cantidad), orden(nombre))


def orden_unidades(filas):
    """Ordena filas de unidades_medida (con 'nombre' y 'cantidad') como pidió Fernando."""
    return sorted(filas, key=lambda u: llave_unidad(u["nombre"], u["cantidad"]))
