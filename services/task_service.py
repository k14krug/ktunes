from datetime import datetime
from flask import current_app
from services.spotify_service import fetch_and_update_recent_tracks, export_playlist_to_spotify, check_if_krug_playlist_is_playing
from services.playlist_generator_service import generate_default_playlist
#from extensions import scheduler

def run_export_default_playlist(username=None, force_update=False):
    """
    Executes the full process of fetching recent Spotify tracks, updating the database,
    generating the default playlist, and exporting it to Spotify.
    This is called from the UI and a scheduled task. If from a scheudled task, no user is available.

    :param username: Username for the playlist (defaults to "kkrug")
    :param force_update: If True, skip the "currently playing" check and update anyway
    :return: (success: bool, message: str)
    """
    with current_app.app_context():
        username = "kkrug"
        
        # Step 0: Check if KRUG FM 96.2 is currently playing (unless forced)
        if not force_update:
            current_app.logger.info("Checking if KRUG FM 96.2 playlist is currently playing")
            is_playing, current_track_info, playback_error = check_if_krug_playlist_is_playing()
            
            if playback_error:
                current_app.logger.warning(f"Could not check current playback status: {playback_error}")
                # Continue with export despite the error - better to update playlist than skip
            elif is_playing and current_track_info:
                current_app.logger.info(f"KRUG FM 96.2 is currently playing '{current_track_info['track_name']}' by '{current_track_info['artist']}'. Skipping playlist update to avoid interruption.")
                return True, f"Playlist update skipped. KRUG FM 96.2 is currently playing: {current_track_info['track_name']} by {current_track_info['artist']}"
            else:
                current_app.logger.info("KRUG FM 96.2 is not currently playing. Proceeding with playlist update.")
        else:
            current_app.logger.info("Force update requested. Skipping current playback check.")
        
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
        success, message = _generate_playlist_and_export(playlist_name, username)
        if not success:
            current_app.logger.error(f"Failed to generate and export playlist: {message}")
            return False, f"Failed to generate and export playlist: {message}"

        return True, message

def _generate_playlist_and_export(playlist_name, username):
    """
    Generates the playlist and then exports it.
    """
    print(f"Generating playlist {playlist_name} for user {username}, target platform=spotify")
    success, playlist_entries = generate_default_playlist(playlist_name, username, target_platform='spotify')
    if not success:
        return False, playlist_entries

    current_app.logger.info(f"Playlist '{playlist_name}' generated successfully with {len(playlist_entries)} tracks.")

    # Step 3: Export the playlist to Spotify
    print("Exporting playlist to Spotify")
    export_message = export_playlist_to_spotify(playlist_name, username, playlist_entries)
    current_app.logger.info(f"Task completed: {export_message}")

    return True, export_message

def task_service_test():
    with current_app.app_context():
        current_app.logger.info("Executing test_context_job. In task_service.py.test_service_test")
        tracks, error = fetch_and_update_recent_tracks(limit=50)
        if error:
            current_app.logger.error(f"Error fetching recent Spotify tracks: {error}")
            return False, f"Error fetching recent Spotify tracks: {error}"
