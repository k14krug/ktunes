from flask import current_app
from services.task_service import run_export_default_playlist, task_service_test


def export_playlist_wrapper():
    """
    Top-level function APScheduler can pickle.
    Provides the Flask app context, calls the real logic.
    """
    print(" Running export_playlist_wrapper")
    
    import app_context_holder  # Import the holder to access the app
    
    # Access the app via the holder
    app = app_context_holder.app
    with app.app_context():
        app.logger.info("Running scheduled task: export_default_playlist...")
        print(" Running run_export_default_playlist")
        success, message = run_export_default_playlist()
        if not success:
            app.logger.error(message)
        else:
            app.logger.info(message)

def test_context_wrapper():
    """
    Another top-level function for the test context job.
    """
    import app_context_holder  # Import the holder to access the app
    
    # Access the app via the holder
    app = app_context_holder.app
    with app.app_context():
        task_service_test()
        app.logger.info("Test context job ran successfully.")

# (If you still want these old functions, you can keep them, but no longer schedule them directly.)
def export_default_playlist_to_spotify_task():
    """
    Possibly redundant now, if your new wrapper is doing everything.
    """
    app = current_app._get_current_object()
    with app.app_context():
        success, message = run_export_default_playlist()
        ...
def test_context():
    """
    Possibly redundant if test_context_wrapper is used.
    """
    app = current_app._get_current_object()
    with app.app_context():
        task_service_test()
