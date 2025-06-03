from flask import redirect, url_for, jsonify, flash, render_template, request, session, abort, current_app
from flask_login import login_required, current_user
from flask_paginate import Pagination, get_page_parameter
from datetime import datetime
import json
import os
from sqlalchemy import func, distinct, desc
from models import Playlist, Track, PlayedTrack, SpotifyURI
from services.itunes_integrator_wsl import iTunesIntegrator
from services.playlist_generator_service import PlaylistGenerator
from services.spotify_service import get_spotify_client
from services.itunes_service import update_database_from_xml_logic

from config_loader import  dump_config
from extensions import db
#from app import app

from . import main_bp
@main_bp.route('/update_database_from_xml')
@login_required
def update_database_from_xml():
    updates, inserts = update_database_from_xml_logic()
    flash(f"Database updated: {updates} rows updated, {inserts} rows inserted", "success")
    return redirect(url_for('settings'))

@main_bp.route('/')
@login_required
def index():
    # Reload config to ensure we have the latest values
    # kkrug 1/31/2025 see change_log.md for why next two lines are commented out
    #global config
    #config = load_config()
    config = current_app.config
    if request.method == 'GET':
        # Initialize PlaylistGenerator with default values to get initial track counts
        default_categories = config['playlist_defaults']['categories']
        generator = PlaylistGenerator(
            playlist_name="",  # Empty placeholder
            playlist_length=config['playlist_defaults']['playlist_length'],
            minimum_recent_add_playcount=config['playlist_defaults']['minimum_recent_add_playcount'],
            categories=default_categories,
            username=current_user.username,
            target_platform='local'  # Added for UI context
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


@main_bp.route('/generate_playlist', methods=['POST'])
@login_required
def generate_playlist():
    # kkrug 1/31/2025 see change_log.md for why next line was added.
    config = current_app.config
    #print(f"generate_playlist - config = {config}")
    current_app.logger.info("In generate_playlist route")
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
    # kkrug 1/31/2025 see change_log.md about use of filtered_config
    filtered_config = dump_config(config)
    with open('config.json', 'w') as f:
        json.dump(filtered_config, f, indent=4)

    # Generate playlist logic...
    current_app.logger.info("Instantiating PlaylistGenerator, then calling generate()")
    generator = PlaylistGenerator(playlist_name, playlist_length, minimum_recent_add_playcount, categories, current_user.username, target_platform='local') # Added for UI context

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
            'redirect': url_for('main.view_playlist', playlist_name=playlist_name)
        })
    except Exception as e:
        db.session.rollback()  # Rollback the session in case of error
        current_app.logger.error(f"Error generating playlist: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Error generating playlist: {str(e)}'
        }), 500

    
@main_bp.route('/check_playlist_name')
@login_required
def check_playlist_name():
    name = request.args.get('name', '')
    playlist_exists = Playlist.query.filter_by(playlist_name=name, username=current_user.username).first() is not None
    return jsonify({'exists': playlist_exists})    
    

@main_bp.route('/tracks')
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


