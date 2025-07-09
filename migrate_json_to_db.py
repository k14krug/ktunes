#!/usr/bin/env python3
"""
Migration script to move data from legacy JSON files to the database.
This script reads mismatch.json and not_in_spotify.json and creates corresponding 
SpotifyURI records in the database.
"""

import json
import sys
import os
from datetime import datetime

# Add the current directory to the Python path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from extensions import db
from models import SpotifyURI, Track

def convert_spotify_url_to_uri(spotify_url):
    """Convert Spotify URL to URI format."""
    if "open.spotify.com/track/" in spotify_url:
        track_id = spotify_url.split("/track/")[-1].split("?")[0]
        return f"spotify:track:{track_id}"
    return spotify_url

def migrate_mismatches():
    """Migrate mismatch.json data to SpotifyURI table."""
    mismatch_file = 'mismatch.json'
    if not os.path.exists(mismatch_file):
        print(f"No {mismatch_file} found, skipping mismatch migration.")
        return 0, 0
    
    with open(mismatch_file, 'r') as f:
        mismatches = json.load(f)
    
    created_count = 0
    skipped_count = 0
    
    for mismatch in mismatches:
        track_id = mismatch.get('track_id')
        spotify_url = mismatch.get('spotify_url')
        
        if not track_id or not spotify_url:
            print(f"Skipping incomplete mismatch entry: {mismatch}")
            skipped_count += 1
            continue
        
        # Check if track exists
        track = Track.query.get(track_id)
        if not track:
            print(f"Track with ID {track_id} not found, skipping.")
            skipped_count += 1
            continue
        
        # Convert URL to URI
        spotify_uri = convert_spotify_url_to_uri(spotify_url)
        
        # Check if SpotifyURI already exists
        existing = SpotifyURI.query.filter_by(track_id=track_id, uri=spotify_uri).first()
        if existing:
            print(f"SpotifyURI already exists for track {track_id} with URI {spotify_uri}, skipping.")
            skipped_count += 1
            continue
        
        # Create new SpotifyURI with mismatch_accepted status
        new_uri = SpotifyURI(
            track_id=track_id,
            uri=spotify_uri,
            status='mismatch_accepted'
        )
        
        db.session.add(new_uri)
        created_count += 1
        
        if created_count % 100 == 0:
            print(f"Processed {created_count} mismatches...")
    
    return created_count, skipped_count

def migrate_not_found():
    """Migrate not_in_spotify.json data to SpotifyURI table."""
    not_found_file = 'not_in_spotify.json'
    if not os.path.exists(not_found_file):
        print(f"No {not_found_file} found, skipping not-found migration.")
        return 0, 0
    
    with open(not_found_file, 'r') as f:
        not_found_tracks = json.load(f)
    
    created_count = 0
    skipped_count = 0
    
    for track_data in not_found_tracks:
        track_id = track_data.get('track_id')
        
        if not track_id:
            print(f"Skipping incomplete not-found entry: {track_data}")
            skipped_count += 1
            continue
        
        # Check if track exists
        track = Track.query.get(track_id)
        if not track:
            print(f"Track with ID {track_id} not found, skipping.")
            skipped_count += 1
            continue
        
        # Check if SpotifyURI already exists for this track
        existing = SpotifyURI.query.filter_by(track_id=track_id).first()
        if existing:
            print(f"SpotifyURI already exists for track {track_id}, skipping.")
            skipped_count += 1
            continue
        
        # Create new SpotifyURI with not_found_in_spotify status
        placeholder_uri = f"spotify:track:not_found_in_spotify_{track_id}"
        new_uri = SpotifyURI(
            track_id=track_id,
            uri=placeholder_uri,
            status='not_found_in_spotify'
        )
        
        db.session.add(new_uri)
        created_count += 1
        
        if created_count % 100 == 0:
            print(f"Processed {created_count} not-found tracks...")
    
    return created_count, skipped_count

def main():
    """Main migration function."""
    app = create_app()
    
    with app.app_context():
        print("Starting migration from JSON files to database...")
        
        # Migrate mismatches
        print("\n--- Migrating mismatch.json ---")
        mismatch_created, mismatch_skipped = migrate_mismatches()
        
        # Migrate not found tracks
        print("\n--- Migrating not_in_spotify.json ---")
        not_found_created, not_found_skipped = migrate_not_found()
        
        # Commit all changes
        try:
            db.session.commit()
            print(f"\n✅ Migration completed successfully!")
            print(f"   Created {mismatch_created} mismatch records")
            print(f"   Created {not_found_created} not-found records")
            print(f"   Skipped {mismatch_skipped + not_found_skipped} existing/invalid records")
            
            # Create backups of the JSON files
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if os.path.exists('mismatch.json'):
                backup_name = f"mismatch_{timestamp}.json.backup"
                os.rename('mismatch.json', backup_name)
                print(f"   Moved mismatch.json to {backup_name}")
            
            if os.path.exists('not_in_spotify.json'):
                backup_name = f"not_in_spotify_{timestamp}.json.backup"
                os.rename('not_in_spotify.json', backup_name)
                print(f"   Moved not_in_spotify.json to {backup_name}")
                
        except Exception as e:
            db.session.rollback()
            print(f"❌ Migration failed: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
