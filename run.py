"""Arranca el servidor. Úsalo en el PC principal del local: python run.py"""
import logging
import socket

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

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ip = ip_local()
    print("=" * 60)
    print(" Sistema de droguería en marcha")
    print(f" En este PC:          http://localhost:{config.PORT}")
    print(f" Desde otro PC (LAN): http://{ip}:{config.PORT}")
    print(" Para detenerlo: cierra esta ventana o presiona Ctrl+C")
    print("=" * 60)
    serve(app, host=config.HOST, port=config.PORT, threads=8)
