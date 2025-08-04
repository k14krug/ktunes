from flask import render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required
from . import resolve_bp
from models import Track, SpotifyURI, PlayedTrack # Will be needed for POST actions
from extensions import db
from services.resolution_service import (
    resolve_link_track_to_spotify_uri, 
    resolve_update_track_status
)
from services.spotify_service import normalize_text, normalize_text_for_matching, get_spotify_client # For similarity matching
from sqlalchemy import or_
from thefuzz import fuzz # For similarity scores

@resolve_bp.route('/mismatches')
@login_required
def view_mismatches():
    # Query the database view for tracks that need review
    mismatches_query = """
        SELECT * FROM spotify_resolution_view 
        WHERE match_status = 'mismatch_accepted'
        ORDER BY track_id, match_date DESC
    """
    
    mismatches_raw = db.session.execute(db.text(mismatches_query)).fetchall()
    
    # Get Spotify client to fetch track details
    sp = get_spotify_client()
    
    # Group by track_id and check for existing good matches
    track_groups = {}
    for row in mismatches_raw:
        track_id = row.track_id
        if track_id not in track_groups:
            track_groups[track_id] = {
                'local_track': {
                    'id': row.track_id,
                    'song': row.local_song,
                    'artist': row.local_artist,
                    'album': row.local_album
                },
                'mismatches': [],
                'has_good_match': False,
                'good_match_uri': None
            }
        
        # Check if this track already has a 'matched' or 'manual_match' record
        existing_good_match = db.session.execute(db.text("""
            SELECT uri FROM spotify_uris 
            WHERE track_id = :track_id 
            AND status IN ('matched', 'manual_match')
            ORDER BY created_at DESC
            LIMIT 1
        """), {'track_id': track_id}).fetchone()
        
        if existing_good_match:
            track_groups[track_id]['has_good_match'] = True
            track_groups[track_id]['good_match_uri'] = existing_good_match[0]
        
        # Try to get actual Spotify track info from the URI
        spotify_track_name = "Unknown"
        spotify_artist_name = "Unknown"
        
        if row.spotify_uri and row.spotify_uri.startswith('spotify:track:') and sp:
            try:
                track_id_spotify = row.spotify_uri.split(':')[-1]
                spotify_track_info = sp.track(track_id_spotify)
                if spotify_track_info:
                    spotify_track_name = spotify_track_info['name']
                    spotify_artist_name = ', '.join([artist['name'] for artist in spotify_track_info['artists']])
            except Exception as e:
                current_app.logger.warning(f"Could not fetch Spotify track info for URI {row.spotify_uri}: {e}")
        
        track_groups[track_id]['mismatches'].append({
            'log_identifier': f"mismatch_{row.track_id}_{row.spotify_uri.split(':')[-1] if row.spotify_uri else 'unknown'}",
            'found': f"{spotify_track_name} by {spotify_artist_name}",
            'spotify_url': row.spotify_url,
            'spotify_track_uri': row.spotify_uri,
            'timestamp': row.match_date if row.match_date else None
        })
    
    # Convert grouped data to format expected by template
    mismatches = []
    for track_id, group in track_groups.items():
        if group['has_good_match']:
            # Get info about the good match
            good_match_info = "Unknown Track"
            if group['good_match_uri'] and sp:
                try:
                    good_track_id = group['good_match_uri'].split(':')[-1]
                    good_spotify_info = sp.track(good_track_id)
                    if good_spotify_info:
                        good_match_info = f"{good_spotify_info['name']} by {', '.join([artist['name'] for artist in good_spotify_info['artists']])}"
                except Exception as e:
                    current_app.logger.warning(f"Could not fetch good match info for URI {group['good_match_uri']}: {e}")
            
            # Create a special entry for tracks that already have good matches
            mismatches.append({
                'is_duplicate_group': True,
                'local_track_details': group['local_track'],
                'good_match_info': good_match_info,
                'good_match_uri': group['good_match_uri'],
                'duplicate_count': len(group['mismatches']),
                'mismatches': group['mismatches']
            })
        else:
            # Regular mismatch entries (no existing good match)
            for mismatch in group['mismatches']:
                # Check for ANY existing Spotify URI for this track
                existing_uri_info = None
                existing_uri_record = db.session.execute(db.text("""
                    SELECT uri, status FROM spotify_uris 
                    WHERE track_id = :track_id 
                    ORDER BY created_at DESC
                    LIMIT 1
                """), {'track_id': track_id}).fetchone()
                
                if existing_uri_record:
                    existing_uri = existing_uri_record[0]
                    existing_status = existing_uri_record[1]
                    current_app.logger.info(f"Found existing URI for track {track_id}: {existing_uri} (status: {existing_status})")
                    
                    # Try to get info about the existing URI
                    existing_track_info = "Unknown Track"
                    if sp:
                        try:
                            if existing_uri.startswith('spotify:track:'):
                                existing_track_id = existing_uri.split(':')[-1]
                                existing_spotify_info = sp.track(existing_track_id)
                                if existing_spotify_info:
                                    existing_track_info = f"{existing_spotify_info['name']} by {', '.join([artist['name'] for artist in existing_spotify_info['artists']])}"
                        except Exception as e:
                            current_app.logger.warning(f"Could not fetch existing URI info for {existing_uri}: {e}")
                            existing_track_info = "Could not retrieve track info"
                    else:
                        current_app.logger.warning("No Spotify client available for URI validation")
                        existing_track_info = "Spotify client unavailable"
                    
                    # Check if existing URI is different from the found track URI
                    is_different = existing_uri != mismatch['spotify_track_uri']
                    
                    existing_uri_info = {
                        'uri': existing_uri,
                        'status': existing_status,
                        'spotify_track_info': existing_track_info,
                        'is_different_from_found': is_different
                    }
                else:
                    current_app.logger.info(f"No existing URI found for track {track_id}")
                
                mismatches.append({
                    'is_duplicate_group': False,
                    'log_identifier': mismatch['log_identifier'],
                    'local_track_details': group['local_track'],
                    'found': mismatch['found'],
                    'spotify url': mismatch['spotify_url'],
                    'spotify_track_uri': mismatch['spotify_track_uri'],
                    'timestamp': mismatch['timestamp'],
                    'existing_spotify_uri': existing_uri_info
                })
    
    return render_template('resolve/resolve_mismatches.html', mismatches=mismatches, title="Resolve Mismatches")

