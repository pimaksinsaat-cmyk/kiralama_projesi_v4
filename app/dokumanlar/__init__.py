from flask import Blueprint

# Dökümanlar modülü için Blueprint oluşturuluyor
# template_folder belirtiyoruz ki 'templates/dokumanlar' klasöründeki dosyaları bulabilsin
dokumanlar_bp = Blueprint('dokumanlar', __name__, template_folder='templates')

from app.dokumanlar import routes
from . import kiralama_routes
from . import teslim_tutanagi_hazirla