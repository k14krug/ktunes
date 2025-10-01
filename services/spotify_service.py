import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import current_app, session, url_for, request, redirect, jsonify
from flask_login import current_user
from models import Track, Playlist, SpotifyToken, PlayedTrack, SpotifyURI, db
import time
from datetime import datetime
import pytz
import json
import os
import base64
from PIL import Image
from sqlalchemy import func
import re
import string
def normalize_text(text_input):
    """
    Normalize text by converting to lowercase, removing punctuation, articles,
    normalizing 'feat.', and collapsing whitespace.
    """
    if not text_input:
        return ""
    text = str(text_input) # Ensure text is a string
    # Convert to lowercase
    text = text.lower()
    # Remove articles (e.g., "the", "a", "an") as whole words at the beginning
    text = re.sub(r'^\b(the|a|an)\b\s+', '', text, flags=re.IGNORECASE)
    # Normalize "feat.", "ft.", "featuring" to "feat"
    text = re.sub(r'\b(featuring|ft\.|ft)\b', 'feat', text, flags=re.IGNORECASE)
    # Remove common punctuation but keep ampersands for now
    text = text.translate(str.maketrans('', '', string.punctuation.replace('&', '')))
    # Normalize ampersands to 'and'
    text = text.replace('&', 'and')
    # Collapse multiple spaces to one and strip leading/trailing
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def normalize_text_for_matching(text_input):
    """
    Enhanced normalization for track matching that handles remastering, 
    editions, and other common Spotify variations.
    """
    if not text_input:
        return ""
    
    text = str(text_input).lower()
    
    # Remove articles at the beginning
    text = re.sub(r'^\b(the|a|an)\b\s+', '', text, flags=re.IGNORECASE)
    
    # Remove remastering and edition information
    remaster_patterns = [
        r'\s*-?\s*remaster(ed)?\s*\d{4}',  # "- Remastered 2010", "Remaster 2010"
        r'\s*-?\s*\d{4}\s*remaster(ed)?',  # "- 2010 Remastered" 
        r'\s*-?\s*remaster(ed)?',          # "- Remastered", "Remaster"
        r'\s*-?\s*\d{4}\s*edition',        # "- 2010 Edition"
        r'\s*-?\s*special\s*edition',      # "- Special Edition"
        r'\s*-?\s*deluxe\s*edition',       # "- Deluxe Edition"
        r'\s*-?\s*expanded\s*edition',     # "- Expanded Edition"
        r'\s*-?\s*anniversary\s*edition',  # "- Anniversary Edition"
        r'\s*-?\s*stereo',                 # "- Stereo"
        r'\s*-?\s*mono',                   # "- Mono"
        r'\s*\([^)]*remaster[^)]*\)',      # "(Remastered)", "(2010 Remaster)"
        r'\s*\([^)]*\d{4}[^)]*\)',         # "(2010)", "(Live 1970)"
    ]
    
    for pattern in remaster_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # Normalize featuring
    text = re.sub(r'\b(featuring|feat\.|ft\.|ft)\b', 'feat', text, flags=re.IGNORECASE)
    
    # Remove punctuation except &
    text = text.translate(str.maketrans('', '', string.punctuation.replace('&', '')))
    
    # Normalize ampersands to 'and'
    text = text.replace('&', 'and')
    
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


# Cache for Spotify client to avoid recreating it for every call
_spotify_client_cache = None
_spotify_client_cache_time = None

# Cache for last API check to avoid redundant calls
_last_api_check_cache = None
_last_api_check_time = None

def get_spotify_client(allow_interactive_auth=False):
    """
    Get an authenticated Spotify client using SpotifyOAuth with caching.
    
    Args:
        allow_interactive_auth (bool): If True, allows interactive browser authentication.
                                     If False, only uses stored tokens (for background tasks).
    """
    global _spotify_client_cache, _spotify_client_cache_time
    
    # Cache client for 10 minutes to avoid overhead
    cache_timeout = 600  # 10 minutes
    current_time = time.time()
    
    if (_spotify_client_cache is not None and 
        _spotify_client_cache_time is not None and 
        current_time - _spotify_client_cache_time < cache_timeout):
        return _spotify_client_cache
    
    try:
        # For background tasks, we need to use stored tokens only
        if not allow_interactive_auth:
            # Try to get existing token from database
            token = get_spotify_token()
            if not token:
                current_app.logger.error("No Spotify token found in database for background task")
                return None
            
            # Check if token is still valid (with 5 minute buffer)
            current_time_unix = int(time.time())
            if token.expires_at - 300 < current_time_unix:
                # Token is expired or expiring soon, try to refresh
                try:
                    sp_oauth = SpotifyOAuth(
                        client_id=current_app.config['SPOTIPY_CLIENT_ID'],
                        client_secret=current_app.config['SPOTIPY_CLIENT_SECRET'],
                        redirect_uri=current_app.config['SPOTIPY_REDIRECT_URI'],
                        scope="playlist-modify-public playlist-modify-private playlist-read-private playlist-read-collaborative user-read-recently-played user-read-playback-state ugc-image-upload",
                    )
                    
                    # Refresh the token without user interaction
                    refreshed_token_info = sp_oauth.refresh_access_token(token.refresh_token)
                    
                    # Update token in database
                    token.access_token = refreshed_token_info['access_token']
                    token.refresh_token = refreshed_token_info.get('refresh_token', token.refresh_token)
                    token.expires_at = refreshed_token_info['expires_at']
                    db.session.commit()
                    
                    current_app.logger.info("Successfully refreshed Spotify token for background task")
                    
                except Exception as refresh_error:
                    current_app.logger.error(f"Failed to refresh Spotify token for background task: {refresh_error}")
                    return None
            
            # Create client with the valid token
            try:
                client = spotipy.Spotify(
                    auth=token.access_token,
                    requests_timeout=5,
                    retries=1,
                    backoff_factor=0.1
                )
                
                # Test the client with a simple API call
                client.me()
                
                # Cache the client
                _spotify_client_cache = client
                _spotify_client_cache_time = current_time
                
                return client
                
            except Exception as client_error:
                current_app.logger.error(f"Failed to create Spotify client with token: {client_error}")
                return None
        
        else:
            # Interactive mode - original behavior for web requests
            sp_oauth = SpotifyOAuth(
                client_id=current_app.config['SPOTIPY_CLIENT_ID'],
                client_secret=current_app.config['SPOTIPY_CLIENT_SECRET'],
                redirect_uri=current_app.config['SPOTIPY_REDIRECT_URI'],
                scope="playlist-modify-public playlist-modify-private playlist-read-private playlist-read-collaborative user-read-recently-played user-read-playback-state ugc-image-upload",
            )
            # Add timeout and retry configuration to avoid hanging on slow API calls
            client = spotipy.Spotify(
                auth_manager=sp_oauth,
                requests_timeout=5,  # Reduced from 10 to 5 seconds
                retries=1,  # Reduced from 3 to 1 for faster failure
                backoff_factor=0.1  # Faster backoff between retries
            )
            
            # Cache the client
            _spotify_client_cache = client
            _spotify_client_cache_time = current_time
            
            return client
    except Exception as e:
        current_app.logger.error(f"Error creating Spotify client: {e}")
        return None



def spotify_auth():
    """Redirect the user to Spotify authentication."""
    sp_oauth = SpotifyOAuth(
        client_id=current_app.config['SPOTIPY_CLIENT_ID'],
        client_secret=current_app.config['SPOTIPY_CLIENT_SECRET'],
        redirect_uri=current_app.config['SPOTIPY_REDIRECT_URI'],
        #scope="playlist-modify-public playlist-modify-private user-read-recently-played"
        scope="playlist-modify-public playlist-modify-private playlist-read-private playlist-read-collaborative user-read-recently-played user-read-playback-state ugc-image-upload"
    )
    auth_url = sp_oauth.get_authorize_url()
    return url_for('route_callback', _external=True, _scheme='http')


def spotify_callback():
    """
    Handle Spotify OAuth callback.
    """
    sp_oauth = SpotifyOAuth(
        client_id=current_app.config['SPOTIPY_CLIENT_ID'],
        client_secret=current_app.config['SPOTIPY_CLIENT_SECRET'],
        redirect_uri=current_app.config['SPOTIPY_REDIRECT_URI']
    )
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    save_spotify_token(
        token_info['access_token'],
        token_info['refresh_token'],
        token_info['expires_in']
    )
    return redirect(url_for('playlists'))

def save_spotify_token(access_token, refresh_token, expires_in):
    """
    Save the Spotify token details to the database.
    """
    expires_at = int(time.time()) + expires_in
    token = SpotifyToken.query.first()
    if token:
        token.access_token = access_token
        token.refresh_token = refresh_token
        token.expires_at = expires_at
    else:
        token = SpotifyToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at
        )
        db.session.add(token)
    db.session.commit()

def get_spotify_token():
    """Fetch the Spotify token from the database."""
    token = SpotifyToken.query.first()
    if token:
        pass
        #current_app.logger.debug(f"Retrieved Spotify token: {token.access_token[:10]}...")  # Log partial token for debugging
    else:
        current_app.logger.warning("No Spotify token found in the database.")
    return token
