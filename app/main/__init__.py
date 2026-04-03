from flask import Blueprint

# 'main' adında bir blueprint (departman tabelası) oluştur
main_bp = Blueprint('main', __name__)

# Bu departmana ait rotaları (URL'leri) bağla
# (Circular import'u önlemek için import en sonda yapılır)
from app.main import routes