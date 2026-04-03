from flask import Blueprint

# 1. Önce Blueprint tanımlanır
makinedegisim_bp = Blueprint('makinedegisim', __name__, template_folder='templates')

# 2. Sonra rotalar EN ALTTA içeri aktarılır (import edilir)
# Eğer bu satır yoksa, yazdığın routes.py çalışmaz ve 404 verir!
from . import routes 
