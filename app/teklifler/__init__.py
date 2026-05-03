from flask import Blueprint


teklifler_bp = Blueprint('teklifler', __name__)

from app.teklifler import routes  # noqa: E402,F401
