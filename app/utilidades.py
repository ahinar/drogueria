"""R2 · Estado de resultados: ¿cuánto ganó de verdad la droguería?

LA CUENTA (de arriba hacia abajo):

      Ventas sin IVA            (lo que se vendió, sin el IVA, que es de la DIAN)
    − Costo de lo vendido       (lo que costó en la compra cada unidad vendida)
    = UTILIDAD BRUTA            (ganancia de la mercancía)
    − Gastos                    (arriendo, servicios, nómina, sueldo del dueño...)
    − Pérdidas de inventario    (vencidos dados de baja, faltantes del conteo)
    = UTILIDAD NETA             (ganancia real del negocio)

    Aparte, solo para información:
      Retiros del dueño         (plata que el dueño se llevó; NO es gasto)
      Queda en el negocio = utilidad neta − retiros del dueño

DE DÓNDE SALE CADA NÚMERO:
    - Ventas: venta_lineas de ventas COMPLETADAS (las anuladas no cuentan).
      "subtotal" de cada línea ya es el valor sin IVA y con el descuento aplicado.
    - Costo: cada línea de venta guarda en lotes_json de qué lotes salió y
      cuántas unidades; se multiplica por el costo_unitario de ese lote.
      Es el costo REAL (no un promedio).
    - Gastos: tabla gastos (activos), agrupados por categoría.
    - Pérdidas: movimientos_inventario de tipo 'ajuste' o 'baja' con cantidad
      NEGATIVA (salió mercancía sin venderse), valorizados al costo del lote.
      Los sobrantes (ajustes positivos) NO se suman como ganancia, porque
      incluyen el inventario inicial cargado con el primer conteo.
    - Retiros del dueño: retiros de caja menor marcados "retiro del dueño".

PERÍODOS:
    Por defecto: el mes actual comparado con el mes anterior. Si el mes actual
    va en curso (por ejemplo, hoy es 9), se compara con los MISMOS días del
    mes anterior (1 al 9), para que la comparación sea justa.
"""
import calendar
import json
from datetime import date, timedelta

from .db import get_db

MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


# ======================================================================
# 1. PERÍODOS
# ======================================================================

def _fecha(texto):
    """'2026-10-09' -> date, o None si no es una fecha válida."""
    try:
        return date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def _corta(d):
    """date -> '09/10/2026'"""
    return d.strftime("%d/%m/%Y")


def _rango_txt(desde, hasta):
    """Texto bonito para un rango: '1 al 9 de octubre de 2026', 'octubre de 2026'..."""
    ultimo = calendar.monthrange(hasta.year, hasta.month)[1]
    if desde.day == 1 and desde.year == hasta.year and desde.month == hasta.month:
        if hasta.day == ultimo:
            return f"{MESES[desde.month]} de {desde.year}"
        return f"1 al {hasta.day} de {MESES[desde.month]} de {desde.year}"
    return f"{_corta(desde)} al {_corta(hasta)}"


def periodos(mes=None, desde=None, hasta=None, hoy=None):
    """Decide qué período mostrar y con cuál compararlo.

    - desde y hasta (ambos válidos): rango libre; se compara con el rango de
      igual duración que termina justo el día anterior.
    - mes = 'AAAA-MM': ese mes; se compara con el mes anterior.
    - nada: el mes actual.
    Devuelve un diccionario con 'actual' y 'anterior', cada uno con desde,
    hasta y un texto para mostrar.
    """
    hoy = hoy or date.today()
    d, h = _fecha(desde), _fecha(hasta)

    if d and h:
        if d > h:
            d, h = h, d
        dias = (h - d).days + 1
        prev_h = d - timedelta(days=1)
        prev_d = prev_h - timedelta(days=dias - 1)
        modo = "rango"
    else:
        # Mes pedido o el actual
        try:
            anio, numero = (int(x) for x in (mes or "").split("-"))
            d = date(anio, numero, 1)
        except (ValueError, TypeError):
            d = hoy.replace(day=1)
        ultimo = calendar.monthrange(d.year, d.month)[1]
        h = d.replace(day=ultimo)
        en_curso = d <= hoy <= h
        if en_curso:
            h = hoy                                 # el mes va hasta hoy
        prev_h = d - timedelta(days=1)              # último día del mes anterior
        prev_d = prev_h.replace(day=1)
        if en_curso:
            # Mismos días del mes anterior (si el mes anterior es más corto, hasta su fin)
            prev_h = prev_d.replace(day=min(hoy.day, prev_h.day))
        modo = "mes"

    return {
        "modo": modo,
        "mes": d.strftime("%Y-%m") if modo == "mes" else "",
        "actual": {"desde": d, "hasta": h, "texto": _rango_txt(d, h)},
        "anterior": {"desde": prev_d, "hasta": prev_h, "texto": _rango_txt(prev_d, prev_h)},
    }


