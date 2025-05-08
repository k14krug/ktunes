from flask import render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
from . import resolve_bp
from models import Track, SpotifyURI, PlayedTrack # Will be needed for POST actions
from extensions import db
from services.resolution_service import (
    load_mismatches, load_not_found,
    resolve_link_track_to_spotify_uri, 
    resolve_update_track_status,
    resolve_remove_from_log
)
from services.spotify_service import normalize_text # For similarity matching
from sqlalchemy import or_
from thefuzz import fuzz # For similarity scores

# MISMATCH_FILE and NOT_FOUND_FILE are used as defaults in resolution_service
import json
import os

@resolve_bp.route('/mismatches')
@login_required
def view_mismatches():
    mismatches = load_mismatches() # Uses default filename from resolution_service
    # Enrich mismatches with track details if local_track_id is present
    for item in mismatches:
        if 'local_track_id' in item:
            track = Track.query.get(item['local_track_id'])
            item['local_track_details'] = track # Store the whole track object
    return render_template('resolve_mismatches.html', mismatches=mismatches, title="Resolve Mismatches")

@resolve_bp.route('/not_found')
@login_required
def view_not_found():
    not_found_tracks = load_not_found() # Uses default filename from resolution_service
    # Enrich not_found_tracks with track details
    for item in not_found_tracks:
        if 'local_track_id' in item:
            track = Track.query.get(item['local_track_id'])
            item['local_track_details'] = track
    return render_template('resolve_not_found.html', not_found_tracks=not_found_tracks, title="Resolve Not Found Tracks")

@resolve_bp.route('/unmatched_tracks')
@login_required
def view_unmatched_tracks():
    unmatched_tracks_query = Track.query.filter(Track.category == 'Unmatched') \
                                     .outerjoin(SpotifyURI, Track.id == SpotifyURI.track_id) \
                                     .add_columns(Track.id.label("track_id"), Track.song, Track.artist, Track.album, SpotifyURI.uri.label("spotify_track_uri"), SpotifyURI.id.label("spotify_uri_id")) \
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

        normalized_unmatched_song = normalize_text(unmatched.song) if unmatched.song else ""
        normalized_unmatched_artist = normalize_text(unmatched.artist) if unmatched.artist else ""
        
        potential_matches = []
        for lib_track in potential_library_tracks:
            if lib_track.id == unmatched.track_id: # Don't compare with itself
                continue

            normalized_lib_song = normalize_text(lib_track.song) if lib_track.song else ""
            normalized_lib_artist = normalize_text(lib_track.artist) if lib_track.artist else ""

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
                        # Delete the redundant 'Unmatched' Track record
                        db.session.delete(unmatched_track_obj)
                        # Delete the associated 'unmatched' SpotifyURI record if it exists
                        if spotify_uri_obj and spotify_uri_obj.track_id == unmatched.track_id:
                             current_app.logger.info(f"Deleting associated SpotifyURI ID {spotify_uri_obj.id}")
                             db.session.delete(spotify_uri_obj)
                        db.session.commit()
                        auto_resolved = True
                        auto_resolved_count += 1
                        break # Exit inner loop once auto-resolved
                    except Exception as e:
                        db.session.rollback()
                        current_app.logger.error(f"Error auto-resolving unmatched track ID {unmatched.track_id}: {e}")
                        # Proceed with manual display if auto-resolve fails
            # --- End Auto-resolution Check ---

            # If not auto-resolved, check threshold for adding to potential matches for manual review
            if not auto_resolved and overall_similarity > 60:
                 # Fetch the matched Spotify URI for display if we didn't already fetch it for auto-resolution
                if 'library_match_uri' not in locals(): # Avoid fetching twice if similarity wasn't 100
                    matched_uri_record = SpotifyURI.query.filter_by(
                        track_id=lib_track.id,
                        status='matched'
                    ).first()
                    library_match_uri = matched_uri_record.uri if matched_uri_record else None

                potential_matches.append({
                    'track': lib_track,
                    'matched_uri': library_match_uri, # Add the URI here
                    'song_similarity': song_similarity,
                    'artist_similarity': artist_similarity,
                    'overall_similarity': round(overall_similarity, 2)
                })
            # Clear library_match_uri for next iteration if it was defined
            if 'library_match_uri' in locals():
                del library_match_uri

        # If the track was auto-resolved in the inner loop, skip adding it for manual display
        if auto_resolved:
            continue

        # Sort potential matches by overall similarity, descending
        potential_matches.sort(key=lambda x: x['overall_similarity'], reverse=True)
        
        tracks_to_display.append({
            'id': unmatched.track_id,
            'song': unmatched.song,
            'artist': unmatched.artist,
            'album': unmatched.album,
            'spotify_track_uri': unmatched.spotify_track_uri,
            'spotify_uri_id': unmatched.spotify_uri_id, # ID of the SpotifyURI record associated with this unmatched track
            'potential_matches': potential_matches[:5] # Top 5 matches
        })

    current_app.logger.info(f"Processed {processed_count} unmatched tracks. Auto-resolved: {auto_resolved_count}. Displaying: {len(tracks_to_display)}")
    if auto_resolved_count > 0:
        flash(f"Automatically resolved {auto_resolved_count} clear duplicate unmatched track(s).", "info")
        
    return render_template('resolve_unmatched.html', unmatched_tracks=tracks_to_display, title="Resolve Unmatched Tracks")


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
        status='matched', # Confirming the found Spotify track is correct
        log_identifier=log_identifier,
        log_filename='mismatch.json' # Explicitly pass filename
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