@resolve_bp.route('/not_found')
@login_required
def view_not_found():
    # Query tracks with not_found_in_spotify status
    not_found_spotify_uris = SpotifyURI.query.filter_by(status='not_found_in_spotify').all()
    
    # Convert to format expected by the template and detect anomalies
    not_found_tracks = []
    for spotify_uri in not_found_spotify_uris:
        track = spotify_uri.track
        
        # Check for anomaly: Does this track have multiple SpotifyURI records?
        all_uris_for_track = SpotifyURI.query.filter_by(track_id=track.id).all()
        has_anomaly = len(all_uris_for_track) > 1
        
        # If anomaly exists, find any valid Spotify URIs
        valid_spotify_uris = []
        if has_anomaly:
            valid_spotify_uris = [uri for uri in all_uris_for_track 
                                if uri.uri and uri.uri.startswith('spotify:track:') 
                                and not uri.uri.endswith('not_found_in_spotify')
                                and uri.status != 'not_found_in_spotify']
        
        item = {
            'log_identifier': f"notfound_{track.id}",
            'local_track_details': {
                'id': track.id,
                'song': track.song,
                'artist': track.artist,
                'album': track.album
            },
            'timestamp': spotify_uri.created_at,
            'has_anomaly': has_anomaly,
            'total_spotify_uris': len(all_uris_for_track),
            'valid_spotify_uris': valid_spotify_uris,
            'spotify_uri_details': all_uris_for_track  # For debugging/detailed view
        }
        not_found_tracks.append(item)
    
    return render_template('resolve/resolve_not_found.html', not_found_tracks=not_found_tracks, title="Resolve Not Found Tracks")

