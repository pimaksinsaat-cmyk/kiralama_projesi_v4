from flask import Blueprint

# 'firmalar' adında bir blueprint (departman tabelası) oluştur
firmalar_bp = Blueprint('firmalar', __name__)
from . import models
# Bu departmana ait rotaları (URL'leri) bağla
# (Circular import'u önlemek için import en sonda yapılır)
from app.firmalar import routes