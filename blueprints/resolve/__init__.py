from flask import Blueprint

resolve_bp = Blueprint('resolve', __name__)

from . import routes
