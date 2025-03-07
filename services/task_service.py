from datetime import datetime
from flask import current_app
from services.spotify_service import fetch_and_update_recent_tracks, export_playlist_to_spotify
from services.playlist_generator_service import generate_default_playlist
#from extensions import scheduler

def run_export_default_playlist(username=None):
    """
    Executes the full process of fetching recent Spotify tracks, updating the database,
    generating the default playlist, and exporting it to Spotify.
    This is called from the UI and a scheduled task. If from a scheudled task, no user is available.

    :return: (success: bool, message: str)
    """
    with current_app.app_context():
        username = "kkrug"
        # Step 1: Fetch and update recent Spotify tracks
        current_app.logger.info("Fetching and updating recent Spotify tracks")
        tracks, error = fetch_and_update_recent_tracks(limit=50)
        if error:
            current_app.logger.error(f"Error fetching recent Spotify tracks: {error}")
            return False, f"Error fetching recent Spotify tracks: {error}"

        if not tracks:
            current_app.logger.info("No new Spotify songs played since last check. Skipping playlist generation.")
            return True, "Playlist not created. No new Spotify songs played since last check."

        # Step 2: Generate the default 
        print("Generating default playlist")
        playlist_name = "KRUG FM 96.2"
        # kkrug 1/15/2025 - Removed the date from the playlist name
        # kkurg 2/7/2025 - Added the date back into the playlist name. Hoping this will tell me if the playlist is recent.
        #playlist_name = "kTunes Radio"
        success, message = generate_default_playlist(playlist_name,username)
        if not success:
            current_app.logger.error(f"Failed to generate playlist: {message}")
            return False, f"Failed to generate playlist: {message}"

        current_app.logger.info(f"Playlist '{playlist_name}' generated successfully: {message}")

        # Step 3: Export the playlist to Spotify
        print("Exporting playlist to Spotify")
        #db = current_app.extensions['sqlalchemy'].db
        export_message = export_playlist_to_spotify(playlist_name, username)
        current_app.logger.info(f"Task completed: {export_message}")

        return True, export_message
def task_service_test():
    with current_app.app_context():
        current_app.logger.info("Executing test_context_job. In task_service.py.test_service_test")
        tracks, error = fetch_and_update_recent_tracks(limit=50)
        if error:
            current_app.logger.error(f"Error fetching recent Spotify tracks: {error}")
            return False, f"Error fetching recent Spotify tracks: {error}"

