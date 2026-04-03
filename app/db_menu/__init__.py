from flask import Blueprint

db_menu_bp = Blueprint('db_menu', __name__)

from app.db_menu import routes
