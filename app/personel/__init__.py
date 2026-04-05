from flask import Blueprint


personel_bp = Blueprint('personel', __name__)


from app.personel import models
from app.personel import routes