# spotify_integration.py

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import current_app, session, redirect, url_for, request

def get_spotify_client():
    print(f"Getting Spotify client")
    if not session.get('token_info'):
        print("No token info in session")
        return None
    print(f" Token info: {session['token_info']}. Gonna try to create a Spotify client")
    sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=current_app.config['SPOTIPY_CLIENT_ID'],
        client_secret=current_app.config['SPOTIPY_CLIENT_SECRET'],
        redirect_uri=current_app.config['SPOTIPY_REDIRECT_URI'],
        scope='playlist-modify-private'
    ))
    return sp

def spotify_auth():
    print("Inside spotify_inegration. Trying to Authenticate with Spotify")
    sp_oauth = SpotifyOAuth(
        client_id=current_app.config['SPOTIPY_CLIENT_ID'],
        client_secret=current_app.config['SPOTIPY_CLIENT_SECRET'],
        redirect_uri=current_app.config['SPOTIPY_REDIRECT_URI'],
        scope='playlist-modify-private'
    )
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

def spotify_callback():
    print("Inside spotify_integration.spotify_callback")
    sp_oauth = SpotifyOAuth(
        client_id=current_app.config['SPOTIPY_CLIENT_ID'],
        client_secret=current_app.config['SPOTIPY_CLIENT_SECRET'],
        redirect_uri=current_app.config['SPOTIPY_REDIRECT_URI'],
        scope='playlist-modify-private'
    )
    session.clear()
    code = request.args.get('code')  # Use request directly
    token_info = sp_oauth.get_access_token(code)
    session["token_info"] = token_info
    return redirect(url_for('playlists'))

def create_spotify_playlist(playlist_name, tracks):
    sp = get_spotify_client()
    if not sp:
        return False, "Spotify authentication required"
    
    user_id = sp.me()['id']
    playlist = sp.user_playlist_create(user_id, playlist_name, public=False)
    
    track_uris = []
    for track in tracks:
        results = sp.search(q=f"track:{track.song} artist:{track.artist}", type='track', limit=1)
        if results['tracks']['items']:
            track_uris.append(results['tracks']['items'][0]['uri'])
    
    if track_uris:
        sp.playlist_add_items(playlist['id'], track_uris)
        return True, f"Playlist '{playlist_name}' created on Spotify with {len(track_uris)} tracks"
    else:
        return False, "No matching tracks found on Spotify"