@resolve_bp.route('/unmatched_tracks')
@login_required
def view_unmatched_tracks():
    unmatched_tracks_query = Track.query.filter(Track.category == 'Unmatched') \
                                     .outerjoin(SpotifyURI, Track.id == SpotifyURI.track_id) \
                                     .add_columns(Track.id.label("track_id"), Track.song, Track.artist, Track.album, Track.last_play_dt, SpotifyURI.uri.label("spotify_track_uri"), SpotifyURI.id.label("spotify_uri_id")) \
                                     .order_by(Track.artist, Track.song).all()

    unmatched_tracks_data = []
    potential_library_tracks = Track.query.filter(
        or_(Track.category == None, Track.category != 'Unmatched') # noqa E711
    ).all()

    processed_count = 0
    auto_resolved_count = 0
    tracks_to_display = [] # Build a new list for tracks that need manual review

    for unmatched in unmatched_tracks_query:
        processed_count += 1
        auto_resolved = False # Flag for this specific unmatched track

        # Fetch the full Track object for potential deletion
        unmatched_track_obj = db.session.get(Track, unmatched.track_id)
        if not unmatched_track_obj:
            current_app.logger.warning(f"Could not find Track object for ID {unmatched.track_id} during unmatched resolution.")
            continue # Skip if the track object somehow doesn't exist

        # Fetch the associated SpotifyURI object for potential deletion
        spotify_uri_obj = None
        if unmatched.spotify_uri_id:
            spotify_uri_obj = db.session.get(SpotifyURI, unmatched.spotify_uri_id)

        normalized_unmatched_song = normalize_text_for_matching(unmatched.song) if unmatched.song else ""
        normalized_unmatched_artist = normalize_text_for_matching(unmatched.artist) if unmatched.artist else ""
        
        potential_matches = []
        for lib_track in potential_library_tracks:
            if lib_track.id == unmatched.track_id: # Don't compare with itself
                continue

            normalized_lib_song = normalize_text_for_matching(lib_track.song) if lib_track.song else ""
            normalized_lib_artist = normalize_text_for_matching(lib_track.artist) if lib_track.artist else ""

            song_similarity = fuzz.token_set_ratio(normalized_unmatched_song, normalized_lib_song)
            artist_similarity = fuzz.token_set_ratio(normalized_unmatched_artist, normalized_lib_artist)
            
            # Weighted average, giving more importance to song title
            # You can adjust weights or use a different scoring logic
            overall_similarity = (song_similarity * 0.6) + (artist_similarity * 0.4)

            # --- Auto-resolution Check ---
            if overall_similarity == 100:
                # Fetch the matched Spotify URI for the potential library match to compare
                matched_uri_record = SpotifyURI.query.filter_by(
                    track_id=lib_track.id,
                    status='matched'
                ).first()
                library_match_uri = matched_uri_record.uri if matched_uri_record else None

                # Check if URIs match (and exist)
                if unmatched.spotify_track_uri and library_match_uri and unmatched.spotify_track_uri == library_match_uri:
                    current_app.logger.info(f"Auto-resolving unmatched track ID {unmatched.track_id} ('{unmatched.song}') - Found 100% match with identical URI to track ID {lib_track.id} ('{lib_track.song}').")
                    try:
                        # Find ALL SpotifyURI records that reference this unmatched track
                        all_spotify_uris_for_track = SpotifyURI.query.filter_by(track_id=unmatched.track_id).all()
                        
                        # Delete ALL associated SpotifyURI records
                        for uri_record in all_spotify_uris_for_track:
                            current_app.logger.info(f"Deleting associated SpotifyURI ID {uri_record.id}")
                            db.session.delete(uri_record)
                        
                        # Now delete the redundant unmatched track
                        db.session.delete(unmatched_track_obj)
                        
                        db.session.commit()
                        auto_resolved = True
                        auto_resolved_count += 1
                        break # Exit inner loop once auto-resolved
                    except Exception as e:
                        db.session.rollback()
                        current_app.logger.error(f"Error auto-resolving unmatched track ID {unmatched.track_id}: {e}")

            # --- End Auto-resolution Check ---

            # If not auto-resolved, check threshold for adding to potential matches for manual review
            if not auto_resolved and overall_similarity > 60:
                potential_matches.append({
                    'track': lib_track,
                    'song_similarity': song_similarity,
                    'artist_similarity': artist_similarity,
                    'overall_similarity': overall_similarity
                })

        # If the track was auto-resolved in the inner loop, skip adding it for manual display
        if auto_resolved:
            continue

        # Sort potential matches by overall similarity, descending
        potential_matches.sort(key=lambda x: x['overall_similarity'], reverse=True)

        tracks_to_display.append({
            'unmatched': unmatched,
            'potential_matches': potential_matches
        })

    current_app.logger.info(f"Processed {processed_count} unmatched tracks. Auto-resolved: {auto_resolved_count}. Displaying: {len(tracks_to_display)}")
    if auto_resolved_count > 0:
        flash(f"Auto-resolved {auto_resolved_count} duplicate tracks.", 'success')
        
    return render_template('resolve/resolve_unmatched.html', unmatched_tracks=tracks_to_display, title="Resolve Unmatched Tracks")


# POST routes for Mismatches

@resolve_bp.route('/mismatch/link_track', methods=['POST'])
@login_required
def link_mismatch_to_spotify_track():
    log_identifier = request.form.get('log_identifier')
    local_track_id = request.form.get('local_track_id')
    spotify_uri_of_mismatch = request.form.get('spotify_uri_of_mismatch')

    if not all([log_identifier, local_track_id, spotify_uri_of_mismatch]):
        flash('Missing data for linking mismatch.', 'danger')
        return redirect(url_for('resolve.view_mismatches'))

    success = resolve_link_track_to_spotify_uri(
        local_track_id=int(local_track_id),
        spotify_uri=spotify_uri_of_mismatch,
        status='matched' # Confirming the found Spotify track is correct
    )

    if success:
        flash('Track successfully linked to the Spotify URI and mismatch resolved.', 'success')
    else:
        flash('Failed to link track or resolve mismatch. Check logs.', 'danger')
    
    return redirect(url_for('resolve.view_mismatches'))

