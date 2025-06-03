from flask import Blueprint

resolve_bp = Blueprint('resolve', __name__, template_folder='templates')

from . import routes
