# itunes_service.py
from libpytunes import Library
from datetime import datetime, timezone
from models import db, Track
import logging
#import pytz
import time
import os

def update_database_from_xml_logic(config, db):
    """
    Update the database from the iTunes XML file specified in the config.

    :param config: The application configuration containing the iTunes directory and library file.
    :param db: The database instance to use for committing updates.
    :return: A tuple of (updates: int, inserts: int) indicating the number of rows updated and inserted.
    """
    print(f"Updating database from iTunes XML located at {config['itunes_dir']}, file name '{config['itunes_lib']}'")
    xml_path = os.path.join(config['itunes_dir'], config['itunes_lib'])
    inserts, updates = 0, 0

    if os.path.exists(xml_path):
        parser = ITunesXMLParser(xml_path)
        try:
            updates, inserts = parser.update_database()
            print(f"Database updated successfully: {updates} rows updated, {inserts} rows inserted.")
        except Exception as e:
            print(f"Error updating database from iTunes XML: {str(e)}")
            raise
    else:
        print(f"iTunes XML file not found at {xml_path}")

    return updates, inserts

class ITunesXMLParser:
    def __init__(self, xml_path):
        self.xml_path = xml_path
        self.library = Library(xml_path)
        self.processed_tracks_count = 0
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
            # Fetch all tracks from the database in a single query
            existing_tracks = { (track.song, track.artist): track for track in Track.query.all() }

            for song in self.library.songs.values():
                self.processed_tracks_count += 1  # Increment the total number of songs processed
                category = self._convert_genre_to_category(song.genre)
                if category:
                    self.processed_tracks_count += 1  # Increment the total number of songs processed
                    track_key = (song.name, song.artist)
                    if track_key in existing_tracks:
                        self._update_track(existing_tracks[track_key], song, category)
                    else:
                        logging.info(f"Adding new track: {song.name} by {song.artist} song {song}")
                        self._add_new_track(song, category)
            
            
            logging.info(f"Total Tracks processed: {self.processed_tracks_count}")  # Log the total number of songs processed
            logging.info(f"             Updated:    {self.updated_tracks_count}")
            logging.info(f"             Inserted:   {self.inserted_tracks_count}")

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
    '''
    def _update_track(self, track, song, category):
        updated = False
        changes = []
        if track.location != song.location:
            changes.append(f"location: {track.location} -> {song.location}")
            track.location = song.location
            updated = True
        if track.category != category:
            changes.append(f"category: {track.category} -> {category}")
            track.category = category
            updated = True
        if track.last_play_dt and self._parse_date(song.lastplayed):
            if track.last_play_dt.replace(tzinfo=None) < self._parse_date(song.lastplayed).replace(microsecond=0, tzinfo=None):
                changes.append(f"last_play_dt: {track.last_play_dt} -> {self._parse_date(song.lastplayed).replace(microsecond=0)}")
                track.last_play_dt = self._parse_date(song.lastplayed).replace(microsecond=0)
                updated = True
        if track.date_added and self._parse_date(song.date_added):
            if track.date_added.replace(tzinfo=None) != self._parse_date(song.date_added).replace(microsecond=0, tzinfo=None):
                changes.append(f"date_added: {track.date_added} -> {self._parse_date(song.date_added).replace(microsecond=0)}")
                track.date_added = self._parse_date(song.date_added).replace(microsecond=0)
                updated = True
        if self._parse_date(song.play_count):
            if track.play_cnt < song.play_count:
                changes.append(f"play_cnt: {track.play_cnt} -> {song.play_count}")
                track.play_cnt = song.play_count
                updated = True

        if updated:
            self.updated_tracks_count += 1
            logging.info(f"Updated track: {song.name} by {song.artist} with changes: {', '.join(changes)}")
    '''
    def _update_track(self, track, song, category):
        updated = False
        changes = []
        parsed_last_play_dt = self._parse_date(song.lastplayed)
        parsed_date_added = self._parse_date(song.date_added)

        if track.location != song.location:
            print(f"song {song.name} location changed from {track.location} to {song.location}")
            changes.append(f"location: {track.location} -> {song.location}")
            track.location = song.location
            updated = True
        if track.category != category:
            #print(f"song {song.name} category changed from {track.category} to {category}")
            changes.append(f"category: {track.category} -> {category}")
            track.category = category
            updated = True
        if track.last_play_dt and parsed_last_play_dt:
            if isinstance(parsed_last_play_dt, datetime) and isinstance(track.last_play_dt, datetime):
                if track.last_play_dt.replace(tzinfo=None) < parsed_last_play_dt.replace(microsecond=0, tzinfo=None):
                    print(f"song {song.name} last_play_dt changed from {track.last_play_dt.replace(tzinfo=None)} to {parsed_last_play_dt.replace(microsecond=0)}")
                    changes.append(f"last_play_dt: {track.last_play_dt} -> {parsed_last_play_dt.replace(microsecond=0)}")
                    track.last_play_dt = parsed_last_play_dt.replace(microsecond=0)
                    updated = True
            else:
                logging.error(f"Unexpected date type: {type(parsed_last_play_dt)} or {type(track.last_play_dt)}")

        if track.date_added and parsed_date_added:
            if isinstance(parsed_date_added, datetime) and isinstance(track.date_added, datetime):
                if track.date_added.replace(tzinfo=None) < parsed_date_added.replace(microsecond=0, tzinfo=None):
                    changes.append(f"date_added: {track.date_added} -> {parsed_date_added.replace(microsecond=0)}")
                    track.date_added = parsed_date_added.replace(microsecond=0)
                    updated = True
            else:
                logging.error(f"Unexpected date type: {type(parsed_date_added)} or {type(track.date_added)}")

        if track.play_cnt is not None and song.play_count is not None:
            if track.play_cnt < song.play_count:
                changes.append(f"play_cnt: {track.play_cnt} -> {song.play_count}")
                track.play_cnt = song.play_count
                updated = True

        if updated:
            self.updated_tracks_count += 1
            logging.info(f"Updated track: {song.name} by {song.artist} with changes: {', '.join(changes)}")

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