import json
import os
from app import db # Assuming db instance is available from app
from models import Track, SpotifyURI # Import models

# Define paths to log files - consider making these configurable
MISMATCH_FILE = 'mismatch.json'
NOT_FOUND_FILE = 'not_in_spotify.json'

def load_mismatches(filename=MISMATCH_FILE):
    """
    Reads, parses, and perhaps assigns unique identifiers to mismatch.json entries.
    """
    # To be implemented
    if not os.path.exists(filename):
        return []
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        # Assign unique IDs based on content for more robust identification
        for entry in data:
            # Ensure keys exist, provide default if not for robustness, though they should exist
            local_track_id = entry.get('local_track_id', 'unknown')
            spotify_track_uri = entry.get('spotify_track_uri', 'unknown') # URI of the track Spotify *found*
            entry['log_identifier'] = f"mismatch_{local_track_id}_{spotify_track_uri}"
        return data
    except (json.JSONDecodeError, FileNotFoundError):
        return [] # Or handle error appropriately

def load_not_found(filename=NOT_FOUND_FILE):
    """
    Similar to load_mismatches for not_in_spotify.json.
    """
    # To be implemented
    if not os.path.exists(filename):
        return []
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        # Assign unique IDs based on content
        for entry in data:
            local_track_id = entry.get('local_track_id', 'unknown')
            entry['log_identifier'] = f"notfound_{local_track_id}"
        return data
    except (json.JSONDecodeError, FileNotFoundError):
        return [] # Or handle error appropriately

def resolve_link_track_to_spotify_uri(local_track_id, spotify_uri, status='matched', log_identifier=None, log_filename=None):
    """
    Creates/updates SpotifyURI. Removes entry from the relevant log file.
    """
    track = Track.query.get(local_track_id)
    if not track:
        return False # Track not found

    # Check if a SpotifyURI already exists for this track and specific URI
    existing_uri_for_track = SpotifyURI.query.filter_by(track_id=local_track_id, uri=spotify_uri).first()

    if existing_uri_for_track:
        existing_uri_for_track.status = status
    else:
        # If we are linking to a new URI, we might want to ensure other URIs for the same track are handled.
        # For now, let's assume we are adding/updating one specific link.
        # Potentially, mark other 'mismatched' or 'unmatched' URIs for this track as 'obsolete' or delete them.
        # This simplification assumes one primary Spotify link per track for 'matched' or 'manual_match'.
        
        # Remove any existing 'unmatched' or 'confirmed_no_spotify' for this track_id before adding a new definitive match.
        SpotifyURI.query.filter_by(track_id=local_track_id, status='unmatched').delete()
        SpotifyURI.query.filter_by(track_id=local_track_id, status='confirmed_no_spotify').delete()

        # If a different URI was previously 'matched' or 'manual_match', this new one might supersede it.
        # For simplicity, we'll add the new one. Complex de-duplication/superseding logic can be added later.
        new_uri = SpotifyURI(track_id=local_track_id, uri=spotify_uri, status=status)
        db.session.add(new_uri)
    
    try:
        db.session.commit()
        if log_identifier and log_filename:
            return resolve_remove_from_log(log_identifier, log_filename)
        return True # DB updated, but no log removal requested or needed
    except Exception as e:
        db.session.rollback()
        # Log error e
        return False

def resolve_update_track_status(local_track_id, new_status_or_flag, log_identifier=None, log_filename=None):
    """
    e.g., to mark as 'confirmed_not_on_spotify'.
    Removes entry from the relevant log file.
    """
    track = Track.query.get(local_track_id)
    if not track:
        return False # Track not found

    # This status update primarily applies to the Spotify linkage.
    # If 'confirmed_no_spotify', we ensure any existing SpotifyURI reflects this.
    # If other statuses, it implies an update to an existing link.

    existing_spotify_link = SpotifyURI.query.filter_by(track_id=local_track_id).first()

    if new_status_or_flag == 'confirmed_no_spotify':
        # Remove any existing links for this track as they are now superseded by 'confirmed_no_spotify'
        SpotifyURI.query.filter_by(track_id=local_track_id).delete()
        # Add a new record indicating this confirmation
        # Using a placeholder URI for 'confirmed_no_spotify'
        placeholder_uri = f"spotify:track:confirmed_no_spotify_{local_track_id}"
        new_uri_record = SpotifyURI(track_id=local_track_id, uri=placeholder_uri, status='confirmed_no_spotify')
        db.session.add(new_uri_record)
    elif existing_spotify_link:
        # For other status updates, update the existing link
        # This assumes there's one primary link we're updating.
        # If multiple URIs are linked to a track, logic might need to be more specific.
        existing_spotify_link.status = new_status_or_flag
        # Potentially update URI if new_status_or_flag implies a new URI was found,
        # but this function is more about status of an existing/implicit link.
        # resolve_link_track_to_spotify_uri is for changing the URI itself.
    else:
        # If no existing link, and status is not 'confirmed_no_spotify',
        # it's ambiguous what to do. This function is best for tracks with some prior Spotify context
        # or for explicitly marking as 'confirmed_no_spotify'.
        # For now, if no link and not 'confirmed_no_spotify', we don't create a new one here.
        # This case should ideally be handled by resolve_link_track_to_spotify_uri if a URI is involved.
        if new_status_or_flag != 'unmatched': # 'unmatched' implies a URI should be present
             return False # Cannot update status if no link and not confirming no spotify

        # If status is 'unmatched', it implies a URI should exist or be created.
        # This function might not be the right place if URI is also changing.
        # Let's assume 'unmatched' is set by other processes that also set a URI.

    try:
        db.session.commit()
        if log_identifier and log_filename:
            return resolve_remove_from_log(log_identifier, log_filename)
        return True # DB updated, but no log removal requested
    except Exception as e:
        db.session.rollback()
        # Log error e
        return False

def resolve_remove_from_log(log_identifier, filename):
    """
    A generic function to remove an entry from a JSON log file based on a unique identifier.
    This needs a robust way to identify and remove entries.
    If log_identifier is based on index, care must be taken if list is modified.
    A better way might be to match based on content if identifiers are not stable.
    The log_identifier is expected to be generated by load_mismatches or load_not_found.
    """
    if not os.path.exists(filename):
        return False # File doesn't exist

    try:
        with open(filename, 'r') as f:
            entries = json.load(f)
    except json.JSONDecodeError:
        return False # File is not valid JSON

    original_length = len(entries)
    updated_entries = []
    item_removed = False

    for entry in entries:
        # Reconstruct the identifier for the current entry to compare
        current_entry_identifier = ""
        local_track_id = entry.get('local_track_id', 'unknown')
        if filename == MISMATCH_FILE:
            spotify_track_uri = entry.get('spotify_track_uri', 'unknown')
            current_entry_identifier = f"mismatch_{local_track_id}_{spotify_track_uri}"
        elif filename == NOT_FOUND_FILE:
            current_entry_identifier = f"notfound_{local_track_id}"
        
        if current_entry_identifier == log_identifier:
            item_removed = True
            # Skip this entry, effectively removing it
        else:
            updated_entries.append(entry)

    if item_removed and len(updated_entries) < original_length:
        try:
            with open(filename, 'w') as f:
                json.dump(updated_entries, f, indent=4)
            return True
        except IOError:
            # Handle file writing error
            return False
    elif item_removed and len(updated_entries) == original_length:
        # This case should ideally not happen if item_removed is true
        # but indicates a logic flaw or duplicate identifiers if it does.
        return False 
    
    return False # Item not found or not removed
