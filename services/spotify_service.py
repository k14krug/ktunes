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


def get_spotify_client():
    """
    Get an authenticated Spotify client using SpotifyOAuth.
    """
    try:
        sp_oauth = SpotifyOAuth(
            client_id=current_app.config['SPOTIPY_CLIENT_ID'],
            client_secret=current_app.config['SPOTIPY_CLIENT_SECRET'],
            redirect_uri=current_app.config['SPOTIPY_REDIRECT_URI'],
            scope="playlist-modify-public playlist-modify-private playlist-read-private playlist-read-collaborative user-read-recently-played ugc-image-upload",
        )
        return spotipy.Spotify(auth_manager=sp_oauth)
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
        scope="playlist-modify-public playlist-modify-private playlist-read-private playlist-read-collaborative user-read-recently-played ugc-image-upload"
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

last_recent_played_at = None  # In-memory variable to track the last fetched played_at

def fetch_and_update_recent_tracks(limit=50):   
    """
    Fetch recent Spotify tracks and update the database accordingly.

    :param limit: The maximum number of recent tracks to fetch.
    :return: A tuple of (tracks, error) where `tracks` contains the updated tracks, and `error` is None if successful.
    """
    global last_recent_played_at
    current_app.logger.info(f"Starting fetch and update_recent_tracks with limit: {limit}")
    try:
        print("Checking the most recent track...")
        # Fetch only the most recent track and compare it to the last time we did this check. If its newer we'll get the last 50, else no need to go further
        single_track_list, error = fetch_recent_tracks(limit=1)
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

        # Compare with our in-memory last_recent_played_at
        if last_recent_played_at and most_recent_track_time <= last_recent_played_at:
            print(f"No new track since last check({last_recent_played_at}). Exiting.")
            return [], None
        else:
            print(f"New track found since last check: {most_recent_track.get('track_name', 'UNKNOWN')} by {most_recent_track.get('artist', 'UNKNOWN')}, previously at {last_recent_played_at}")    
        
        # Update our last_recent_played_at with the new track time
        last_recent_played_at = most_recent_track_time        
        
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
        # Get Spotify client
        sp = get_spotify_client()
        if not sp:
            return False, {"message": "Spotify client not authenticated.", "redirect": spotify_auth()}

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
    sp = get_spotify_client()
    if not sp:
        return False, "Spotify client not authenticated."

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

                    # Normalize local and Spotify track/artist names for comparison
                    local_song_norm = normalize_text(track.song)
                    local_artist_norm = normalize_text(track.artist)
                    spotify_song_norm = normalize_text(spotify_song)
                    spotify_artist_norm = normalize_text(spotify_artist_original)

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

def fetch_recent_tracks(limit=50, ktunes_playlist_name="kTunes"):
    """Fetch the most recently played tracks from Spotify."""
    sp = get_spotify_client()
    if not sp:
        return None, "Spotify client not authenticated."
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
                context = item.get('context')
                playlist_name = None
                if context and context.get('type') == 'playlist':
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
