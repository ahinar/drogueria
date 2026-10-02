"""Bitácora de auditoría: quién hizo qué y cuándo."""
from flask import g, has_request_context, request

from .db import ahora, get_db


def registrar(accion, tabla=None, registro_id=None, detalle=None, usuario=None):
    """Guarda una entrada en la bitácora. `usuario` es opcional (por ejemplo, en el inicio de sesión)."""
    db = get_db()
    if usuario is None and has_request_context():
        usuario = g.get("user")
    ip = request.remote_addr if has_request_context() else None
    db.execute(
        "INSERT INTO bitacora (fecha, usuario_id, usuario_nombre, accion, tabla, registro_id, detalle, ip) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ahora(),
            usuario["id"] if usuario is not None else None,
            usuario["usuario"] if usuario is not None else None,
            accion,
            tabla,
            registro_id,
            detalle,
            ip,
        ),
    )
    db.commit()
