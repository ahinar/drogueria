"""
VARIOS COMPUTADORES: quién puede entrar y quién está conectado
==============================================================

PARA QUÉ (para aprender):
    Desde la versión 1.1.0 el programa puede usarse en dos computadores:

      - PC PRINCIPAL (mostrador): aquí está la base de datos y corre el
        programa de verdad.
      - PC CONECTADO (portátil): solo abre una ventana que muestra el
        programa del principal. Lo que se hace en el portátil queda guardado
        en el principal, al instante.

    Para que el portátil funcione también desde la casa se usa TAILSCALE:
    un programa gratuito que se instala en los dos PC con la misma cuenta y
    los une en una "red privada" cifrada, estén donde estén, sin tocar el
    router ni abrir puertos a internet.

SEGURIDAD (dos candados):
    1. El cortafuegos de Windows (lo configura el instalador): solo deja
       pasar conexiones al puerto 8765 desde la red del local y Tailscale.
    2. Este archivo: aunque algo pase el cortafuegos, el programa revisa la
       dirección de quien llega y rechaza (error 403) todo lo que no sea:
         - este mismo computador        127.x.x.x
         - la red del local             192.168.x.x, 10.x.x.x, 172.16-31.x.x
         - Tailscale                    100.64.x.x a 100.127.x.x
       Además, para entrar siempre hace falta usuario y contraseña.

    Así, aunque alguien en internet supiera la dirección del local, no podría
    ni siquiera ver la página de entrada.

Este archivo también lleva la cuenta de qué equipos han usado el programa en
los últimos minutos (se ve en Administración → Red y equipos).
"""
import ipaddress
import socket
import threading
import time

import config

# ---------------------------------------------------------------------------
# 1. ¿Desde dónde se permite entrar?
# ---------------------------------------------------------------------------
REDES_PERMITIDAS = [ipaddress.ip_network(red) for red in (
    "127.0.0.0/8",        # este mismo computador
    "10.0.0.0/8",         # redes privadas (la del local)
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",     # red "automática" de Windows cuando no hay router
    "100.64.0.0/10",      # Tailscale (IPv4)
    "::1/128",            # este mismo computador (IPv6)
    "fe80::/10",          # red local (IPv6)
    "fc00::/7",           # redes privadas IPv6, incluye la de Tailscale (fd7a:115c:a1e0::/48)
)]
TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


def _como_ip(texto):
    """Convierte "192.168.1.5" en una dirección; None si no se entiende."""
    try:
        ip = ipaddress.ip_address((texto or "").split("%")[0])   # "%" = zona IPv6 (fe80::1%12)
    except ValueError:
        return None
    # Una IPv4 escrita "a la IPv6" (::ffff:192.168.1.5) se revisa como IPv4
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip


def red_permitida(direccion: str) -> bool:
    """True si la dirección viene de este PC, de la red del local o de Tailscale."""
    ip = _como_ip(direccion)
    return ip is not None and any(ip in red for red in REDES_PERMITIDAS if red.version == ip.version)


def tipo_de_red(direccion: str) -> str:
    """Nombre para mostrar: "Este computador", "Tailscale" o "Red del local"."""
    ip = _como_ip(direccion)
    if ip is None:
        return "Desconocida"
    if ip.is_loopback:
        return "Este computador"
    if ip.version == 4 and ip in TAILSCALE or str(ip).startswith("fd7a:115c:a1e0:"):
        return "Tailscale"
    return "Red del local"


# ---------------------------------------------------------------------------
# 2. Las direcciones de ESTE computador (para escribirlas en el portátil)
# ---------------------------------------------------------------------------
def nombre_del_pc() -> str:
    """Nombre del computador en Windows (ej. "MOSTRADOR"). Tailscale lo usa en minúsculas."""
    return socket.gethostname()


def direcciones_de_este_pc() -> list:
    """Lista de {"ip", "red"} de este computador, sin repetir (sin las internas 127.x)."""
    vistas = []
    try:
        for familia, _t, _p, _c, dir_ in socket.getaddrinfo(socket.gethostname(), None):
            if familia == socket.AF_INET:          # solo IPv4: son las fáciles de escribir
                vistas.append(dir_[0])
    except OSError:
        pass
    # La que usa para salir a la red (funciona aunque el nombre no se resuelva)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))           # no manda nada: solo pregunta la ruta
        vistas.append(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    resultado = []
    for ip in dict.fromkeys(vistas):               # quita repetidas sin cambiar el orden
        if not ip.startswith("127."):
            resultado.append({"ip": ip, "red": tipo_de_red(ip)})
    # Primero Tailscale (sirve en el local y en la casa), luego la red del local
    resultado.sort(key=lambda d: d["red"] != "Tailscale")
    return resultado


# ---------------------------------------------------------------------------
# 3. ¿Quién está conectado? (en memoria: se borra al cerrar el programa)
# ---------------------------------------------------------------------------
_conectados = {}
_candado = threading.Lock()
MINUTOS_CONECTADO = 15     # si no ha hecho nada en 15 minutos, ya no se muestra


def anotar_visita(direccion: str, usuario: str = "") -> None:
    """Se llama en cada página que se abre: guarda desde dónde y quién."""
    with _candado:
        anterior = _conectados.get(direccion, {})
        _conectados[direccion] = {
            "usuario": usuario or anterior.get("usuario", ""),
            "ultimo": time.time(),
        }


def conectados() -> list:
    """Equipos que usaron el programa en los últimos minutos, del más reciente al más viejo."""
    limite = time.time() - MINUTOS_CONECTADO * 60
    with _candado:
        filas = [{"ip": ip, "red": tipo_de_red(ip), "usuario": d["usuario"],
                  "hace_min": int((time.time() - d["ultimo"]) // 60)}
                 for ip, d in _conectados.items() if d["ultimo"] >= limite]
    return sorted(filas, key=lambda f: f["hace_min"])


# ---------------------------------------------------------------------------
# 4. Conectar el candado al programa (lo llama create_app)
# ---------------------------------------------------------------------------
def init_app(app):
    from flask import abort, g, request

    @app.before_request
    def _solo_red_del_local():
        # Waitress pone en remote_addr la dirección real de quien se conecta
        if not red_permitida(request.remote_addr):
            abort(403)

    @app.after_request
    def _anotar(respuesta):
        # No se anotan los archivos de estilos, imágenes ni la pregunta /salud
        if not request.path.startswith("/static/") and request.path != "/salud":
            usuario = g.get("user")
            anotar_visita(request.remote_addr or "?", usuario["nombre"] if usuario else "")
        return respuesta


def info() -> dict:
    """Todo lo que muestra la página Administración → Red y equipos."""
    return {
        "modo": config.EQUIPO["modo"],
        "compartir": config.EQUIPO["compartir"],
        "instalado": config.INSTALADO,
        "puerto": config.PORT,
        "nombre": nombre_del_pc(),
        "direcciones": direcciones_de_este_pc(),
        "conectados": conectados(),
    }
