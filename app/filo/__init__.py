from flask import Blueprint

# 'filo' adında bir blueprint oluştur
filo_bp = Blueprint('filo', __name__)

from app.filo import routes