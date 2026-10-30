"""POS · PRODUCTOS: buscar, ver la ficha rápida («i») y editar desde el POS.

Versión 1.1.15: esto estaba en app/pos.py (que tenía más de 1.600 líneas). Ahora el POS
está repartido en tres archivos, por tema, y las direcciones (/pos/...) son las mismas:
    pos.py           -> la caja: abrir, cerrar, movimientos de plata, gastos, otros ingresos
    pos_productos.py -> (este) buscar productos, ficha «i» y «Editar producto»
    pos_ventas.py    -> cobrar, venta libre, comprobante, tirilla, cajón, anular
Las rutas se registran en el mismo blueprint "pos" (bp), por eso url_for('pos.…') no cambia.
"""
from datetime import date

from flask import jsonify, request

from . import presentaciones as pres
from .audit import registrar
from .auth import login_required, roles_required
from .db import ahora, get_db
from .formato import pesos
from .productos import IVA_TIPOS
from .utils_imagenes import eliminar_imagen, guardar_imagen
# Lo que comparten las tres partes del POS (está en app/pos.py)
from .pos import bp, _json_error, SQL_LOTE_VENDIBLE


def _usos_de(ids):
    """{producto_id: ['Fiebre', 'Gripa', ...]} para una lista de productos."""
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    resultado = {}
    for fila in get_db().execute(
            "SELECT pu.producto_id, c.nombre FROM productos_usos pu "
            f"JOIN catalogos c ON c.id = pu.catalogo_id WHERE pu.producto_id IN ({marcas}) "
            "ORDER BY c.nombre COLLATE ES", ids):
        resultado.setdefault(fila["producto_id"], []).append(fila["nombre"])
    return resultado


