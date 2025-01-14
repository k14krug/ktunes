from flask import Blueprint

# Create the Blueprint instance for the scheduler
scheduler_bp = Blueprint('apscheduler', __name__)

# Import the routes to associate them with this Blueprint
from . import routes