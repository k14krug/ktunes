from flask import redirect, url_for, jsonify, flash, render_template, request, current_app, make_response
from flask_login import login_required
from extensions import db
from . import spotify_bp
from services.task_service import run_export_default_playlist
from services.spotify_service import (
    spotify_auth, spotify_callback, get_spotify_client, 
    export_playlist_to_spotify, fetch_and_update_recent_tracks,
    get_listening_history_with_playlist_context, check_if_krug_playlist_is_playing
)
from models import Track, SpotifyURI, PlayedTrack, Playlist
from datetime import datetime
from sqlalchemy import func
import time

class PaginationInfo:
    """Pagination helper class to match template expectations"""
    def __init__(self, page, per_page, total_count, total_pages, has_prev, has_next, prev_num, next_num):
        self.page = page
        self.per_page = per_page
        self.limit = per_page  # Keep both for compatibility
        self.total_count = total_count
        self.total_pages = total_pages
        self.has_prev = has_prev
        self.has_next = has_next
        self.prev_num = prev_num
        self.next_num = next_num
        self.total = total_count  # Alternative name used in template
    
    def iter_pages(self, left_edge=2, left_current=2, right_current=3, right_edge=2):
        """Generate page numbers for pagination display"""
        last = self.total_pages
        for num in range(1, last + 1):
            if num <= left_edge or \
               (self.page - left_current - 1 < num < self.page + right_current) or \
               num > last - right_edge:
                yield num

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

@spotify_bp.route('/check_current_playback')
@login_required
def check_current_playback():
    """Test endpoint to check if KRUG FM 96.2 is currently playing"""
    # For web requests, we can use interactive auth if needed
    try:
        # First try non-interactive (faster)
        is_playing, current_track_info, error = check_if_krug_playlist_is_playing()
        
        if error and "not authenticated" in error:
            # If auth failed, we can try interactive for web requests
            # But for now, just return the error to avoid browser popups
            pass
    except Exception as e:
        error = str(e)
        is_playing = False
        current_track_info = None
    
    if error:
        return jsonify({
            "success": False,
            "error": error
        }), 500
    
    if is_playing and current_track_info:
        return jsonify({
            "success": True,
            "is_krug_playing": True,
            "current_track": current_track_info,
            "message": f"KRUG FM 96.2 is currently playing: {current_track_info['track_name']} by {current_track_info['artist']}"
        })
    else:
        return jsonify({
            "success": True,
            "is_krug_playing": False,
            "current_track": None,
            "message": "KRUG FM 96.2 is not currently playing"
        })

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
    sp = get_spotify_client(allow_interactive_auth=True)
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
    sp = get_spotify_client(allow_interactive_auth=True)
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
    sp = get_spotify_client(allow_interactive_auth=True)
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
    sp = get_spotify_client(allow_interactive_auth=True)
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

@spotify_bp.route('/refresh_listening_history')
@login_required
def refresh_listening_history():
    """
    Manually refresh Spotify listening history by fetching latest tracks from Spotify API.
    Then redirect back to the listening history page.
    """
    try:
        from datetime import datetime
        import time
        refresh_start = datetime.utcnow()
        current_app.logger.info("Manual refresh of Spotify listening history requested")
        
        # Fetch latest tracks from Spotify - this is synchronous and will wait for completion
        start_time = time.time()
        tracks, error = fetch_and_update_recent_tracks(limit=50)
        processing_time = time.time() - start_time
        
        current_app.logger.info(f"Refresh completed in {processing_time:.2f} seconds")
        
        if error:
            flash(f"Error fetching latest Spotify tracks: {error}", 'error')
        elif tracks:
            flash(f"Successfully fetched {len(tracks)} new tracks from Spotify (took {processing_time:.1f}s)", 'success')
        else:
            flash(f"No new tracks found since last update (checked in {processing_time:.1f}s)", 'info')
            
    except Exception as e:
        current_app.logger.error(f"Error during manual listening history refresh: {str(e)}")
        flash("An error occurred while refreshing listening history. Please try again.", 'error')
    
    # Add a small delay to ensure database commits are complete
    time.sleep(0.5)
    
    # Redirect back to listening history page
    return redirect(url_for('spotify.listening_history'))


