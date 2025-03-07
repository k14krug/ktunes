import spotipy
from spotipy.oauth2 import SpotifyOAuth
import logging
import json
import os
import argparse
import pytz
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)

# Spotify API credentials
SPOTIPY_CLIENT_ID = 'bf5b82bad95f4d94a19f3b0b22dced56'
SPOTIPY_CLIENT_SECRET = 'eab0a2259cde4d98a6048305345ab19c'
SPOTIPY_REDIRECT_URI = 'http://localhost:5010/callback'

# Initialize Spotify client
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET,
    redirect_uri=SPOTIPY_REDIRECT_URI,
    scope='user-read-playback-state user-read-recently-played playlist-modify-public playlist-modify-private'
))

# Path to the JSON file
JSON_FILE_PATH = 'recently_played.json'

def check_if_listening_to_playlist():
    """
    Check if the user is currently listening to a playlist and return the playlist name.
    """
    try:
        current_playback = sp.current_playback()
        if current_playback and current_playback['context'] and 'playlist' in current_playback['context']['type']:
            playlist_uri = current_playback['context']['uri']
            playlist = sp.playlist(playlist_uri)
            return playlist['name']
        return None
    except Exception as e:
        logging.error(f"Error checking playback state: {e}")
        return None

def get_latest_songs(limit=10):
    """
    Retrieve the latest songs the user has listened to and update the JSON file if limit is 50.
    
    :param limit: Number of songs to return.
    :return: List of song names.
    """
    try:
        # Retrieve recently played songs
        results = sp.current_user_recently_played(limit=min(limit, 50))
        new_songs = []

        if limit == 50:
            # Load existing data from JSON file
            if os.path.exists(JSON_FILE_PATH):
                with open(JSON_FILE_PATH, 'r') as file:
                    existing_data = json.load(file)
                # Sort existing data by date_played in descending order
                existing_data.sort(key=lambda x: x['date_played'], reverse=True)
            else:
                existing_data = []

            initial_count = len(existing_data)

            # Append new songs to the list, ensuring no duplicates
            existing_song_ids = {song['spotify_id'] for song in existing_data}
            for item in results['items']:
                utc_time = datetime.strptime(item['played_at'], '%Y-%m-%dT%H:%M:%S.%fZ')
                local_time = utc_time.replace(tzinfo=pytz.utc).astimezone(pytz.timezone('America/Los_Angeles'))  # Change to your local timezone
                song_details = {
                    'artist': item['track']['artists'][0]['name'],
                    'song': item['track']['name'],
                    'date_played': local_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'spotify_id': item['track']['id']
                }
                if song_details['spotify_id'] not in existing_song_ids:
                    new_songs.append(song_details)

            # Combine new songs with existing data and sort by date_played in descending order
            combined_songs = new_songs + existing_data
            combined_songs.sort(key=lambda x: x['date_played'], reverse=True)

            # Update JSON file with combined songs
            with open(JSON_FILE_PATH, 'w') as file:
                json.dump(combined_songs, file, indent=4)

            added_count = len(new_songs)
            logging.info(f"Initial number of songs in the file: {initial_count}")
            logging.info(f"Number of new songs added: {added_count}")
        else:
            # Append new songs to the list without reading/writing the JSON file
            for item in results['items']:
                utc_time = datetime.strptime(item['played_at'], '%Y-%m-%dT%H:%M:%S.%fZ')
                local_time = utc_time.replace(tzinfo=pytz.utc).astimezone(pytz.timezone('America/Los_Angeles'))  # Change to your local timezone
                song_details = {
                    'artist': item['track']['artists'][0]['name'],
                    'song': item['track']['name'],
                    'date_played': local_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'spotify_id': item['track']['id']
                }
                new_songs.append(song_details)

        return [song['song'] for song in new_songs]
    except Exception as e:
        logging.error(f"Error retrieving latest songs: {e}")
        return []
    
def create_or_replace_playlist(playlist_name, songs):
    """
    Create or replace a playlist with the given name and songs.
    
    :param playlist_name: Name of the playlist.
    :param songs: Dictionary of songs with details.
    """
    try:
        # Check if playlist exists
        playlists = sp.current_user_playlists()
        playlist_id = None
        for playlist in playlists['items']:
            if playlist['name'] == playlist_name:
                playlist_id = playlist['id']
                break
        
        # Create or replace playlist
        if playlist_id:
            sp.user_playlist_replace_tracks(user=sp.current_user()['id'], playlist_id=playlist_id, tracks=songs)
        else:
            sp.user_playlist_create(user=sp.current_user()['id'], name=playlist_name, public=False)
            playlist_id = sp.current_user_playlists()['items'][0]['id']
            sp.user_playlist_add_tracks(user=sp.current_user()['id'], playlist_id=playlist_id, tracks=songs)
    except Exception as e:
        logging.error(f"Error creating or replacing playlist: {e}")

# Example usage
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Get the latest songs from Spotify.')
    parser.add_argument('--limit', type=int, default=10, help='Number of songs to retrieve')
    args = parser.parse_args()

    latest_songs = get_latest_songs(args.limit)
    print(f"Latest songs:Limit{args.limit}, {latest_songs}")
    #print(check_if_listening_to_playlist())
    #print(get_latest_songs(5))
    #create_or_replace_playlist("My New Playlist", ["spotify:track:4iV5W9uYEdYUVa79Axb7Rh"])
