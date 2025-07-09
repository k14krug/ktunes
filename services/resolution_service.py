from app import db # Assuming db instance is available from app
from models import Track, SpotifyURI # Import models

# Legacy JSON file paths - no longer used, kept for reference
MISMATCH_FILE = 'mismatch.json'
NOT_FOUND_FILE = 'not_in_spotify.json'

def resolve_link_track_to_spotify_uri(local_track_id, spotify_uri, status='matched'):
    """
    Creates/updates SpotifyURI record in the database.
    No longer removes entries from JSON log files as we now use database-only workflow.
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
        return True # DB updated successfully
    except Exception as e:
        db.session.rollback()
        # Log error e
        return False

def resolve_update_track_status(local_track_id, new_status_or_flag):
    """
    Update track status in the database.
    No longer removes entries from JSON log files as we now use database-only workflow.
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
        return True # DB updated successfully
    except Exception as e:
        db.session.rollback()
        # Log error e
        return False


