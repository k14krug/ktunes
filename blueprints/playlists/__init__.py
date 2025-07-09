# blueprints/playlists/__init__.py
from flask import Blueprint

bp = Blueprint('playlists', __name__)

from . import routes
