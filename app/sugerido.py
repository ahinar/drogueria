"""R6 · Sugerido de compra: ¿qué pedir, cuánto y a quién?

LA IDEA (para aprender):
    Para cada producto activo se miran tres cosas:
      1. STOCK: unidades que se pueden vender hoy (lotes disponibles y sin vencer;
         no cuenta cuarentena, bloqueados ni vencidos).
      2. VENTA DIARIA: unidades vendidas en los últimos 30 días ÷ 30.
         (Si vendió 2 cajas x 100, cuenta 200 unidades: cantidad × factor.)
      3. STOCK MÍNIMO: el que se definió en el producto.

    Con eso:
      - Días que alcanza = stock ÷ venta diaria  (ej: 40 und ÷ 5 al día = 8 días)
      - Lo que se quiere tener = lo que se vende en N días (cobertura, por defecto 15)
                                 pero nunca menos que el stock mínimo
      - Sugerido = lo que se quiere tener − stock  (si da negativo, no se pide)

    Ejemplo: vende 5 al día, cobertura 15 días -> quiere 75. Tiene 40 -> pedir 35.

    Si un producto NO tiene ventas todavía (por ejemplo, las primeras semanas
    después del inventario inicial), se guía solo por el stock mínimo.

    PROVEEDOR (versión 1.1.12, pedido de Fernando): el MÁS BARATO. Para cada
    proveedor que alguna vez le vendió el producto se mira el ÚLTIMO precio que le
    cobró, por unidad de inventario (tableta, frasco...: así se pueden comparar
    aunque uno venda por caja y otro por sello) y CON IVA (lo que de verdad se paga).
    Se sugiere el más barato y se muestran los otros con la fecha de ese precio.
    Si Fernando escoge otro a mano, queda guardado en productos.proveedor_preferido_id
    y se respeta hasta que vuelva a poner "Automático".
    (Antes era siempre el de la última compra.)

LISTAS QUE ARMA:
    - pedido:        lo que hay que pedir, agrupado por proveedor
    - se_agota:      se acaba en menos de 7 días al ritmo actual
    - bajo_minimo:   en o por debajo del stock mínimo
    - sin_rotacion:  tiene stock pero no se vendió nada en 60 (o 90) días:
                     plata quieta en la estantería (y riesgo de vencimiento)
"""
import math
from datetime import date, timedelta

from .db import get_db

DIAS_HISTORIAL = 30      # para calcular la venta diaria
DIAS_SE_AGOTA = 7        # "se agota pronto" = menos de una semana


def _presentacion_mayor(db):
    """{producto_id: (nombre, factor)} de la presentación más grande (ej: Caja x 100).

    Sirve para mostrar el sugerido también en cajas: 250 und ≈ 2,5 Caja x 100.
    """
    salida = {}
    for f in db.execute(
            "SELECT pp.producto_id, u.nombre, pp.factor FROM producto_presentaciones pp "
            "JOIN unidades_medida u ON u.id = pp.unidad_id ORDER BY pp.factor"):
        salida[f["producto_id"]] = (f["nombre"], f["factor"])   # queda la de factor más alto
    return salida


def precios_por_proveedor(db):
    """{producto_id: [{proveedor_id, proveedor, costo, fecha}, ...]} del más barato al más caro.

    costo = el ÚLTIMO precio que cobró cada proveedor por UNA unidad de inventario,
    con IVA (recepcion_lineas.costo_con_iva; las líneas viejas usan costo_unitario).
    Cuentan las recepciones aprobadas o en cuarentena (no las rechazadas) y las
    líneas que no se rechazaron.
    """
    ultimos = {}
    for f in db.execute(
            "SELECT rl.producto_id, r.proveedor_id, p.razon_social, r.fecha, "
            "       COALESCE(rl.costo_con_iva, rl.costo_unitario) AS costo "
            "FROM recepcion_lineas rl JOIN recepciones r ON r.id = rl.recepcion_id "
            "JOIN proveedores p ON p.id = r.proveedor_id "
            "WHERE r.estado IN ('aprobada', 'cuarentena') AND rl.resultado <> 'rechazado' "
            "  AND COALESCE(rl.costo_con_iva, rl.costo_unitario) > 0 "
            "ORDER BY r.fecha DESC, r.id DESC, rl.id DESC"):
        clave = (f["producto_id"], f["proveedor_id"])
        if clave not in ultimos:                      # la primera que aparece es la más reciente
            ultimos[clave] = {"proveedor_id": f["proveedor_id"], "proveedor": f["razon_social"],
                              "costo": float(f["costo"]), "fecha": f["fecha"][:10]}
    salida = {}
    for (producto_id, _), opcion in ultimos.items():
        salida.setdefault(producto_id, []).append(opcion)
    for opciones in salida.values():
        opciones.sort(key=lambda o: (o["costo"], o["fecha"]))   # el más barato primero
    return salida


