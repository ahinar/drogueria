"""FORMAS DE PAGO Y CUENTAS (versión 1.1.14).

PARA QUÉ (para aprender)
------------------------
Antes cada módulo (POS, gastos, abonos, devoluciones, bancos...) tenía escrita
su propia lista: "efectivo, nequi, davivienda, tarjeta". Para agregar DAVIPLATA
había que cambiar unas 25 listas. Ahora la lista vive AQUÍ y todos la leen de
aquí: para agregar otra cuenta en el futuro, se agrega UNA línea en CUENTAS y
una migración que cree su fila en cuentas_bancarias (ver db.py, migración 43).

LAS PALABRAS
------------
  - CUENTA: un lugar donde queda la plata y que tiene saldo propio en Bancos
    (Nequi, Davivienda, Daviplata). Su "clave" es la palabra que se guarda en la
    base de datos ('nequi', 'davivienda', 'daviplata').
  - FORMA DE PAGO: cómo pagó alguien: efectivo, una de las cuentas, tarjeta,
    transferencia (sin decir a cuál cuenta), crédito (fiado) o mixto.
"""

# Cuentas con saldo propio en Bancos: (clave, nombre, ícono). El ORDEN es el de las pantallas.
CUENTAS = [
    ("nequi", "Nequi", "📱"),
    ("davivienda", "Davivienda", "🏦"),
    ("daviplata", "Daviplata", "🔴"),
]
CLAVES_CUENTAS = tuple(c[0] for c in CUENTAS)            # ('nequi', 'davivienda', 'daviplata')
ICONOS = {c[0]: c[2] for c in CUENTAS}

# Nombre bonito de cada forma de pago (para mostrar en pantallas, tirillas y reportes)
NOMBRES = {
    "efectivo": "Efectivo",
    **{c[0]: c[1] for c in CUENTAS},
    "tarjeta": "Tarjeta",
    "transferencia": "Transferencia",
    "credito": "Crédito (cartera)",
    "mixto": "Mixto (varias formas)",
}

# --- Listas que usa cada parte del programa (todas salen de las de arriba) ---
# Formas con las que se cobra una venta en el POS (sin mixto ni crédito, que son especiales)
FORMAS_VENTA_SIMPLE = ("efectivo",) + CLAVES_CUENTAS + ("tarjeta",)
# Todas las formas posibles de una venta
FORMAS_VENTA = FORMAS_VENTA_SIMPLE + ("credito", "mixto")
# Partes de un pago mixto (el efectivo es "lo que falta")
FORMAS_MIXTO = FORMAS_VENTA_SIMPLE
# Formas que NO son efectivo dentro de un mixto (las casillas que se escriben)
FORMAS_MIXTO_OTRAS = CLAVES_CUENTAS + ("tarjeta",)
# Gastos, otros ingresos y abonos de cartera: además se acepta "transferencia"
FORMAS_MOVIMIENTO = FORMAS_VENTA_SIMPLE + ("transferencia",)
# Entradas y salidas a mano en la caja del POS
FORMAS_CAJA = FORMAS_VENTA_SIMPLE
# Formas con las que se le devuelve plata a un cliente
FORMAS_REEMBOLSO = FORMAS_VENTA_SIMPLE
# De dónde se le paga a un proveedor (app/cuentas_pagar.py)
ORIGENES_PAGO = ("caja_menor", "caja_pos") + CLAVES_CUENTAS + ("otro",)


def nombre(forma):
    """'daviplata' → 'Daviplata'. Si no la conoce, la devuelve igual."""
    return NOMBRES.get(forma, forma or "")


def opciones(formas):
    """Lista de diccionarios {valor, texto} para llenar un <select> o el JS del POS."""
    return [{"valor": f, "texto": nombre(f)} for f in formas]
