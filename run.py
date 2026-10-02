"""Arranca el servidor. Úsalo en el PC principal del local: python run.py"""
import logging
import socket
import sys
import traceback

from waitress import serve

import config
from app import create_app


def ip_local() -> str:
    """Dirección IP de este PC en la red local (no necesita internet)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


app = create_app()


def con_diagnostico(wsgi_app):
    """Envuelve la app para imprimir CUALQUIER excepción que Waitress atrape."""
    def wrapper(environ, start_response):
        try:
            return wsgi_app(environ, start_response)
        except Exception:
            print("\n" + "=" * 70, flush=True)
            print(f"EXCEPCIÓN NO CAPTURADA en {environ.get('REQUEST_METHOD')} {environ.get('PATH_INFO')}",
                  file=sys.stderr, flush=True)
            print("=" * 70, file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            print("=" * 70, file=sys.stderr, flush=True)
            raise
    return wrapper


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ip = ip_local()
    print("=" * 60)
    print(" Sistema de droguería en marcha")
    print(f" En este PC:          http://localhost:{config.PORT}")
    print(f" Desde otro PC (LAN): http://{ip}:{config.PORT}")
    print(" Para detenerlo: cierra esta ventana o presiona Ctrl+C")
    print("=" * 60)
    serve(con_diagnostico(app), host=config.HOST, port=config.PORT, threads=4)