def meses_disponibles(hoy=None, cuantos=12):
    """Los últimos 12 meses para el selector: [('2026-10', 'octubre de 2026'), ...]"""
    hoy = hoy or date.today()
    salida, d = [], hoy.replace(day=1)
    for _ in range(cuantos):
        salida.append((d.strftime("%Y-%m"), f"{MESES[d.month]} de {d.year}"))
        d = (d - timedelta(days=1)).replace(day=1)
    return salida


# ======================================================================
# 2. EL CÁLCULO
# ======================================================================

def calcular(desde, hasta):
    """Estado de resultados entre dos fechas (ambas incluidas)."""
    db = get_db()
    # Las fechas se guardan como texto 'AAAA-MM-DD HH:MM:SS'. Para incluir TODO
    # el último día, se pide "fecha < día siguiente".
    ini = desde.isoformat()
    fin = (hasta + timedelta(days=1)).isoformat()

    # ---- 2.1 Ventas y costo de lo vendido ----
    lineas = db.execute(
        "SELECT vl.subtotal, vl.iva_valor, vl.total, vl.descuento_linea, vl.lotes_json, vl.venta_id "
        "FROM venta_lineas vl JOIN ventas v ON v.id = vl.venta_id "
        "WHERE v.estado = 'completada' AND v.fecha >= ? AND v.fecha < ?", (ini, fin)).fetchall()

    # Costo de cada lote, leído una sola vez: {lote_id: costo_unitario}
    lotes_usados = set()
    for ln in lineas:
        for a in json.loads(ln["lotes_json"] or "[]"):
            lotes_usados.add(a["lote_id"])
    costos = {}
    if lotes_usados:
        marcas = ",".join("?" * len(lotes_usados))
        costos = {f["id"]: float(f["costo_unitario"] or 0) for f in db.execute(
            f"SELECT id, costo_unitario FROM lotes WHERE id IN ({marcas})", list(lotes_usados))}

    ventas = iva = total_con_iva = descuentos = costo = 0.0
    lineas_sin_costo = 0     # líneas cuyo lote tiene costo $0 (la utilidad sale "inflada")
    for ln in lineas:
        ventas += ln["subtotal"]
        iva += ln["iva_valor"]
        total_con_iva += ln["total"]
        descuentos += ln["descuento_linea"]
        costo_linea = sum(a["cantidad"] * costos.get(a["lote_id"], 0)
                          for a in json.loads(ln["lotes_json"] or "[]"))
        if costo_linea <= 0:
            lineas_sin_costo += 1
        costo += costo_linea
    n_ventas = len({ln["venta_id"] for ln in lineas})

    # ---- 2.1b Devoluciones de clientes (se restan de las ventas) ----
    # Lo devuelto se resta de las ventas. Si el producto volvió al inventario
    # también se resta su costo; si se dio de baja, el costo se queda (pérdida).
    dev = db.execute(
        "SELECT COALESCE(SUM(l.subtotal), 0) AS subtotal, "
        "       COALESCE(SUM(CASE WHEN l.destino = 'reingreso' THEN l.costo ELSE 0 END), 0) AS costo_reingreso "
        "FROM devolucion_lineas l JOIN devoluciones d ON d.id = l.devolucion_id "
        "WHERE d.tipo = 'cliente' AND d.fecha >= ? AND d.fecha < ?", (ini, fin)).fetchone()
    devoluciones = float(dev["subtotal"])
    costo -= float(dev["costo_reingreso"])

    # ---- 2.2 Gastos por categoría (con el detalle de cada gasto) ----
    gastos_filas = db.execute(
        "SELECT g.id, g.fecha, g.descripcion, g.monto, g.forma_pago, "
        "       COALESCE(c.nombre, 'Sin categoría') AS categoria "
        "FROM gastos g LEFT JOIN catalogos c ON c.id = g.categoria_id "
        "WHERE g.activo = 1 AND g.fecha >= ? AND g.fecha < ? "
        "ORDER BY g.fecha", (ini, fin)).fetchall()
    por_categoria = {}
    for gf in gastos_filas:
        cat = por_categoria.setdefault(gf["categoria"], {"categoria": gf["categoria"], "total": 0.0, "detalle": []})
        cat["total"] += gf["monto"]
        cat["detalle"].append(dict(gf))
    gastos = sorted(por_categoria.values(), key=lambda c: -c["total"])
    total_gastos = sum(c["total"] for c in gastos)

    # ---- 2.3 Pérdidas de inventario (salió mercancía sin venderse) ----
    perdidas_filas = db.execute(
        "SELECT m.cantidad, m.referencia, COALESCE(l.costo_unitario, 0) AS costo "
        "FROM movimientos_inventario m LEFT JOIN lotes l ON l.id = m.lote_id "
        "WHERE m.tipo IN ('ajuste', 'baja') AND m.cantidad < 0 "
        "AND m.fecha >= ? AND m.fecha < ?", (ini, fin)).fetchall()
    faltantes_conteo = sum(-f["cantidad"] * f["costo"] for f in perdidas_filas
                           if (f["referencia"] or "").startswith("Conteo"))
    bajas = sum(-f["cantidad"] * f["costo"] for f in perdidas_filas
                if not (f["referencia"] or "").startswith("Conteo"))
    total_perdidas = faltantes_conteo + bajas

    # ---- 2.4 Retiros del dueño (informativo) ----
    retiros = db.execute(
        "SELECT COALESCE(SUM(monto), 0) FROM caja_menor_movimientos "
        "WHERE tipo = 'retiro' AND retiro_dueno = 1 AND fecha >= ? AND fecha < ?",
        (ini, fin)).fetchone()[0]

    # ---- 2.5 Resultados ----
    utilidad_bruta = ventas - devoluciones - costo
    utilidad_neta = utilidad_bruta - total_gastos - total_perdidas
    netas = ventas - devoluciones          # los márgenes se calculan sobre las ventas netas
    pct = lambda parte: (parte / netas * 100) if netas else 0

    return {
        "desde": desde, "hasta": hasta,
        "n_ventas": n_ventas,
        "ticket_promedio": (total_con_iva / n_ventas) if n_ventas else 0,
        "total_con_iva": total_con_iva, "iva": iva, "descuentos": descuentos,
        "ventas": ventas,
        "devoluciones": devoluciones,
        "costo": costo,
        "utilidad_bruta": utilidad_bruta, "margen_bruto": pct(utilidad_bruta),
        "gastos": gastos, "total_gastos": total_gastos,
        "faltantes_conteo": faltantes_conteo, "bajas": bajas, "total_perdidas": total_perdidas,
        "utilidad_neta": utilidad_neta, "margen_neto": pct(utilidad_neta),
        "retiros_dueno": float(retiros),
        "queda": utilidad_neta - float(retiros),
        "lineas_sin_costo": lineas_sin_costo,
    }


