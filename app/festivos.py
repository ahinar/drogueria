"""
FESTIVOS DE COLOMBIA Y DÍAS HÁBILES
===================================

PARA QUÉ (para aprender):
    Algunos plazos se cuentan en DÍAS HÁBILES (sin sábados, domingos ni
    festivos). Por ejemplo, una queja se debe responder en 15 días hábiles
    (Ley 1755 de 2015). Para contar bien hay que saber qué días son festivos.

CÓMO SE CALCULAN LOS FESTIVOS EN COLOMBIA:
    1. Fijos (caen el día que sea): 1 ene, 1 may, 20 jul, 7 ago, 8 dic, 25 dic.
    2. "Ley Emiliani" (Ley 51 de 1983): si no caen lunes, se pasan al lunes
       siguiente: 6 ene, 19 mar, 29 jun, 15 ago, 12 oct, 1 nov, 11 nov.
    3. Los que dependen de la Pascua (Domingo de Resurrección):
       Jueves y Viernes Santo (3 y 2 días antes), y la Ascensión, Corpus
       Christi y Sagrado Corazón (se pasan al lunes: 43, 64 y 71 días después).
"""
from datetime import date, timedelta
from functools import lru_cache


def pascua(anio):
    """Domingo de Pascua (algoritmo de Meeus/Jones/Butcher, calendario gregoriano)."""
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(anio, mes, dia + 1)


def _al_lunes(dia):
    """Pasa una fecha al lunes siguiente (si ya es lunes, se queda)."""
    return dia + timedelta(days=(7 - dia.weekday()) % 7)


@lru_cache(maxsize=None)
def festivos(anio):
    """Conjunto con las fechas festivas de un año en Colombia."""
    fijos = {date(anio, 1, 1), date(anio, 5, 1), date(anio, 7, 20), date(anio, 8, 7),
             date(anio, 12, 8), date(anio, 12, 25)}
    emiliani = {_al_lunes(date(anio, m, d)) for m, d in
                ((1, 6), (3, 19), (6, 29), (8, 15), (10, 12), (11, 1), (11, 11))}
    p = pascua(anio)
    semana_santa = {p - timedelta(days=3), p - timedelta(days=2)}
    movibles = {p + timedelta(days=43), p + timedelta(days=64), p + timedelta(days=71)}
    return frozenset(fijos | emiliani | semana_santa | movibles)


def es_habil(dia):
    return dia.weekday() < 5 and dia not in festivos(dia.year)


def sumar_dias_habiles(desde, dias):
    """La fecha que queda `dias` días hábiles después de `desde` (sin contar `desde`)."""
    actual = desde
    while dias > 0:
        actual += timedelta(days=1)
        if es_habil(actual):
            dias -= 1
    return actual


def dias_habiles_entre(desde, hasta):
    """Cuántos días hábiles hay después de `desde` y hasta `hasta` (incluido). Negativo si `hasta` es antes."""
    if hasta < desde:
        return -dias_habiles_entre(hasta, desde)
    return sum(1 for n in range(1, (hasta - desde).days + 1) if es_habil(desde + timedelta(days=n)))