def _extract_spotify_uri(uri_or_url):
    """Helper to extract Spotify URI from a URI or URL."""
    if uri_or_url.startswith("spotify:track:"):
        return uri_or_url
    elif "open.spotify.com/track/" in uri_or_url:
        try:
            track_id = uri_or_url.split("open.spotify.com/track/")[1].split("?")[0]
            return f"spotify:track:{track_id}"
        except IndexError:
            return None
    return None # Not a recognized format

def _validate_spotify_uri(spotify_uri, local_track=None):
    """
    Validate that a Spotify URI points to a real track by checking with Spotify API.
    If local_track is provided, also validates similarity between Spotify and local track.
    """
    try:
        from services.spotify_service import get_spotify_client
        sp = get_spotify_client()
        if not sp:
            return False, "Spotify client not available"
        
        # Extract track ID from URI
        if not spotify_uri.startswith("spotify:track:"):
            return False, "Invalid Spotify URI format"
        
        track_id = spotify_uri.split(":")[-1]
        
        # Try to get track info from Spotify
        track_info = sp.track(track_id)
        if not track_info:
            return False, "Track not found on Spotify"
            
        track_name = track_info['name']
        artist_name = ', '.join([artist['name'] for artist in track_info['artists']])
        spotify_description = f"{track_name} by {artist_name}"
        
        # If local track provided, check similarity
        if local_track:
            from services.spotify_service import normalize_text_for_matching
            local_song = normalize_text_for_matching(local_track.song)
            local_artist = normalize_text_for_matching(local_track.artist)
            spotify_song = normalize_text_for_matching(track_name)
            spotify_artist = normalize_text_for_matching(artist_name)
            
            # Calculate similarity scores
            song_similarity = fuzz.ratio(local_song, spotify_song)
            artist_similarity = fuzz.ratio(local_artist, spotify_artist)
            
            # Set reasonable thresholds for similarity
            MIN_SONG_SIMILARITY = 60  # Allows for some variation
            MIN_ARTIST_SIMILARITY = 70  # Artists should match closer
            
            if song_similarity < MIN_SONG_SIMILARITY:
                return False, f"Song title mismatch: '{local_track.song}' vs '{track_name}' (similarity: {song_similarity}%)"
            
            if artist_similarity < MIN_ARTIST_SIMILARITY:
                return False, f"Artist mismatch: '{local_track.artist}' vs '{artist_name}' (similarity: {artist_similarity}%)"
            
            # If we get here, it's a good match
            return True, f"✅ Good match: {spotify_description} (song: {song_similarity}%, artist: {artist_similarity}%)"
        
        # No local track to compare, just return Spotify info
        return True, spotify_description
            
    except Exception as e:
        return False, f"Error validating Spotify URI: {str(e)}"

@resolve_bp.route('/mismatch/validate_manual_link', methods=['POST'])
@login_required
def validate_manual_link():
    """AJAX endpoint to validate manual link without submitting the form."""
    try:
        local_track_id = request.form.get('local_track_id')
        manual_spotify_uri_input = request.form.get('manual_spotify_uri')
        force_link = request.form.get('force_link') == '1'

        if not all([local_track_id, manual_spotify_uri_input]):
            return jsonify({'valid': False, 'message': 'Missing required data.'}), 400

        spotify_uri = _extract_spotify_uri(manual_spotify_uri_input)
        if not spotify_uri:
            return jsonify({'valid': False, 'message': 'Invalid Spotify URI or URL format provided.'}), 400

        # Get the local track for similarity validation
        local_track = Track.query.get(int(local_track_id))
        if not local_track:
            return jsonify({'valid': False, 'message': 'Local track not found.'}), 400

        # Validate the Spotify URI with Spotify API and similarity check
        if force_link:
            # Skip similarity validation, just check if URI exists
            is_valid, validation_message = _validate_spotify_uri(spotify_uri)
            if is_valid:
                validation_message = f"⚠️ FORCED LINK: {validation_message}"
        else:
            # Full validation with similarity check
            is_valid, validation_message = _validate_spotify_uri(spotify_uri, local_track)
        
        return jsonify({
            'valid': is_valid,
            'message': validation_message
        })
        
    except Exception as e:
        return jsonify({'valid': False, 'message': f'Validation error: {str(e)}'}), 500

