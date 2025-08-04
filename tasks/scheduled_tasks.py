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


def playlist_versioning_cleanup_wrapper():
    """
    Scheduled task wrapper for playlist versioning cleanup.
    Provides the Flask app context and calls the cleanup logic.
    """
    import app_context_holder  # Import the holder to access the app
    
    # Access the app via the holder
    app = app_context_holder.app
    with app.app_context():
        try:
            from services.playlist_versioning_service import PlaylistVersioningService
            from services.playlist_versioning_config import get_versioning_config
            
            app.logger.info("Running scheduled playlist versioning cleanup...")
            
            # Get configuration
            config = get_versioning_config()
            retention_days = config.get_retention_days()
            max_versions = config.get_max_versions()
            
            # Run cleanup for all playlists
            cleanup_results = PlaylistVersioningService.cleanup_all_playlists(
                retention_days=retention_days,
                max_versions=max_versions
            )
            
            total_cleaned = sum(cleanup_results.values())
            
            if total_cleaned > 0:
                app.logger.info(f"Playlist versioning cleanup completed: removed {total_cleaned} old versions across {len(cleanup_results)} playlists")
                for playlist_name, count in cleanup_results.items():
                    if count > 0:
                        app.logger.info(f"  - {playlist_name}: {count} versions cleaned")
            else:
                app.logger.info("Playlist versioning cleanup completed: no versions needed cleanup")
                
        except Exception as e:
            app.logger.error(f"Error during playlist versioning cleanup: {str(e)}")
            # Don't raise the exception to prevent scheduler issues

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
