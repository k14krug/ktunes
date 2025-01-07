import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort,session
from flask_login import login_user, login_required, logout_user, current_user
from flask_paginate import Pagination, get_page_parameter
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
import json
from itunes_xml_parser import ITunesXMLParser
from itunes_integrator_wsl import iTunesIntegrator
from playlist_generator import PlaylistGenerator
from extensions import db, login_manager
from flask_session import Session  
from datetime import timedelta, datetime  
from sqlalchemy import func, distinct, desc
from sqlalchemy.orm import aliased
from spotify_integration import spotify_auth, spotify_callback, create_spotify_playlist, get_spotify_client
from spotipy.oauth2 import SpotifyOAuth
import spotipy
import socket
from spotify_integration import fetch_recent_tracks  
#from spotify_client import SpotifyClient 

app = Flask(__name__)
app_root = os.path.abspath(os.path.dirname(__file__))
app.instance_path = os.path.join(app_root, 'instance')
os.makedirs(app.instance_path, exist_ok=True)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(app.instance_path, "kTunes.sqlite")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configure server-side sessions to use filesystem. Makes testing easier because don't need to relogin every time you save code.
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.path.join(app.instance_path, 'flask_session')
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=31)  # Set session lifetime to 31 days
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
Session(app)

# Spotify configuration
app.config['SPOTIPY_CLIENT_ID'] = 'bf5b82bad95f4d94a19f3b0b22dced56'
app.config['SPOTIPY_CLIENT_SECRET'] = 'eab0a2259cde4d98a6048305345ab19c'
app.config['SPOTIPY_REDIRECT_URI'] = 'http://localhost:5010/callback'

db.init_app(app)
migrate = Migrate(app, db)
login_manager.init_app(app)
login_manager.login_view = 'login'

# Import models after initializing db to avoid circular imports
from models import User, Track, Playlist

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def load_config(force_defaults=False):
    default_config = {
        'itunes_dir': '/mnt/c/Users/nwkru/Music/iTunes',
        'itunes_lib': 'iTunes Library.xml',
        'playlist_defaults': {
            'playlist_length': 40.0,
            'minimum_recent_add_playcount': 15,
            'categories': [
                {'name': 'RecentAdd', 'percentage': 25.0, 'artist_repeat': 21},
                {'name': 'Latest', 'percentage': 25.0, 'artist_repeat': 21},
                {'name': 'In Rot', 'percentage': 30.0, 'artist_repeat': 40},
                {'name': 'Other', 'percentage': 10.0, 'artist_repeat': 200},
                {'name': 'Old', 'percentage': 7.0, 'artist_repeat': 200},
                {'name': 'Album', 'percentage': 3.0, 'artist_repeat': 200}
            ]
        }
    }

    config_path = 'config.json'

    if force_defaults:
        if os.path.exists(config_path):
            print("Loading default config without rewriting the existing config file")
            return default_config
        else:
            print("Creating default config file")
            with open(config_path, 'w') as f:
                json.dump(default_config, f, indent=4)
            return default_config
    else:
        if os.path.exists(config_path):
            print("Loading config from file")
            with open(config_path, 'r') as f:
                return json.load(f)
        else:
            print("Creating default config file")
            with open(config_path, 'w') as f:
                json.dump(default_config, f, indent=4)
            return default_config

config = load_config()

def update_database_from_xml_logic():
    print(f"Updating database from iTunes XML located at {config['itunes_dir']}, file name '{config['itunes_lib']}'")
    xml_path = os.path.join(config['itunes_dir'], config['itunes_lib'])
    inserts, updates = 0, 0
    if (os.path.exists(xml_path)):
        parser = ITunesXMLParser(xml_path)
        try:
            #print(f"Updating database from iTunes XML located at {xml_path}")
            with app.app_context():
                updates, inserts = parser.update_database()
            #app.logger.info("Database updated successfully from iTunes XML")
        except Exception as e:
            app.logger.error(f"Error updating database from iTunes XML: {str(e)}")
    else:
        app.logger.warning(f"iTunes XML file not found at {xml_path}")
    
    return updates, inserts