@bp.route("/api/productos")
@login_required
def api_productos():
    """Busca productos para el POS. Devuelve hasta 40, con su stock vendible."""
    q = (request.args.get("q") or "").strip()
    cat = (request.args.get("cat") or "").strip()
    hoy = date.today().isoformat()

    sql = (
        "SELECT p.id, p.codigo, p.codigo_barras, p.nombre, p.concentracion, "
        "p.precio_venta, p.iva_tipo, p.iva_tarifa, p.requiere_formula, "
        "p.control_especial, p.imagen, p.venta_defecto_unidad_id, "
        "(SELECT nombre FROM catalogos WHERE id = p.laboratorio_id) AS laboratorio, "
        "COALESCE((SELECT SUM(l.cantidad_disponible) FROM lotes l "
        f"          WHERE l.producto_id = p.id AND {SQL_LOTE_VENDIBLE}), 0) AS stock "
        "FROM productos p WHERE p.activo = 1"
    )
    params = [hoy]

    # Cada palabra escrita debe aparecer en ALGUNO de estos lugares:
    #   nombre, código, código de barras, principio activo (texto o catálogo)
    #   o en los USOS del producto (nombre del uso o su descripción).
    # Así funciona el "buscador por síntoma": si el producto tiene el uso
    # "Gripa" con descripción "resfriado, congestión", escribir "resfriado"
    # lo encuentra.
    #   (también el código de barras de sus presentaciones: sobre, caja...)
    #   Versión 1.1.3: también la CONCENTRACIÓN y el LABORATORIO, para distinguir
    #   productos que se llaman igual ("trazodona san fer").
    #   Versión 1.1.6: sin importar TILDES ("codeina" = "Codeína"): PLANO() en app/nombres.py
    from .nombres import plano
    for palabra in q.split():
        sql += (" AND (PLANO(p.nombre) LIKE ? OR PLANO(p.codigo) LIKE ? OR PLANO(p.codigo_barras) LIKE ? "
                "OR PLANO(p.principio_activo) LIKE ? OR PLANO(p.concentracion) LIKE ? "
                "OR EXISTS (SELECT 1 FROM catalogos lb WHERE lb.id = p.laboratorio_id "
                "           AND PLANO(lb.nombre) LIKE ?) "
                "OR EXISTS (SELECT 1 FROM producto_presentaciones pp WHERE pp.producto_id = p.id "
                "           AND pp.codigo_barras = ?) "
                "OR EXISTS (SELECT 1 FROM producto_principios ppr JOIN catalogos cpr ON cpr.id = ppr.catalogo_id "
                "           WHERE ppr.producto_id = p.id AND PLANO(cpr.nombre) LIKE ?) "
                "OR EXISTS (SELECT 1 FROM catalogos pa WHERE pa.id = p.principio_id "
                "           AND PLANO(pa.nombre) LIKE ?) "
                "OR EXISTS (SELECT 1 FROM productos_usos pu "
                "           JOIN catalogos u ON u.id = pu.catalogo_id "
                "           WHERE pu.producto_id = p.id "
                "           AND (PLANO(u.nombre) LIKE ? OR PLANO(u.descripcion) LIKE ?)))")
        params += [f"%{plano(palabra)}%"] * 6 + [palabra] + [f"%{plano(palabra)}%"] * 4

    if cat.isdigit():
        sql += " AND p.id IN (SELECT producto_id FROM productos_categorias WHERE catalogo_id = ?)"
        params.append(int(cat))
    # ?ids=3,8,15 -> esos productos exactos (lo usa "Cargar cotización en el POS")
    ids = [int(x) for x in (request.args.get("ids") or "").split(",") if x.strip().isdigit()]
    if ids:
        sql += f" AND p.id IN ({','.join('?' * len(ids))})"
        params += ids

    # Orden (versión 1.1.11): lo más parecido a lo escrito de primero (TAMPONES antes
    # que aceTAMinofen, ver busqueda.orden_relevancia); después los que tienen
    # existencias; los que se llaman igual, juntos y por laboratorio.
    from .busqueda import orden_relevancia
    orden, orden_params = orden_relevancia(q)
    sql += f" ORDER BY {orden}, (stock > 0) DESC, p.nombre COLLATE ES, laboratorio COLLATE ES LIMIT 40"
    params += orden_params
    filas = get_db().execute(sql, params).fetchall()

    usos = _usos_de([f["id"] for f in filas])
    # Formas de vender cada producto: [unidad principal, sobre, caja...]
    presentaciones = pres.presentaciones_de([f["id"] for f in filas])
    productos = [{
        "id": f["id"], "codigo": f["codigo"], "codigo_barras": f["codigo_barras"],
        "nombre": f["nombre"], "concentracion": f["concentracion"],
        "laboratorio": f["laboratorio"] or "",     # se muestra en la tarjeta para distinguir "iguales"
        "precio": f["precio_venta"], "iva_tipo": f["iva_tipo"], "iva_tarifa": f["iva_tarifa"],
        "requiere_formula": bool(f["requiere_formula"]),
        "control_especial": bool(f["control_especial"]),
        "imagen": f["imagen"], "stock": f["stock"],
        "usos": usos.get(f["id"], []),     # para mostrar "Sirve para: ..." en la tarjeta
        "presentaciones": presentaciones.get(f["id"], []),
        # La que agrega el POS al tocar la tarjeta (0 = unidad de inventario)
        "presentacion_defecto": pres.id_por_defecto(presentaciones.get(f["id"], []),
                                                    f["venta_defecto_unidad_id"]),
    } for f in filas]

    # ¿Se escaneó un código de barras exacto? Puede ser el del producto o el de
    # una de sus presentaciones (ej: el código de la CAJA). En ese caso el POS
    # agrega directamente esa presentación, sin preguntar.
    exacto, presentacion_id = False, None
    if q and len(productos) == 1:
        for opcion in productos[0]["presentaciones"]:
            if opcion["codigo_barras"] == q:
                exacto, presentacion_id = True, opcion["id"]
                # El código del PRODUCTO (no el de una caja en particular) agrega lo
                # que se vende normalmente (ej. el Sello x 10), igual que tocar la tarjeta.
                # Para vender suelto se cambia en el carrito.
                if opcion["id"] == pres.PRINCIPAL:
                    presentacion_id = productos[0]["presentacion_defecto"]
                break
    return jsonify({"ok": True, "productos": productos, "exacto": exacto,
                    "presentacion_id": presentacion_id})

