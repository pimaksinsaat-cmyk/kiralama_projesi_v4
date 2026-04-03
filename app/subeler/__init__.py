from flask import Blueprint

# Blueprint'i oluşturuyoruz
subeler_bp = Blueprint('subeler', __name__)

# Rotaları (sayfaları) içeri aktarıyoruz
from app.subeler import routes