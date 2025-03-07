from flask import Blueprint

# Create the Blueprint instance for the scheduler
spotify_bp = Blueprint('spotify', __name__)

# Import the routes to associate them with this Blueprint
from . import routes