@bp.route("/api/producto/<int:producto_id>")
@login_required
def api_producto_info(producto_id):
    """Datos de un producto para la ventana "i" del POS. Solo LEE, no modifica nada.

    Devuelve en un solo paquete (JSON):
      - datos básicos y precios del producto
      - lotes que se pueden vender hoy (el que vence primero va primero)
      - cuántos lotes hay en otros estados (cuarentena, bloqueados, vencidos)
      - costo promedio y margen
      - las últimas 4 compras (recepciones aprobadas)
    """
    db = get_db()
    hoy = date.today().isoformat()

    p = db.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    if p is None:
        return _json_error("El producto no existe.", 404)

    # ---- Lotes que se pueden vender hoy ----
    lotes = db.execute(
        "SELECT l.lote, l.vencimiento, l.cantidad_disponible, l.costo_unitario FROM lotes l "
        f"WHERE l.producto_id = ? AND {SQL_LOTE_VENDIBLE} "
        "ORDER BY (l.vencimiento IS NULL OR l.vencimiento = ''), l.vencimiento, l.id",
        (producto_id, hoy),
    ).fetchall()
    stock = sum(l["cantidad_disponible"] for l in lotes)

    # ---- Lotes con mercancía que NO se pueden vender (para avisar) ----
    otros = db.execute(
        "SELECT "
        " SUM(CASE WHEN estado = 'cuarentena' THEN 1 ELSE 0 END) AS cuarentena, "
        " SUM(CASE WHEN estado = 'bloqueado' THEN 1 ELSE 0 END) AS bloqueados, "
        " SUM(CASE WHEN estado = 'disponible' AND vencimiento IS NOT NULL AND vencimiento <> '' "
        "          AND vencimiento < ? THEN 1 ELSE 0 END) AS vencidos "
        "FROM lotes WHERE producto_id = ? AND cantidad_disponible > 0",
        (hoy, producto_id),
    ).fetchone()

    # ---- Últimas 4 compras (solo recepciones aprobadas y líneas aceptadas) ----
    compras = db.execute(
        "SELECT r.numero, r.fecha, COALESCE(pr.razon_social, 'Sin proveedor') AS proveedor, "
        "       rl.cantidad_recibida, rl.costo_unitario "
        "FROM recepcion_lineas rl "
        "JOIN recepciones r ON r.id = rl.recepcion_id "
        "LEFT JOIN proveedores pr ON pr.id = r.proveedor_id "
        "WHERE rl.producto_id = ? AND r.estado = 'aprobada' AND rl.resultado = 'aceptado' "
        "ORDER BY r.fecha DESC, r.id DESC, rl.id DESC LIMIT 4",
        (producto_id,),
    ).fetchall()

    # ---- Costo: promedio de los lotes vendibles, pesado por cantidad ----
    # Ej.: 5 unidades a $1.000 y 5 a $1.200 -> costo promedio $1.100.
    # Si no hay lotes con costo, se usa la última compra; si tampoco, el precio
    # de compra escrito en la ficha del producto.
    lotes_con_costo = [l for l in lotes if (l["costo_unitario"] or 0) > 0]
    if lotes_con_costo:
        unidades = sum(l["cantidad_disponible"] for l in lotes_con_costo)
        costo = sum(l["cantidad_disponible"] * l["costo_unitario"] for l in lotes_con_costo) / unidades
        costo_origen = "promedio de lotes"
    elif compras:
        costo, costo_origen = float(compras[0]["costo_unitario"] or 0), "última compra"
    else:
        costo, costo_origen = float(p["precio_compra"] or 0), "ficha del producto"

    # ---- Margen: se calcula sobre el precio SIN IVA (el IVA no es ganancia) ----
    precio = float(p["precio_venta"] or 0)
    tarifa = float(p["iva_tarifa"] or 0)
    precio_sin_iva = precio / (1 + tarifa / 100) if p["iva_tipo"] == "gravado" and tarifa > 0 else precio
    margen = precio_sin_iva - costo
    margen_pct = (margen / precio_sin_iva * 100) if precio_sin_iva > 0 else 0

    categorias = [f["catalogo_id"] for f in db.execute(
        "SELECT catalogo_id FROM productos_categorias WHERE producto_id = ?", (producto_id,))]
    from . import principios

    # Presentaciones (unidad, sobre, caja...) con el margen de CADA una:
    # costo de la presentación = costo de 1 unidad x factor
    lista_pres = []
    for opcion in pres.presentaciones_de([producto_id]).get(producto_id, []):
        sin_iva = (opcion["precio"] / (1 + tarifa / 100)
                   if p["iva_tipo"] == "gravado" and tarifa > 0 else opcion["precio"])
        costo_pres = costo * opcion["factor"]
        lista_pres.append({
            **opcion,
            "margen": round(sin_iva - costo_pres, 2),
            "margen_pct": round((sin_iva - costo_pres) / sin_iva * 100, 1) if sin_iva > 0 else 0,
        })

    return jsonify({"ok": True, "producto": {
        "id": p["id"], "codigo": p["codigo"], "codigo_barras": p["codigo_barras"],
        "nombre": p["nombre"], "concentracion": p["concentracion"], "imagen": p["imagen"],
        "precio": precio, "precio_maximo": p["precio_maximo"],
        "precio_sin_iva": round(precio_sin_iva, 2),
        "iva_tipo": p["iva_tipo"], "iva_tarifa": tarifa,
        "iva_valor": round(precio - precio_sin_iva, 2),
        "requiere_formula": bool(p["requiere_formula"]),
        "cadena_frio": bool(p["cadena_frio"]),
        "control_especial": bool(p["control_especial"]),
        "maneja_vencimiento": bool(p["maneja_vencimiento"]),
        # Para la sección "Cómo se vende" de la ventana Editar (versión 1.1.12)
        "vende_suelto": bool(p["vende_suelto"]), "unidad_venta_id": p["unidad_venta_id"],
        "stock_minimo": p["stock_minimo"] or 0,
        "categorias": categorias,
        "usos": _usos_de([producto_id]).get(producto_id, []),
        # Todos los principios activos: "Acetaminofén + Codeína" (versión 1.1.6)
        "principio_activo": principios.texto_de(db, producto_id, " + ") or p["principio_activo"],
        "stock": stock,
        "presentaciones": lista_pres,
        # Cómo se vende normalmente (para decir "29 Sobre x 10 + 5 Tableta")
        "presentacion_defecto": pres.id_por_defecto(lista_pres, p["venta_defecto_unidad_id"]),
        "lotes": [{"lote": l["lote"], "vencimiento": l["vencimiento"],
                   "cantidad": l["cantidad_disponible"]} for l in lotes],
        "otros_lotes": {"cuarentena": otros["cuarentena"] or 0,
                        "bloqueados": otros["bloqueados"] or 0,
                        "vencidos": otros["vencidos"] or 0},
        "costo": round(costo, 2), "costo_origen": costo_origen,
        "margen": round(margen, 2), "margen_pct": round(margen_pct, 1),
        "compras": [{"numero": c["numero"], "fecha": c["fecha"], "proveedor": c["proveedor"],
                     "cantidad": c["cantidad_recibida"], "costo": c["costo_unitario"]}
                    for c in compras],
    }})


