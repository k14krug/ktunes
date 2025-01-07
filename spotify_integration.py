import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import current_app, session, url_for, request, redirect, jsonify
from models import Track
import time
from datetime import datetime
import pytz

def get_spotify_client():
    """Get an authenticated Spotify client."""
    print(f"Getting spotify client")
    if 'spotify_token' not in session:
        return None

    token_info = session['spotify_token']
    if token_info['expires_at'] - 60 < time.time():
        sp_oauth = SpotifyOAuth(
            client_id=current_app.config['SPOTIPY_CLIENT_ID'],
            client_secret=current_app.config['SPOTIPY_CLIENT_SECRET'],
            redirect_uri=current_app.config['SPOTIPY_REDIRECT_URI']
        )
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        session['spotify_token'] = token_info
    print("Got spotify Token")
    return spotipy.Spotify(auth=token_info['access_token'])


def spotify_auth():
    """Redirect the user to Spotify authentication."""
    sp_oauth = SpotifyOAuth(
        client_id=current_app.config['SPOTIPY_CLIENT_ID'],
        client_secret=current_app.config['SPOTIPY_CLIENT_SECRET'],
        redirect_uri=current_app.config['SPOTIPY_REDIRECT_URI'],
        #scope="playlist-modify-public playlist-modify-private user-read-recently-played"
        scope="playlist-modify-public playlist-modify-private playlist-read-private playlist-read-collaborative user-read-recently-played"
    )
    auth_url = sp_oauth.get_authorize_url()
    return url_for('route_callback', _external=True, _scheme='http')


def spotify_callback():
    """Handle Spotify OAuth callback."""
    sp_oauth = SpotifyOAuth(
        client_id=current_app.config['SPOTIPY_CLIENT_ID'],
        client_secret=current_app.config['SPOTIPY_CLIENT_SECRET'],
        redirect_uri=current_app.config['SPOTIPY_REDIRECT_URI']
    )
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    session['spotify_token'] = token_info
    return redirect(url_for('playlists'))


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

