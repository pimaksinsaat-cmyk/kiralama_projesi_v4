from flask import Blueprint

araclar_bp = Blueprint('araclar', __name__, template_folder='templates')

from . import routes