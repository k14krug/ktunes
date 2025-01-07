from flask import Flask, redirect, request, session, url_for
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import time

app = Flask(__name__)
app.secret_key = 'your_secret_key'

CLIENT_ID = 'bf5b82bad95f4d94a19f3b0b22dced56'
CLIENT_SECRET = 'eab0a2259cde4d98a6048305345ab19c'
REDIRECT_URI = 'http://localhost:5010/callback'
SCOPE = 'user-read-recently-played user-read-playback-state'


def create_spotify_oauth():
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE
    )


@app.route('/')
def index():
    sp_oauth = create_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return f'<h2>Welcome to Spotify Auth</h2><a href="{auth_url}">Login to Spotify</a>'


@app.route('/callback')
def callback():
    sp_oauth = create_spotify_oauth()
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code, as_dict=True)
    session['token_info'] = token_info
    return redirect(url_for('profile'))


@app.route('/profile')
def profile():
    token_info = session.get('token_info')

    if not token_info:
        return redirect('/')

    if token_info['expires_at'] - 60 < time.time():
        sp_oauth = create_spotify_oauth()
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        session['token_info'] = token_info

    sp = spotipy.Spotify(auth=token_info['access_token'])
    recently_played = sp.current_user_recently_played(limit=50)

    tracks_html = '<h2>Recently Played Tracks</h2><ul>'
    for index, item in enumerate(recently_played['items'], start=1):
        track = item['track']['name']
        artist = ', '.join(artist['name'] for artist in item['track']['artists'])
        played_at = item['played_at']
        context = item.get('context', {})

        playlist_info = "Unknown Source"
        if context and context.get('type') == 'playlist':
            try:
                playlist_uri = context.get('uri')
                if playlist_uri:
                    playlist_name = sp.playlist(playlist_uri)['name']
                    playlist_info = f'Playlist: {playlist_name} (<a href="https://open.spotify.com/playlist/{playlist_uri.split(":")[-1]}" target="_blank">Open</a>)'
            except spotipy.exceptions.SpotifyException as e:
                print(f"Error fetching playlist: {e}")
                playlist_info = "Playlist unavailable"

        tracks_html += f'<li>{index}. Track: {track} by {artist}, Played At: {played_at}<br>{playlist_info}</li>'
    tracks_html += '</ul>'

    return tracks_html


@app.route('/is_playlist_playing')
def is_playlist_playing():
    token_info = session.get('token_info')

    if not token_info:
        return redirect('/')

    if token_info['expires_at'] - 60 < time.time():
        sp_oauth = create_spotify_oauth()
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        session['token_info'] = token_info

    sp = spotipy.Spotify(auth=token_info['access_token'])

    try:
        playback = sp.current_playback()
        if playback and playback['context']:
            context = playback['context']
            if context['type'] == 'playlist':
                playlist_uri = context['uri']
                playlist_name = sp.playlist(playlist_uri)['name']
                return f'<h2>Currently Playing</h2>Playlist: {playlist_name} (<a href="https://open.spotify.com/playlist/{playlist_uri.split(":")[-1]}" target="_blank">Open</a>)'
        return '<h2>No playlist is currently being played.</h2>'
    except spotipy.exceptions.SpotifyException as e:
        return f'<h2>Error</h2><p>{str(e)}</p>'


if __name__ == '__main__':
    app.run(debug=True, port=5010)
