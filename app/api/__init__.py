from flask import Blueprint

api_bp = Blueprint('api', __name__, url_prefix='/api')

from app.api.auth import protect_api_request  # noqa: E402

api_bp.before_request(protect_api_request)

from app.api import routes  # noqa: E402,F401
from app.api import kiralama_routes  # noqa: E402,F401
from app.api import firmalar_routes  # noqa: E402,F401
from app.api import filo_routes  # noqa: E402,F401
