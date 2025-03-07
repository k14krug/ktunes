import json
from datetime import datetime
from collections import defaultdict
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from models import Track, PlayedTrack
from extensions import db
from datetime import datetime

# Connect to the SQLite database
engine = create_engine('sqlite:///instance/kTunes.sqlite')
Session = sessionmaker(bind=engine)
session = Session()

def check_played_tracks_against_tracks():
    """
    Go through the played_tracks table sequentially. For each track, try to find a match in the tracks table
    based on spotify_id matching the third piece of spotify_uri or matching on song and artist. On matches,
    check the played_at against the last_play_dt. If it's greater, print both dates. If a match is not found, report that.
    """
    played_tracks = session.query(PlayedTrack).order_by(PlayedTrack.played_at).all()
    
    for index, played_track in enumerate(played_tracks, start=1):
        output = f"# {index} "
        spotify_id = played_track.spotify_id
        if not spotify_id:
            output += " No spotify_id"
        else:
            # Find matching track in the tracks table by spotify_id
            matching_track = session.query(Track).filter(Track.spotify_uri.like(f"%:{spotify_id}")).first()
            if not matching_track:
                # If no match by spotify_id, try to find by song and artist
                matching_track = session.query(Track).filter_by(song=played_track.song, artist=played_track.artist).first()

            if matching_track:
                output += f" Played at: {played_track.played_at}, Last played at: {matching_track.last_play_dt}"
                if matching_track.last_play_dt is None or played_track.played_at > matching_track.last_play_dt:
                    output += "Update needed"
                else:
                    output += " No update needed"
            else:
                output += f" No match found in tracks table for spotify_id: {spotify_id}"  
        print(f"{output} Spotify_id {spotify_id}, Track: {played_track.song} by {played_track.artist}  ")
        

    
    # Update tracks for the "updates" list
#    print("\nUpdating tracks:")
#    for _, matching_track, played_track in sorted(updates, key=lambda x: x[0]):
#        matching_track.last_play_dt = played_track.played_at
#        matching_track.play_cnt = (matching_track.play_cnt or 0) + 1
#        session.commit()
#        print(f"Updated track: {matching_track.song} by {matching_track.artist} | New last_play_dt: {matching_track.last_play_dt}, New play_cnt: {matching_track.play_cnt}")

# Run the function
check_played_tracks_against_tracks()

# Close the session
#session.close()
