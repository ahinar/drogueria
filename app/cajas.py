"""
SESIONES DE CAJA Y SUS DIFERENCIAS (versión 1.1.6)
=================================================

PARA QUÉ (para aprender):
    Cada vez que se abre y se cierra la caja del POS queda una "sesión de caja"
    (tabla cajas). Al cerrarla se cuenta el efectivo y se compara con el que
    DEBERÍA haber (efectivo esperado):

        diferencia = efectivo contado − efectivo esperado
            = 0   → cuadró          (se muestra en AZUL)
            < 0   → FALTÓ plata     (ROJO, con signo −)
            > 0   → SOBRÓ plata     (VERDE, con signo +)

    ¿Dónde queda esa diferencia en la contabilidad? Como en cualquier negocio:
        - un SOBRANTE es un OTRO INGRESO (categoría "Sobrante de caja")
        - un FALTANTE es un GASTO        (categoría "Faltante de caja")
    Así la UTILIDAD refleja la plata que de verdad hay.

    OJO: es solo un APUNTE contable. No se mueve plata de ninguna caja, porque
    el efectivo contado ya volvió a la caja menor al cerrar (ver pos.api_cerrar_caja).
    Si se moviera plata otra vez, se contaría doble.

    registrar_diferencia() lo hace para UNA caja (se llama al cerrarla).
    registrar_pendientes() lo hace para TODAS las cajas cerradas que no lo
    tengan todavía (las que se cerraron antes de la versión 1.1.6). Se llama al
    arrancar el programa. Nunca registra dos veces la misma caja
    (columna cajas.diferencia_revisada).
"""
from .db import ahora

CATEGORIA_SOBRANTE = "Sobrante de caja"      # categoría de OTROS INGRESOS
CATEGORIA_FALTANTE = "Faltante de caja"      # categoría de GASTOS


def _categoria(db, tipo, nombre):
    """Id de la categoría (la crea si no existe). tipo = 'categoria_gasto' o 'categoria_ingreso'."""
    from .nombres import catalogo_igual
    fila = catalogo_igual(db, tipo, nombre)
    if fila:
        if not fila["activo"]:
            db.execute("UPDATE catalogos SET activo = 1 WHERE id = ?", (fila["id"],))
        return fila["id"]
    return db.execute("INSERT INTO catalogos (tipo, nombre, descripcion, activo, creado_en) VALUES (?, ?, ?, 1, ?)",
                      (tipo, nombre, "Lo registra solo el programa al cerrar la caja del POS", ahora())).lastrowid


def registrar_diferencia(db, caja_id):
    """Apunta el sobrante (ingreso) o el faltante (gasto) de una caja cerrada. No hace commit."""
    caja = db.execute("SELECT * FROM cajas WHERE id = ?", (caja_id,)).fetchone()
    if caja is None or caja["estado"] != "cerrada" or caja["diferencia_revisada"]:
        return
    diferencia = round(float(caja["diferencia"] or 0), 2)
    gasto_id = ingreso_id = None
    fecha = caja["cerrada_en"] or ahora()
    quien = caja["cerrada_por_nombre"] or "—"
    texto = f"Caja POS #{caja['numero']} · cerró {quien}"
    if diferencia >= 0.5:                     # SOBRÓ plata → otro ingreso
        ingreso_id = db.execute(
            "INSERT INTO otros_ingresos (fecha, categoria_id, descripcion, monto, forma_pago, origen, caja_id, "
            "comprobante, observaciones, usuario_id, usuario_nombre, activo, creado_en) "
            "VALUES (?, ?, ?, ?, 'efectivo', 'ninguna', ?, ?, ?, ?, ?, 1, ?)",
            (fecha, _categoria(db, "categoria_ingreso", CATEGORIA_SOBRANTE),
             f"Sobrante de caja · {texto}", diferencia, caja_id, f"Caja {caja['numero']}",
             "Registrado solo por el programa al cerrar la caja (no mueve plata).",
             caja["cerrada_por"], quien, ahora())).lastrowid
    elif diferencia <= -0.5:                  # FALTÓ plata → gasto
        gasto_id = db.execute(
            "INSERT INTO gastos (fecha, categoria_id, descripcion, monto, forma_pago, comprobante, observaciones, "
            "usuario_id, usuario_nombre, activo, creado_en, origen, caja_id) "
            "VALUES (?, ?, ?, ?, 'efectivo', ?, ?, ?, ?, 1, ?, 'general', ?)",
            (fecha, _categoria(db, "categoria_gasto", CATEGORIA_FALTANTE),
             f"Faltante de caja · {texto}", -diferencia, f"Caja {caja['numero']}",
             "Registrado solo por el programa al cerrar la caja (no mueve plata).",
             caja["cerrada_por"], quien, ahora(), caja_id)).lastrowid
    db.execute("UPDATE cajas SET diferencia_revisada = 1, diferencia_gasto_id = ?, diferencia_ingreso_id = ? "
               "WHERE id = ?", (gasto_id, ingreso_id, caja_id))


def registrar_pendientes(db):
    """Registra las diferencias de TODAS las cajas cerradas que aún no se revisaron. Hace commit."""
    pendientes = [f["id"] for f in db.execute(
        "SELECT id FROM cajas WHERE estado = 'cerrada' AND COALESCE(diferencia_revisada, 0) = 0")]
    for caja_id in pendientes:
        registrar_diferencia(db, caja_id)
    if pendientes:
        db.commit()
    return len(pendientes)


def clase_diferencia(diferencia):
    """Color de la diferencia: 'cuadra' (azul), 'falta' (rojo) o 'sobra' (verde). None si la caja sigue abierta."""
    if diferencia is None:
        return None
    if diferencia <= -0.5:
        return "falta"
    if diferencia >= 0.5:
        return "sobra"
    return "cuadra"


def resumen_sesion(db, caja):
    """Todo lo de una sesión de caja: ventas por forma de pago, esperado, contado y diferencia.

    Para las cajas CERRADAS se usan el contado y la diferencia que quedaron guardados al
    cerrar (así el número no cambia si después se anula una venta). El esperado sale de
    ahí: esperado = contado − diferencia.
    """
    from .pos import _resumen_caja
    r = _resumen_caja(caja)
    if caja["estado"] == "cerrada" and caja["efectivo_contado"] is not None:
        contado = float(caja["efectivo_contado"])
        diferencia = float(caja["diferencia"] or 0)
        esperado = contado - diferencia
    else:
        contado = diferencia = None
        esperado = r["efectivo_esperado"]
    return {
        "caja": caja,
        "n_ventas": r["n_ventas"],
        "total_ventas": r["total_ventas"],
        "por_forma": {
            "efectivo": r["ventas_efectivo"], "nequi": r["ventas_nequi"],
            "davivienda": r["ventas_davivienda"], "tarjeta": r["ventas_tarjeta"], "credito": r["ventas_credito"],
        },
        "efectivo_inicial": r["efectivo_inicial"],
        "ingresos_efectivo": r["ingresos_efectivo"],
        "salidas_efectivo": r["salidas_efectivo"],
        "movimientos": r["movimientos"],
        "esperado": esperado,
        "contado": contado,
        "diferencia": diferencia,
        "clase": clase_diferencia(diferencia),
    }
