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
ORDEN_NOMBRE_LAB = (f"p.nombre COLLATE NOCASE, {SQL_LAB} COLLATE NOCASE, "
                    "p.concentracion COLLATE NOCASE")


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
    for palabra in palabras(q):
        like = f"%{palabra}%"
        partes = [f"{c} LIKE ?" for c in campos]
        # Laboratorio y principio activo están en el catálogo (otra tabla)
        partes.append("EXISTS (SELECT 1 FROM catalogos cb WHERE cb.id = p.laboratorio_id AND cb.nombre LIKE ?)")
        partes.append("EXISTS (SELECT 1 FROM catalogos cb WHERE cb.id = p.principio_id AND cb.nombre LIKE ?)")
        sql += " AND (" + " OR ".join(partes) + ")"
        params += [like] * (len(campos) + 2)
    return sql, params