@main_bp.route('/played_tracks')
@login_required
def played_tracks():
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
    query = PlayedTrack.query

    # Apply filters
    if song_filter:
        query = query.filter(PlayedTrack.song.ilike(f'%{song_filter}%'))
    if artist_filter:
        query = query.filter(PlayedTrack.artist.ilike(f'%{artist_filter}%'))
    if category_filter:
        query = query.filter(PlayedTrack.category.ilike(f'%{category_filter}%'))

    # Apply sorting
    if sort_direction == 'desc':
        query = query.order_by(desc(getattr(PlayedTrack, sort_column)))
    else:
        query = query.order_by(getattr(PlayedTrack, sort_column))

    # Get total number of tracks (for pagination)
    total = query.count()

    # Apply pagination
    played_tracks = query.paginate(page=page, per_page=per_page, error_out=False)

    # Create pagination object
    pagination = Pagination(page=page, total=total, per_page=per_page, css_framework='bootstrap4')

    return render_template('played_tracks.html', 
                        played_tracks=played_tracks.items, 
                        pagination=pagination, 
                        sort_column=sort_column, 
                        sort_direction=sort_direction)  

    '''
    track = Track.query.get_or_404(track_id)
    if request.method == 'POST':
        if 'delete' in request.form:
            db.session.delete(track)
            db.session.commit()
            flash('Track deleted successfully', 'success')
            return redirect(url_for('tracks'))
        else:
            track.song = request.form['song']
            track.artist = request.form['artist']
            track.album = request.form['album']
            track.category = request.form['category']
            track.play_cnt = request.form['play_cnt']
            print(f"request.form['date_added'] = {request.form['date_added']}")
            track.date_added = datetime.strptime(request.form['date_added'], '%Y-%m-%dT%H:%M:%S')
            track.last_play_dt = datetime.strptime(request.form['last_play_dt'], '%Y-%m-%dT%H:%M:%S')
            track.spotify_uri = request.form['spotify_uri']
            db.session.commit()
            flash('Track updated successfully', 'success')
            return redirect(url_for('main.tracks'))
    return render_template('edit_track.html', track=track)
'''

@main_bp.route('/manage_artists', methods=['GET', 'POST'])
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


@main_bp.route('/autocomplete/artists')
def autocomplete_artists():
    print("In autocomplete_artists route")
    search = request.args.get('term', '')
    artists = db.session.query(distinct(Track.artist)).filter(
        Track.artist.ilike(f'%{search}%')
    ).order_by(Track.artist).limit(10).all()
    return jsonify([artist[0] for artist in artists])

@main_bp.route('/autocomplete/common_names')
def autocomplete_common_names():
    search = request.args.get('term', '')
    common_names = db.session.query(distinct(Track.artist_common_name)).filter(
        Track.artist_common_name.ilike(f'%{search}%'),
        Track.artist_common_name != None,
        Track.artist_common_name != ''
    ).order_by(Track.artist_common_name).limit(10).all()
    return jsonify([name[0] for name in common_names if name[0]])

@main_bp.route('/settings', methods=['GET', 'POST'])
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

@main_bp.route('/playlist/<playlist_name>')
@login_required
def view_playlist(playlist_name):
    config = current_app.config
    sp = get_spotify_client()
    if not sp:
        return redirect(url_for('route_spotify_auth'))
    
    # Get filter parameters
    song_filter = request.args.get('song', '')
    artist_filter = request.args.get('artist', '')
    category_filter = request.args.get('category', '')

    # Modified query to join with SpotifyURI table
    query = db.session.query(
        Playlist,
        Track.last_play_dt,
        Track.id.label('track_id')  # Get track_id to fetch URIs later
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
    
    # Fetch Spotify URIs for all tracks in the playlist
    track_ids = [track.track_id for track in playlist_tracks]
    spotify_uris_map = {}
    
    # Query SpotifyURI table for all tracks in this playlist
    spotify_uris = db.session.query(SpotifyURI).filter(
        SpotifyURI.track_id.in_(track_ids)
    ).all()
    
    # Group URIs by track_id for easy access in template
    for uri in spotify_uris:
        if uri.track_id not in spotify_uris_map:
            spotify_uris_map[uri.track_id] = []
        spotify_uris_map[uri.track_id].append(uri)
    
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
                        category_repeats=category_repeats,
                        spotify_uris_map=spotify_uris_map)  # Pass Spotify URIs map to the template

@main_bp.route('/playlists')
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
    return render_template('playlists.html', playlists=unique_playlists)