@resolve_bp.route('/mismatch/manual_link', methods=['POST'])
@login_required
def manual_link_mismatch():
    log_identifier = request.form.get('log_identifier')
    local_track_id = request.form.get('local_track_id')
    manual_spotify_uri_input = request.form.get('manual_spotify_uri')
    force_link = request.form.get('force_link') == '1'

    if not all([log_identifier, local_track_id, manual_spotify_uri_input]):
        flash('Missing data for manual linking.', 'danger')
        return redirect(url_for('resolve.view_mismatches'))

    spotify_uri = _extract_spotify_uri(manual_spotify_uri_input)
    if not spotify_uri:
        flash('Invalid Spotify URI or URL format provided.', 'danger')
        return redirect(url_for('resolve.view_mismatches'))

    # Get the local track for similarity validation
    local_track = Track.query.get(int(local_track_id))
    if not local_track:
        flash('Local track not found.', 'danger')
        return redirect(url_for('resolve.view_mismatches'))

    # Validate the Spotify URI with Spotify API and similarity check
    if force_link:
        # Skip similarity validation, just check if URI exists
        is_valid, validation_message = _validate_spotify_uri(spotify_uri)
        if is_valid:
            validation_message = f"⚠️ FORCED LINK: {validation_message}"
    else:
        # Full validation with similarity check
        is_valid, validation_message = _validate_spotify_uri(spotify_uri, local_track)
    
    if not is_valid:
        flash(f'Spotify URI validation failed: {validation_message}', 'danger')
        return redirect(url_for('resolve.view_mismatches'))

    success = resolve_link_track_to_spotify_uri(
        local_track_id=int(local_track_id),
        spotify_uri=spotify_uri,
        status='manual_match' # User manually provided this link
    )

    if success:
        flash(f'Track successfully linked manually to: {validation_message}. Mismatch resolved.', 'success')
    else:
        flash('Failed to manually link track or resolve mismatch. Check logs.', 'danger')
    
    return redirect(url_for('resolve.view_mismatches'))

@resolve_bp.route('/mismatch/mark_no_match', methods=['POST'])
@login_required
def mark_mismatch_as_no_match():
    log_identifier = request.form.get('log_identifier')
    local_track_id = request.form.get('local_track_id')

    if not all([log_identifier, local_track_id]):
        flash('Missing data for marking mismatch as no match.', 'danger')
        return redirect(url_for('resolve.view_mismatches'))

    success = resolve_update_track_status(
        local_track_id=int(local_track_id),
        new_status_or_flag='confirmed_no_spotify'
    )

    if success:
        flash('Track marked as having no match on Spotify and mismatch resolved.', 'success')
    else:
        flash('Failed to mark track or resolve mismatch. Check logs.', 'danger')
        
    return redirect(url_for('resolve.view_mismatches'))

@resolve_bp.route('/mismatch/ignore', methods=['POST'])
@login_required
def ignore_mismatch():
    log_identifier = request.form.get('log_identifier')

    if not log_identifier:
        flash('Missing data for ignoring mismatch.', 'danger')
        return redirect(url_for('resolve.view_mismatches'))

    # Extract track_id from log_identifier (format: "mismatch_{track_id}_{spotify_id}")
    try:
        parts = log_identifier.split('_')
        if len(parts) >= 2 and parts[0] == 'mismatch':
            track_id = int(parts[1])
            
            # Delete the SpotifyURI record with mismatch_accepted status
            spotify_uri = SpotifyURI.query.filter_by(
                track_id=track_id, 
                status='mismatch_accepted'
            ).first()
            
            if spotify_uri:
                db.session.delete(spotify_uri)
                db.session.commit()
                flash('Mismatch ignored and removed from database.', 'success')
            else:
                flash('Mismatch record not found in database.', 'warning')
        else:
            flash('Invalid log identifier format.', 'danger')
    except (ValueError, IndexError):
        flash('Invalid log identifier format.', 'danger')
        
    return redirect(url_for('resolve.view_mismatches'))

# POST routes for Not-Found Tracks

@resolve_bp.route('/not_found/manual_link', methods=['POST'])
@login_required
def manual_link_not_found():
    log_identifier = request.form.get('log_identifier')
    local_track_id = request.form.get('local_track_id')
    manual_spotify_uri_input = request.form.get('manual_spotify_uri')

    if not all([log_identifier, local_track_id, manual_spotify_uri_input]):
        flash('Missing data for manual linking a not-found track.', 'danger')
        return redirect(url_for('resolve.view_not_found'))

    spotify_uri = _extract_spotify_uri(manual_spotify_uri_input)
    if not spotify_uri:
        flash('Invalid Spotify URI or URL format provided.', 'danger')
        return redirect(url_for('resolve.view_not_found'))

    success = resolve_link_track_to_spotify_uri(
        local_track_id=int(local_track_id),
        spotify_uri=spotify_uri,
        status='manual_match' # User manually provided this link
    )

    if success:
        flash('Track successfully linked manually and "not found" entry resolved.', 'success')
    else:
        flash('Failed to manually link track or resolve "not found" entry. Check logs.', 'danger')
    
    return redirect(url_for('resolve.view_not_found'))

@resolve_bp.route('/not_found_in_spotify_export')
@login_required
def view_not_found_in_spotify_export():
    """Displays tracks that were marked as 'not_found_in_spotify' during a playlist export."""
    tracks_not_found_on_export = db.session.query(Track)\
        .join(SpotifyURI, Track.id == SpotifyURI.track_id)\
        .filter(SpotifyURI.status == 'not_found_in_spotify')\
        .order_by(Track.artist, Track.song)\
        .all()
    
    return render_template(
        'resolve/resolve_not_found_export.html', 
        tracks=tracks_not_found_on_export, 
        title="Tracks Not Found During Spotify Export"
    )