@spotify_bp.route('/playlist_review_guide')
@login_required
def playlist_review_guide():
    """Render the in-app wiki guide for Spotify playlist review."""
    return render_template('spotify_playlist_review_guide.html')


@spotify_bp.route('/listening_history')
@login_required
def listening_history():
    """
    Display recent Spotify listening history with playlist context
    Optimized with performance monitoring and better error handling
    
    Query Parameters:
    - page: int (default: 1) - Page number for pagination
    - limit: int (default: 50) - Number of records per page
    
    Returns:
    - Rendered template with listening history data
    """
    from services.cache_service import log_cache_stats
    
    route_start_time = time.time()
    
    try:
        # Get pagination parameters from query string with validation
        try:
            page = request.args.get('page', 1, type=int)
            limit = request.args.get('limit', 50, type=int)
        except (ValueError, TypeError) as param_error:
            flash("Invalid pagination parameters. Using default values.", 'warning')
            page = 1
            limit = 50
        
        # Validate pagination parameters with performance considerations
        if page < 1:
            flash("Invalid page number. Showing first page.", 'warning')
            page = 1
        if limit < 1 or limit > 100:  # Reduced max limit for better performance
            if limit > 100:
                flash("Requested limit too high. Showing maximum of 100 records per page for optimal performance.", 'warning')
            limit = min(50, max(1, limit))  # Clamp between 1 and 50
            
        # Calculate offset for pagination
        offset = (page - 1) * limit
        
        # Log cache stats periodically for monitoring
        if page == 1:  # Only log on first page to avoid spam
            log_cache_stats()
        
        # Get listening history data from service with timeout consideration
        try:
            service_start_time = time.time()
            # Try versioned correlation first, fall back to current method if needed
            try:
                from services.spotify_service import get_listening_history_with_versioned_playlist_context
                current_app.logger.info("Using versioned playlist correlation")
                listening_data, total_count, error_message = get_listening_history_with_versioned_playlist_context(
                    limit=limit, 
                    offset=offset
                )
                current_app.logger.info(f"Versioned correlation returned {len(listening_data)} tracks")
            except ImportError:
                # Fallback if versioned function is not available
                current_app.logger.info("Versioned function not available, using current correlation")
                listening_data, total_count, error_message = get_listening_history_with_playlist_context(
                    limit=limit, 
                    offset=offset
                )
            service_time = time.time() - service_start_time
            
            # Log slow service calls
            if service_time > 1.5:
                current_app.logger.warning(f"Slow service call: get_listening_history_with_playlist_context took {service_time:.3f}s")
                
        except Exception as service_error:
            current_app.logger.error(f"Service error in listening_history route: {service_error}")
            flash("Unable to load listening history due to a service error. Please try again later.", 'error')
            return redirect(url_for('main.index'))
        
        # Handle service-level error messages with improved categorization
        if error_message:
            # Determine flash message type based on severity
            if any(keyword in error_message.lower() for keyword in ["database", "connection", "unexpected error"]):
                flash(error_message, 'error')
            elif any(keyword in error_message.lower() for keyword in ["playlist", "not found", "empty"]):
                flash(error_message, 'info')
            elif any(keyword in error_message.lower() for keyword in ["slow", "performance", "timeout"]):
                flash(error_message, 'warning')
            else:
                flash(error_message, 'warning')
        
        # Handle edge case where service returns no data due to errors
        if total_count == 0 and not listening_data:
            if not error_message:  # Only show this if no other error message was set
                flash("No listening history available. This could be due to no recent Spotify activity or a data synchronization issue.", 'info')
        
        # Optimized pagination calculation
        try:
            if total_count == 0:
                total_pages = 1
            else:
                total_pages = (total_count + limit - 1) // limit  # Ceiling division
            
            has_prev = page > 1
            has_next = page < total_pages
            
            # Prepare pagination data for template
            pagination = PaginationInfo(
                page=page,
                per_page=limit,
                total_count=total_count,
                total_pages=total_pages,
                has_prev=has_prev,
                has_next=has_next,
                prev_num=page - 1 if has_prev else None,
                next_num=page + 1 if has_next else None
            )
        except Exception as pagination_error:
            current_app.logger.error(f"Error calculating pagination: {pagination_error}")
            # Fallback pagination
            pagination = PaginationInfo(
                page=1,
                per_page=limit,
                total_count=total_count,
                total_pages=1,
                has_prev=False,
                has_next=False,
                prev_num=None,
                next_num=None
            )
            flash("Pagination may not work correctly due to a calculation error.", 'warning')
        
        # Validate that we have data to show or appropriate empty state
        if not listening_data and total_count > 0:
            flash("No data found for the requested page. You may have requested a page that doesn't exist.", 'warning')
            # Redirect to first page with performance-optimized limit
            return redirect(url_for('spotify.listening_history', page=1, limit=min(limit, 50)))
        
        # Extract time period stats if available
        time_period_stats = None
        if listening_data and listening_data[0].get('time_period_stats'):
            time_period_stats = listening_data[0]['time_period_stats']
        
        # Log total route performance
        route_time = time.time() - route_start_time
        if route_time > 3.0:
            current_app.logger.warning(f"Slow route: listening_history took {route_time:.3f}s total")
        
        response = make_response(render_template(
            'spotify_listening_history.html',
            listening_history=listening_data,
            total_tracks=total_count,
            pagination_info=pagination,
            time_period_stats=time_period_stats
        ))
        
        # Add cache-busting headers to ensure fresh data after refresh
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response
        
    except Exception as e:
        current_app.logger.error(f"Unexpected error in listening_history route: {e}")
        flash(f"An unexpected error occurred while loading the listening history page. Please try again later.", 'error')
        return redirect(url_for('main.index'))

