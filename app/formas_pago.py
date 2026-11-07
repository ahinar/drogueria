"""FORMAS DE PAGO Y CUENTAS (versión 1.1.14; configurables desde la 1.1.17).

PARA QUÉ (para aprender)
------------------------
Antes cada módulo (POS, gastos, abonos, devoluciones, bancos...) tenía escrita
su propia lista: "efectivo, nequi, davivienda, tarjeta". En la 1.1.14 la lista
pasó a vivir AQUÍ y todos la leen de aquí.

Versión 1.1.17 (pedido de Fernando): las CUENTAS ya no están escritas en el
código. Viven en la tabla cuentas_bancarias y se manejan en
Configuración → Formas de pago (app/formas_pago_config.py):
  - agregar una cuenta nueva (Bancolombia, Nu...) con su ícono,
  - ocultar una forma de pago que no se usa (ej. Tarjeta): deja de ofrecerse
    para cobrar, pero NO se borra: lo viejo sigue en reportes y en Bancos,
  - cambiar el orden de las cuentas.

LAS PALABRAS
------------
  - CUENTA: un lugar donde queda la plata y que tiene saldo propio en Bancos
    (Nequi, Davivienda, Daviplata...). Su "clave" es la palabra que se guarda en
    la base de datos ('nequi', 'davivienda', 'bancolombia'...).
  - FORMA DE PAGO: cómo pagó alguien: efectivo, una de las cuentas, tarjeta,
    transferencia (sin decir a cuál cuenta), crédito (fiado) o mixto.

CÓMO SE USA (igual que antes, para no tener que cambiar todo el programa)
------------------------------------------------------------------------
    from . import formas_pago as fp
    fp.CLAVES_CUENTAS      → ('nequi', 'davivienda', 'daviplata')   (las VISIBLES, en su orden)
    fp.FORMAS_VENTA        → ('efectivo', 'nequi', ..., 'tarjeta', 'credito', 'mixto')
    fp.nombre('daviplata') → 'Daviplata'   (también de las ocultas, para lo viejo)
Esos nombres en MAYÚSCULA ya no son listas fijas: se calculan cada vez con lo que
haya en la base de datos (función __getattr__ de abajo). Dentro de una misma
página se calculan una sola vez (se guardan en flask.g).
"""
from flask import g, has_app_context

# Las formas que no son cuentas. Efectivo no se puede ocultar (siempre hay caja).
FIJAS = {
    "efectivo": ("Efectivo", "💵"),
    "tarjeta": ("Tarjeta", "💳"),
    "transferencia": ("Transferencia", "🔁"),
    "credito": ("Crédito (cartera)", "📒"),
    "mixto": ("Mixto (varias formas)", "🔀"),
}
OCULTABLES = ("tarjeta", "transferencia", "credito", "mixto")
# Palabras que el programa ya usa para otras cosas: una cuenta nueva no puede llamarse así
RESERVADAS = set(FIJAS) | {"caja_menor", "caja_pos", "otro", "dueno", "cuenta"}

# Por si se usa sin base de datos (al arrancar, en pruebas sueltas): las de siempre
_CUENTAS_INICIALES = [
    {"clave": "nequi", "nombre": "Nequi", "icono": "📱", "oculta": False},
    {"clave": "davivienda", "nombre": "Davivienda", "icono": "🏦", "oculta": False},
    {"clave": "daviplata", "nombre": "Daviplata", "icono": "🔴", "oculta": False},
]


def _leer():
    """Lee de la base de datos las cuentas y las formas ocultas (una vez por página)."""
    if not has_app_context():
        return {"cuentas": _CUENTAS_INICIALES, "ocultas": set()}
    if "_formas_pago" in g:
        return g._formas_pago
    from .db import get_db
    db = get_db()
    try:
        filas = db.execute("SELECT clave, nombre, COALESCE(icono, '🏦') AS icono, COALESCE(oculta, 0) AS oculta "
                           "FROM cuentas_bancarias WHERE activa = 1 ORDER BY COALESCE(orden, id), id").fetchall()
        cuentas = [{"clave": f["clave"], "nombre": f["nombre"], "icono": f["icono"], "oculta": bool(f["oculta"])}
                   for f in filas]
        fila = db.execute("SELECT valor FROM config WHERE clave = 'formas_ocultas'").fetchone()
        ocultas = {x for x in ((fila[0] if fila else "") or "").split(",") if x in OCULTABLES}
    except Exception:                    # (base de datos vieja, todavía sin migrar)
        cuentas, ocultas = _CUENTAS_INICIALES, set()
    g._formas_pago = {"cuentas": cuentas, "ocultas": ocultas}
    return g._formas_pago


