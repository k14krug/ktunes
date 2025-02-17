from flask import Blueprint

genres_bp = Blueprint(
    'genres',
    __name__,
    template_folder='templates',  # Points to the local templates folder
    static_folder='static'       # Points to the local static folder
)

from . import routes  # Import routes to register them on this blueprint