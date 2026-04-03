from flask import Blueprint

ayarlar_bp = Blueprint('ayarlar', __name__)

from app.ayarlar import routes