# playlist_generator.py
from typing import List, Dict, Tuple, Any
from sqlalchemy.sql import func
from sqlalchemy import text, or_
from models import db, Track, Playlist
from datetime import datetime, timedelta
import numpy as np
import logging
from collections import defaultdict
from pytz import timezone
from tzlocal import get_localzone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PlaylistGenerator:
    def __init__(self, playlist_name: str, playlist_length: int, minimum_recent_add_playcount: int, categories: List[Dict[str, Any]], username: str):
        """
        Initialize the PlaylistGenerator.

        :param playlist_name: Name of the playlist
        :param playlist_length: Length of the playlist in minutes
        :param minimum_recent_add_playcount: Minimum play count for recent additions
        :param categories: List of category dictionaries with 'name', 'percentage', and 'artist_repeat' keys
        :param username: Username of the playlist creator
        """
        self.playlist_name = playlist_name
        self.playlist_length = playlist_length
        self.minimum_recent_add_playcount = minimum_recent_add_playcount
        self.categories = {cat['name']: cat for cat in categories}  # Convert to dictionary for easier access
        self.username = username
        self.total_songs = int(playlist_length * 60 / 4)  # Assuming average song length of 4 minutes
        self.playlist: List[Dict[str, Any]] = []
        self.category_counts = {cat['name']: int(self.total_songs * cat['percentage'] / 100) for cat in categories}
        self.play_counts = defaultdict(int)
        self.track_counts = self._get_track_counts()
        
        # Next two variables used to insure artist repeat interval across categories
        self.artist_last_played = {} 
        self.artist_max_repeat_interval = {}

        self.local_tz = get_localzone()  # Get the local timezone   

    def generate(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Generate the playlist.

        :return: Tuple of the generated playlist and statistics
        """
        #self.reset_play_counts()
        self._prepare_virtual_categories()
        category_distribution = self._generate_category_distribution()
        
        for position, category in enumerate(category_distribution):
            track = self._get_next_track(category)
            if track:
                self.playlist.append({
                    'position': position + 1,
                    'artist': track.artist,
                    'song': track.song,
                    'category': category,
                    'play_cnt': track.play_cnt or 0,
                    'artist_common_name': track.artist_common_name
                })
                self._update_play_counts(track, category)
            else:
                logger.warning(f"No suitable track found for category {category} at position {position + 1}")
        
        self._save_playlist_to_database()
        #self.save_play_counts()
        self._create_m3u_file()
        
        return self.playlist, self._get_statistics()
    
    def _get_track_counts(self) -> Dict[str, Dict[str, int]]:
        #Get track counts for each category before and after virtual category moves. This is used to display the category counts in the UI when generating a playlist.
        counts = {cat: {'before': 0, 'after': 0} for cat in self.categories}
        
        # Count before virtual moves
        for category in self.categories:
            counts[category]['before'] = Track.query.filter(Track.category == category).count()
        
        # Perform virtual moves (similar to _prepare_virtual_categories)
        first_category = list(self.categories.keys())[1]
        second_category = list(self.categories.keys())[2]
        
        recent_tracks = Track.query.filter(
            Track.category == first_category,
            or_(Track.play_cnt < self.minimum_recent_add_playcount, Track.play_cnt == None)
        ).count()
        counts['RecentAdd']['after'] = recent_tracks
        counts[first_category]['after'] = counts[first_category]['before'] - recent_tracks
        
        eighteen_months_ago = datetime.now() - timedelta(days=18*30)
        old_tracks = Track.query.filter(
            Track.category == first_category,
            Track.date_added < eighteen_months_ago
        ).count()
        counts[second_category]['after'] = counts[second_category]['before'] + old_tracks
        counts[first_category]['after'] -= old_tracks
        
        return counts

    def reset_play_counts(self):
        """Clear all existing play counts at the start of a run."""
        #db.session.execute(text("TRUNCATE TABLE playlist_song_play_counts"))
        db.session.commit()
        logger.info("Cleared existing play counts")

    def _prepare_virtual_categories(self) -> None:
        """Prepare virtual categories by moving tracks between categories based on play count and age."""
        logger.info("Starting _prepare_virtual_categories")
        
        # Debug: Print all categories
        logger.info(f"Available categories: {list(self.categories.keys())}")
        
        first_category = list(self.categories.keys())[1]
        second_category = list(self.categories.keys())[2]
        
        logger.info(f"First category: {first_category}")
        logger.info(f"Second category: {second_category}")

        # Move tracks from first category to RecentAdd if play count is below minimum
        recent_tracks = Track.query.filter(
            Track.category == first_category,
            Track.play_cnt < self.minimum_recent_add_playcount
        ).all()

        recent_tracks = Track.query.filter(
            Track.category == first_category,
            or_(Track.play_cnt < self.minimum_recent_add_playcount, Track.play_cnt == None)
        ).all()
        logger.info(f"Tracks with play count < {self.minimum_recent_add_playcount} in {first_category}: {len(recent_tracks)}")
        for track in recent_tracks:
            track.category = 'RecentAdd'
            #logger.info(f"Moving track to RecentAdd: {track.artist} - {track.song}")
        
        # Move tracks older than 18 months from first to second category
        eighteen_months_ago = datetime.now() - timedelta(days=18*30)  # Approximation of 18 months
        old_tracks = Track.query.filter(
            Track.category == first_category,
            Track.date_added < eighteen_months_ago
        ).all()
        logger.info(f"Tracks older than 18 months in {first_category}: {len(old_tracks)}")
        for track in old_tracks:
            track.category = second_category
            #logger.info(f"Moving track to {second_category}: {track.artist} - {track.song}")
        
        # Debug: Print category counts after moving
        for category in self.categories.keys():
            count = Track.query.filter(Track.category == category).count()
            logger.info(f"Tracks in {category} after moving: {count}")
        
        db.session.commit()
        logger.info("Finished _prepare_virtual_categories")

    def _generate_category_distribution(self) -> List[str]:
        """Generate a distribution of categories for the playlist."""
        distribution = []
        fractions = [1 / count for count in self.category_counts.values()]
        while len(distribution) < self.total_songs:
            min_fraction_index = np.argmin(fractions)
            category = list(self.category_counts.keys())[min_fraction_index]
            distribution.append(category)
            fractions[min_fraction_index] += 1 / self.category_counts[category]
        return distribution

    def _get_next_track(self, category: str) -> Track:
        """Get the next track for the given category."""
        query = Track.query.filter(Track.category == category)
        
        # Filter out recently played artists across all categories
        current_position = len(self.playlist)
        for artist, last_played in self.artist_last_played.items():
            repeat_interval = self.artist_max_repeat_interval.get(artist, 0)
            if current_position - last_played < repeat_interval:
                query = query.filter(Track.artist_common_name != artist)
        
        track = query.order_by(func.coalesce(Track.last_play_dt, datetime.min).asc()).first()
        if not track:
            # Try next category if no track found
            next_category = self._get_next_category(category)
            if next_category != category:
                return self._get_next_track(next_category)
            else:
                # Reset category if we've cycled through all
                self._reset_category(category)
                return self._get_next_track(category)
        
        return track

    def _get_next_category(self, current_category: str) -> str:
        """Get the next category in the rotation."""
        categories = list(self.category_counts.keys())
        current_index = categories.index(current_category)
        return categories[(current_index + 1) % len(categories)]

    def _reset_category(self, category: str) -> None:
        """Reset the 'played' status for all tracks in a category."""
        Track.query.filter(Track.category == category).update({'played': False})
        db.session.commit()

    def _update_play_counts(self, track: Track, category: str) -> None:
        """Update play counts and last played information for a track."""
        track.cat_cnt = (track.cat_cnt or 0) + 1
        track.artist_cat_cnt = track.cat_cnt
        track.played = True
        track.last_play_dt = datetime.utcnow()
        
        # Update in-memory play counts
        key = (track.song, track.artist_common_name)
        self.play_counts[key] += 1
        
        # Update artist_last_played for all categories
        self.artist_last_played[track.artist_common_name] = len(self.playlist)
        
        # Update artist_max_repeat_interval
        current_repeat_interval = self.categories[category]['artist_repeat']
        self.artist_max_repeat_interval[track.artist_common_name] = max(
            self.artist_max_repeat_interval.get(track.artist_common_name, 0),
            current_repeat_interval
        )

    def _save_playlist_to_database(self) -> None:
        """Save the generated playlist to the database."""
        print("Saving playlist to database")
        now = datetime.now(self.local_tz)  # Get current time in local timezone
        for track in self.playlist:
            playlist_entry = Playlist(
                playlist_name=self.playlist_name,
                playlist_date=now,
                track_position=track['position'],
                artist=track['artist'],
                song=track['song'],
                category=track['category'],
                play_cnt=track['play_cnt'],
                artist_common_name=track['artist_common_name'],
                username=self.username
            )
            db.session.add(playlist_entry)
        db.session.commit()

    def _create_m3u_file(self) -> None:
        """Create an M3U file for the generated playlist."""
        with open(f"{self.playlist_name}.m3u", "w") as m3u_file:
            m3u_file.write("#EXTM3U\n")
            for track in self.playlist:
                track_obj = Track.query.filter_by(artist=track['artist'], song=track['song']).first()
                if track_obj:
                    m3u_file.write(f"#EXTINF:{track['play_cnt']},{track['artist']} - {track['song']}\n")
                    m3u_file.write(f"#{track['category']}\n")
                    m3u_file.write(f"{track_obj.location}\n")
                else:
                    logger.warning(f"Track not found in database: {track['artist']} - {track['song']}")

    def _get_statistics(self) -> Dict[str, Any]:
        """Get statistics for the generated playlist."""
        category_stats = {cat: 0 for cat in self.categories}
        for track in self.playlist:
            category_stats[track['category']] += 1
        return {
            "total_songs": len(self.playlist),
            "category_distribution": category_stats
        }