from flask import render_template, request, redirect, url_for, flash, jsonify, session, abort
from flask_login import login_user, logout_user, login_required, current_user
from flask_paginate import Pagination, get_page_parameter
from extensions import db
from models import User, Playlist, Track
from services.playlist_generator_service import PlaylistGenerator, generate_default_playlist
from services.spotify_service import spotify_auth, spotify_callback, create_spotify_playlist, get_spotify_client, fetch_and_update_recent_tracks, export_playlist_to_spotify
from services.itunes_service import update_database_from_xml_logic
from services.itunes_integrator_wsl import iTunesIntegrator
from services.task_service import run_export_default_playlist
from config_loader import load_config
from sqlalchemy import func, desc
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta, datetime 


# Global config variable
config = load_config()

def register_routes(app):
    """Define and attach all routes to the given app."""

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


    @app.route('/edit_track/<int:track_id>', methods=['GET', 'POST'])
    @login_required
    def edit_track(track_id):
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
                return redirect(url_for('tracks'))
        return render_template('edit_track.html', track=track)

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
        success, result = export_playlist_to_spotify(playlist_name, db)

        if not success:
            if "redirect" in result:
                return jsonify({"success": False, "redirect": result["redirect"]}), 401
            return jsonify({"success": False, "message": result["message"], "failed_tracks": result.get("failed_tracks", [])}), 500

        return jsonify({"success": True, "message": result["message"], "failed_tracks": result.get("failed_tracks", [])})

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
        tracks, error = fetch_and_update_recent_tracks(limit=50)
        
        if error:
            flash(error, 'error')
            return redirect(url_for('index'))

        return render_template('recent_spotify_tracks.html', tracks=tracks)


    @app.route('/export_default_playlist_to_spotify')
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

        return redirect(url_for('playlists'))
    
    # End of all routes - return the app
    return(app)
