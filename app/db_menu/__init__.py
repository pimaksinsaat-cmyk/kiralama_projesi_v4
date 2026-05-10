from flask import Blueprint

db_menu_bp = Blueprint('db_menu', __name__)

from app.db_menu import routes
from app.db_menu import belge_arsiv_yonetimi