@resolve_bp.route('/mismatch/manual_link', methods=['POST'])
@login_required
def manual_link_mismatch():
    log_identifier = request.form.get('log_identifier')
    local_track_id = request.form.get('local_track_id')
    manual_spotify_uri_input = request.form.get('manual_spotify_uri')

    if not all([log_identifier, local_track_id, manual_spotify_uri_input]):
        flash('Missing data for manual linking.', 'danger')
        return redirect(url_for('resolve.view_mismatches'))

    spotify_uri = _extract_spotify_uri(manual_spotify_uri_input)
    if not spotify_uri:
        flash('Invalid Spotify URI or URL format provided.', 'danger')
        return redirect(url_for('resolve.view_mismatches'))

    success = resolve_link_track_to_spotify_uri(
        local_track_id=int(local_track_id),
        spotify_uri=spotify_uri,
        status='manual_match', # User manually provided this link
        log_identifier=log_identifier,
        log_filename='mismatch.json'
    )

    if success:
        flash('Track successfully linked manually and mismatch resolved.', 'success')
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
        new_status_or_flag='confirmed_no_spotify',
        log_identifier=log_identifier,
        log_filename='mismatch.json'
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

    success = resolve_remove_from_log(
        log_identifier=log_identifier,
        filename='mismatch.json'
    )

    if success:
        flash('Mismatch ignored and removed from log.', 'success')
    else:
        flash('Failed to ignore mismatch. Check logs or if the item was already removed.', 'danger')
        
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
    new_category = request.form.get('new_category', 'Uncategorized').strip()
    spotify_uri_id = request.form.get('spotify_uri_id')


    if not unmatched_track_id:
        flash('Missing unmatched track ID.', 'danger')
        return redirect(url_for('resolve.view_unmatched_tracks'))
    
    if not new_category: # Ensure new_category is not empty after stripping
        new_category = 'Uncategorized'

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

    spotify_uri = _extract_spotify_uri(manual_spotify_uri_input)
    if not spotify_uri:
        flash('Invalid Spotify URI or URL format provided.', 'danger')
        return redirect(url_for('resolve.view_not_found'))

    success = resolve_link_track_to_spotify_uri(
        local_track_id=int(local_track_id),
        spotify_uri=spotify_uri,
        status='manual_match', # User manually provided this link
        log_identifier=log_identifier,
        log_filename='not_in_spotify.json'
    )

    if success:
        flash('Track successfully linked manually and "not found" entry resolved.', 'success')
    else:
        flash('Failed to manually link track or resolve "not found" entry. Check logs.', 'danger')
    
    return redirect(url_for('resolve.view_not_found'))

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
        new_status_or_flag='confirmed_no_spotify',
        log_identifier=log_identifier,
        log_filename='not_in_spotify.json'
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

    success = resolve_remove_from_log(
        log_identifier=log_identifier,
        filename='not_in_spotify.json'
    )

    if success:
        flash('"Not found" entry ignored and removed from log.', 'success')
    else:
        flash('Failed to ignore "not found" entry. Check logs or if the item was already removed.', 'danger')
        
    return redirect(url_for('resolve.view_not_found'))