'''
def refresh_spotify_token(scope=None):
    """
    Refresh the Spotify token if it exists, or create a new one if it does not.
    """
    token = get_spotify_token()

    # If no token exists, use OAuth to create a new one
    if not token:
        current_app.logger.info("No token in the database. Attempting to create a new token.")
        try:
            sp_oauth = SpotifyOAuth(
                client_id=current_app.config['SPOTIPY_CLIENT_ID'],
                client_secret=current_app.config['SPOTIPY_CLIENT_SECRET'],
                redirect_uri=current_app.config['SPOTIPY_REDIRECT_URI'],
                scope=scope or "playlist-modify-public playlist-modify-private playlist-read-private playlist-read-collaborative user-read-recently-played ugc-image-upload"
            )
            auth_url = sp_oauth.get_authorize_url()
            current_app.logger.info(f"Please authenticate Spotify via this URL: {auth_url}")
            
            print("Visit the above URL, authenticate, and paste the code here:")
            auth_code = input("Enter the Spotify authorization code: ").strip()
            
            token_info = sp_oauth.get_access_token(auth_code)

            # Save the token to the database
            new_token = SpotifyToken(
                access_token=token_info['access_token'],
                refresh_token=token_info['refresh_token'],
                expires_at=token_info['expires_at']
            )
            db.session.add(new_token)
            db.session.commit()

            current_app.logger.info("New Spotify token created and saved successfully.")
            return new_token.access_token
        except Exception as e:
            current_app.logger.error(f"Error creating a new Spotify token: {e}")
            return None  # Return None to indicate failure

    # Check if the token is near expiration
    current_time = time.time()
    if token.expires_at - 60 > current_time:
        return token.access_token  # Token is still valid

    # Refresh the token using SpotifyOAuth
    try:
        sp_oauth = SpotifyOAuth(
            client_id=current_app.config['SPOTIPY_CLIENT_ID'],
            client_secret=current_app.config['SPOTIPY_CLIENT_SECRET'],
            redirect_uri=current_app.config['SPOTIPY_REDIRECT_URI'],
            scope=scope or "playlist-modify-public playlist-modify-private playlist-read-private playlist-read-collaborative user-read-recently-played ugc-image-upload"
        )
        refreshed_token_info = sp_oauth.refresh_access_token(token.refresh_token)

        # Update the token in the database
        token.access_token = refreshed_token_info['access_token']
        token.refresh_token = refreshed_token_info.get('refresh_token', token.refresh_token)
        token.expires_at = refreshed_token_info['expires_at']
        db.session.commit()

        current_app.logger.info("Spotify token refreshed successfully.")
        return token.access_token
    except Exception as e:
        current_app.logger.error(f"Error refreshing Spotify token: {e}")
        return None  # Return None to indicate failure
'''

def get_last_recent_played_at():
    """Get the last processed played_at timestamp from the database."""
    try:
        # Get the most recent PlayedTrack from Spotify
        latest_track = PlayedTrack.query.filter_by(source='spotify').order_by(PlayedTrack.played_at.desc()).first()
        if latest_track:
            return latest_track.played_at
    except Exception as e:
        current_app.logger.error(f"Error getting last played_at from database: {e}")
    return None

def fetch_and_update_recent_tracks(limit=50):   
    """
    Fetch recent Spotify tracks and update the database accordingly.

    :param limit: The maximum number of recent tracks to fetch.
    :return: A tuple of (tracks, error) where `tracks` contains the updated tracks, and `error` is None if successful.
    """
    global _last_api_check_cache, _last_api_check_time
    
    start_time = time.time()
    current_app.logger.info(f"Starting fetch and update_recent_tracks with limit: {limit}")
    
    # For scheduled jobs that run frequently, cache the "no new tracks" result for 2 minutes
    # This prevents hammering the Spotify API when there's no new activity
    cache_timeout = 120  # 2 minutes
    current_time = time.time()
    
    if (limit == 50 and _last_api_check_cache is not None and 
        _last_api_check_time is not None and 
        current_time - _last_api_check_time < cache_timeout and
        _last_api_check_cache == "no_new_tracks"):
        print(f"Using cached result: no new tracks (cached {current_time - _last_api_check_time:.0f}s ago)")
        return [], None
    
    try:
        print("Checking the most recent track...")
        # Fetch only the most recent track and compare it to the last time we did this check. If its newer we'll get the last 50, else no need to go further
        api_start = time.time()
        single_track_list, error = fetch_recent_tracks(limit=1)
        api_time = time.time() - api_start
        print(f"Spotify API call took {api_time:.2f} seconds")
        
        if error:
            print(f"Error returned from fetch_recent_tracks: {error}")  
            return None, error
        if not single_track_list:
            print("No recent track found.")
            return [], None
        
        # single_track_list[0] should be the most recent
        most_recent_track = single_track_list[0]
        played_at_raw = most_recent_track.get('played_at')
        datetime_format = '%Y-%m-%d %H:%M:%S'
        most_recent_track_time = datetime.strptime(played_at_raw, datetime_format)

        # Get the last processed timestamp from the database instead of global variable
        db_start = time.time()
        last_recent_played_at = get_last_recent_played_at()
        db_time = time.time() - db_start
        print(f"Database lookup took {db_time:.3f} seconds")

        # Compare with our database's last_recent_played_at
        if last_recent_played_at and most_recent_track_time <= last_recent_played_at:
            total_time = time.time() - start_time
            print(f"No new track since last check({last_recent_played_at}). Exiting. Total time: {total_time:.2f} seconds")
            
            # Cache this "no new tracks" result for future calls
            _last_api_check_cache = "no_new_tracks"
            _last_api_check_time = current_time
            
            return [], None
        else:
            print(f"New track found since last check: {most_recent_track.get('track_name', 'UNKNOWN')} by {most_recent_track.get('artist', 'UNKNOWN')}, previously at {last_recent_played_at}")    
            
            # Clear the cache since we found new tracks
            _last_api_check_cache = None
            _last_api_check_time = None
        
        # No need to update a global variable anymore - the database will track this automatically        
        
        #print(f"Starting fetch_and_update_recent_tracks with limit: {limit}")

        # Step 1: Fetch recent tracks
        print("Calling fetch_recent_tracks...")
        recent_tracks, error = fetch_recent_tracks(limit=limit)
        print("Fetch recent tracks completed.")

        if error:
            print(f"Error returned from fetch_recent_tracks: {error}")
            return None, error

        if not recent_tracks:
            print("No tracks fetched.")
            return [], None

        datetime_format = '%Y-%m-%d %H:%M:%S'
        pacific_tz = pytz.timezone('America/Los_Angeles')
        current_local_time = datetime.now(pacific_tz)  # Get the current local time

        print(f"Processing {limit} fetched recent tracks...")
        for i, recent_track in enumerate(recent_tracks, start=1):
            
            played_at_raw = recent_track.get('played_at', 'MISSING')
            played_at_pacific = datetime.strptime(played_at_raw, datetime_format)
            # It appears that spotify is returning the time in local time, so we don't need to convert it
            #played_at_pacific = played_at_utc.replace(tzinfo=pytz.utc).astimezone(pacific_tz)
            output= f"FaURT Track {i} played at  {played_at_pacific}"

            # Check if the track already exists in the PlayedTrack table. If not, insert it.
            existing_track = PlayedTrack.query.filter_by(
                source='spotify',
                spotify_id=recent_track['track_id'],
                played_at=played_at_pacific
            ).first()

            if not existing_track:
                # Insert the new played track
                db_track = Track.query.filter_by(song=recent_track['track_name'], artist=recent_track['artist']).first()
                category = db_track.category if db_track else "None"

                new_played_track = PlayedTrack(
                    source='spotify',
                    artist=recent_track['artist'],
                    song=recent_track['track_name'],
                    spotify_id=recent_track['track_id'],
                    played_at=played_at_pacific,
                    category=category,
                    playlist_name=recent_track.get('playlist'),
                    created_at=current_local_time  # Set created_at to the current local time
                )
                db.session.add(new_played_track)
                db.session.commit()
                output += " Inserted track "

            
                # Try to find matching track by URI first - include all matched statuses
                db_track = Track.query.join(SpotifyURI).filter(
                    SpotifyURI.uri.like(f"%:{recent_track['track_id']}"),
                    SpotifyURI.status.in_(['matched', 'mismatch_accepted', 'manual_match'])
                ).first()
                
                # If no URI match, try song/artist match
                if not db_track:
                    # Normalize for comparison
                    recent_track_name_norm = normalize_text(recent_track['track_name'])
                    recent_artist_norm = normalize_text(recent_track['artist'])
                    
                    # Query using normalized fields if we had them, or compare normalized python-side
                    # For now, let's fetch potential matches and normalize Track.song and Track.artist in Python
                    # This is less efficient than a normalized DB query but avoids schema changes for now.
                    
                    # A more direct approach if we assume Track.song and Track.artist are reasonably clean:
                    # We will normalize the Track.song and Track.artist from the DB for comparison
                    
                    # First, try a case-insensitive raw match as before, then refine if needed,
                    # or directly go to a broader query if we expect many normalization variations.
                    
                    # Let's adjust to normalize the DB fields during comparison:
                    all_tracks_by_artist = Track.query.filter(func.lower(Track.artist) == func.lower(recent_track['artist'])).all()
                    found_match = False
                    for track_in_db in all_tracks_by_artist:
                        db_song_norm = normalize_text(track_in_db.song)
                        if db_song_norm == recent_track_name_norm:
                            db_track = track_in_db
                            found_match = True
                            break
                    if not found_match: # If no match by artist, try by song title (less likely to be unique)
                        all_tracks_by_song = Track.query.filter(func.lower(Track.song) == func.lower(recent_track['track_name'])).all()
                        for track_in_db in all_tracks_by_song:
                            db_artist_norm = normalize_text(track_in_db.artist)
                            if db_artist_norm == recent_artist_norm:
                                db_track = track_in_db
                                # found_match = True # Not strictly needed here as we assign db_track
                                break

                # Update last_play_dt if we found a match
                if db_track:
                    if not db_track.last_play_dt or played_at_pacific > db_track.last_play_dt:
                        db_track.last_play_dt = played_at_pacific
                        db_track.play_cnt = (db_track.play_cnt or 0) + 1
                    new_played_track.category = db_track.category
                else:
                    # Create new Track with 'Unmatched' category
                    new_track = Track(
                        song=recent_track['track_name'],
                        artist=recent_track['artist'],
                        category='Unmatched',
                        last_play_dt=played_at_pacific
                    )
                    db.session.add(new_track)
                    db.session.flush()  # Get the new track ID
                    new_played_track.category = 'Unmatched'
                    
                    # Create SpotifyURI record
                    new_uri = SpotifyURI(
                        track_id=new_track.id,
                        uri=f"spotify:track:{recent_track['track_id']}",
                        status='unmatched'
                    )
                    db.session.add(new_uri)
            else:
                output += " Already exists in played_tracks"
            
            db.session.commit()
            output += " Inserted track "
            print(f"{output} {recent_track.get('track_name', 'UNKNOWN')} by {recent_track.get('artist', 'UNKNOWN')}")

        print("All tracks processed successfully.")
        return recent_tracks, None
    except Exception as e:
        print(f"Unexpected error in fetch_and_update_recent_tracks: {str(e)}")
        return None, str(e)

    
