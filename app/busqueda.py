"""
BUSCAR PRODUCTOS POR PALABRAS (nombre + concentración + LABORATORIO)
====================================================================

PARA QUÉ (para aprender):
    Hay muchos productos que se llaman igual y solo cambia el laboratorio:

        TRAZODONA CLORHIDRATO 50 MG · SAN FER
        TRAZODONA CLORHIDRATO 50 MG · GENFAR
        TRAZODONA CLORHIDRATO 50 MG · MK

    Antes, el buscador tomaba TODO lo escrito como un solo pedazo de texto:
    "trazodona san fer" no encontraba nada, porque esas palabras juntas no
    están en ningún nombre. Ahora se parte en PALABRAS y cada palabra puede
    estar en cualquiera de estos lugares:

        nombre · código · código de barras · concentración ·
        principio activo · LABORATORIO

    Así "trazodona san fer", "traz 50 sanfer"... sí lo encuentran: el
    producto tiene que tener TODAS las palabras, cada una en algún lugar.

    Además, los resultados salen ordenados por nombre y luego por
    LABORATORIO, para que los "iguales" queden juntos y se distingan.

CÓMO SE USA (desde otro archivo):
    from .busqueda import condicion_palabras, ORDEN_NOMBRE_LAB, SQL_LAB

    cond, params = condicion_palabras(q)        # q = lo que escribió la persona
    sql = "SELECT ... FROM productos p WHERE p.activo = 1" + cond
    sql += " ORDER BY " + ORDEN_NOMBRE_LAB

    "p" tiene que ser el nombre corto (alias) de la tabla productos en la
    consulta. extra = más columnas donde buscar (ej. "l.lote" en inventario).
"""

# Nombre del laboratorio de un producto (se lee del catálogo de laboratorios)
SQL_LAB = "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id)"

# Orden: primero por nombre, después por laboratorio, después por concentración.
ORDEN_NOMBRE_LAB = (f"p.nombre COLLATE ES, {SQL_LAB} COLLATE ES, "
                    "p.concentracion COLLATE ES")


def orden_relevancia(q):
    """Lo MÁS PARECIDO a lo escrito, de primero (versión 1.1.11, pedido de Fernando).

    Devuelve (texto SQL, parámetros) para ponerlo de PRIMERO en un ORDER BY:
        sql += " ORDER BY " + orden + ", " + ORDEN_NOMBRE_LAB

    Antes se ordenaba solo por nombre (A, B, C...): al escribir "TAM" salía de
    primero ACETAMINOFEN (porque "aceTAMinofen" tiene "tam" adentro) y TAMPONES
    quedaba de último, o ni aparecía si había más de 40 resultados.
    Ahora cada producto recibe un "puesto" y se ordena por ese puesto:
        0 = el código o el código de barras es exactamente lo escrito
        1 = el NOMBRE empieza por todo lo escrito          "TAMPONES"        (tam)
        2 = el NOMBRE empieza por la primera palabra       "TAMPONES OB"     (tam pon)
        3 = una PALABRA del nombre empieza por lo escrito  "TOALLAS TAMAÑO"  (tam)
        4 = el nombre tiene lo escrito en la mitad         "ACETAMINOFEN"    (tam)
        5 = lo demás (lo encontró por laboratorio, principio activo, uso...)
    Sin tildes ni mayúsculas (PLANO, ver app/nombres.py).
    """
    from .nombres import plano
    q = (q or "").strip()
    if not q:
        # Sin nada escrito no hay "más parecido": NULL no cambia el orden. (Ojo: un número
        # solo, como "0", SQLite lo entiende como "ordenar por la columna 0" y da error.)
        return "NULL", []
    todo = plano(q)
    primera = plano(palabras(q)[0])
    # El nombre con un espacio adelante y los signos (+ / - paréntesis) cambiados por espacios,
    # para encontrar palabras que EMPIEZAN por lo escrito: "% tam%"
    nombre_palabras = ("PLANO(' ' || REPLACE(REPLACE(REPLACE(REPLACE(p.nombre, '/', ' '), '-', ' '), "
                       "'(', ' '), '+', ' '))")
    sql = ("CASE WHEN p.codigo = ? OR p.codigo_barras = ? THEN 0 "
           "WHEN PLANO(p.nombre) LIKE ? THEN 1 "
           "WHEN PLANO(p.nombre) LIKE ? THEN 2 "
           f"WHEN {nombre_palabras} LIKE ? THEN 3 "
           "WHEN PLANO(p.nombre) LIKE ? THEN 4 "
           "ELSE 5 END")
    return sql, [q, q, todo + "%", primera + "%", "% " + primera + "%", "%" + primera + "%"]


def palabras(q):
    """Parte lo escrito en palabras sueltas: "  Trazodona  san fer " → ["Trazodona", "san", "fer"]."""
    return [x for x in (q or "").split() if x]


def condicion_palabras(q, extra=()):
    """Devuelve (texto SQL, parámetros) para agregar a un WHERE.

    Cada palabra agrega un " AND ( ... OR ... )": el producto debe tener
    esa palabra en alguno de sus campos. Si no escribieron nada, devuelve
    ("", []) y no filtra nada.

    Se usan "?" (parámetros) y no se pega el texto dentro del SQL: así nadie
    puede "colar" órdenes en la base de datos escribiendo cosas raras.
    """
    sql, params = "", []
    campos = ["p.nombre", "p.codigo", "p.codigo_barras", "p.concentracion",
              "p.principio_activo"] + list(extra)
    from .nombres import plano
    for palabra in palabras(q):
        # Versión 1.1.6: sin importar TILDES: "codeina" encuentra "Codeína".
        # PLANO(...) quita tildes y mayúsculas en la base (ver app/nombres.py).
        like = f"%{plano(palabra)}%"
        partes = [f"PLANO({c}) LIKE ?" for c in campos]
        # Laboratorio y principio activo están en el catálogo (otra tabla)
        partes.append("EXISTS (SELECT 1 FROM catalogos cb WHERE cb.id = p.laboratorio_id AND PLANO(cb.nombre) LIKE ?)")
        partes.append("EXISTS (SELECT 1 FROM catalogos cb WHERE cb.id = p.principio_id AND PLANO(cb.nombre) LIKE ?)")
        # Versión 1.1.6: cualquiera de sus principios activos (compuestos)
        partes.append("EXISTS (SELECT 1 FROM producto_principios pb JOIN catalogos cb ON cb.id = pb.catalogo_id "
                      "WHERE pb.producto_id = p.id AND PLANO(cb.nombre) LIKE ?)")
        sql += " AND (" + " OR ".join(partes) + ")"
        params += [like] * (len(campos) + 3)
    return sql, params