@app.route('/update_database_from_xml')
@login_required
def update_database_from_xml():
    updates, inserts = update_database_from_xml_logic()
    flash(f"Database updated: {updates} rows updated, {inserts} rows inserted", "success")
    return redirect(url_for('settings'))

@app.route('/')
@login_required
def index():
    # Reload config to ensure we have the latest values
    global config
    config = load_config()
    if request.method == 'GET':
        # Initialize PlaylistGenerator with default values to get initial track counts
        default_categories = config['playlist_defaults']['categories']
        generator = PlaylistGenerator(
            playlist_name="",  # Empty placeholder
            playlist_length=config['playlist_defaults']['playlist_length'],
            minimum_recent_add_playcount=config['playlist_defaults']['minimum_recent_add_playcount'],
            categories=default_categories,
            username=current_user.username
        )

        # Fetch the most recent playlist and last played track position
        recent_playlist, stop_point = generator.preview_last_playlist()
        # Store values in session for later use when/if we generate the playlist
        session['recent_playlist'] = recent_playlist.playlist_name if recent_playlist else None
        session['stop_point'] = stop_point
        
        track_counts = generator._get_track_counts()
        
    return render_template(
        'index.html',
        config=config['playlist_defaults'],
        track_counts=track_counts,
        recent_playlist=recent_playlist,  # Pass the recent playlist to the template
        stop_point=stop_point  # Pass the stop point to the template
    )

    
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
        else:
            new_user = User(username=username, password=generate_password_hash(password))
            db.session.add(new_user)
            db.session.commit()
            flash('User registered successfully')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/generate_playlist', methods=['POST'])
@login_required
def generate_playlist():
    app.logger.info("In generate_playlist route")
    playlist_name = request.form['playlist_name']
    playlist_length = float(request.form['playlist_length'])
    minimum_recent_add_playcount = int(request.form['minimum_recent_add_playcount'])
    replace_existing = request.form.get('replace_existing', 'false') == 'true'
    use_recent_playlist = request.form.get('use_recent_playlist') == 'on'

    # Retrieve recent playlist and stop point from session
    recent_playlist_name = session.get('recent_playlist')
    stop_point = session.get('stop_point')
    
    # Check if playlist already exists
    existing_playlist = Playlist.query.filter_by(playlist_name=playlist_name, username=current_user.username).first()
    
    if existing_playlist and not replace_existing:
        return jsonify({
            'exists': True,
            'message': f"A playlist named '{playlist_name}' already exists. Do you want to replace it?"
        }), 409  # 409 Conflict

    if existing_playlist:
        # Delete existing playlist
        Playlist.query.filter_by(playlist_name=playlist_name, username=current_user.username).delete()
        db.session.commit()
    
    # Update config with new values
    config['playlist_defaults']['playlist_length'] = playlist_length
    config['playlist_defaults']['minimum_recent_add_playcount'] = minimum_recent_add_playcount

    categories = []
    for i in range(len(config['playlist_defaults']['categories'])):
        category = {
            'name': request.form[f'category_name_{i}'],
            'percentage': float(request.form[f'category_percentage_{i}']),
            'artist_repeat': int(request.form[f'category_artist_repeat_{i}'])
        }
        categories.append(category)
    
    config['playlist_defaults']['categories'] = categories
    
    # Save updated config to file
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)

    # Generate playlist logic...
    app.logger.info("Instantiating PlaylistGenerator, then calling generate()")
    generator = PlaylistGenerator(playlist_name, playlist_length, minimum_recent_add_playcount, categories, current_user.username)

    # Initialize artist_last_played based on user choice
    if use_recent_playlist and recent_playlist_name:
        # Fetch the recent playlist
        recent_playlist = Playlist.query.filter_by(playlist_name=recent_playlist_name).first()
        generator._initialize_artist_last_played(recent_playlist, stop_point)
    else:
        generator._initialize_artist_last_played(None, None)
    
    try:
        playlist, stats = generator.generate()
        return jsonify({
            'success': True,
            'message': f"Playlist '{playlist_name}' generated successfully. Stats: {stats}",
            'redirect': url_for('view_playlist', playlist_name=playlist_name)
        })
    except Exception as e:
        db.session.rollback()  # Rollback the session in case of error
        app.logger.error(f"Error generating playlist: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Error generating playlist: {str(e)}'
        }), 500

    