def export_playlist_to_spotify(playlist_name, username=None, playlist_tracks=None):
    """
    Export a playlist to Spotify.

    :param playlist_name: The name of the playlist to export.
    :param db: The database session.
    :param username: (Optional) The username to fetch the playlist for. Defaults to the current user.
    :param playlist_tracks: (Optional) A list of playlist tracks to export. If not provided, they will be fetched from the database.
    :return: A tuple (success: bool, result: dict).
    """
    try:
        # Get Spotify client - use non-interactive for background tasks
        sp = get_spotify_client(allow_interactive_auth=False)
        if not sp:
            return False, {"message": "Spotify client not authenticated for background task.", "redirect": spotify_auth()}

        # Use the provided username or default to the current user
        username = username or current_user.username
        print(f"Starting export_playlist_to_spotify for playlist: {playlist_name} and username: {username}")
    
        # Fetch tracks for the playlist if not provided
        if playlist_tracks is None:
            playlist_tracks = Playlist.query.filter_by(
                username=username,
                playlist_name=playlist_name
            ).order_by(Playlist.track_position).all()

        # Create Spotify playlist
        success, result = create_spotify_playlist(playlist_name, playlist_tracks)
        return success, result

    except Exception as e:
        print(f"Error exporting playlist '{playlist_name}' to Spotify: {str(e)}")
        return False, {"message": f"Error: {str(e)}"}

def list_playlists():
    sp = get_spotify_client()
    if not sp:
        return False, "Spotify client not authenticated."

    playlists = sp.current_user_playlists(limit=50)
    result = []
    for playlist in playlists['items']:
        result.append({
            "name": playlist['name'],
            "owner": playlist['owner']['display_name'],
            "id": playlist['id']
        })
    return jsonify({"playlists": result})



def create_spotify_playlist(playlist_name, tracks, public=True):
    """Create or replace the 'kTunes' playlist on Spotify and add tracks."""
    print(f"Starting create_spotify_playlist: {playlist_name}")
    mismatches = []
    # Use non-interactive auth for background tasks
    sp = get_spotify_client(allow_interactive_auth=False)
    if not sp:
        return False, "Spotify client not authenticated for background task."

    user_id = sp.me()['id']
    
    existing_playlist_id = None
    playlists = sp.current_user_playlists(limit=50)
    for playlist in playlists['items']:
        if playlist['name'] == playlist_name:
            existing_playlist_id = playlist['id']
            break

    # If the playlist exists, remove all its current songs
    if existing_playlist_id:
        print(f"Removing all songs from existing playlist: {playlist_name}")
        sp.playlist_replace_items(existing_playlist_id, [])
        playlist_id = existing_playlist_id
    else:
        playlist = sp.user_playlist_create(user_id, playlist_name, public=public)
        playlist_id = playlist['id']
        print(f"Creating new playlist: {playlist_name}")

    if playlist_name.startswith("KRUG"):
        now = datetime.now(pytz.timezone('America/Los_Angeles')).strftime("%B %d, %Y %I:%M %p")
        description = f"Curated for nostalgic souls who love newer music. Updated {now}."
        sp.playlist_change_details(playlist_id, description=description)
        # Load and upload the image
        print(f"Uploading image to playlist: {playlist_name}")
        #image_path = '/home/kkrug/apps/ktunes/static/images/krugfm96-2.png'
        image_path = os.path.join(current_app.static_folder, 'images', 'krugfm96-2.png')
        try:
            # Encode the image to Base64
            encoded_image = encode_image_to_base64(image_path)
            if not encoded_image:
                print("Failed to encode image to Base64. Aborting.")
                return False, "Failed to encode image to Base64."

            # Upload the Base64-encoded image
            sp.playlist_upload_cover_image(playlist_id, encoded_image)
            print(f"Uploaded image to playlist: {playlist_name}")
        except Exception as e:
            print(f"Error uploading playlist image: {e}")
            return False, f"Error uploading playlist image: {e}"

    track_uris = []
    invalid_uris = []
    failed_tracks = []
    excluded_artists = {"Radio Promo", "Liam"}  # Artists to exclude from failure rule
    print(f"Processing {len(tracks)} tracks")
    for track in tracks:
        db_track = db.session.query(Track).filter_by(song=track.song, artist=track.artist).first()

        if db_track:
            # Check for any matched URIs in SpotifyURI table
            matched_uri = SpotifyURI.query.filter_by(
                track_id=db_track.id,
                status='matched'
            ).first()
            if matched_uri:
                # Validate URI format before adding
                uri = matched_uri.uri.strip()
                if uri.startswith("spotify:track") and len(uri) > 14:
                    track_uris.append(uri)
                else:
                    print(f"Invalid URI format found in database: '{uri}' for {track.song} by {track.artist}")
                    invalid_uris.append({
                        'song': track.song,
                        'artist': track.artist,
                        'uri': uri
                    })
                continue
            # Check if this track is already known to not be in Spotify
            is_known_not_in_spotify = False
            if db_track:
                existing_spotify_uri = SpotifyURI.query.filter_by(track_id=db_track.id).first()
                if existing_spotify_uri and existing_spotify_uri.status in ['not_found_in_spotify', 'confirmed_no_spotify']:
                    is_known_not_in_spotify = True
                    
            if track.artist not in excluded_artists and not is_known_not_in_spotify:
                query = f"{track.song} artist:{track.artist}"
                print(f"Searching Spotify for: {query}")
                results = sp.search(q=query, type='track', limit=1)

                if results['tracks']['items']:
                    spotify_track = results['tracks']['items'][0]
                    spotify_uri = spotify_track['uri']
                    spotify_song = spotify_track['name']
                    spotify_artist_original = ', '.join(artist['name'] for artist in spotify_track['artists'])
                    spotify_api_url = spotify_track['href']  # API URL for the song
                    spotify_url = spotify_track['external_urls']['spotify']  # Spotify URL for the song

                    # Normalize local and Spotify track/artist names for comparison using enhanced matching
                    local_song_norm = normalize_text_for_matching(track.song)
                    local_artist_norm = normalize_text_for_matching(track.artist)
                    spotify_song_norm = normalize_text_for_matching(spotify_song)
                    spotify_artist_norm = normalize_text_for_matching(spotify_artist_original)

                    # Compare the normalized song and artist names
                    is_mismatch = local_song_norm != spotify_song_norm or local_artist_norm != spotify_artist_norm

                    if is_mismatch:
                        # NEW: Create SpotifyURI record with mismatch_accepted status
                        if db_track:
                            # Check if SpotifyURI already exists for this track
                            existing_uri = SpotifyURI.query.filter_by(track_id=db_track.id).first()
                            if existing_uri:
                                # Update existing record
                                existing_uri.uri = spotify_uri
                                existing_uri.status = 'mismatch_accepted'
                                print(f"  Updated existing SpotifyURI for '{track.song}' to 'mismatch_accepted'.")
                            else:
                                # Create new SpotifyURI record
                                new_uri = SpotifyURI(
                                    track_id=db_track.id,
                                    uri=spotify_uri,
                                    status='mismatch_accepted'
                                )
                                db.session.add(new_uri)
                                print(f"  Created SpotifyURI for mismatch '{track.song}' with status 'mismatch_accepted'.")
                            db.session.commit()
                        
                        print(f"  Mismatch detected for '{track.song}'. Searched: {track.song}/{track.artist}, Found: {spotify_song}/{spotify_artist_original}.")
                    else:
                        # This is a correct match, so we create the SpotifyURI record with 'matched' status
                        if db_track:
                            new_uri = SpotifyURI(
                                track_id=db_track.id,
                                uri=spotify_uri,
                                status='matched'
                            )
                            db.session.add(new_uri)
                            db.session.commit()
                            print(f"  Correct match. SpotifyURI created for '{track.song}' with status 'matched'.")
                        else:
                            # This case implies the local track (from playlist_tracks) wasn't found in the Track table
                            # at the start of the loop if db_track was None there.
                            print(f"  Correct match for '{track.song}', but no corresponding local db_track record to associate SpotifyURI with.")
                    
                    # This print confirms URI was found, whether match or mismatch
                    print(f"  Found URI on Spotify: {spotify_uri} (Local track: '{track.song}')")
                    # Add to Spotify playlist URI list regardless of local match status
                    track_uris.append(spotify_uri)
                else:
                    if track.artist not in excluded_artists:
                        print(f"  Failed to find track on Spotify: {track.song} by {track.artist}")
                        failed_tracks.append({"song": track.song, "artist": track.artist})
                        # Update SpotifyURI status to 'not_found_in_spotify'
                        if db_track:
                            existing_spotify_uri = SpotifyURI.query.filter_by(track_id=db_track.id).first()
                            if existing_spotify_uri:
                                existing_spotify_uri.status = 'not_found_in_spotify'
                                existing_spotify_uri.uri = "spotify:track:not_found_in_spotify" # Placeholder URI
                                # Removed spotify_track_name and spotify_artist_name assignments
                                print(f"    Updated SpotifyURI for track ID {db_track.id} to 'not_found_in_spotify'.")
                            else:
                                new_uri_record = SpotifyURI(
                                    track_id=db_track.id,
                                    status='not_found_in_spotify',
                                    uri="spotify:track:not_found_in_spotify" # Placeholder URI
                                    # Removed spotify_track_name and spotify_artist_name keyword arguments
                                )
                                db.session.add(new_uri_record)
                                print(f"    Created new SpotifyURI for track ID {db_track.id} with status 'not_found_in_spotify'.")
                            db.session.commit()
                        else:
                            print(f"    Cannot update/create SpotifyURI as db_track is not available for {track.song} by {track.artist}")
                        

                    else:
                        print(f"  Skipping failure count for track: {track.song} by {track.artist}")

        # Stop if more than 10 non-excluded tracks have failed
        if len(failed_tracks) > 10:
            print("Too many tracks failed. Deleting playlist.")
            sp.current_user_unfollow_playlist(playlist_id)
            return False, {
                "message": f"Playlist '{playlist_name}' could not be created. Too many tracks were not found.",
                "failed_tracks": failed_tracks,
            }
        


    # Log invalid URIs if any were found
    if invalid_uris:
        print(f"Found {len(invalid_uris)} invalid URIs:")
        for invalid in invalid_uris:
            print(f"  {invalid['song']} by {invalid['artist']}: {invalid['uri']}")

    # Add found tracks to the playlist
    if track_uris:
        try:
            for i in range(0, len(track_uris), 100):
                sp.playlist_add_items(playlist_id, track_uris[i:i+100])

            if failed_tracks:
                return True, {
                    "message": f"Playlist '{playlist_name}' created successfully, but some tracks were not found.",
                    "failed_tracks": failed_tracks,
                }
            else:
                return True, {
                    "message": f"Playlist '{playlist_name}' created successfully.",
                    "failed_tracks": [],
                }
        except Exception as e:
            print(f"Error adding tracks to playlist: {e}")
            sp.current_user_unfollow_playlist(playlist_id)
            return False, {
                "message": f"Error creating playlist: {e}",
                "failed_tracks": failed_tracks,
            }
    else:
        print("No tracks found to add to the playlist. Deleting playlist.")
        sp.current_user_unfollow_playlist(playlist_id)
        return False, {
            "message": f"Playlist '{playlist_name}' could not be created. No tracks were found.",
            "failed_tracks": failed_tracks,
        }