def olvidar():
    """Después de cambiar algo en Configuración: que la próxima lectura vaya a la base de datos."""
    if has_app_context():
        g.pop("_formas_pago", None)


def cuentas(incluir_ocultas=False):
    """[{clave, nombre, icono, oculta}, ...] en el orden escogido."""
    return [c for c in _leer()["cuentas"] if incluir_ocultas or not c["oculta"]]


def visible(forma):
    """¿Se ofrece esta forma de pago para registrar cosas nuevas?"""
    if forma == "efectivo":
        return True
    if forma in FIJAS:
        return forma not in _leer()["ocultas"]
    return any(c["clave"] == forma for c in cuentas())


def _si_visibles(*formas):
    return tuple(f for f in formas if visible(f))


def nombre(forma):
    """'daviplata' → 'Daviplata'. Sirve también para las ocultas. Si no la conoce, la devuelve igual."""
    if forma in FIJAS:
        return FIJAS[forma][0]
    for c in cuentas(incluir_ocultas=True):
        if c["clave"] == forma:
            return c["nombre"]
    return forma or ""


def icono(forma):
    if forma in FIJAS:
        return FIJAS[forma][1]
    return next((c["icono"] for c in cuentas(incluir_ocultas=True) if c["clave"] == forma), "🏦")


def opciones(formas):
    """Lista de diccionarios {valor, texto} para llenar un <select> o el JS del POS."""
    return [{"valor": f, "texto": nombre(f)} for f in formas]


def __getattr__(nombre_lista):
    """Las listas de siempre (fp.CLAVES_CUENTAS, fp.FORMAS_VENTA...), calculadas en el momento.

    Python llama esta función cuando se pide algo que no existe en el archivo
    (por ejemplo fp.FORMAS_VENTA). Así cada lista sale con lo que haya HOY en
    Configuración, sin que los demás módulos tengan que cambiar.
    """
    if nombre_lista not in _LISTAS:          # (Python también pregunta cosas como __path__)
        raise AttributeError(f"formas_pago no tiene «{nombre_lista}»")
    claves = tuple(c["clave"] for c in cuentas())
    simples = ("efectivo",) + claves + _si_visibles("tarjeta")
    listas = {
        "CUENTAS": [(c["clave"], c["nombre"], c["icono"]) for c in cuentas()],
        "CLAVES_CUENTAS": claves,
        # Todas las cuentas, también las ocultas (para mostrar lo viejo en Bancos y reportes)
        "TODAS_LAS_CUENTAS": tuple(c["clave"] for c in cuentas(incluir_ocultas=True)),
        "ICONOS": {c["clave"]: c["icono"] for c in cuentas(incluir_ocultas=True)},
        "NOMBRES": {**{k: v[0] for k, v in FIJAS.items()},
                    **{c["clave"]: c["nombre"] for c in cuentas(incluir_ocultas=True)}},
        "FORMAS_VENTA_SIMPLE": simples,
        "FORMAS_VENTA": simples + _si_visibles("credito", "mixto"),
        "FORMAS_MIXTO": simples,
        "FORMAS_MIXTO_OTRAS": claves + _si_visibles("tarjeta"),
        "FORMAS_MOVIMIENTO": simples + _si_visibles("transferencia"),
        "FORMAS_CAJA": simples,
        "FORMAS_REEMBOLSO": simples,
        "ORIGENES_PAGO": ("caja_menor", "caja_pos") + claves + ("otro",),
    }
    return listas[nombre_lista]


_LISTAS = ("CUENTAS", "CLAVES_CUENTAS", "TODAS_LAS_CUENTAS", "ICONOS", "NOMBRES", "FORMAS_VENTA_SIMPLE",
           "FORMAS_VENTA", "FORMAS_MIXTO", "FORMAS_MIXTO_OTRAS", "FORMAS_MOVIMIENTO", "FORMAS_CAJA",
           "FORMAS_REEMBOLSO", "ORIGENES_PAGO")