@app.route('/check_playlist_name')
@login_required
def check_playlist_name():
    name = request.args.get('name', '')
    playlist_exists = Playlist.query.filter_by(playlist_name=name, username=current_user.username).first() is not None
    return jsonify({'exists': playlist_exists})    
    

@app.route('/tracks')
@login_required
def tracks():
    sp = get_spotify_client()
    if not sp:
        return redirect(url_for('route_spotify_auth'))
    
    page = request.args.get(get_page_parameter(), type=int, default=1)
    per_page = 50  # Number of tracks per page

    # Get filter and sort parameters
    song_filter = request.args.get('song', '')
    artist_filter = request.args.get('artist', '')
    category_filter = request.args.get('category', '')
    sort_column = request.args.get('sort', 'artist')
    sort_direction = request.args.get('direction', 'asc')

    # Build the query
    query = Track.query

    # Apply filters
    if song_filter:
        query = query.filter(Track.song.ilike(f'%{song_filter}%'))
    if artist_filter:
        query = query.filter(Track.artist.ilike(f'%{artist_filter}%'))
    if category_filter:
        query = query.filter(Track.category.ilike(f'%{category_filter}%'))

    # Apply sorting
    if sort_direction == 'desc':
        query = query.order_by(desc(getattr(Track, sort_column)))
    else:
        query = query.order_by(getattr(Track, sort_column))

    # Get total number of tracks (for pagination)
    total = query.count()

    # Apply pagination
    tracks = query.paginate(page=page, per_page=per_page, error_out=False)

    # Create pagination object
    pagination = Pagination(page=page, total=total, per_page=per_page, css_framework='bootstrap4')

    return render_template('tracks.html', 
                           tracks=tracks.items, 
                           pagination=pagination, 
                           sort_column=sort_column, 
                           sort_direction=sort_direction)  




@app.route('/manage_artists', methods=['GET', 'POST'])
@login_required
def manage_artists():
    if request.method == 'POST':
        artist = request.form.get('artist')
        common_name = request.form.get('common_name')
        
        if artist and common_name:
            # Update all tracks for the given artist with the new common name
            updated_rows = Track.query.filter_by(artist=artist).update({'artist_common_name': common_name})
            db.session.commit()
            if updated_rows > 0:
                flash(f'Updated {updated_rows} tracks for artist "{artist}" with common name: {common_name}', 'success')
            else:
                flash(f'No tracks found for artist "{artist}". No changes made.', 'warning')
        else:
            flash('Both artist and common name are required', 'error')
    
    # Get all unique artists, their current common names, and track counts
    artist_mappings = db.session.query(
        Track.artist,
        Track.artist_common_name,
        func.count(Track.id).label('artist_count'),
        func.count(func.distinct(Track.artist_common_name)).label('common_name_count')
    ).group_by(Track.artist, Track.artist_common_name)\
     .order_by(Track.artist_common_name, Track.artist).all()
    
    # Filter out entries where artist_common_name is the same as artist
    artist_mappings = [
        mapping for mapping in artist_mappings
        if mapping.artist_common_name != mapping.artist
    ]

    # Calculate total tracks for each common name
    common_name_totals = {}
    for mapping in db.session.query(
        Track.artist_common_name,
        func.count(Track.id).label('total_count')
    ).group_by(Track.artist_common_name).all():
        if mapping.artist_common_name:
            common_name_totals[mapping.artist_common_name] = mapping.total_count

    return render_template('manage_artists.html', artist_mappings=artist_mappings, common_name_totals=common_name_totals)


@app.route('/autocomplete/artists')
def autocomplete_artists():
    search = request.args.get('term', '')
    artists = db.session.query(distinct(Track.artist)).filter(
        Track.artist.ilike(f'%{search}%')
    ).order_by(Track.artist).limit(10).all()
    return jsonify([artist[0] for artist in artists])