# POST routes for Unmatched Tracks

@resolve_bp.route('/unmatched/link_existing', methods=['POST'])
@login_required
def link_unmatched_to_existing():
    unmatched_track_id_str = request.form.get('unmatched_track_id')
    existing_track_id_str = request.form.get('existing_track_id')
    spotify_uri_id_of_unmatched = request.form.get('spotify_uri_id_of_unmatched') # This is the ID of the SpotifyURI record

    if not unmatched_track_id_str or not existing_track_id_str: # Check if form fields are present
        flash('Missing data for linking unmatched track (track IDs not received).', 'danger')
        return redirect(url_for('resolve.view_unmatched_tracks'))

    try:
        unmatched_track_id = int(unmatched_track_id_str)
        existing_track_id = int(existing_track_id_str) # Convert checked string
        if spotify_uri_id_of_unmatched:
            spotify_uri_id_of_unmatched = int(spotify_uri_id_of_unmatched)
    except ValueError:
        flash('Invalid track ID format.', 'danger')
        return redirect(url_for('resolve.view_unmatched_tracks'))

    # Service function to handle the logic (to be created in resolution_service.py)
    # success = resolve_link_unmatched_to_existing_track(unmatched_track_id, existing_track_id, spotify_uri_id_of_unmatched)
    
    # --- Direct implementation for now, can be moved to service ---
    # Use modern db.session.get()
    unmatched_track = db.session.get(Track, unmatched_track_id)
    existing_track = db.session.get(Track, existing_track_id)
    spotify_uri_record = None
    # Fetch the SpotifyURI record *before* potential deletion of unmatched_track
    if spotify_uri_id_of_unmatched:
        spotify_uri_record = db.session.get(SpotifyURI, spotify_uri_id_of_unmatched) # Use modern get

    if not unmatched_track or not existing_track:
        flash('Unmatched or existing track not found.', 'danger')
        return redirect(url_for('resolve.view_unmatched_tracks'))

    # DEBUG: Log fetched existing track ID
    current_app.logger.info(f"Fetched existing_track with ID: {existing_track.id if existing_track else 'Not Found'}")
    current_app.logger.info(f"Value of existing_track_id variable before try block: {existing_track_id} (type: {type(existing_track_id)})")


    if unmatched_track.category != 'Unmatched':
        flash('Source track is not categorized as Unmatched.', 'danger')
        return redirect(url_for('resolve.view_unmatched_tracks'))

    try:
        original_uri_string = None
        # Check if the existing SpotifyURI record needs handling
        if spotify_uri_record and spotify_uri_record.track_id == unmatched_track_id:
            original_uri_string = spotify_uri_record.uri # Store the URI
            current_app.logger.info(f"Preparing to delete original SpotifyURI ID {spotify_uri_record.id} linked to unmatched track {unmatched_track_id}")
            db.session.delete(spotify_uri_record) # Delete the old record

        # Delete the original 'Unmatched' track record
        current_app.logger.info(f"Deleting unmatched Track ID {unmatched_track.id}")
        db.session.delete(unmatched_track)
        
        # If we had an original URI, create a new one linked to the existing track
        if original_uri_string:
            current_app.logger.info(f"Creating new SpotifyURI linking URI {original_uri_string} to existing Track ID {existing_track_id}")
            new_uri = SpotifyURI(
                track_id=existing_track_id, # Use the integer ID directly
                uri=original_uri_string,
                status='manual_match' # Or 'matched'
            )
            db.session.add(new_uri)
        else:
             current_app.logger.warning(f"No original SpotifyURI found or it wasn't linked to the unmatched track {unmatched_track_id}. Cannot create new link automatically.")
             # Optionally, flash a different message here? Or rely on the main success/fail flash.

        db.session.commit()
        flash(f'Successfully linked unmatched track "{unmatched_track.song}" to "{existing_track.song}". The original unmatched record has been deleted.', 'success')
        success = True
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error linking unmatched track: {e}")
        flash(f'Error linking unmatched track: {e}', 'danger')
        success = False
    # --- End direct implementation ---

    return redirect(url_for('resolve.view_unmatched_tracks'))