def encode_image_to_base64(image_path):
    """
    Encodes an image file to a Base64 string for Spotify playlist covers.
    Converts to JPEG format and ensures it meets Spotify's requirements.

    :param image_path: Path to the image file
    :return: Base64-encoded string, or None if encoding fails
    """
    try:
        # Open and convert image to JPEG format
        with Image.open(image_path) as img:
            # Convert to RGB if necessary (removes transparency)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize if too large (Spotify recommends 300x300 minimum)
            max_size = (640, 640)  # Reasonable size that's not too large
            if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            # Save as JPEG to BytesIO
            import io
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG', quality=90, optimize=True)
            img_buffer.seek(0)
            
            # Check file size (Spotify limit is 256KB)
            img_size = len(img_buffer.getvalue())
            if img_size > 256 * 1024:  # 256KB limit
                # Reduce quality if too large
                img_buffer = io.BytesIO()
                img.save(img_buffer, format='JPEG', quality=70, optimize=True)
                img_buffer.seek(0)
                img_size = len(img_buffer.getvalue())
                
                if img_size > 256 * 1024:
                    print(f"Warning: Image still too large ({img_size} bytes) after compression")
            
            # Encode to base64
            encoded_image = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
            print(f"Image encoded successfully: {img_size} bytes")
            return encoded_image
            
    except Exception as e:
        print(f"Error encoding image to Base64: {e}")
        return None

def check_if_krug_playlist_is_playing():
    """
    Check if the KRUG FM 96.2 playlist is currently being played on Spotify.
    
    Returns:
        tuple: (is_playing: bool, current_track_info: dict, error: str)
        - is_playing: True if KRUG FM 96.2 is currently playing
        - current_track_info: Dict with track details if playing, None otherwise
        - error: Error message if API call fails, None otherwise
    """
    # Use non-interactive auth for background tasks
    sp = get_spotify_client(allow_interactive_auth=False)
    if not sp:
        return False, None, "Spotify client not authenticated for background task."
    
    try:
        current_playback = sp.current_playback()
        
        # Check if anything is currently playing
        if not current_playback or not current_playback.get('is_playing'):
            return False, None, None
        
        # Check if playback is from a playlist context
        context = current_playback.get('context')
        if not context or context.get('type') != 'playlist':
            return False, None, None
        
        # Get the playlist URI and fetch playlist details
        playlist_uri = context.get('uri')
        if not playlist_uri:
            return False, None, None
        
        try:
            playlist = sp.playlist(playlist_uri)
            playlist_name = playlist.get('name', '')
            
            # Check if it's the KRUG FM 96.2 playlist
            if playlist_name == "KRUG FM 96.2":
                # Extract current track information
                track = current_playback.get('item', {})
                current_track_info = {
                    'track_name': track.get('name', 'Unknown'),
                    'artist': ', '.join(artist['name'] for artist in track.get('artists', [])),
                    'track_id': track.get('id'),
                    'progress_ms': current_playback.get('progress_ms', 0),
                    'duration_ms': track.get('duration_ms', 0),
                    'playlist_name': playlist_name,
                    'playlist_uri': playlist_uri
                }
                
                current_app.logger.info(f"KRUG FM 96.2 is currently playing: {current_track_info['track_name']} by {current_track_info['artist']}")
                return True, current_track_info, None
            else:
                current_app.logger.debug(f"Different playlist is playing: {playlist_name}")
                return False, None, None
                
        except Exception as playlist_error:
            current_app.logger.warning(f"Error fetching playlist details: {playlist_error}")
            return False, None, f"Error fetching playlist details: {playlist_error}"
        
    except Exception as e:
        current_app.logger.error(f"Error checking current playback: {e}")
        return False, None, f"Error checking current playback: {e}"

def fetch_recent_tracks(limit=50, ktunes_playlist_name="kTunes"):
    """Fetch the most recently played tracks from Spotify."""
    # Use non-interactive auth for background tasks (scheduled jobs)
    sp = get_spotify_client(allow_interactive_auth=False)
    if not sp:
        return None, "Spotify client not authenticated for background task."
    try:
        results = sp.current_user_recently_played(limit=limit)
        recent_tracks = []
        ktunes_playlist_uri = None  # Cache for the ktunes playlist URI
        local_tz = pytz.timezone('America/Los_Angeles')  # Replace with your local timezone
        print(f"Fetching {limit} recent tracks...")
        while results:
            for item in results['items']:
                track_name = item['track']['name']
                artist_name = ', '.join(artist['name'] for artist in item['track']['artists'])
                
                # Handle timestamps with and without microseconds
                played_at = item['played_at']
                try:
                    played_at_utc = datetime.strptime(played_at, "%Y-%m-%dT%H:%M:%S.%fZ")
                except ValueError:
                    played_at_utc = datetime.strptime(played_at, "%Y-%m-%dT%H:%M:%SZ")
                
                played_at_local = played_at_utc.replace(tzinfo=pytz.utc).astimezone(local_tz).strftime("%Y-%m-%d %H:%M:%S")
                track_id = item['track']['id']

                # Determine if the track is associated with a playlist
                # OPTIMIZATION: Skip expensive playlist lookups when only fetching 1 track for comparison
                context = item.get('context')
                playlist_name = None
                if context and context.get('type') == 'playlist' and limit > 1:
                    playlist_uri = context['uri']
                    if ktunes_playlist_uri and playlist_uri == ktunes_playlist_uri:
                        playlist_name = ktunes_playlist_name
                    else:
                        try:
                            playlist_name = sp.playlist(playlist_uri)['name']
                            if playlist_name == ktunes_playlist_name:
                                ktunes_playlist_uri = playlist_uri
                        except:
                            playlist_name = "Unknown Playlist"
                elif context and context.get('type') == 'playlist' and limit == 1:
                    # For single track fetches (comparison mode), just note that it was from a playlist
                    playlist_name = "playlist_context_skipped"

                recent_tracks.append({
                    'track_name': track_name,
                    'artist': artist_name,
                    'played_at': played_at_local,
                    'playlist': playlist_name,
                    'track_id': track_id
                })

            # Check if there are more pages of results
            if results.get('next'):
                results = sp.next(results)
            else:
                break  # Exit the loop if there are no more pages

        return recent_tracks[:limit], None
    except spotipy.exceptions.SpotifyException as e:
        error_message = f"Spotify API error: {e.http_status} - {e.msg}"
        current_app.logger.error(f"SpotifyException in fetch_recent_tracks: {error_message}")
        if e.http_status == 401: # Unauthorized / Token issue
            # Potentially trigger a re-auth or token refresh if applicable,
            # or notify user that re-authentication is needed.
            # For now, just log and return a specific message.
            error_message = "Spotify API unauthorized (401). Token may be invalid or expired."
        elif e.http_status == 404:
            error_message = "Spotify API resource not found (404)."
        elif e.http_status == 429:
            error_message = "Spotify API rate limit exceeded (429). Please try again later."
        elif e.http_status >= 500 and e.http_status <= 504: # Server-side errors (500, 502, 503, 504)
            error_message = f"Spotify API server error ({e.http_status}). Please try again later. Details: {e.msg}"
        
        # The original error from Spotipy (e) often contains the HTML response in e.msg for 502 etc.
        # We'll return our custom error_message instead of the raw e or str(e) to avoid logging full HTML.
        return None, error_message
    except Exception as e: # Catch any other unexpected errors
        current_app.logger.error(f"Unexpected generic exception in fetch_recent_tracks: {str(e)}")
        return None, f"Unexpected error fetching recent tracks: {str(e)}"