def variacion(actual, anterior):
    """Cambio en % de anterior a actual. None si no se puede calcular (anterior = 0)."""
    if not anterior:
        return None
    return (actual - anterior) / abs(anterior) * 100


def estado_de_resultados(mes=None, desde=None, hasta=None, hoy=None):
    """Todo lo que necesita la pantalla y el PDF: período, cálculo y comparación."""
    per = periodos(mes, desde, hasta, hoy)
    actual = calcular(per["actual"]["desde"], per["actual"]["hasta"])
    anterior = calcular(per["anterior"]["desde"], per["anterior"]["hasta"])

    # Gastos del período anterior por categoría, para comparar fila por fila
    gastos_ant = {c["categoria"]: c["total"] for c in anterior["gastos"]}
    categorias = [c["categoria"] for c in actual["gastos"]] + \
                 [n for n in gastos_ant if n not in {c["categoria"] for c in actual["gastos"]}]
    filas_gastos = []
    for nombre in categorias:
        act = next((c for c in actual["gastos"] if c["categoria"] == nombre), None)
        filas_gastos.append({
            "categoria": nombre,
            "actual": act["total"] if act else 0,
            "anterior": gastos_ant.get(nombre, 0),
            "detalle": act["detalle"] if act else [],
        })

    return {"periodo": per, "actual": actual, "anterior": anterior, "filas_gastos": filas_gastos}