@app.route('/autocomplete/common_names')
def autocomplete_common_names():
    search = request.args.get('term', '')
    common_names = db.session.query(distinct(Track.artist_common_name)).filter(
        Track.artist_common_name.ilike(f'%{search}%'),
        Track.artist_common_name != None,
        Track.artist_common_name != ''
    ).order_by(Track.artist_common_name).limit(10).all()
    return jsonify([name[0] for name in common_names if name[0]])

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    global config
    if request.method == 'POST':
        # Update settings
        new_itunes_dir = request.form.get('itunes_dir', '').strip()
        new_itunes_lib = request.form.get('itunes_lib', '').strip()
        print(f"A Updating settings with new iTunes directory: {new_itunes_dir}, library file: {new_itunes_lib}")
        
        # Validate inputs
        if not new_itunes_dir or not new_itunes_lib:
            flash('Both iTunes directory and library file must be provided', 'error')
        elif not os.path.isdir(new_itunes_dir):
            flash(f'Directory not found: {new_itunes_dir}', 'error')
        elif not os.path.isfile(os.path.join(new_itunes_dir, new_itunes_lib)):
            print(f'Library file "{new_itunes_lib}" not found in "{new_itunes_dir}"', 'error')
            flash(f'Library file "{new_itunes_lib}" not found in "{new_itunes_dir}"', 'error')
        else:
            # Update config
            print(f"B Updating config with new iTunes directory: {new_itunes_dir}, library file: {new_itunes_lib}")
            config['itunes_dir'] = new_itunes_dir
            config['itunes_lib'] = new_itunes_lib
            
            # Save updated config to file
            try:
                with open('config.json', 'w') as f:
                    json.dump(config, f, indent=4)
                flash('Settings updated successfully', 'success')
            except IOError:
                flash('Failed to save settings', 'error')
        
        return redirect(url_for('settings'))
    
    # For GET requests, just load the current settings
    return render_template('settings.html', 
                           itunes_dir=config['itunes_dir'], 
                           itunes_lib=config['itunes_lib'])

@app.route('/playlist/<playlist_name>')
@login_required
def view_playlist(playlist_name):
    sp = get_spotify_client()
    if not sp:
        return redirect(url_for('route_spotify_auth'))
    
    # Get filter parameters
    song_filter = request.args.get('song', '')
    artist_filter = request.args.get('artist', '')
    category_filter = request.args.get('category', '')

    # Query to join Playlist and Track tables on artist and song
    query = db.session.query(
        Playlist,
        Track.last_play_dt,
        Track.spotify_uri
    ).join(
        Track, 
        (Playlist.artist == Track.artist) & (Playlist.song == Track.song)
    ).filter(
        Playlist.playlist_name == playlist_name,
        Playlist.username == current_user.username
    )

    # Apply user filters
    if song_filter:
        query = query.filter(Playlist.song.ilike(f'%{song_filter}%'))
    if artist_filter:
        query = query.filter(Playlist.artist.ilike(f'%{artist_filter}%'))
    if category_filter:
        query = query.filter(Playlist.category.ilike(f'%{category_filter}%'))

    # Execute the query and order by track position
    playlist_tracks = query.order_by(Playlist.track_position).all()
    
    if not playlist_tracks:
        abort(404)  # Playlist not found
    
    # Get playlist information from the first track
    playlist_info = {
        'playlist_name': playlist_tracks[0].Playlist.playlist_name,
        'playlist_date': playlist_tracks[0].Playlist.playlist_date,
        'track_count': len(playlist_tracks)
    }
    
    # Calculate category percentages
    category_counts = {}
    total_tracks = len(playlist_tracks)
    for track in playlist_tracks:
        category_counts[track.Playlist.category] = category_counts.get(track.Playlist.category, 0) + 1
    
    # Get the ordered list of categories from the configuration
    ordered_categories = [cat['name'] for cat in config['playlist_defaults']['categories']]
    
    # Create an ordered dictionary of category percentages
    category_percentages = []
    category_repeats = {}
    for category in ordered_categories:
        if category in category_counts:
            percentage = (category_counts[category] / total_tracks) * 100
            category_percentages.append((category, percentage))
            
            # Calculate the maximum number of times any song repeats in the category
            category_tracks = [track for track in playlist_tracks if track.Playlist.category == category]
            song_repeat_counts = {}
            for track in category_tracks:
                song_key = (track.Playlist.artist, track.Playlist.song)
                song_repeat_counts[song_key] = song_repeat_counts.get(song_key, 0) + 1
            max_repeats = max(song_repeat_counts.values(), default=0)
            category_repeats[category] = max_repeats
    
    return render_template('playlist.html', 
                           playlist=playlist_info, 
                           tracks=playlist_tracks, 
                           category_percentages=category_percentages,
                           category_repeats=category_repeats)  # Pass category repeats to the template