@main_bp.route('/delete_playlist/<playlist_name>', methods=['POST'])
@login_required
def delete_playlist(playlist_name):
    try:
        Playlist.query.filter_by(username=current_user.username, playlist_name=playlist_name).delete()
        db.session.commit()
        return jsonify({"success": True, "message": f'Playlist "{playlist_name}" has been deleted.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@main_bp.route('/upload_to_itunes/<playlist_name>', methods=['POST'])
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

@main_bp.route('/edit_track/<int:track_id>', methods=['GET', 'POST'])
@login_required
def edit_track(track_id):
    track = Track.query.get_or_404(track_id)
    if request.method == 'POST':
        # Debug logging of form data
        current_app.logger.debug("Form data received:")
        for key, value in request.form.items():
            current_app.logger.debug(f"  {key}: {value}")

        if 'delete' in request.form:
            try:
                # First delete related Spotify URIs
                SpotifyURI.query.filter_by(track_id=track_id).delete()
                
                # Then delete the track
                db.session.delete(track)
                db.session.commit()
                flash('Track and related Spotify URIs deleted successfully', 'success')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error deleting track: {str(e)}", exc_info=True)
                flash(f'Error deleting track: {str(e)}', 'error')
            return redirect(url_for('main.tracks'))
        else:
            try:
                # Debug print the keys we need to access
                current_app.logger.debug(f"Song: {request.form.get('song', 'MISSING')}")
                current_app.logger.debug(f"Artist: {request.form.get('artist', 'MISSING')}")
                
                # Update track details with careful validation
                if 'song' not in request.form or not request.form['song'].strip():
                    raise ValueError("Song name cannot be empty")
                track.song = request.form['song'].strip()
                
                if 'artist' not in request.form or not request.form['artist'].strip():
                    raise ValueError("Artist name cannot be empty")
                track.artist = request.form['artist'].strip()
                
                track.album = request.form.get('album', '').strip()
                track.category = request.form.get('category', '').strip()
                
                # Handle play count carefully
                play_cnt = request.form.get('play_cnt', '')
                current_app.logger.debug(f"Play count: {play_cnt}")
                if play_cnt.strip():
                    try:
                        track.play_cnt = int(play_cnt)
                    except ValueError:
                        current_app.logger.error(f"Invalid play count: {play_cnt}")
                        flash(f"Invalid play count: {play_cnt}. Using zero.", "warning")
                        track.play_cnt = 0
                else:
                    track.play_cnt = 0
                
                # Debug print the date values
                current_app.logger.debug(f"Date added (raw): {request.form.get('date_added', 'MISSING')}")
                current_app.logger.debug(f"Last play (raw): {request.form.get('last_play_dt', 'MISSING')}")
                
                # Parse dates more flexibly with detailed debugging
                date_added_str = request.form.get('date_added', '').strip()
                if date_added_str:
                    current_app.logger.debug(f"Attempting to parse date_added: {date_added_str}")
                    formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']
                    parsed = False
                    
                    for fmt in formats:
                        try:
                            current_app.logger.debug(f"  Trying format: {fmt}")
                            track.date_added = datetime.strptime(date_added_str, fmt)
                            current_app.logger.debug(f"  Success! Parsed as: {track.date_added}")
                            parsed = True
                            break
                        except ValueError as e:
                            current_app.logger.debug(f"  Failed with format {fmt}: {str(e)}")
                    
                    if not parsed:
                        current_app.logger.error(f"Could not parse date_added: {date_added_str}")
                        flash(f"Invalid date format for Date Added: {date_added_str}. Using current date.", "warning")
                        track.date_added = datetime.now()
                else:
                    current_app.logger.debug("No date_added provided")
                
                last_play_dt_str = request.form.get('last_play_dt', '').strip()
                if last_play_dt_str:
                    current_app.logger.debug(f"Attempting to parse last_play_dt: {last_play_dt_str}")
                    formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']
                    parsed = False
                    
                    for fmt in formats:
                        try:
                            current_app.logger.debug(f"  Trying format: {fmt}")
                            track.last_play_dt = datetime.strptime(last_play_dt_str, fmt)
                            current_app.logger.debug(f"  Success! Parsed as: {track.last_play_dt}")
                            parsed = True
                            break
                        except ValueError as e:
                            current_app.logger.debug(f"  Failed with format {fmt}: {str(e)}")
                    
                    if not parsed:
                        current_app.logger.error(f"Could not parse last_play_dt: {last_play_dt_str}")
                        flash(f"Invalid date format for Last Played: {last_play_dt_str}. Using current date.", "warning")
                        track.last_play_dt = datetime.now()
                else:
                    current_app.logger.debug("No last_play_dt provided")
                    track.last_play_dt = None  # Allow null last play date

                # Handle Spotify URIs with debugging
                uri_ids = request.form.getlist('uri_id')
                uris = request.form.getlist('spotify_uri')
                
                current_app.logger.debug(f"URI IDs: {uri_ids}")
                current_app.logger.debug(f"URIs: {uris}")
                
                # Track which URIs we've processed to avoid deleting newly added ones
                processed_uri_ids = set()
                
                # Update existing URIs and create new ones
                for i, (uri_id, uri) in enumerate(zip(uri_ids, uris)):
                    current_app.logger.debug(f"Processing URI {i+1}: ID={uri_id}, URI={uri}")
                    
                    if uri_id and uri_id.strip().isdigit():  # Existing URI with valid ID
                        uri_id = int(uri_id.strip())
                        spotify_uri = SpotifyURI.query.get(uri_id)
                        if spotify_uri:
                            current_app.logger.debug(f"  Updating existing URI {uri_id}")
                            spotify_uri.uri = uri.strip()
                            processed_uri_ids.add(uri_id)
                        else:
                            current_app.logger.warning(f"  URI ID {uri_id} not found in database")
                    elif uri and uri.strip():  # New URI with content
                        current_app.logger.debug(f"  Creating new URI: {uri}")
                        # Commit the track changes first to ensure valid track_id
                        db.session.flush()
                        
                        # Create the new URI
                        spotify_uri = SpotifyURI(
                            track_id=track_id,
                            uri=uri.strip(),
                            status='matched',
                            created_at=datetime.utcnow()
                        )
                        db.session.add(spotify_uri)
                        db.session.flush()  # Flush to get the new URI ID
                        
                        current_app.logger.debug(f"  Created new URI with ID: {spotify_uri.id}")
                        processed_uri_ids.add(spotify_uri.id)
                
                # Get current URIs from the database again (to include any we just added)
                current_uris = SpotifyURI.query.filter_by(track_id=track_id).all()
                current_uri_ids = {uri.id for uri in current_uris}
                
                current_app.logger.debug(f"Current URI IDs in DB: {current_uri_ids}")
                current_app.logger.debug(f"Processed URI IDs: {processed_uri_ids}")
                
                # Only delete URIs that weren't in the form and aren't newly added
                uris_to_delete = current_uri_ids - processed_uri_ids
                
                if uris_to_delete:
                    current_app.logger.debug(f"Deleting URIs with IDs: {uris_to_delete}")
                    SpotifyURI.query.filter(SpotifyURI.id.in_(uris_to_delete)).delete()
                
                # Commit changes
                current_app.logger.debug("Committing changes to database")
                db.session.commit()
                
                # Verify the URIs were saved
                saved_uris = SpotifyURI.query.filter_by(track_id=track_id).all()
                current_app.logger.debug(f"Saved URIs after commit: {[uri.uri for uri in saved_uris]}")
                
                flash('Track updated successfully', 'success')
                return redirect(url_for('main.tracks'))
                
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error updating track: {str(e)}", exc_info=True)
                flash(f'Error updating track: {str(e)}', 'error')
                return render_template('edit_track.html', track=track)

    # For GET requests, add debugging for what we're sending to template
    current_app.logger.debug(f"Rendering edit form for track {track_id}")
    current_app.logger.debug(f"  Song: {track.song}")
    current_app.logger.debug(f"  Artist: {track.artist}")
    current_app.logger.debug(f"  Date Added: {track.date_added}")
    current_app.logger.debug(f"  Last Played: {track.last_play_dt}")
    current_app.logger.debug(f"  URIs: {[uri.uri for uri in track.spotify_uris]}")
    
    # Refresh track from database to ensure we have the latest URIs
    db.session.refresh(track)
    
    # Format dates for display in the template
    return render_template('edit_track.html', track=track)
