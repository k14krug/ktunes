from flask import redirect, url_for, jsonify, flash, render_template, request
from flask_login import login_required
from extensions import db
from . import spotify_bp
from services.task_service import run_export_default_playlist
from services.spotify_service import (
    spotify_auth, spotify_callback, get_spotify_client, 
    export_playlist_to_spotify, fetch_and_update_recent_tracks
)
from models import Track, SpotifyURI
from datetime import datetime

#@spotify_bp.route('/auth')
@spotify_bp.route('/spotify_auth')
@login_required
def route_spotify_auth():
    print("  Redirecting to Spotify auth")
    return spotify_auth()

@spotify_bp.route('/callback')
def route_callback():
    print("  Redirecting to Spotify callback")
    return spotify_callback()

@spotify_bp.route('/export_to_spotify/<playlist_name>', methods=['POST'])
@login_required
def export_to_spotify(playlist_name):
    print(f"Exporting playlist '{playlist_name}' to Spotify")
    
    # Instead of letting export_playlist_to_spotify handle authentication,
    # first ensure we have a valid client (same as automatic process)
    sp = get_spotify_client(force_refresh=True)  # Add force_refresh parameter to get_spotify_client
    
    if not sp:
        # If get_spotify_client couldn't get a valid client even after trying to refresh,
        # we need user authentication
        auth_url = spotify_auth(return_url=True)  # Modify spotify_auth to optionally return URL
        return jsonify({"success": False, "redirect": auth_url}), 401
    
    # Now call export with the verified client
    success, result = export_playlist_to_spotify(playlist_name, db, sp)  # Pass sp as an argument

    if not success:
        if "redirect" in result:
            return jsonify({"success": False, "redirect": result["redirect"]}), 401
        return jsonify({"success": False, "message": result["message"], "failed_tracks": result.get("failed_tracks", [])}), 500

    return jsonify({"success": True, "message": result["message"], "failed_tracks": result.get("failed_tracks", [])})

@spotify_bp.route('/spotify_playlists')
@login_required
def spotify_playlists():
    sp = get_spotify_client()
    if not sp:
        return redirect(url_for('route_spotify_auth'))

    playlists = sp.current_user_playlists(limit=50)
    result = []
    for playlist in playlists['items']:
        result.append({
            "name": playlist['name'],
            "owner": playlist['owner']['display_name'],
            "id": playlist['id']
        })
    return jsonify({"playlists": result})
    
@spotify_bp.route('/spotify_playlist/<playlist_id>')
@login_required
def spotify_playlist(playlist_id):
    sp = get_spotify_client()
    if not sp:
        return redirect(url_for('route_spotify_auth'))
    
    try:
        playlist = sp.playlist(playlist_id)
        return jsonify(playlist)  # Return the entire JSON of the specified playlist
    except Exception as e:
        flash(f"Error retrieving playlist: {str(e)}", 'error')
        return redirect(url_for('spotify.spotify_playlists'))

