from flask import Blueprint

takvim_bp = Blueprint(
    'takvim',
    __name__,
    url_prefix='/takvim',
    template_folder='../templates/takvim'
)

from app.takvim import routes
