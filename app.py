import os
import socket
import logging
from flask import Flask
from flask_session import Session
from datetime import timedelta

from extensions import db, login_manager, scheduler, migrate, configure_scheduler
from config_loader import load_config
from services.itunes_service import update_database_from_xml_logic
#from tasks.scheduled_tasks import export_default_playlist_to_spotify_task
from models import User, SpotifyToken
from blueprints.scheduler import scheduler_bp  
import app_context_holder # Module to hold the global app context for APScheduler tasks

global_app = None

def configure_logging(app):
    """ Configure logging levels & format for both Flask and APScheduler logs. """
    app.logger.setLevel(logging.DEBUG)

    apscheduler_logger = logging.getLogger('apscheduler')
    apscheduler_logger.setLevel(logging.DEBUG)
    apscheduler_logger.propagate = False

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    app.logger.addHandler(console_handler)

    apscheduler_file_handler = logging.FileHandler('apscheduler.log')
    apscheduler_file_handler.setLevel(logging.DEBUG)
    apscheduler_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    apscheduler_logger.addHandler(apscheduler_file_handler)


def create_app(app_debug):
    """ Application factory for creating and configuring the Flask app. """
    global global_app # Needed to access the app context in the APScheduler tasks
    app = Flask(__name__)

    # Set up instance path
    app_root = os.path.abspath(os.path.dirname(__file__))
    app.instance_path = os.path.join(app_root, 'instance')
    os.makedirs(app.instance_path, exist_ok=True)

    # Flask Configuration
    app.config['SECRET_KEY'] = os.urandom(24)
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(app.instance_path, "kTunes.sqlite")}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_FILE_DIR'] = os.path.join(app.instance_path, 'flask_session')
    app.config['SESSION_PERMANENT'] = True
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=31)
    os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

    # Spotify config (unchanged)
    app.config['SPOTIPY_CLIENT_ID'] = 'bf5b82bad95f4d94a19f3b0b22dced56'
    app.config['SPOTIPY_CLIENT_SECRET'] = 'eab0a2259cde4d98a6048305345ab19c'
    app.config['SPOTIPY_REDIRECT_URI'] = 'http://localhost:5010/callback'

    # (Removed any 'SCHEDULER_API_ENABLED' or 'SCHEDULER_API_PREFIX' since we're not using flask_apscheduler)

    configure_logging(app)

    # Initialize Flask extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    Session(app)

    # Configure & Start the native APScheduler
    # (uses the function from extensions.py that configures job stores)
    configure_scheduler(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Because we started APScheduler just above, we do NOT need the old:
    #    if os.getenv('FLASK_ENV') != 'migrate' and not os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    #        scheduler.start()
    # It's now done in configure_scheduler(app)

    # Run startup tasks within an app_context
    with app.app_context():
        app.logger.debug("Performing Startup Tasks...")
        db.create_all()
        if not app_debug or not os.environ.get('WERKZEUG_RUN_MAIN'):
            config = load_config()
            update_database_from_xml_logic(config, db)

    # Register your routes
    from routes import register_routes
    register_routes(app)

    # Register your jobs
    register_jobs()
    app.register_blueprint(scheduler_bp, url_prefix='/scheduler')  

    app_context_holder.app = app #  Set the global reference in the holder module to the app for use in the APScheduler tasks
    
    return app


def register_jobs():
    
    # run the export_default_playlist_to_spotify_task on app startup
    scheduler.add_job(
        id='export_default_playlist_to_spotify_on_startup',
        func='tasks.scheduled_tasks:export_playlist_wrapper'
    )

    # run the export_default_playlist_to_spotify_task every 60 minutes
    scheduler.add_job(
        id='export_default_playlist_to_spotify_hourly',
        func='tasks.scheduled_tasks:export_playlist_wrapper',  # top-level function
        trigger='interval',
        minutes=5,
        replace_existing=True
    )

    # If you want to schedule the test context job too:
    scheduler.add_job(
        id='test_context_job',
        func='tasks.scheduled_tasks:test_context_wrapper',
        trigger='interval',
        minutes=60,
        replace_existing=True
    )

def find_open_port(start_port=5010, end_port=5500):
    """Find an open port for the server to bind to."""
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
    raise RuntimeError("No open ports available in the specified range")


if __name__ == '__main__':
    print("Creating app")
    app_debug = False
    app = create_app(app_debug)

    port = find_open_port(5010, 5500)

    print("# # # # # # # # # # # # # # # # #")
    print(f"# Starting server on port {port}  #")
    print("# # # # # # # # # # # # # # # # #")

    app.run(port=port, debug=app_debug)
