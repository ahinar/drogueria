from flask import Blueprint, render_template

from .auth import login_required

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def inicio():
    return render_template("inicio.html")