@spotify_bp.route('/performance_stats')
@login_required
def performance_stats():
    """
    Display performance statistics for listening history feature
    Useful for monitoring and optimization
    """
    from services.cache_service import get_cache, log_cache_stats
    from services.spotify_service import optimize_database_queries
    
    try:
        # Get cache statistics
        cache = get_cache()
        cache_size = cache.size()
        expired_cleaned = cache.cleanup_expired()
        
        # Run database performance check
        db_stats = optimize_database_queries()
        
        # Get some basic metrics
        total_played_tracks = db.session.query(func.count(PlayedTrack.id))\
            .filter(PlayedTrack.source == 'spotify')\
            .scalar()
        
        latest_playlist_date = db.session.query(func.max(Playlist.playlist_date))\
            .filter(Playlist.playlist_name == 'KRUG FM 96.2')\
            .scalar()
        
        playlist_track_count = 0
        if latest_playlist_date:
            playlist_track_count = db.session.query(func.count(Playlist.id))\
                .filter(
                    Playlist.playlist_name == 'KRUG FM 96.2',
                    Playlist.playlist_date == latest_playlist_date
                )\
                .scalar()
        
        stats = {
            'cache': {
                'size': cache_size,
                'expired_cleaned': expired_cleaned
            },
            'database': db_stats,
            'metrics': {
                'total_played_tracks': total_played_tracks,
                'latest_playlist_date': latest_playlist_date.strftime('%Y-%m-%d %H:%M:%S') if latest_playlist_date else 'None',
                'playlist_track_count': playlist_track_count
            }
        }
        
        return jsonify({
            'success': True,
            'stats': stats,
            'recommendations': _get_performance_recommendations(db_stats)
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting performance stats: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def _get_performance_recommendations(db_stats):
    """Generate performance recommendations based on database stats"""
    recommendations = []
    
    if not db_stats:
        recommendations.append("Unable to analyze database performance - check logs for errors")
        return recommendations
    
    if db_stats.get('count_time', 0) > 0.1:
        recommendations.append("Count queries are slow - consider adding index on played_tracks(source)")
    
    if db_stats.get('query_time', 0) > 0.1:
        recommendations.append("Main queries are slow - consider adding composite index on played_tracks(source, played_at)")
    
    if db_stats.get('playlist_date_time', 0) > 0.1:
        recommendations.append("Playlist date queries are slow - consider adding index on playlists(playlist_name, playlist_date)")
    
    if db_stats.get('total_records', 0) > 10000:
        recommendations.append("Large dataset detected - consider implementing data archiving for old played tracks")
    
    if not recommendations:
        recommendations.append("Database performance looks good - all queries are executing efficiently")
    
    return recommendations