def calcular(cobertura=15, dias_sin_rotacion=60, hoy=None):
    """Arma todas las listas del sugerido de compra."""
    db = get_db()
    hoy = hoy or date.today()
    hoy_txt = hoy.isoformat()
    desde_ventas = (hoy - timedelta(days=DIAS_HISTORIAL)).isoformat()
    desde_rotacion = (hoy - timedelta(days=dias_sin_rotacion)).isoformat()

    # Una sola consulta con todo lo necesario por producto.
    #  - stock:      lotes vendibles hoy
    #  - vendido_30: unidades vendidas en 30 días (ventas no anuladas)
    #  - ultima_venta: fecha de la última venta (para "sin rotación")
    #  - proveedor y costo: de la última recepción aprobada del producto
    filas = db.execute(
        """
        SELECT p.id, p.codigo, p.nombre, p.concentracion, p.stock_minimo,
               COALESCE(u.nombre, 'Unidad') AS unidad,
               COALESCE((SELECT SUM(l.cantidad_disponible) FROM lotes l
                  WHERE l.producto_id = p.id AND l.estado = 'disponible' AND l.cantidad_disponible > 0
                  AND (l.vencimiento IS NULL OR l.vencimiento = '' OR l.vencimiento >= :hoy)), 0) AS stock,
               COALESCE((SELECT SUM(l.cantidad_disponible * l.costo_unitario) FROM lotes l
                  WHERE l.producto_id = p.id AND l.estado = 'disponible' AND l.cantidad_disponible > 0
                  AND (l.vencimiento IS NULL OR l.vencimiento = '' OR l.vencimiento >= :hoy)), 0) AS valor_stock,
               COALESCE((SELECT SUM(vl.cantidad * COALESCE(vl.factor, 1)) FROM venta_lineas vl
                  JOIN ventas v ON v.id = vl.venta_id
                  WHERE vl.producto_id = p.id AND v.estado = 'completada' AND v.fecha >= :desde_ventas), 0) AS vendido,
               (SELECT MAX(v.fecha) FROM venta_lineas vl JOIN ventas v ON v.id = vl.venta_id
                  WHERE vl.producto_id = p.id AND v.estado = 'completada') AS ultima_venta,
               (SELECT r.proveedor_id FROM recepcion_lineas rl JOIN recepciones r ON r.id = rl.recepcion_id
                  WHERE rl.producto_id = p.id AND r.estado = 'aprobada'
                  ORDER BY r.fecha DESC, r.id DESC LIMIT 1) AS proveedor_id,
               (SELECT rl.costo_unitario FROM recepcion_lineas rl JOIN recepciones r ON r.id = rl.recepcion_id
                  WHERE rl.producto_id = p.id AND r.estado = 'aprobada'
                  ORDER BY r.fecha DESC, r.id DESC LIMIT 1) AS ultimo_costo,
               p.precio_compra, p.proveedor_preferido_id
        FROM productos p
        LEFT JOIN unidades_medida u ON u.id = p.unidad_venta_id
        WHERE p.activo = 1
        ORDER BY p.nombre COLLATE ES
        """,
        {"hoy": hoy_txt, "desde_ventas": desde_ventas}).fetchall()

    proveedores = {f["id"]: dict(f) for f in db.execute(
        "SELECT id, razon_social, telefono, contacto FROM proveedores")}
    mayores = _presentacion_mayor(db)
    precios = precios_por_proveedor(db)

    pedido, se_agota, bajo_minimo, sin_rotacion = {}, [], [], []
    for f in filas:
        stock = float(f["stock"])
        minimo = float(f["stock_minimo"] or 0)
        diaria = float(f["vendido"]) / DIAS_HISTORIAL
        dias_alcanza = (stock / diaria) if diaria > 0 else None
        # ---- A quién pedirle (versión 1.1.12): el escogido a mano, o el más barato ----
        opciones = precios.get(f["id"], [])
        preferido = f["proveedor_preferido_id"]
        if preferido and preferido in proveedores:
            proveedor_id, eleccion = preferido, "manual"
        elif opciones:
            proveedor_id, eleccion = opciones[0]["proveedor_id"], "barato"
        else:
            proveedor_id, eleccion = f["proveedor_id"], "ultimo"    # nunca se ha comprado con precio
        escogida = next((o for o in opciones if o["proveedor_id"] == proveedor_id), None)
        costo = escogida["costo"] if escogida else float(f["ultimo_costo"] or f["precio_compra"] or 0)

        # ---- Cuánto pedir ----
        objetivo = max(diaria * cobertura, minimo)
        sugerido = math.ceil(objetivo - stock) if objetivo - stock > 1e-9 else 0

        item = {
            "id": f["id"], "codigo": f["codigo"],
            "nombre": f["nombre"] + (f" {f['concentracion']}" if f["concentracion"] else ""),
            "unidad": f["unidad"], "stock": stock, "minimo": minimo,
            "diaria": diaria, "dias_alcanza": dias_alcanza,
            "sugerido": sugerido, "costo": costo, "subtotal": sugerido * costo,
            "valor_stock": float(f["valor_stock"]),
            "ultima_venta": f["ultima_venta"],
            "motivo": ("ventas" if diaria > 0 else "mínimo"),   # por qué se sugiere
            "en_presentacion": None,
            # Proveedores con su último precio (el más barato primero) y cuál se escogió
            "opciones": opciones, "proveedor_id": proveedor_id or 0, "eleccion": eleccion,
        }
        if f["id"] in mayores and sugerido:
            nombre_pres, factor = mayores[f["id"]]
            cajas = sugerido / factor
            if cajas >= 0.1:     # "≈ 0,0 cajas" no le sirve a nadie
                texto = f"{cajas:.1f}".replace(".", ",")
                if texto.endswith(",0"):
                    texto = texto[:-2]          # 3,0 -> 3
                item["en_presentacion"] = f"≈ {texto} {nombre_pres}"

        if sugerido > 0:
            prov = proveedores.get(proveedor_id)
            clave = prov["id"] if prov else 0
            grupo = pedido.setdefault(clave, {
                "proveedor": prov["razon_social"] if prov else "Sin proveedor (nunca se ha comprado)",
                "proveedor_id": clave,
                "telefono": (prov or {}).get("telefono") or "",
                "contacto": (prov or {}).get("contacto") or "",
                "items": [], "total": 0.0,
            })
            grupo["items"].append(item)
            grupo["total"] += item["subtotal"]

        if dias_alcanza is not None and dias_alcanza < DIAS_SE_AGOTA:
            se_agota.append(item)
        if minimo > 0 and stock <= minimo:
            bajo_minimo.append(item)
        if stock > 0 and (not f["ultima_venta"] or f["ultima_venta"] < desde_rotacion):
            sin_rotacion.append(item)

    # Proveedores con más plata a pedir primero; "sin proveedor" al final
    grupos = sorted(pedido.values(), key=lambda g: (g["proveedor_id"] == 0, -g["total"]))
    se_agota.sort(key=lambda i: i["dias_alcanza"])
    sin_rotacion.sort(key=lambda i: -i["valor_stock"])

    return {
        "cobertura": cobertura, "dias_sin_rotacion": dias_sin_rotacion,
        "dias_historial": DIAS_HISTORIAL, "dias_se_agota": DIAS_SE_AGOTA,
        "pedido": grupos,
        "total_pedido": sum(g["total"] for g in grupos),
        "n_items": sum(len(g["items"]) for g in grupos),
        "se_agota": se_agota, "bajo_minimo": bajo_minimo,
        "sin_rotacion": sin_rotacion,
        "valor_sin_rotacion": sum(i["valor_stock"] for i in sin_rotacion),
        "hay_ventas": any(f["vendido"] for f in filas),
    }


def telefono_whatsapp(telefono):
    """'300 123 4567' -> '573001234567' (para el enlace wa.me). '' si no sirve."""
    digitos = "".join(c for c in (telefono or "") if c.isdigit())
    if len(digitos) == 10 and digitos.startswith("3"):    # celular colombiano sin indicativo
        return "57" + digitos
    if len(digitos) == 12 and digitos.startswith("57"):
        return digitos
    return ""