@resolve_bp.route('/unmatched/confirm_new', methods=['POST'])
@login_required
def confirm_unmatched_as_new():
    unmatched_track_id = request.form.get('unmatched_track_id')
    # Automatically set new tracks to 'Latest' category
    new_category = 'Latest'
    spotify_uri_id = request.form.get('spotify_uri_id')


    if not unmatched_track_id:
        flash('Missing unmatched track ID.', 'danger')
        return redirect(url_for('resolve.view_unmatched_tracks'))
    
    # No need to check if new_category is empty since we're setting it to 'Latest'

    try:
        unmatched_track_id = int(unmatched_track_id)
    except ValueError:
        flash('Invalid track ID format.', 'danger')
        return redirect(url_for('resolve.view_unmatched_tracks'))

    # --- Direct implementation for now, can be moved to service ---
    track_to_update = db.session.get(Track, unmatched_track_id) # Use modern get
    if not track_to_update:
        flash('Track not found.', 'danger')
        return redirect(url_for('resolve.view_unmatched_tracks'))

    if track_to_update.category != 'Unmatched':
        flash('Track is not categorized as "Unmatched".', 'warning')
        # Optionally, still allow category update if desired, or redirect
        # return redirect(url_for('resolve.view_unmatched_tracks'))

    try:
        track_to_update.category = new_category
        db.session.add(track_to_update)

        # Update associated SpotifyURI status if it exists
        if spotify_uri_id:
            try:
                s_uri_id = int(spotify_uri_id)
                spotify_uri_record = db.session.get(SpotifyURI, s_uri_id) # Use modern get
                if spotify_uri_record and spotify_uri_record.track_id == track_to_update.id:
                    spotify_uri_record.status = 'matched' # Or a new status like 'confirmed_new_track_match'
                    db.session.add(spotify_uri_record)
            except ValueError:
                current_app.logger.warning(f"Invalid spotify_uri_id format: {spotify_uri_id} for track {unmatched_track_id}")
            except Exception as e_spotify_uri:
                 current_app.logger.error(f"Error updating SpotifyURI for confirmed new track {unmatched_track_id}: {e_spotify_uri}")


        db.session.commit()
        flash(f'Track "{track_to_update.song}" confirmed as new and category updated to "{new_category}".', 'success')
        success = True
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error confirming unmatched track as new: {e}")
        flash(f'Error confirming track as new: {e}', 'danger')
        success = False
    # --- End direct implementation ---
    
    return redirect(url_for('resolve.view_unmatched_tracks'))

@resolve_bp.route('/unmatched/ignore', methods=['POST'])
@login_required
def ignore_unmatched_track():
    unmatched_track_id = request.form.get('unmatched_track_id')

    if not unmatched_track_id:
        flash('Missing unmatched track ID for ignoring.', 'danger')
        return redirect(url_for('resolve.view_unmatched_tracks'))
    
    try:
        unmatched_track_id = int(unmatched_track_id)
    except ValueError:
        flash('Invalid track ID format.', 'danger')
        return redirect(url_for('resolve.view_unmatched_tracks'))

    # --- Direct implementation for now, can be moved to service ---
    # For "ignore", we could:
    # 1. Delete the 'Unmatched' track. (Simplest, but it might be recreated)
    # 2. Change its category to something like 'IgnoredUnmatched'. (Allows review later)
    # 3. Add it to a separate log/table of ignored items.
    # Option 2 seems like a reasonable balance.
    
    track_to_ignore = db.session.get(Track, unmatched_track_id) # Use modern get
    if not track_to_ignore:
        flash('Track to ignore not found.', 'danger')
        return redirect(url_for('resolve.view_unmatched_tracks'))

    if track_to_ignore.category != 'Unmatched':
        flash('Track is not categorized as "Unmatched", cannot ignore in this context.', 'warning')
        return redirect(url_for('resolve.view_unmatched_tracks'))

    try:
        # Option 2: Change category
        track_to_ignore.category = 'IgnoredUnmatched' 
        # Optionally, also update SpotifyURI status if relevant
        # spotify_uri_record = SpotifyURI.query.filter_by(track_id=track_to_ignore.id, status='unmatched').first()
        # if spotify_uri_record:
        #     spotify_uri_record.status = 'ignored_unmatched_link'
        #     db.session.add(spotify_uri_record)

        db.session.add(track_to_ignore)
        db.session.commit()
        flash(f'Track "{track_to_ignore.song}" marked as "IgnoredUnmatched". It will no longer appear in this list unless its category is changed back.', 'info')
        success = True
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error ignoring unmatched track: {e}")
        flash(f'Error ignoring track: {e}', 'danger')
        success = False
    # --- End direct implementation ---

    return redirect(url_for('resolve.view_unmatched_tracks'))

@resolve_bp.route('/not_found/confirm_no_match', methods=['POST'])
@login_required
def confirm_track_not_on_spotify():
    log_identifier = request.form.get('log_identifier')
    local_track_id = request.form.get('local_track_id')

    if not all([log_identifier, local_track_id]):
        flash('Missing data for confirming track not on Spotify.', 'danger')
        return redirect(url_for('resolve.view_not_found'))

    success = resolve_update_track_status(
        local_track_id=int(local_track_id),
        new_status_or_flag='confirmed_no_spotify'
    )

    if success:
        flash('Track confirmed as not on Spotify and "not found" entry resolved.', 'success')
    else:
        flash('Failed to confirm track status or resolve "not found" entry. Check logs.', 'danger')
        
    return redirect(url_for('resolve.view_not_found'))

