from flask import Blueprint

# kiralama Blueprint'ini tanımlıyoruz
kiralama_bp = Blueprint('kiralama', __name__, template_folder='templates')

# Alttaki satırlar, rotaların uygulamaya dahil edilmesini sağlar.

from . import models
from . import routes
