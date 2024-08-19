# itunes_xml_parser.py
from libpytunes import Library
from datetime import datetime, timezone
from models import db, Track
import logging
#import pytz
import time

class ITunesXMLParser:
    def __init__(self, xml_path):
        self.xml_path = xml_path
        self.library = Library(xml_path)
        self.updated_tracks_count = 0
        self.inserted_tracks_count = 0
        self.genre_category_map = {
            "Latest*": "Latest",
            "In rot*": "In Rot",
            "Other than New*": "Other",
            "Old*": "Old",
            "Album*": "Album",
            "Delete*": "Delete"
        }

    def update_database(self):
        try:
            for song in self.library.songs.values():
                category = self._convert_genre_to_category(song.genre)
                if category:
                    track = Track.query.filter_by(song=song.name, artist=song.artist).first()
                    if track:
                        self._update_track(track, song, category)
                    else:
                        logging.info(f"Adding new track: {song.name} by {song.artist} song {song}")
                        self._add_new_track(song, category)
            
            logging.info(f"Tracks updated: {self.updated_tracks_count}")
            logging.info(f"Tracks inserted: {self.inserted_tracks_count}")

            db.session.commit()
        except Exception as e:
            logging.error(f"Error in update_database: {str(e)}")
            db.session.rollback()
        
        return self.updated_tracks_count, self.inserted_tracks_count

    def _convert_genre_to_category(self, genre):
        if genre is None:
            return None
        genre_lower = genre.lower()
        for pattern, category in self.genre_category_map.items():
            if self._match_wildcard(genre_lower, pattern.lower()):
                return category
        return None

    def _match_wildcard(self, text, pattern):
        if text is None:
            return False
        if pattern.endswith('*'):
            return text.startswith(pattern[:-1])
        return text == pattern

    def _update_track(self, track, song, category):
        track.location = song.location
        track.category = category
        
        track.last_play_dt = self._parse_date(song.lastplayed)
        track.date_added = self._parse_date(song.date_added)

        track.play_cnt = song.play_count
        #track.length = song.length

        self.updated_tracks_count += 1

    def _add_new_track(self, song, category):
        last_play_dt = self._parse_date(song.lastplayed)
        date_added = self._parse_date(song.date_added)

        new_track = Track(
            song=song.name,
            artist=song.artist,
            album=song.album,
            location=song.location,
            category=category,
            last_play_dt=last_play_dt,
            date_added=date_added,
            play_cnt=song.play_count,
            artist_common_name=song.artist
            #length=song.length
        )
        db.session.add(new_track)

        self.inserted_tracks_count += 1

    def _parse_date(self, date_value):
        if date_value is None:
            return None

        if isinstance(date_value, time.struct_time):
            return datetime.fromtimestamp(time.mktime(date_value), timezone.utc)
        elif isinstance(date_value, str):
            try:
                # Parse the ISO 8601 format
                return datetime.strptime(date_value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                try:
                    # Fallback to parsing without 'Z'
                    return datetime.strptime(date_value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    logging.error(f"Unable to parse date string: {date_value}")
                    return None
        elif isinstance(date_value, datetime):
            return date_value.replace(tzinfo=timezone.utc)
        else:
            logging.error(f"Unexpected date type: {type(date_value)}")
            return None