def _format_relative_time(played_at):
    """
    Format a datetime as relative time (e.g., '2 hours ago')
    """
    try:
        if not played_at:
            return 'Unknown'
        
        from datetime import datetime, timedelta
        import pytz
        
        # Ensure we're working with timezone-aware datetime
        if played_at.tzinfo is None:
            pacific_tz = pytz.timezone('America/Los_Angeles')
            played_at = pacific_tz.localize(played_at)
        
        now = datetime.now(played_at.tzinfo)
        diff = now - played_at
        
        if diff.days > 0:
            if diff.days == 1:
                return '1 day ago'
            else:
                return f'{diff.days} days ago'
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            if hours == 1:
                return '1 hour ago'
            else:
                return f'{hours} hours ago'
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            if minutes == 1:
                return '1 minute ago'
            else:
                return f'{minutes} minutes ago'
        else:
            return 'Just now'
    except Exception as e:
        current_app.logger.warning(f"Error formatting relative time: {e}")
        return 'Unknown'

def _get_time_period_stats(played_tracks):
    """
    Calculate statistics for the current time period
    
    Args:
        played_tracks: List of PlayedTrack objects
    
    Returns:
        dict: Statistics including total tracks, time period info
    """
    try:
        if not played_tracks:
            return {
                'total_tracks_in_period': 0,
                'time_period_start': None,
                'time_period_end': None,
                'period_description': 'No tracks'
            }
        
        # Get time range
        earliest_track = min(played_tracks, key=lambda t: t.played_at)
        latest_track = max(played_tracks, key=lambda t: t.played_at)
        
        # Calculate period description
        from datetime import datetime, timedelta
        import pytz
        
        pacific_tz = pytz.timezone('America/Los_Angeles')
        now = datetime.now(pacific_tz)
        
        # Ensure earliest_track.played_at is timezone-aware
        earliest_played_at = earliest_track.played_at
        if earliest_played_at.tzinfo is None:
            earliest_played_at = pacific_tz.localize(earliest_played_at)
        
        time_diff = now - earliest_played_at
        
        if time_diff.days > 7:
            period_description = f"Last {time_diff.days} days"
        elif time_diff.days > 1:
            period_description = f"Last {time_diff.days} days"
        elif time_diff.seconds > 3600:
            hours = time_diff.seconds // 3600
            period_description = f"Last {hours} hours"
        else:
            period_description = "Recent activity"
        
        return {
            'total_tracks_in_period': len(played_tracks),
            'time_period_start': earliest_track.played_at,
            'time_period_end': latest_track.played_at,
            'period_description': period_description
        }
    except Exception as e:
        current_app.logger.warning(f"Error calculating time period stats: {e}")
        return {
            'total_tracks_in_period': len(played_tracks) if played_tracks else 0,
            'time_period_start': None,
            'time_period_end': None,
            'period_description': 'Unknown period'
        }

def _format_track_data(track, from_krug_playlist=False, track_position=None, position_confidence='unknown', position_method='', position_info=None):
    """
    Helper function to format track data consistently with enhanced formatting
    """
    try:
        # Get play count from the Track model if available
        play_count = None
        db_track = None
        try:
            db_track = Track.query.filter_by(song=track.song, artist=track.artist).first()
            if db_track:
                play_count = db_track.play_cnt
        except Exception as db_error:
            current_app.logger.warning(f"Error fetching play count for track {track.id}: {db_error}")
        
        # Format track position display
        position_display = None
        if from_krug_playlist and position_info:
            if position_info.get('position'):
                position_display = f"Track #{position_info['position']}"
            else:
                position_display = "Position unknown"
        
        # Enhanced timestamp formatting
        played_at_formatted = 'Unknown'
        played_at_relative = 'Unknown'
        if track.played_at:
            try:
                played_at_formatted = track.played_at.strftime('%b %d, %Y at %I:%M %p')
                played_at_relative = _format_relative_time(track.played_at)
            except Exception as time_error:
                current_app.logger.warning(f"Error formatting timestamp for track {track.id}: {time_error}")
                played_at_formatted = track.played_at.strftime('%Y-%m-%d %H:%M:%S')
        
        return {
            'id': track.id,
            'artist': track.artist or 'Unknown Artist',
            'song': track.song or 'Unknown Song',
            'played_at': track.played_at,
            'played_at_formatted': played_at_formatted,
            'played_at_relative': played_at_relative,
            'category': track.category or 'Unknown',
            'playlist_name': track.playlist_name,
            'album': getattr(track, 'album', None),
            'spotify_id': getattr(track, 'spotify_id', None),
            'play_count': play_count,
            'from_krug_playlist': from_krug_playlist,
            'track_position': track_position,
            'position_confidence': position_confidence,
            'position_method': position_method,
            'position_info': position_info,
            'position_display': position_display
        }
    except Exception as e:
        current_app.logger.warning(f"Error formatting track data for track {getattr(track, 'id', 'unknown')}: {e}")
        # Return minimal safe data
        return {
            'id': getattr(track, 'id', 0),
            'artist': 'Unknown Artist',
            'song': 'Unknown Song',
            'played_at': None,
            'played_at_formatted': 'Unknown',
            'played_at_relative': 'Unknown',
            'category': 'Unknown',
            'playlist_name': None,
            'album': None,
            'spotify_id': None,
            'play_count': None,
            'from_krug_playlist': False,
            'track_position': None,
            'position_confidence': 'unknown',
            'position_method': 'Error formatting track data',
            'position_info': None,
            'position_display': None
        }

def get_listening_history_with_versioned_playlist_context(limit=50, offset=0):
    """
    Enhanced version of listening history correlation that uses playlist versioning.
    Falls back to current playlist correlation if versioning is unavailable.
    
    Args:
        limit (int): Maximum number of records to return
        offset (int): Number of records to skip for pagination
    
    Returns:
        tuple: (listening_data, total_count, error_message)
        - listening_data: List of enriched PlayedTrack records with versioned playlist context
        - total_count: Total number of available PlayedTrack records
        - error_message: None if successful, error message string if there were issues
    """
    from services.playlist_versioning_service import PlaylistVersioningService
    from services.playlist_versioning_config import get_versioning_config
    
    error_message = None
    start_time = time.time()
    
    try:
        # Get total count of played tracks
        try:
            total_count = db.session.query(func.count(PlayedTrack.id))\
                .filter(PlayedTrack.source == 'spotify')\
                .scalar()
        except Exception as count_error:
            current_app.logger.error(f"Error getting total count: {count_error}")
            return [], 0, "Error retrieving listening history count. Please try again."
        
        # Get played tracks
        try:
            played_tracks = db.session.query(PlayedTrack)\
                .filter(PlayedTrack.source == 'spotify')\
                .order_by(PlayedTrack.played_at.desc())\
                .limit(limit)\
                .offset(offset)\
                .all()
        except Exception as query_error:
            current_app.logger.error(f"Error querying played tracks: {query_error}")
            return [], total_count, "Error retrieving listening history. Please try again."
        
        if not played_tracks:
            return [], total_count, None
        
        # Check if versioning is enabled
        config = get_versioning_config()
        use_versioning = config.is_playlist_enabled('KRUG FM 96.2')
        
        listening_data = []
        
        if use_versioning:
            # Check if any playlist versions exist
            from services.playlist_versioning_service import PlaylistVersioningService
            versioned_playlists = PlaylistVersioningService.get_all_versioned_playlists()
            
            if 'KRUG FM 96.2' in versioned_playlists:
                # Use versioned correlation
                current_app.logger.info("Using playlist versioning for correlation")
                for track in played_tracks:
                    correlation_result = correlate_track_with_versioned_playlist(
                        track.artist, track.song, track.played_at
                    )
                    listening_data.append(_format_versioned_track_data(track, correlation_result))
            else:
                # No versions exist yet - use temporal-aware correlation
                current_app.logger.info("No playlist versions found, using temporal-aware correlation")
                
                # Get the current playlist date for comparison
                try:
                    latest_playlist_date = db.session.query(func.max(Playlist.playlist_date))\
                        .filter(Playlist.playlist_name == 'KRUG FM 96.2')\
                        .scalar()
                except Exception as e:
                    current_app.logger.error(f"Error getting playlist date: {e}")
                    latest_playlist_date = None
                
                for track in played_tracks:
                    # Only correlate with current playlist if track was played AFTER playlist creation
                    if latest_playlist_date and track.played_at > latest_playlist_date:
                        # Track was played after current playlist was created - could be from this playlist
                        correlation_result = correlate_track_with_current_playlist_temporal(
                            track.artist, track.song, track.played_at, latest_playlist_date
                        )
                    else:
                        # Track was played before current playlist existed - cannot be from current playlist
                        correlation_result = {
                            'from_playlist': False,
                            'version_id': None,
                            'position': None,
                            'confidence': 'high',
                            'method': f'Played before current playlist (track: {track.played_at.strftime("%m/%d %H:%M")}, playlist: {latest_playlist_date.strftime("%m/%d %H:%M") if latest_playlist_date else "unknown"})',
                            'version_date': None
                        }
                    
                    listening_data.append(_format_versioned_track_data(track, correlation_result))
        else:
            # Fall back to current playlist correlation
            current_app.logger.info("Versioning disabled, falling back to current playlist correlation")
            return get_listening_history_with_playlist_context(limit, offset)
        
        correlation_time = time.time() - start_time
        current_app.logger.info(f"Versioned correlation completed in {correlation_time:.3f}s for {len(listening_data)} tracks")
        
        return listening_data, total_count, error_message
        
    except Exception as e:
        current_app.logger.error(f"Unexpected error in versioned listening history: {e}")
        # Fall back to current method
        current_app.logger.info("Falling back to current playlist correlation due to error")
        return get_listening_history_with_playlist_context(limit, offset)