def create_spotify_playlist(playlist_name, tracks, db,public=True):
    """Create or replace the 'kTunes' playlist on Spotify and add tracks."""
    print(f"Starting create_spotify_playlist: {playlist_name}")
    sp = get_spotify_client()
    if not sp:
        return False, "Spotify client not authenticated."

    user_id = sp.me()['id']
    
    # Check for an existing playlist named 'kTunes'
    existing_playlist_id = None
    playlists = sp.current_user_playlists(limit=50)
    for playlist in playlists['items']:
        print(f"Existing Spotify playlist: {playlist['name']}")
        if playlist['name'] == playlist_name:
            existing_playlist_id = playlist['id']
            break

    # If existing playlist and playlist_name starts with 'kTunes', use sp.current_user_unfollow_playlist to delete existing playlist_id
    if existing_playlist_id and playlist_name.startswith("kTunes"):
        print(f"Deleting existing playlist: {playlist_name}")
        sp.current_user_unfollow_playlist(existing_playlist_id)
        print(f"Deleted existing playlist: {playlist_name}")
    
    # Create the new 'kTunes' playlist
    playlist = sp.user_playlist_create(user_id, playlist_name, public=public)
    print(f"Creating new playlist: {playlist_name}")

    track_uris = []
    failed_tracks = []
    excluded_artists = {"Radio Promo", "Liam"}  # Artists to exclude from failure rule
    print(f"Processing {len(tracks)} tracks")
    for track in tracks:
        #print(f"Processing track: {track.song} by {track.artist}")
        db_track = db.session.query(Track).filter_by(song=track.song, artist=track.artist).first()

        if db_track and db_track.spotify_uri:
            #print(f"Found cached URI for track: {db_track.spotify_uri}")
            track_uris.append(db_track.spotify_uri)
        else:
            if track.artist not in excluded_artists:
                query = f"{track.song} artist:{track.artist}"
                print(f"Searching Spotify for: {query}")
                results = sp.search(q=query, type='track', limit=1)

                if results['tracks']['items']:
                    spotify_track = results['tracks']['items'][0]
                    spotify_uri = spotify_track['uri']
                    spotify_song = spotify_track['name']
                    spotify_artist = ', '.join(artist['name'] for artist in spotify_track['artists'])
                    spotify_api_url = spotify_track['href']  # API URL for the song
                    spotify_url = spotify_track['external_urls']['spotify']  # Spotify URL for the song

                    # Compare the retrieved song and artist with the search query
                    if spotify_song.lower() != track.song.lower() or spotify_artist.lower() != track.artist.lower():
                        print(f"  Mismatch found:")
                        print(f"    Searched for: {track.song} by {track.artist}")
                        print(f"    Found: {spotify_song} by {spotify_artist}")
                        print(f"    Spotify URL: {spotify_url}")

                    print(f"  Found URI on Spotify: {spotify_uri}")
                    track_uris.append(spotify_uri)

                    if db_track:
                        db_track.spotify_uri = spotify_uri
                        db.session.commit()
                else:
                    if track.artist not in excluded_artists:
                        print(f"  Failed to find track on Spotify: {track.song} by {track.artist}")
                        failed_tracks.append({"song": track.song, "artist": track.artist})
                    else:
                        print(f"  Skipping failure count for track: {track.song} by {track.artist}")

        # Stop if more than 10 non-excluded tracks have failed
        if len(failed_tracks) > 10:
            print("Too many tracks failed. Deleting playlist.")
            sp.current_user_unfollow_playlist(playlist['id'])
            return False, {
                "message": f"Playlist '{playlist_name}' could not be created. Too many tracks were not found.",
                "failed_tracks": failed_tracks,
            }

    # Add found tracks to the playlist
    if track_uris:
        try:
            for i in range(0, len(track_uris), 100):
                #print(f"Adding tracks to playlist: {track_uris[i:i+100]}")
                sp.playlist_add_items(playlist['id'], track_uris[i:i+100])

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
            sp.current_user_unfollow_playlist(playlist['id'])
            return False, {
                "message": f"Error creating playlist: {e}",
                "failed_tracks": failed_tracks,
            }
    else:
        print("No tracks found to add to the playlist. Deleting playlist.")
        sp.current_user_unfollow_playlist(playlist['id'])
        return False, {
            "message": f"Playlist '{playlist_name}' could not be created. No tracks were found.",
            "failed_tracks": failed_tracks,
        }


def fetch_recent_tracks(limit=50, ktunes_playlist_name="kTunes"):
    """Fetch the most recently played tracks from Spotify."""
    sp = get_spotify_client()
    if not sp:
        return None, "Spotify client not authenticated."

    try:
        results = sp.current_user_recently_played(limit=limit)
        recent_tracks = []
        ktunes_playlist_uri = None  # Cache for the ktunes playlist URI
        local_tz = pytz.timezone('America/New_York')  # Replace with your local timezone
        while results:
            for item in results['items']:
                track_name = item['track']['name']
                artist_name = ', '.join(artist['name'] for artist in item['track']['artists'])
                played_at_utc = datetime.strptime(item['played_at'], "%Y-%m-%dT%H:%M:%S.%fZ")
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
                        except spotipy.exceptions.SpotifyException as e:
                            print(f"Error fetching playlist: {e}")
                            playlist_name = "Unknown Playlist"

                recent_tracks.append({
                    'track_name': track_name,
                    'artist': artist_name,
                    'played_at': played_at_local,
                    'playlist': playlist_name,
                    'track_id': track_id
                })

            if len(recent_tracks) >= limit or not results['next']:
                break
            results = sp.next(results)

        return recent_tracks[:limit], None
    except spotipy.exceptions.SpotifyException as e:
        if e.http_status == 404:
            return None, "Resource not found."
        return None, f"Error fetching recent tracks: {str(e)}"


