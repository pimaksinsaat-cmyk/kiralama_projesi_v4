from flask import Blueprint

raporlama_bp = Blueprint('raporlama', __name__)

from app.raporlama import routes
