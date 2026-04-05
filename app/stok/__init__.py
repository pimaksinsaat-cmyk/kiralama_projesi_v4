from flask import Blueprint


stok_bp = Blueprint('stok', __name__)


from app.stok import routes