@app.route('/playlists')
@login_required
def playlists():
    # Get unique playlists for the current user
    unique_playlists = db.session.query(
        Playlist.id,
        Playlist.playlist_name,
        func.max(Playlist.playlist_date).label('playlist_date'),
        func.count(Playlist.id).label('track_count')
    ).filter_by(username=current_user.username)\
     .group_by(Playlist.playlist_name)\
     .order_by(func.max(Playlist.playlist_date).desc())\
     .all()
    print(f"Displaying playlists template")
    return render_template('playlists.html', playlists=unique_playlists)

@app.route('/delete_playlist/<playlist_name>', methods=['POST'])
@login_required
def delete_playlist(playlist_name):
    try:
        Playlist.query.filter_by(username=current_user.username, playlist_name=playlist_name).delete()
        db.session.commit()
        return jsonify({"success": True, "message": f'Playlist "{playlist_name}" has been deleted.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/upload_to_itunes/<playlist_name>', methods=['POST'])
@login_required
def upload_to_itunes(playlist_name):
    print(f"Uploading playlist {playlist_name} to iTunes")
    # Fetch the playlist tracks
    playlist_tracks = Playlist.query.filter_by(
        username=current_user.username, 
        playlist_name=playlist_name
    ).order_by(Playlist.track_position).all()
    
    # Prepare the tracks for iTunes
    itunes_tracks = [
        {'artist': track.artist, 'song': track.song}
        for track in playlist_tracks
    ]
    
    # Use the iTunesIntegrator to upload the playlist
    print(f"Uploading playlist {playlist_name} to iTunes")
    itunes_integrator = iTunesIntegrator(playlist_name, config)
    print(f"itunes_integrator created")
    success, result_message = itunes_integrator.insert_playlist_to_itunes()
    if success:
        return jsonify({"success": True, "message": result_message})
    else:
        return jsonify({"success": False, "message": result_message}), 500

@app.route('/spotify_auth')
@login_required
def route_spotify_auth():
    print("  Redirecting to Spotify auth")
    return spotify_auth()

@app.route('/callback')
def route_callback():
    print("  Redirecting to Spotify callback")
    return spotify_callback()

@app.route('/export_to_spotify/<playlist_name>', methods=['POST'])
@login_required
def export_to_spotify(playlist_name):
    print(f"Exporting playlist '{playlist_name}' to Spotify")
    sp = get_spotify_client()
    if not sp:
        return jsonify({"success": False, "redirect": spotify_auth()}), 401

    playlist_tracks = Playlist.query.filter_by(
        username=current_user.username,
        playlist_name=playlist_name
    ).order_by(Playlist.track_position).all()

    success, result = create_spotify_playlist(playlist_name, playlist_tracks, db)
    failed_tracks = result.get("failed_tracks", [])
    if failed_tracks:
        print(f"Failed tracks: {failed_tracks}")
    if success:
        return jsonify({"success": True, "message": result["message"], "failed_tracks": failed_tracks})
    else:
        return jsonify({"success": False, "message": result["message"], "failed_tracks": failed_tracks}), 500


@app.route('/spotify_playlists')
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
    
@app.route('/spotify_playlist/<playlist_id>')
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
        return redirect(url_for('spotify_playlists'))

@app.route('/recent_spotify_tracks')
@login_required
def recent_spotify_tracks():
    print("Fetching recent Spotify tracks")
    try:
        tracks, error = fetch_recent_tracks(limit=50)
        if error:
            flash(error, 'error')
            return redirect(url_for('index'))
        
        # Define the date-time format used in the tracks.played_at value returned from fetch_recent_tracks
        datetime_format = '%Y-%m-%d %H:%M:%S'
        
        # Check if each song is in the tracks table and get the last play date
        for track in tracks:
            # Filter the Track table by matching the third piece of the spotify_uri
            db_track = Track.query.filter(Track.spotify_uri.like(f"%:{track['track_id']}")).first()

            if db_track:
                print(f"Track found in database: {track['track_name']} by {track['artist']}, last played: {db_track.last_play_dt}")
                
                # Parse the played_at value
                played_at = datetime.strptime(track['played_at'], datetime_format)
                
                # Compare and update last_play_dt if played_at is greater or if last_play_dt is None
                if db_track.last_play_dt is None or played_at > db_track.last_play_dt:
                    db_track.last_play_dt = played_at
                    db_track.play_cnt = (db_track.play_cnt or 0) + 1  # Increment play_cnt by 1
                    db.session.commit()
                    print(f"Updated last_play_dt for {track['track_name']} by {track['artist']} to {played_at}")
                track['last_play_dt'] = db_track.last_play_dt
            else:
                print(f"Track not found in database: {track['track_name']} by {track['artist']}")
                track['last_play_dt'] = None

        return render_template('recent_spotify_tracks.html', tracks=tracks)
    except spotipy.exceptions.SpotifyException as e:
        flash(f"Error fetching recent tracks: {str(e)}", 'error')
        return redirect(url_for('index'))



def generate_default_playlist(playlist_name):
    try:
        # Use hard-coded default_config
        config = load_config(force_defaults=True)
        playlist_length = config['playlist_defaults']['playlist_length']
        minimum_recent_add_playcount = config['playlist_defaults']['minimum_recent_add_playcount']
        categories = config['playlist_defaults']['categories']
        username = current_user.username

        # Check if playlist already exists
        existing_playlist = Playlist.query.filter_by(playlist_name=playlist_name, username=username).first()
        
        if existing_playlist:
            # Delete existing playlist
            Playlist.query.filter_by(playlist_name=playlist_name, username=username).delete()
            db.session.commit()
        
        # Initialize PlaylistGenerator
        generator = PlaylistGenerator(
            playlist_name=playlist_name,
            playlist_length=playlist_length,
            minimum_recent_add_playcount=minimum_recent_add_playcount,
            categories=categories,
            username=username
        )

        # Now that we've initialized the PlaylistGenerator, we need to make sure we get back the latest config
        config = load_config

        # Initialize artist_last_played
        generator._initialize_artist_last_played(None, None)

        # Generate the playlist
        playlist, stats = generator.generate()
        print(f"Playlist '{playlist_name}' generated successfully. Stats: {stats}")

        return True, f"Playlist '{playlist_name}' generated successfully."
    
    except Exception as e:
        print(f"Error: {str(e)}")
        return False, f"Error: {str(e)}"

@app.route('/export_default_playlist_to_spotify')
@login_required
def export_default_playlist_to_spotify():
    print("Exporting default playlist to Spotify")
    playlist_name = "kTunes Radio " + datetime.now().strftime("%Y-%m-%d")
    
    success, message = generate_default_playlist(playlist_name)
    
    if success:
        sp = get_spotify_client()
        if not sp:
            flash("Spotify client not authenticated.", 'error')
            return redirect(url_for('index'))

        playlist_tracks = Playlist.query.filter_by(
            username=current_user.username,
            playlist_name=playlist_name
        ).order_by(Playlist.track_position).all()

        success, result = create_spotify_playlist(playlist_name, playlist_tracks, db)
        failed_tracks = result.get("failed_tracks", [])
        if failed_tracks:
            print(f"Failed tracks: {failed_tracks}")
        if success:
            flash(result["message"], 'success')
        else:
            flash(result["message"], 'error')
    else:
        flash(message, 'error')
    
    return redirect(url_for('playlists'))

def find_open_port(start_port=5010, end_port=5500):
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
    raise RuntimeError("No open ports available in the specified range")

if __name__ == '__main__':
    port = find_open_port()
    print("# # # # # # # # # # # # # # # # #")
    print(f"# Starting server on port {port}  #")
    print("# # # # # # # # # # # # # # # # #")


    with app.app_context():
        db.create_all()
    update_database_from_xml_logic()
    app.run(port=port, debug=True, use_reloader=True)