def correlate_track_with_current_playlist_temporal(artist: str, song: str, played_at: datetime, playlist_date: datetime) -> dict:
    """
    Correlate a track with the current playlist, but only if timing makes sense.
    
    Args:
        artist: Track artist
        song: Track title
        played_at: When the track was played
        playlist_date: When the current playlist was created
        
    Returns:
        dict: Correlation result with timing-aware logic
    """
    try:
        # Query current playlist for this track
        from sqlalchemy import and_
        
        playlist_track = db.session.query(Playlist).filter(
            and_(
                Playlist.playlist_name == 'KRUG FM 96.2',
                Playlist.artist == artist,
                Playlist.song == song,
                Playlist.playlist_date == playlist_date
            )
        ).first()

        if not playlist_track:
            # Fallback to normalized comparison so formatting differences still match
            normalized_artist = normalize_text(artist)
            normalized_song = normalize_text(song)

            candidate_tracks = db.session.query(Playlist).filter(
                and_(
                    Playlist.playlist_name == 'KRUG FM 96.2',
                    Playlist.playlist_date == playlist_date
                )
            ).all()

            for candidate in candidate_tracks:
                if (normalize_text(candidate.artist) == normalized_artist and
                        normalize_text(candidate.song) == normalized_song):
                    playlist_track = candidate
                    break

        if playlist_track:
            return {
                'from_playlist': True,
                'version_id': f'current-{playlist_date.strftime("%Y%m%d-%H%M")}',
                'position': playlist_track.track_position,
                'confidence': 'medium',  # Medium because we can't be 100% sure without versions
                'method': f'Found in current playlist (created {playlist_date.strftime("%m/%d %H:%M")})',
                'version_date': playlist_date
            }
        else:
            return {
                'from_playlist': False,
                'version_id': None,
                'position': None,
                'confidence': 'high',
                'method': 'Not found in current playlist',
                'version_date': None
            }
            
    except Exception as e:
        current_app.logger.error(f"Error in temporal correlation for '{artist} - {song}': {str(e)}")
        return {
            'from_playlist': False,
            'version_id': None,
            'position': None,
            'confidence': 'unknown',
            'method': f'Correlation error: {str(e)}',
            'version_date': None
        }


def correlate_track_with_versioned_playlist(artist: str, song: str, played_at: datetime) -> dict:
    """
    Correlate a played track with the appropriate playlist version.
    
    Args:
        artist: Track artist
        song: Track title
        played_at: When the track was played
        
    Returns:
        dict: Correlation result with version info, position, confidence level
    """
    from services.playlist_versioning_service import PlaylistVersioningService
    
    try:
        # Find the playlist version that was active when the track was played
        active_version = PlaylistVersioningService.get_active_version_at_time(
            'KRUG FM 96.2', played_at, username='kkrug'
        )
        
        if not active_version:
            return {
                'from_playlist': False,
                'version_id': None,
                'position': None,
                'confidence': 'unknown',
                'method': 'No playlist version found for timestamp',
                'version_date': None
            }
        
        # Look for the track in this version
        version_track = PlaylistVersioningService.find_track_in_version(
            active_version.version_id, artist, song
        )
        
        if version_track:
            return {
                'from_playlist': True,
                'version_id': active_version.version_id,
                'position': version_track.track_position,
                'confidence': 'high',
                'method': f'Found in version {active_version.version_id[:8]}',
                'version_date': active_version.active_from
            }
        else:
            return {
                'from_playlist': False,
                'version_id': active_version.version_id,
                'position': None,
                'confidence': 'high',
                'method': f'Not found in active version {active_version.version_id[:8]}',
                'version_date': active_version.active_from
            }
            
    except Exception as e:
        current_app.logger.error(f"Error correlating track '{artist} - {song}' at {played_at}: {str(e)}")
        return {
            'from_playlist': False,
            'version_id': None,
            'position': None,
            'confidence': 'unknown',
            'method': f'Correlation error: {str(e)}',
            'version_date': None
        }


def _format_versioned_track_data(track: PlayedTrack, correlation_result: dict) -> dict:
    """
    Format track data with versioned playlist correlation information.
    
    Args:
        track: PlayedTrack object
        correlation_result: Result from correlate_track_with_versioned_playlist
        
    Returns:
        Formatted track data dictionary
    """
    # Calculate relative time
    now = datetime.utcnow()
    time_diff = now - track.played_at
    
    if time_diff.days > 0:
        relative_time = f"{time_diff.days} day{'s' if time_diff.days != 1 else ''} ago"
    elif time_diff.seconds > 3600:
        hours = time_diff.seconds // 3600
        relative_time = f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif time_diff.seconds > 60:
        minutes = time_diff.seconds // 60
        relative_time = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    else:
        relative_time = "Just now"
    
    # Format timestamps
    played_at_formatted = 'Unknown'
    if track.played_at:
        try:
            played_at_formatted = track.played_at.strftime('%b %d, %Y at %I:%M %p')
        except Exception as time_error:
            current_app.logger.warning(f"Error formatting timestamp for track {track.id}: {time_error}")
            played_at_formatted = track.played_at.strftime('%Y-%m-%d %H:%M:%S')
    
    # Format position information
    if correlation_result['from_playlist'] and correlation_result['position']:
        position_display = f"Track #{correlation_result['position']}"
        if correlation_result['version_date']:
            version_date_str = correlation_result['version_date'].strftime('%m/%d %H:%M')
            position_display += f" (v{version_date_str})"
    else:
        position_display = correlation_result['method']
    
    return {
        'id': getattr(track, 'id', 0),
        'artist': track.artist,
        'song': track.song,
        'played_at': track.played_at,
        'played_at_formatted': played_at_formatted,
        'played_at_relative': relative_time,
        'relative_time': relative_time,  # Keep both for compatibility
        'category': getattr(track, 'category', 'Unknown'),
        'album': getattr(track, 'album', 'Unknown Album'),
        'spotify_id': getattr(track, 'spotify_id', None),
        'from_krug_playlist': correlation_result['from_playlist'],
        'position': correlation_result['position'],
        'position_display': position_display,
        'confidence': correlation_result['confidence'],
        'version_id': correlation_result['version_id'],
        'version_date': correlation_result['version_date'],
        'correlation_method': correlation_result['method']
    }


