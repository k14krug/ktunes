import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, request, redirect, jsonify

# Set your Spotify API credentials
CLIENT_ID = 'bf5b82bad95f4d94a19f3b0b22dced56'
CLIENT_SECRET = 'eab0a2259cde4d98a6048305345ab19c'
REDIRECT_URI = 'http://localhost:5010/callback'

# Scope to manage playlists
SCOPE = 'playlist-modify-private playlist-modify-public playlist-read-private'

# Initialize Flask app
app = Flask(__name__)

# Global variables to store Spotify client and authorization code
sp_client = None
auth_manager = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPE
)

@app.route('/')
def login():
    """Redirect user to Spotify's login page."""
    auth_url = auth_manager.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    """Handle the Spotify callback and fetch the access token."""
    global sp_client
    code = request.args.get('code')
    token_info = auth_manager.get_access_token(code)
    sp_client = spotipy.Spotify(auth=token_info['access_token'])
    return jsonify({"message": "Authorization successful! You can now use the app."})

@app.route('/create_playlist', methods=['POST'])
def create_playlist():
    """Create a new Spotify playlist."""
    if not sp_client:
        return jsonify({"error": "Spotify client not authenticated. Please login at / first."}), 401

    playlist_name = request.json.get('name', 'New Playlist')
    user_id = sp_client.me()['id']
    new_playlist = sp_client.user_playlist_create(user_id, playlist_name, public=True)
    return jsonify({"message": f"Playlist '{playlist_name}' created successfully.", "id": new_playlist['id']})

@app.route('/list_all_playlists', methods=['GET'])
def list_all_playlists():
    """List all playlists visible to the authenticated user."""
    if not sp_client:
        return jsonify({"error": "Spotify client not authenticated. Please login at / first."}), 401

    playlists = sp_client.current_user_playlists(limit=50)
    result = []
    for playlist in playlists['items']:
        result.append({
            "name": playlist['name'],
            "owner": playlist['owner']['display_name'],
            "id": playlist['id']
        })
    return jsonify({"playlists": result})

@app.route('/list_owned_playlists', methods=['GET'])
def list_owned_playlists():
    """List all playlists owned by the authenticated user."""
    if not sp_client:
        return jsonify({"error": "Spotify client not authenticated. Please login at / first."}), 401

    playlists = sp_client.current_user_playlists(limit=50)
    user_id = sp_client.me()['id']
    result = []
    for playlist in playlists['items']:
        if playlist['owner']['id'] == user_id:
            result.append({
                "name": playlist['name'],
                "id": playlist['id']
            })
    return jsonify({"owned_playlists": result})

if __name__ == "__main__":
    app.run(port=5010)
