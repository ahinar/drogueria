"""Formatos colombianos para mostrar números en mensajes.

pesos(1234567)  -> '$1.234.567'   (punto para los miles, como se escribe en Colombia)
pesos(-5000)    -> '-$5.000'

Python por defecto escribe 1,234,567 (con comas, estilo inglés); por eso esta ayuda.
"""


def pesos(valor):
    valor = float(valor or 0)
    texto = "$" + f"{abs(valor):,.0f}".replace(",", ".")
    return "-" + texto if valor < -0.5 else texto
