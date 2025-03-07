# Description: This file is used to store the app context for the application.
# This is needed for the APScheduler tasks to run in the correct context.
app = None

def set_app(application):
    """
    Set the Flask application instance for use by scheduled tasks.
    Call this function during application initialization.
    """
    global app
    app = application