def get_listening_history_with_playlist_context(limit=50, offset=0):
    """
    Retrieve recent listening history from PlayedTrack with playlist correlation
    Optimized with caching and improved database queries
    
    Args:
        limit (int): Maximum number of records to return
        offset (int): Number of records to skip for pagination
    
    Returns:
        tuple: (listening_data, total_count, error_message)
        - listening_data: List of enriched PlayedTrack records with playlist context
        - total_count: Total number of available PlayedTrack records
        - error_message: None if successful, error message string if there were issues
    """
    from services.cache_service import (
        get_cached_playlist_data, cache_playlist_data,
        get_cached_playlist_lookup, cache_playlist_lookup
    )
    
    error_message = None
    start_time = time.time()
    
    try:
        # Optimized total count query with index hint
        try:
            total_count = db.session.query(func.count(PlayedTrack.id))\
                .filter(PlayedTrack.source == 'spotify')\
                .scalar()
        except Exception as count_error:
            current_app.logger.error(f"Error getting total count: {count_error}")
            return [], 0, "Error retrieving listening history count. Please try again."
        
        # Optimized played tracks query using index on (source, played_at)
        try:
            played_tracks = db.session.query(PlayedTrack)\
                .filter(PlayedTrack.source == 'spotify')\
                .order_by(PlayedTrack.played_at.desc())\
                .limit(limit)\
                .offset(offset)\
                .all()
        except Exception as query_error:
            current_app.logger.error(f"Error querying played tracks: {query_error}")
            return [], total_count, "Error retrieving listening history. Please try again."
        
        if not played_tracks:
            return [], total_count, None
        
        # Optimized playlist date query with index on (playlist_name, playlist_date)
        try:
            latest_playlist_date = db.session.query(func.max(Playlist.playlist_date))\
                .filter(Playlist.playlist_name == 'KRUG FM 96.2')\
                .scalar()
        except Exception as playlist_date_error:
            current_app.logger.error(f"Error querying playlist date: {playlist_date_error}")
            # Graceful degradation - return tracks without playlist context
            error_message = "Unable to load playlist data. Showing listening history without playlist context."
            listening_data = []
            for track in played_tracks:
                listening_data.append(_format_track_data(
                    track, 
                    from_krug_playlist=False,
                    position_method='Playlist data unavailable due to database error'
                ))
            return listening_data, total_count, error_message
        
        if not latest_playlist_date:
            # No KRUG FM 96.2 playlist found, return tracks without playlist context
            current_app.logger.info("No KRUG FM 96.2 playlist found in database")
            error_message = "No KRUG FM 96.2 playlist found. Showing listening history without playlist context."
            listening_data = []
            for track in played_tracks:
                listening_data.append(_format_track_data(
                    track, 
                    from_krug_playlist=False,
                    position_method='No KRUG FM 96.2 playlist found'
                ))
            return listening_data, total_count, error_message
        
        # Try to get playlist data from cache first
        playlist_data = get_cached_playlist_data('KRUG FM 96.2', latest_playlist_date)
        
        if playlist_data is None:
            # Cache miss - query database with optimized query using composite index
            try:
                playlist_data = db.session.query(Playlist)\
                    .filter(
                        Playlist.playlist_name == 'KRUG FM 96.2',
                        Playlist.playlist_date == latest_playlist_date
                    )\
                    .order_by(Playlist.track_position)\
                    .all()
                
                # Cache the result for 10 minutes
                cache_playlist_data('KRUG FM 96.2', latest_playlist_date, playlist_data, ttl=600)
                
            except Exception as playlist_query_error:
                current_app.logger.error(f"Error querying playlist data: {playlist_query_error}")
                # Graceful degradation - return tracks without playlist context
                error_message = "Unable to load playlist tracks. Showing listening history without playlist context."
                listening_data = []
                for track in played_tracks:
                    listening_data.append(_format_track_data(
                        track, 
                        from_krug_playlist=False,
                        position_method='Playlist tracks unavailable due to database error'
                    ))
                return listening_data, total_count, error_message
        
        if not playlist_data:
            # Playlist exists but has no tracks
            current_app.logger.warning(f"KRUG FM 96.2 playlist found but contains no tracks (date: {latest_playlist_date})")
            error_message = "KRUG FM 96.2 playlist found but appears to be empty. Showing listening history without playlist context."
            listening_data = []
            for track in played_tracks:
                listening_data.append(_format_track_data(
                    track, 
                    from_krug_playlist=False,
                    position_method='KRUG FM 96.2 playlist is empty'
                ))
            return listening_data, total_count, error_message
        
        # Try to get playlist lookup from cache
        playlist_lookup = get_cached_playlist_lookup('KRUG FM 96.2', latest_playlist_date)
        
        if playlist_lookup is None:
            # Cache miss - create lookup dictionary with error handling
            try:
                playlist_lookup = {}
                for playlist_track in playlist_data:
                    try:
                        key = (normalize_text(playlist_track.artist), normalize_text(playlist_track.song))
                        if key not in playlist_lookup:
                            playlist_lookup[key] = []
                        playlist_lookup[key].append({
                            'position': playlist_track.track_position,
                            'artist': playlist_track.artist,
                            'song': playlist_track.song
                        })
                    except Exception as normalize_error:
                        current_app.logger.warning(f"Error normalizing playlist track {playlist_track.id}: {normalize_error}")
                        continue  # Skip this track but continue processing others
                
                # Cache the lookup dictionary for 10 minutes
                cache_playlist_lookup('KRUG FM 96.2', latest_playlist_date, playlist_lookup, ttl=600)
                
            except Exception as lookup_error:
                current_app.logger.error(f"Error creating playlist lookup: {lookup_error}")
                # Graceful degradation - return tracks without playlist context
                error_message = "Error processing playlist data. Showing listening history without playlist context."
                listening_data = []
                for track in played_tracks:
                    listening_data.append(_format_track_data(
                        track, 
                        from_krug_playlist=False,
                        position_method='Playlist processing error'
                    ))
                return listening_data, total_count, error_message
        
        # Enrich played tracks with playlist context
        listening_data = []
        correlation_errors = 0
        
        for i, track in enumerate(played_tracks):
            try:
                track_key = (normalize_text(track.artist), normalize_text(track.song))
                
                if track_key in playlist_lookup:
                    # Track is from KRUG FM 96.2 playlist
                    playlist_matches = playlist_lookup[track_key]
                    
                    if len(playlist_matches) == 1:
                        # Single match - easy case
                        position_info = {
                            'position': playlist_matches[0]['position'],
                            'confidence': 'high',
                            'method': 'Single match in playlist'
                        }
                    else:
                        # Multiple matches - need to determine position from context
                        try:
                            surrounding_tracks = _get_surrounding_tracks(played_tracks, i, window_size=5)
                            position_info = determine_track_position_from_context(
                                track.artist, track.song, track.played_at,
                                surrounding_tracks, playlist_data
                            )
                        except Exception as context_error:
                            current_app.logger.warning(f"Error determining position from context for track {track.id}: {context_error}")
                            # Fallback to first match with low confidence
                            position_info = {
                                'position': playlist_matches[0]['position'],
                                'confidence': 'low',
                                'method': 'Context analysis failed, using first match'
                            }
                            correlation_errors += 1
                    
                    listening_data.append(_format_track_data(
                        track,
                        from_krug_playlist=True,
                        track_position=position_info['position'],
                        position_confidence=position_info['confidence'],
                        position_method=position_info['method'],
                        position_info={
                            'position': position_info['position'],
                            'confidence': position_info['confidence'],
                            'method': position_info['method']
                        }
                    ))
                else:
                    # Track is not from KRUG FM 96.2 playlist
                    listening_data.append(_format_track_data(
                        track,
                        from_krug_playlist=False,
                        position_method='Not in KRUG FM 96.2 playlist'
                    ))
                    
            except Exception as track_error:
                current_app.logger.warning(f"Error processing track {track.id}: {track_error}")
                # Add track with minimal data to avoid losing it completely
                listening_data.append(_format_track_data(
                    track,
                    from_krug_playlist=False,
                    position_method='Track processing error'
                ))
                correlation_errors += 1
        
        # Set warning message if there were correlation errors
        if correlation_errors > 0:
            if not error_message:  # Don't override more serious error messages
                error_message = f"Some tracks ({correlation_errors}) had issues with playlist correlation. Position information may be incomplete."
        
        # Add time period statistics to the first track for template access
        if listening_data:
            time_stats = _get_time_period_stats(played_tracks)
            listening_data[0]['time_period_stats'] = time_stats
        
        # Log performance metrics
        end_time = time.time()
        query_time = end_time - start_time
        current_app.logger.info(f"Listening history query completed in {query_time:.3f}s for {len(listening_data)} tracks")
        
        # Warn if query is taking too long
        if query_time > 2.0:
            current_app.logger.warning(f"Slow query detected: listening history took {query_time:.3f}s (target: <2s)")
            if not error_message:
                error_message = f"Query completed but took longer than expected ({query_time:.1f}s). Consider reducing the number of results per page."
        
        return listening_data, total_count, error_message
        
    except Exception as e:
        current_app.logger.error(f"Unexpected error in get_listening_history_with_playlist_context: {e}")
        return [], 0, f"An unexpected error occurred while loading listening history: {str(e)}"


def determine_track_position_from_context(artist, song, played_at, surrounding_tracks, playlist_data):
    """
    Determine track position for repeated songs using context analysis
    
    Args:
        artist (str): Track artist from PlayedTrack
        song (str): Track title from PlayedTrack  
        played_at (datetime): When the track was played from PlayedTrack
        surrounding_tracks: List of PlayedTrack objects played around the same time
        playlist_data: Playlist data for the most recent KRUG FM 96.2 playlist
    
    Returns:
        dict: Position information with confidence level
        - position: int or None
        - confidence: 'high', 'medium', 'low', or 'unknown'
        - method: description of how position was determined
    """
    try:
        # Create playlist lookup by position
        playlist_by_position = {}
        for playlist_track in playlist_data:
            playlist_by_position[playlist_track.track_position] = {
                'artist': playlist_track.artist,
                'song': playlist_track.song
            }
        
        # Find all possible positions for this track in the playlist
        target_key = (normalize_text(artist), normalize_text(song))
        possible_positions = []
        
        for playlist_track in playlist_data:
            playlist_key = (normalize_text(playlist_track.artist), normalize_text(playlist_track.song))
            if playlist_key == target_key:
                possible_positions.append(playlist_track.track_position)
        
        if not possible_positions:
            return {
                'position': None,
                'confidence': 'unknown',
                'method': 'Track not found in playlist'
            }
        
        if len(possible_positions) == 1:
            return {
                'position': possible_positions[0],
                'confidence': 'high',
                'method': 'Single occurrence in playlist'
            }
        
        # Multiple positions - analyze context
        best_position = None
        best_score = 0
        best_method = 'Context analysis failed'
        
        for position in possible_positions:
            score, method = _analyze_position_context(
                position, surrounding_tracks, playlist_by_position, played_at
            )
            
            if score > best_score:
                best_score = score
                best_position = position
                best_method = method
        
        # Determine confidence based on score
        if best_score >= 3:
            confidence = 'high'
        elif best_score >= 2:
            confidence = 'medium'
        elif best_score >= 1:
            confidence = 'low'
        else:
            confidence = 'unknown'
            best_position = possible_positions[0]  # Default to first occurrence
            best_method = 'No context match - using first occurrence'
        
        return {
            'position': best_position,
            'confidence': confidence,
            'method': best_method
        }
        
    except Exception as e:
        current_app.logger.error(f"Error in determine_track_position_from_context: {e}")
        return {
            'position': None,
            'confidence': 'unknown',
            'method': f'Error during analysis: {str(e)}'
        }


