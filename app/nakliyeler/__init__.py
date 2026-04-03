from flask import Blueprint

nakliye_bp = Blueprint('nakliyeler', __name__, template_folder='templates')

from . import routes