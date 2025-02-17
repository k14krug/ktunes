from flask import Blueprint

auth_bp = Blueprint('auth', __name__)

from . import routes  # Import routes to register them on this blueprint