@resolve_bp.route('/not_found/ignore', methods=['POST'])
@login_required
def ignore_not_found():
    log_identifier = request.form.get('log_identifier')

    if not log_identifier:
        flash('Missing data for ignoring "not found" entry.', 'danger')
        return redirect(url_for('resolve.view_not_found'))

    # Extract track_id from log_identifier (format: "notfound_{track_id}")
    try:
        parts = log_identifier.split('_')
        if len(parts) >= 2 and parts[0] == 'notfound':
            track_id = int(parts[1])
            
            # Delete the SpotifyURI record with not_found_in_spotify status
            spotify_uri = SpotifyURI.query.filter_by(
                track_id=track_id, 
                status='not_found_in_spotify'
            ).first()
            
            if spotify_uri:
                db.session.delete(spotify_uri)
                db.session.commit()
                flash('"Not found" entry ignored and removed from database.', 'success')
            else:
                flash('"Not found" record not found in database.', 'warning')
        else:
            flash('Invalid log identifier format.', 'danger')
    except (ValueError, IndexError):
        flash('Invalid log identifier format.', 'danger')
        
    return redirect(url_for('resolve.view_not_found'))

@resolve_bp.route('/cleanup_duplicates', methods=['POST'])
@login_required
def cleanup_duplicates():
    track_id = request.form.get('track_id')
    
    if not track_id:
        flash('Missing track ID for cleanup.', 'danger')
        return redirect(url_for('resolve.view_mismatches'))
    
    try:
        track_id = int(track_id)
        
        # Check if track has a good match (matched or manual_match)
        good_match = SpotifyURI.query.filter_by(
            track_id=track_id
        ).filter(
            SpotifyURI.status.in_(['matched', 'manual_match'])
        ).first()
        
        if not good_match:
            flash('No good match found for this track. Cannot clean up duplicates.', 'warning')
            return redirect(url_for('resolve.view_mismatches'))
        
        # Delete all mismatch_accepted records for this track
        duplicate_count = SpotifyURI.query.filter_by(
            track_id=track_id,
            status='mismatch_accepted'
        ).count()
        
        SpotifyURI.query.filter_by(
            track_id=track_id,
            status='mismatch_accepted'
        ).delete()
        
        db.session.commit()
        
        flash(f'Successfully removed {duplicate_count} duplicate mismatch records. The good match was preserved.', 'success')
        
    except (ValueError, Exception) as e:
        db.session.rollback()
        flash(f'Error cleaning up duplicates: {e}', 'danger')
    
    return redirect(url_for('resolve.view_mismatches'))

@resolve_bp.route('/fix_not_found_anomaly', methods=['POST'])
@login_required
def fix_not_found_anomaly():
    """Fix anomaly where a track has both 'not_found_in_spotify' and valid Spotify URI records."""
    log_identifier = request.form.get('log_identifier')
    local_track_id = request.form.get('local_track_id')
    valid_spotify_uri = request.form.get('valid_spotify_uri')

    if not all([log_identifier, local_track_id, valid_spotify_uri]):
        flash('Missing data for fixing anomaly.', 'danger')
        return redirect(url_for('resolve.view_not_found'))

    try:
        track_id = int(local_track_id)
        
        # Get all SpotifyURI records for this track
        all_uris = SpotifyURI.query.filter_by(track_id=track_id).all()
        
        current_app.logger.info(f"Fixing anomaly for track {track_id}. Found {len(all_uris)} SpotifyURI records.")
        
        # Find and delete the 'not_found_in_spotify' record(s)
        not_found_records = [uri for uri in all_uris if uri.status == 'not_found_in_spotify']
        
        for record in not_found_records:
            current_app.logger.info(f"Deleting not_found_in_spotify record ID {record.id} with URI: {record.uri}")
            db.session.delete(record)
        
        # Ensure the valid URI has the correct status
        valid_record = SpotifyURI.query.filter_by(track_id=track_id, uri=valid_spotify_uri).first()
        if valid_record:
            if valid_record.status not in ['matched', 'manual_match']:
                valid_record.status = 'matched'
                current_app.logger.info(f"Updated valid record ID {valid_record.id} status to 'matched'")
        
        db.session.commit()
        
        flash(f'Anomaly fixed! Removed {len(not_found_records)} duplicate "not found" record(s) and kept the valid Spotify URI.', 'success')
        
    except (ValueError, Exception) as e:
        db.session.rollback()
        current_app.logger.error(f"Error fixing not found anomaly: {e}")
        flash(f'Error fixing anomaly: {e}', 'danger')
    
    return redirect(url_for('resolve.view_not_found'))