@bp.route("/api/producto/<int:producto_id>/editar", methods=["POST"])
@login_required
@roles_required("administrador", "director_tecnico")
def api_producto_editar(producto_id):
    """Edición rápida de un producto desde el POS (ventana "Editar" encima de la "i").

    Solo cambia los campos de esta ventana; el resto de la ficha (registro
    sanitario, laboratorio, usos, etc.) queda igual y se edita en Productos.

    PRECIOS (igual que la ficha completa, ver productos._traducir_venta):
      - "precio_venta" y "precio_maximo" son los de lo que se vende NORMALMENTE.
        Si el producto se vende por "Sobre x 10", son los del SOBRE: se guardan
        en esa presentación y la unidad queda en precio ÷ 10 (o en su propio
        precio si se vende suelto).
      - "precio_pres_<id>": los precios de las demás formas de venderlo
        (id 0 = la unidad suelta; otro número = caja, etc.).
    """
    db = get_db()
    p = db.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    if p is None:
        return _json_error("El producto no existe.", 404)

    f = request.form

    def numero(campo):
        """Convierte '9.800' o '9800,50' en número. Devuelve None si está vacío o no es número."""
        texto = (f.get(campo) or "").strip().replace(" ", "")
        if not texto:
            return None
        # En Colombia el punto separa miles y la coma los decimales: 9.800,50 -> 9800.50
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        elif texto.count(".") == 1 and len(texto.split(".")[1]) == 3:
            texto = texto.replace(".", "")
        try:
            return float(texto)
        except ValueError:
            return "error"

    nombre = (f.get("nombre") or "").strip()
    codigo_barras = (f.get("codigo_barras") or "").strip() or None
    # Versión 1.1.12: la ventana trae la sección "CÓMO SE VENDE" (precio de la unidad,
    # si se vende suelta, las otras presentaciones y cuál vende el POS por defecto).
    # Se guarda con las MISMAS reglas que la ficha completa (presentaciones.validar y
    # presentaciones.guardar). Sin ese campo, funciona como antes (formato viejo).
    formato_nuevo = f.get("formato") == "presentaciones"
    precio_venta = numero("precio_unidad" if formato_nuevo else "precio_venta")
    precio_maximo = numero("maximo_unidad" if formato_nuevo else "precio_maximo")
    # ¿Cómo se vende normalmente? (0 = por la unidad; otro = Sobre x 10, etc.)
    opciones = pres.presentaciones_de([producto_id]).get(producto_id, [])
    defecto_id = pres.id_por_defecto(opciones, p["venta_defecto_unidad_id"])
    defecto = next((o for o in opciones if o["id"] == defecto_id), None)
    # Precios de las demás presentaciones que vinieron en el formulario
    otros_precios = {}
    for o in ([] if formato_nuevo else opciones):
        if o["id"] == defecto_id or f"precio_pres_{o['id']}" not in f:
            continue
        valor = numero(f"precio_pres_{o['id']}")
        if valor in (None, "error") or valor <= 0:
            return _json_error(f"Escribe un precio válido para {o['nombre']}.")
        if o["precio_maximo"] and valor > o["precio_maximo"] + 0.01:
            return _json_error(f"El precio de {o['nombre']} ({pesos(valor)}) supera su precio máximo "
                               f"({pesos(o['precio_maximo'])}).")
        otros_precios[o["id"]] = valor
    iva_tipo = (f.get("iva_tipo") or "").strip()
    iva_tarifa = numero("iva_tarifa")
    requiere_formula = 1 if f.get("requiere_formula") else 0
    control_especial = 1 if f.get("control_especial") else 0
    maneja_vencimiento = 1 if f.get("maneja_vencimiento") else 0
    categorias = sorted({int(x) for x in f.getlist("categorias") if x.isdigit()})

    # ---- Formato nuevo: presentaciones, suelto y por defecto (versión 1.1.12) ----
    if formato_nuevo:
        vende_suelto = 1 if f.get("vende_suelto") else 0
        filas_pres = pres.leer_del_formulario(f)          # pres_unidad_id[], pres_factor[], pres_precio[]...
        errores_pres = pres.validar(filas_pres, p["unidad_venta_id"], producto_id, codigo_barras)
        if errores_pres:
            return _json_error(" ".join(errores_pres))
        defecto_txt = (f.get("venta_defecto") or "").strip()
        defecto_fila = next((x for x in filas_pres if defecto_txt.isdigit() and x["unidad_id"] == int(defecto_txt)),
                            None)
        if not vende_suelto:
            # Si la unidad NO se vende suelta, el POS vende una presentación (ej. el sello):
            # la que se marcó, o la más pequeña. El precio de 1 unidad sale de ella.
            if defecto_fila is None and filas_pres:
                defecto_fila = min(filas_pres, key=lambda x: x["factor"])
            if defecto_fila is None:
                return _json_error("Si la unidad no se vende suelta, agrega la presentación en que se vende "
                                   "(ej. Sello x 10).")
            precio_venta = round(defecto_fila["precio"] / defecto_fila["factor"], 2)
            precio_maximo = (round(defecto_fila["maximo"] / defecto_fila["factor"], 2)
                             if defecto_fila["maximo"] else None)
        venta_defecto_uid = defecto_fila["unidad_id"] if defecto_fila else None

    # ---- Validaciones (si algo falla, no se guarda NADA) ----
    if not nombre:
        return _json_error("El nombre es obligatorio.")
    if precio_venta in (None, "error") or precio_venta <= 0:
        return _json_error("El precio de la unidad debe ser un número mayor a cero." if formato_nuevo
                           else "El precio de venta debe ser un número mayor a cero.")
    if precio_maximo == "error" or (precio_maximo is not None and precio_maximo < 0):
        return _json_error("El precio máximo no es válido.")
    if precio_maximo and precio_venta > precio_maximo + 0.01:
        return _json_error(f"El precio de venta ({pesos(precio_venta)}) no puede superar "
                           f"el precio máximo ({pesos(precio_maximo)}).")
    if iva_tipo not in IVA_TIPOS:
        return _json_error("Tipo de IVA no válido.")
    if iva_tipo == "gravado":
        if iva_tarifa in (None, "error") or not 0 < iva_tarifa <= 100:
            return _json_error("Escribe la tarifa de IVA (por ejemplo 19).")
    else:
        iva_tarifa = 0.0    # excluido y exento no llevan IVA
    if control_especial and not p["registro_sanitario"]:
        return _json_error("Un producto de control especial debe tener registro sanitario INVIMA "
                           "(complétalo en Productos).")
    if control_especial or p["cadena_frio"]:
        maneja_vencimiento = 1   # misma regla que el formulario completo de productos
    if codigo_barras and db.execute(
            "SELECT 1 FROM productos WHERE codigo_barras = ? AND id <> ?",
            (codigo_barras, producto_id)).fetchone():
        return _json_error("Ese código de barras ya lo tiene otro producto.")

    # ---- Foto: subir nueva, borrar o dejar igual ----
    ruta_imagen = p["imagen"]
    if f.get("imagen_accion") == "eliminar":
        ruta_imagen = None
    archivo = request.files.get("imagen")
    if archivo and archivo.filename:
        ruta_nueva, error = guardar_imagen(archivo, "productos", max_px=1200,
                                           max_bytes=5 * 1024 * 1024)
        if error:
            return _json_error(f"No se pudo subir la foto: {error}")
        ruta_imagen = ruta_nueva

    # ---- Traducir los precios a como se guardan ----
    # Lo escrito arriba es el precio de lo que se vende normalmente.
    pres_cambios = []                       # (id de presentación, precio, máximo) a guardar
    if formato_nuevo:
        # Ya está todo: precio de 1 unidad arriba y las presentaciones se guardan completas abajo
        precio_unidad, precio_maximo_unidad = precio_venta, precio_maximo
    elif defecto and defecto_id != pres.PRINCIPAL and defecto["factor"] > 1:
        factor = defecto["factor"]
        pres_cambios.append((defecto_id, precio_venta, precio_maximo))
        precio_maximo_unidad = round(precio_maximo / factor, 2) if precio_maximo else None
        if p["vende_suelto"] and pres.PRINCIPAL in otros_precios:
            precio_unidad = otros_precios.pop(pres.PRINCIPAL)        # la unidad suelta tiene su precio
        elif p["vende_suelto"]:
            precio_unidad = float(p["precio_venta"] or 0) or round(precio_venta / factor, 2)
        else:
            precio_unidad = round(precio_venta / factor, 2)          # no se vende suelta: sale del sobre
        if precio_maximo_unidad and precio_unidad > precio_maximo_unidad + 0.01:
            return _json_error(f"El precio de la unidad suelta ({pesos(precio_unidad)}) supera el máximo por "
                               f"unidad ({pesos(precio_maximo_unidad)}).")
    else:
        precio_unidad, precio_maximo_unidad = precio_venta, precio_maximo
    for pid_pres, valor in otros_precios.items():
        if pid_pres != pres.PRINCIPAL:
            pres_cambios.append((pid_pres, valor, None))          # None = su máximo no cambia

    # ---- Anotar qué cambió (para la bitácora) ----
    antes = {"nombre": p["nombre"], "codigo_barras": p["codigo_barras"],
             "precio_venta": p["precio_venta"], "precio_maximo": p["precio_maximo"],
             "iva": f"{p['iva_tipo']} {p['iva_tarifa'] or 0:g}%",
             "requiere_formula": p["requiere_formula"], "control_especial": p["control_especial"],
             "maneja_vencimiento": p["maneja_vencimiento"], "imagen": p["imagen"]}
    despues = {"nombre": nombre, "codigo_barras": codigo_barras,
               "precio_venta": precio_unidad, "precio_maximo": precio_maximo_unidad,
               "iva": f"{iva_tipo} {iva_tarifa:g}%",
               "requiere_formula": requiere_formula, "control_especial": control_especial,
               "maneja_vencimiento": maneja_vencimiento, "imagen": ruta_imagen}
    cambios = [f"{k}: {antes[k]} -> {despues[k]}" for k in antes if antes[k] != despues[k]]
    categorias_antes = sorted(r["catalogo_id"] for r in db.execute(
        "SELECT catalogo_id FROM productos_categorias WHERE producto_id = ?", (producto_id,)))
    if categorias_antes != categorias:
        cambios.append(f"categorias: {categorias_antes} -> {categorias}")
    por_id = {o["id"]: o for o in opciones}
    for pid_pres, valor, maximo in pres_cambios:
        o = por_id[pid_pres]
        if abs(o["precio"] - valor) > 0.001:
            cambios.append(f"precio {o['nombre']}: {o['precio']:g} -> {valor:g}")
        if maximo is not None or pid_pres == defecto_id:
            if (o["precio_maximo"] or None) != (maximo or None):
                cambios.append(f"precio máximo {o['nombre']}: {o['precio_maximo'] or '-'} -> {maximo or '-'}")

    db.execute(
        "UPDATE productos SET nombre=?, codigo_barras=?, precio_venta=?, precio_maximo=?, "
        "iva_tipo=?, iva_tarifa=?, requiere_formula=?, control_especial=?, "
        "maneja_vencimiento=?, imagen=?, actualizado_en=? WHERE id=?",
        (nombre, codigo_barras, precio_unidad, precio_maximo_unidad, iva_tipo, iva_tarifa,
         requiere_formula, control_especial, maneja_vencimiento, ruta_imagen, ahora(), producto_id),
    )
    # Precios de las presentaciones (sobre, caja...)
    for pid_pres, valor, maximo in pres_cambios:
        if pid_pres == defecto_id:
            db.execute("UPDATE producto_presentaciones SET precio_venta = ?, precio_maximo = ? "
                       "WHERE id = ? AND producto_id = ?", (valor, maximo or None, pid_pres, producto_id))
        else:
            db.execute("UPDATE producto_presentaciones SET precio_venta = ? WHERE id = ? AND producto_id = ?",
                       (valor, pid_pres, producto_id))
    if formato_nuevo:
        # Presentaciones completas (las borra y las vuelve a crear, como la ficha) y cómo se vende
        texto_pres = pres.guardar(db, producto_id, filas_pres, ahora())
        db.execute("UPDATE productos SET vende_suelto = ?, venta_defecto_unidad_id = ? WHERE id = ?",
                   (vende_suelto, venta_defecto_uid, producto_id))
        if bool(p["vende_suelto"]) != bool(vende_suelto):
            cambios.append(f"vende suelto: {'sí' if vende_suelto else 'no'}")
        if (p["venta_defecto_unidad_id"] or None) != (venta_defecto_uid or None):
            cambios.append(f"se vende por defecto: unidad {venta_defecto_uid or 'principal'}")
        if texto_pres:
            cambios.append(texto_pres.strip())
    db.execute("DELETE FROM productos_categorias WHERE producto_id = ?", (producto_id,))
    for cid in categorias:
        db.execute("INSERT OR IGNORE INTO productos_categorias (producto_id, catalogo_id) "
                   "VALUES (?, ?)", (producto_id, cid))
    db.commit()

    # La foto vieja se borra del disco solo DESPUÉS de guardar bien
    if p["imagen"] and p["imagen"] != ruta_imagen:
        eliminar_imagen(p["imagen"])

    registrar("producto_editado", "productos", producto_id,
              "desde POS · " + ("; ".join(cambios) if cambios else "sin cambios"))
    return jsonify({"ok": True, "cambios": len(cambios)})