@spotify_bp.route('/songs_to_add')
@login_required
def songs_to_add():
    sp = get_spotify_client()
    if not sp:
        return redirect(url_for('route_spotify_auth'))

    # Fetch the "Songs to Add" playlist by name
    playlists = sp.current_user_playlists(limit=50)
    playlist_id = None
    playlist_names = []
    for playlist in playlists['items']:
        playlist_names.append(playlist['name'])
        if playlist['name'].lower() == 'sounds to add':
            playlist_id = playlist['id']
            break

    if not playlist_id:
        flash(f'"Songs to Add" playlist not found. Available playlists: {", ".join(playlist_names)}', 'error')
        return redirect(url_for('main.index'))

    # Fetch all tracks from the playlist
    tracks = []
    results = sp.playlist_tracks(playlist_id)
    tracks.extend(results['items'])
    while results['next']:
        results = sp.next(results)
        tracks.extend(results['items'])

    # Sort tracks by added_at and select the 50 most recently added
    tracks = sorted(tracks, key=lambda x: x['added_at'], reverse=True)[:50]

    # Check if tracks are already in the Tracks table by joining with SpotifyURI
    track_ids = [track['track']['id'] for track in tracks]
    spotify_uris = [f'spotify:track:{track_id}' for track_id in track_ids]
    
    # Query tracks through the SpotifyURI relationship, eager loading the Track
    existing_uri_records = SpotifyURI.query.filter(SpotifyURI.uri.in_(spotify_uris)).options(db.joinedload(SpotifyURI.track)).all()
    
    # Create a set of track IDs that exist AND are NOT 'Unmatched'
    existing_and_matched_track_ids = {
        uri.uri.split(':')[2] for uri in existing_uri_records 
        if uri.track and uri.track.category != 'Unmatched'
    }

    # Prepare data for rendering
    track_data = []
    for item in tracks:
        track = item['track']
        track_id = track['id']
        
        # Check if this track exists and is NOT 'Unmatched'
        exists = track_id in existing_and_matched_track_ids
        
        # Find the Track record if it exists
        existing_uri = next((uri for uri in existing_uri_records 
                             if uri.uri == f'spotify:track:{track_id}'), None)
        existing_track = existing_uri.track if existing_uri else None

        track_data.append({
            'id': track['id'],
            'name': track['name'],
            'artist': ', '.join(artist['name'] for artist in track['artists']),
            'album': track['album']['name'],
            'added_at': item['added_at'],
            'date_added': existing_track.date_added if existing_track else None,
            'exists': exists # Use the new 'exists' logic here
        })

    # Get sort parameters
    sort_column = request.args.get('sort', 'added_at')
    sort_direction = request.args.get('direction', 'desc')

    # Sort the track data
    reverse = (sort_direction == 'desc')
    track_data.sort(key=lambda x: x[sort_column], reverse=reverse)

    return render_template('songs_to_add.html', tracks=track_data, sort_column=sort_column, sort_direction=sort_direction)

@spotify_bp.route('/add_songs_to_tracks', methods=['POST'])
@login_required
def add_songs_to_tracks():
    track_ids = request.form.getlist('track_ids')
    sp = get_spotify_client()
    if not sp:
        return redirect(url_for('route_spotify_auth'))

    # Fetch track details from Spotify
    tracks = sp.tracks(track_ids)['tracks']
    current_date = datetime.now()
    category = "Latest"

    for track in tracks:
        new_track = Track(
            song=track['name'],
            artist=', '.join(artist['name'] for artist in track['artists']),
            artist_common_name=', '.join(artist['name'] for artist in track['artists']),
            #spotify_uri=track['uri'],
            album=track['album']['name'],  # Set album
            category=category,
            play_cnt=0,
            date_added=current_date
        )
        db.session.add(new_track)
        db.session.flush()  # To get the new track ID
        
        # Create the SpotifyURI record with the full URI format
        spotify_uri = f"spotify:track:{track['id']}"
        new_uri = SpotifyURI(
            track_id=new_track.id,
            uri=spotify_uri,
            status='matched'
        )
        db.session.add(new_uri)
                
    db.session.commit()

    flash('Selected songs have been added to the Tracks table.', 'success')
    return redirect(url_for('spotify.songs_to_add'))

@login_required
def recent_spotify_tracks():
    print("Fetching recent Spotify tracks")
    tracks, error = fetch_and_update_recent_tracks(limit=50)
    
    if error:
        flash(error, 'error')
        return redirect(url_for('main.index'))

    return render_template('recent_spotify_tracks.html', tracks=tracks)


@spotify_bp.route('/export_default_playlist_to_spotify')
@login_required
def export_default_playlist_to_spotify():
    """
    Route to manually trigger the process of exporting the default playlist to Spotify.
    """
    print("Exporting default playlist to Spotify")
    success, message = run_export_default_playlist()

    if success:
        flash(f"Playlist exported successfully: {message}", "success")
    else:
        flash(f"Failed to export playlist: {message}", "error")

    return redirect(url_for('main.playlists'))
