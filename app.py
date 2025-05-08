import os
from dotenv import load_dotenv
import socket
import logging
from flask import Flask, redirect, url_for
from flask_session import Session
from datetime import timedelta
from extensions import db, login_manager, scheduler, migrate, configure_scheduler
from config_loader import load_config
from services.itunes_service import update_database_from_xml_logic
#from tasks.scheduled_tasks import export_default_playlist_to_spotify_task
from models import User, SpotifyToken
from blueprints.scheduler import scheduler_bp  
from blueprints.auth import auth_bp
from blueprints.spotify import spotify_bp
from blueprints.main import main_bp
from blueprints.resolve import resolve_bp # Added for resolution UI
#from blueprints.genres import genres_bp
import app_context_holder # Module to hold the global app context for APScheduler tasks


global_app = None

# Load environment variables from .env file for thing like Spotify and OPENAI API keys
# This must be done before the genres blueprint because it references the OPENAI_API_KEY
load_dotenv()
from blueprints.genres import genres_bp

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


def format_datetime(value, format='%Y-%m-%d %H:%M:%S'):
    if value is None:
        return ""
    return value.strftime(format)


def create_app(app_debug=False):
    """ Application factory for creating and configuring the Flask app. """
    global global_app # Needed to access the app context in the APScheduler tasks
    app = Flask(__name__)
    app_context_holder.set_app(app)


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

    # Spotify config (from .env file)
    app.config['SPOTIPY_CLIENT_ID'] = os.getenv("SPOTIPY_CLIENT_ID")
    app.config['SPOTIPY_CLIENT_SECRET'] = os.getenv("SPOTIPY_CLIENT_SECRET")
    app.config['SPOTIPY_REDIRECT_URI'] = 'http://localhost:5010/callback'

    # get openai api key
    app.config['OPENAI_API_KEY'] = os.getenv("OPENAI_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise RuntimeError("OPENAI API key is not set in the environment variables!")

    # kkrug 1/31/2025 - Added this line. See change_log.md
    app.config.update(load_config())

    configure_logging(app)

    # Initialize Flask extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    # kkrug 1/15/2025 - added the auth blueprint to the login view for fix a login issue
    login_manager.login_view = 'auth.login'
    Session(app)

    # Configure & Start the native APScheduler
    # (uses the function from extensions.py that configures job stores)
    configure_scheduler(app)

    
    print("Template search paths:", app.jinja_loader.searchpath)

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
            # kkrug 1/31/2025 - Commented out this line. See change_log.md
            #config = load_config()
            update_database_from_xml_logic(app.config, db)

    # All routes are now registered in the blueprints
    #from routes import register_routes
    #register_routes(app)

    # Register your jobs
    print("Registering jobs")
    register_jobs()

    app.register_blueprint(main_bp, url_prefix='/main') 
    app.register_blueprint(scheduler_bp, url_prefix='/scheduler')  
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(spotify_bp, url_prefix='/spotify')
    app.register_blueprint(genres_bp, url_prefix='/genres')
    app.register_blueprint(resolve_bp, url_prefix='/resolve') # Added for resolution UI
    print("Template search paths after all 6 blueprints registered:", app.jinja_loader.searchpath)

    # Register the datetime filter
    app.jinja_env.filters['format_datetime'] = format_datetime

    
    @app.route('/')
    def root():
        return redirect(url_for('main.index'))

    app_context_holder.app = app #  Set the global reference in the holder module to the app for use in the APScheduler tasks
    
    return app


def register_jobs():
    
    # run the export_default_playlist_to_spotify_task on app startup
    scheduler.add_job(
        id='export_default_playlist_to_spotify_on_startup',
        func='tasks.scheduled_tasks:export_playlist_wrapper'
    )

    # run the export_default_playlist_to_spotify_task every 3 hours
    scheduler.add_job(
        id='export_default_playlist_to_spotify_hourly',
        func='tasks.scheduled_tasks:export_playlist_wrapper',  # top-level function
        trigger='interval',
        hours=3,
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

    port = find_open_port(5013, 5500)

    #print("# # # # # # # # # # # # # # # # #")
    #print(f"# Starting server on port {port}  #")
    #print("# # # # # # # # # # # # # # # # #")

    #app.run(host="0.0.0.0", port=port, debug=app_debug)
    app.run(host="0.0.0.0", port=5003, debug=app_debug)

    #app.run(port=port, debug=app_debug)
