from flask import Blueprint


servis_bp = Blueprint('servis', __name__)


from app.servis import routes