def _get_surrounding_tracks(played_tracks, current_index, window_size=5):
    """
    Get tracks played before and after the current track within a time window
    
    Args:
        played_tracks: List of PlayedTrack objects
        current_index: Index of the current track
        window_size: Number of tracks to include before and after
    
    Returns:
        dict: Dictionary with 'before' and 'after' track lists
    """
    try:
        # Validate inputs
        if not played_tracks or current_index < 0 or current_index >= len(played_tracks):
            return {'before': [], 'after': []}
        
        if window_size < 0:
            window_size = 5  # Default fallback
        
        start_index = max(0, current_index - window_size)
        end_index = min(len(played_tracks), current_index + window_size + 1)
        
        before_tracks = played_tracks[start_index:current_index]
        after_tracks = played_tracks[current_index + 1:end_index]
        
        return {
            'before': before_tracks,
            'after': after_tracks
        }
    except Exception as e:
        current_app.logger.warning(f"Error getting surrounding tracks: {e}")
        return {'before': [], 'after': []}


def _analyze_position_context(position, surrounding_tracks, playlist_by_position, played_at):
    """
    Analyze the context around a potential position to determine likelihood
    
    Args:
        position: The playlist position to analyze
        surrounding_tracks: Dictionary with 'before' and 'after' track lists
        playlist_by_position: Dictionary mapping positions to track info
        played_at: When the track was played
    
    Returns:
        tuple: (score, method_description)
    """
    try:
        score = 0
        method_parts = []
        
        # Validate inputs
        if not isinstance(surrounding_tracks, dict) or not playlist_by_position or not played_at:
            return 0, "Invalid input data for context analysis"
        
        # Check tracks played before
        before_tracks = surrounding_tracks.get('before', [])
        for i, before_track in enumerate(reversed(before_tracks)):
            try:
                expected_position = position - (i + 1)
                if expected_position in playlist_by_position:
                    expected_track = playlist_by_position[expected_position]
                    before_key = (normalize_text(before_track.artist), normalize_text(before_track.song))
                    expected_key = (normalize_text(expected_track['artist']), normalize_text(expected_track['song']))
                    
                    if before_key == expected_key:
                        score += 1
                        method_parts.append(f"Match at position {expected_position}")
                        
                        # Check time proximity (tracks should be played close together)
                        if hasattr(before_track, 'played_at') and before_track.played_at:
                            time_diff = abs((played_at - before_track.played_at).total_seconds())
                            if time_diff < 300:  # Within 5 minutes
                                score += 0.5
                                method_parts.append("Close time proximity")
            except Exception as before_error:
                current_app.logger.warning(f"Error analyzing before track {i}: {before_error}")
                continue  # Skip this track but continue with others
        
        # Check tracks played after
        after_tracks = surrounding_tracks.get('after', [])
        for i, after_track in enumerate(after_tracks):
            try:
                expected_position = position + (i + 1)
                if expected_position in playlist_by_position:
                    expected_track = playlist_by_position[expected_position]
                    after_key = (normalize_text(after_track.artist), normalize_text(after_track.song))
                    expected_key = (normalize_text(expected_track['artist']), normalize_text(expected_track['song']))
                    
                    if after_key == expected_key:
                        score += 1
                        method_parts.append(f"Match at position {expected_position}")
                        
                        # Check time proximity
                        if hasattr(after_track, 'played_at') and after_track.played_at:
                            time_diff = abs((after_track.played_at - played_at).total_seconds())
                            if time_diff < 300:  # Within 5 minutes
                                score += 0.5
                                method_parts.append("Close time proximity")
            except Exception as after_error:
                current_app.logger.warning(f"Error analyzing after track {i}: {after_error}")
                continue  # Skip this track but continue with others
        
        # Look for sequence patterns (consecutive tracks from playlist)
        try:
            sequence_score = _check_sequence_patterns(
                position, surrounding_tracks, playlist_by_position
            )
            score += sequence_score
            if sequence_score > 0:
                method_parts.append(f"Sequence pattern (+{sequence_score})")
        except Exception as sequence_error:
            current_app.logger.warning(f"Error checking sequence patterns: {sequence_error}")
            # Continue without sequence analysis
        
        method = '; '.join(method_parts) if method_parts else 'No context matches'
        return score, method
        
    except Exception as e:
        current_app.logger.error(f"Error in _analyze_position_context: {e}")
        return 0, f"Context analysis error: {str(e)}"


def _check_sequence_patterns(position, surrounding_tracks, playlist_by_position):
    """
    Check for consecutive playlist sequences in the surrounding tracks
    
    Args:
        position: The playlist position to analyze
        surrounding_tracks: Dictionary with 'before' and 'after' track lists
        playlist_by_position: Dictionary mapping positions to track info
    
    Returns:
        float: Additional score for sequence patterns
    """
    try:
        sequence_score = 0
        
        # Validate inputs
        if not isinstance(surrounding_tracks, dict) or not playlist_by_position:
            return 0
        
        # Check for ascending sequence (tracks played in playlist order)
        before_tracks = surrounding_tracks.get('before', [])
        after_tracks = surrounding_tracks.get('after', [])
        
        # Look for consecutive matches before the current position
        consecutive_before = 0
        for i, before_track in enumerate(reversed(before_tracks)):
            try:
                check_position = position - (i + 1)
                if check_position in playlist_by_position:
                    expected_track = playlist_by_position[check_position]
                    before_key = (normalize_text(before_track.artist), normalize_text(before_track.song))
                    expected_key = (normalize_text(expected_track['artist']), normalize_text(expected_track['song']))
                    
                    if before_key == expected_key:
                        consecutive_before += 1
                    else:
                        break
            except Exception as before_seq_error:
                current_app.logger.warning(f"Error checking before sequence at position {i}: {before_seq_error}")
                break  # Stop sequence checking on error
        
        # Look for consecutive matches after the current position
        consecutive_after = 0
        for i, after_track in enumerate(after_tracks):
            try:
                check_position = position + (i + 1)
                if check_position in playlist_by_position:
                    expected_track = playlist_by_position[check_position]
                    after_key = (normalize_text(after_track.artist), normalize_text(after_track.song))
                    expected_key = (normalize_text(expected_track['artist']), normalize_text(expected_track['song']))
                    
                    if after_key == expected_key:
                        consecutive_after += 1
                    else:
                        break
            except Exception as after_seq_error:
                current_app.logger.warning(f"Error checking after sequence at position {i}: {after_seq_error}")
                break  # Stop sequence checking on error
        
        # Award bonus points for consecutive sequences
        total_consecutive = consecutive_before + consecutive_after
        if total_consecutive >= 3:
            sequence_score += 2  # Strong sequence pattern
        elif total_consecutive >= 2:
            sequence_score += 1  # Moderate sequence pattern
        elif total_consecutive >= 1:
            sequence_score += 0.5  # Weak sequence pattern
        
        return sequence_score
        
    except Exception as e:
        current_app.logger.error(f"Error in _check_sequence_patterns: {e}")
        return 0

def cleanup_listening_history_cache():
    """
    Cleanup function to invalidate listening history related caches
    Should be called when playlist data is updated
    """
    from services.cache_service import invalidate_playlist_cache, log_cache_stats
    
    try:
        # Invalidate all KRUG FM 96.2 playlist caches
        invalidate_playlist_cache('KRUG FM 96.2')
        
        # Log cache stats after cleanup
        log_cache_stats()
        
        current_app.logger.info("Listening history cache cleanup completed")
        
    except Exception as e:
        current_app.logger.error(f"Error during cache cleanup: {e}")

def optimize_database_queries():
    """
    Function to analyze and suggest database optimizations
    This can be called periodically to monitor query performance
    """
    try:
        # Check if indexes exist by attempting to use them
        start_time = time.time()
        
        # Test the main queries used in listening history
        test_count = db.session.query(func.count(PlayedTrack.id))\
            .filter(PlayedTrack.source == 'spotify')\
            .scalar()
        
        count_time = time.time() - start_time
        
        start_time = time.time()
        test_tracks = db.session.query(PlayedTrack)\
            .filter(PlayedTrack.source == 'spotify')\
            .order_by(PlayedTrack.played_at.desc())\
            .limit(10)\
            .all()
        
        query_time = time.time() - start_time
        
        start_time = time.time()
        test_playlist_date = db.session.query(func.max(Playlist.playlist_date))\
            .filter(Playlist.playlist_name == 'KRUG FM 96.2')\
            .scalar()
        
        playlist_date_time = time.time() - start_time
        
        # Log performance metrics
        current_app.logger.info(f"Database performance check - Count: {count_time:.3f}s, Query: {query_time:.3f}s, Playlist date: {playlist_date_time:.3f}s")
        
        # Warn about slow queries
        if count_time > 0.5:
            current_app.logger.warning(f"Slow count query detected: {count_time:.3f}s - consider adding index on played_tracks(source)")
        
        if query_time > 0.5:
            current_app.logger.warning(f"Slow main query detected: {query_time:.3f}s - consider adding index on played_tracks(source, played_at)")
        
        if playlist_date_time > 0.5:
            current_app.logger.warning(f"Slow playlist date query detected: {playlist_date_time:.3f}s - consider adding index on playlists(playlist_name, playlist_date)")
        
        return {
            'count_time': count_time,
            'query_time': query_time,
            'playlist_date_time': playlist_date_time,
            'total_records': test_count
        }
        
    except Exception as e:
        current_app.logger.error(f"Error during database optimization check: {e}")
        return None
