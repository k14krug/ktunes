# playlist_generator.py
from typing import List, Dict, Tuple, Any
from sqlalchemy.sql import func
from sqlalchemy import text, or_
from sqlalchemy.orm import joinedload
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
        
        # Initialize artist_last_played from the most recent playlist is now done when the index page is initially displayed
        #self._initialize_artist_last_played()
        
        category_distribution = self._generate_category_distribution()
        Track.query.update({'played': False})
        
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
    
    def find_stop_point_in_playlist(self, playlist, recently_played_tracks):
        """Find where the sequence of recently played tracks matches in the playlist."""
        stop_point = None
        # Go through the playlist and look for where the sequence matches
        for i in range(len(playlist) - 2):  # Minus 2 to avoid going out of bounds
            #print range we are looking at
            print(f"Comparing: {playlist[i].song} to {recently_played_tracks[0].song} and {playlist[i+1].song} to {recently_played_tracks[1].song} and {playlist[i+2].song} to {recently_played_tracks[2].song}")      
            
            if (
                playlist[i].song == recently_played_tracks[2].song and
                playlist[i+1].song == recently_played_tracks[1].song and
                playlist[i+2].song == recently_played_tracks[0].song
            ):
                stop_point = i + 2  # The last song in the sequence
                break

        return stop_point

    def preview_last_playlist(self):
        """
        Fetches the most recent playlist the user listened to and determines how far into the playlist
        the user has gotten by identifying the most recently played tracks. This method is used to give
        the user visibility into what the application believes is the last playlist and track position, 
        so they can decide whether to use this data for initializing artist_last_played.
        
        Returns:
            latest_playlist (Playlist): The most recent playlist the user listened to, based on the playlist date.
            stop_point (int): The track position where the user stopped listening, determined by analyzing 
                            the last played tracks in the playlist. If no stop point is found, None is returned.
                            The stop_point is 1-based (i.e., the first track would have a stop_point of 1).
        
        This function is intended to be called before initializing artist_last_played to give the user
        a chance to confirm whether they want to use the most recent playlist to influence the next playlist 
        generation. The method leverages the stored play history to find the last 3 tracks that were played 
        in the most recent playlist and calculates the track position where the user last stopped listening.
        """
        latest_playlist = Playlist.query.order_by(Playlist.playlist_date.desc()).first()
        if not latest_playlist:
            return None, None
        
        last_tracks = (db.session.query(Track)
                       .filter(Track.last_play_dt.isnot(None))
                       .order_by(Track.last_play_dt.desc())
                       .limit(3)
                       .all())

        if not last_tracks:
            return latest_playlist, None

        playlist_tracks = (db.session.query(Track, Playlist)
                           .filter(Track.song == Playlist.song)
                           .filter(Track.artist == Playlist.artist)
                           .filter(Playlist.playlist_name == latest_playlist.playlist_name)
                           .order_by(Playlist.track_position)
                           .all())

        stop_point = self.find_stop_point_in_playlist([track[0] for track in playlist_tracks], last_tracks)
        return latest_playlist, stop_point + 1 if stop_point is not None else None

    
    def _initialize_artist_last_played(self, latest_playlist, stop_point):
        """
        Initializes the artist_last_played dictionary, which tracks how recently each artist 
        was played. This prevents the same artist from being played too frequently in the next 
        playlist generation. The dictionary is initialized using the most recent playlist 
        and the last track position (stop_point) that the user confirmed. 
        
        If the user does not want to use the most recent playlist, the initialization will proceed 
        without reference to prior play history.

        Args:
            latest_playlist (Playlist): The playlist from which to initialize artist_last_played. 
                                        If None, no playlist data is used.
            stop_point (int): The track position in the latest playlist where the user last stopped 
                            listening. Tracks up to this point will be used to set the artist_last_played 
                            values. If None, no track data is used.
        
        This function updates the artist_last_played dictionary as follows:
            - Each artist's "last_played" value is set based on the order in which they appear 
            in the playlist, starting with -1 for the most recent artist.
            - Artists from tracks that were not played (i.e., those beyond the stop_point) are not included.
            - Artists from the most recent playlist are given negative values (e.g., -1, -2, -3, ...), 
            which ensures that they are less likely to be played early in the next playlist.
        
        If no playlist or stop point is provided, artist_last_played will remain uninitialized 
        and will not influence the next playlist generation.
        
        Example:
            If the latest playlist has 10 tracks, and the stop_point is 7, the first 7 tracks are used to 
            initialize artist_last_played. The artist for track 1 will get a "last_played" value of -7, 
            track 2 will get -6, and so on, with track 7 getting -1.
        """

        self.artist_last_played = {}

        if latest_playlist and stop_point is not None:
            playlist_tracks = (db.session.query(Track, Playlist)
                               .filter(Track.song == Playlist.song)
                               .filter(Track.artist == Playlist.artist)
                               .filter(Playlist.playlist_name == latest_playlist.playlist_name)
                               .order_by(Playlist.track_position)
                               .all())
            
            count = -1
            for i in range(stop_point):
                track, playlist = playlist_tracks[i]
                artist_name = track.artist_common_name or track.artist
                category = track.category
                self.artist_last_played[artist_name] = {"last_played": count, "category": category}
                count -= 1

            print(f"Final artist_last_played: {self.artist_last_played}")
        else:
            print("No playlist or stop point confirmed.")

     
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
        if category == 'RecentAdd':
            print(f"Getting next track for category: {category}")
        """Get the next track for the given category."""
        query = Track.query.filter(Track.category == category, Track.played == False)

        current_position = len(self.playlist)

        # Filter only artists that have been played (i.e., have non-zero last_played values)
        for artist, data in self.artist_last_played.items():
            last_played = data["last_played"]
            # Only filter if the artist has been played (last_played != 0)
            if last_played != 0 and data["category"] == category:
                repeat_interval = self.artist_max_repeat_interval.get(artist, 0)
                if current_position - last_played < repeat_interval:
                    query = query.filter(Track.artist_common_name != artist)
                    if category == 'RecentAdd':
                        print(f" Filter artist removed: {artist} last_played: {last_played}, repeat_interval: {repeat_interval} current_position: {current_position}")
            else:
                if (category == 'RecentAdd' and data["category"] == None) or  data["category"] == category:
                    print(f" Filter Artist not removed: {artist}, last_played: {last_played}, repeat_interval: {repeat_interval} current_position: {current_position}")  

        track = query.order_by(func.coalesce(Track.last_play_dt, datetime.min).asc()).first()
        if category == 'RecentAdd':
            eligible_tracks = query.order_by(func.coalesce(Track.last_play_dt, datetime.min).asc())
            for e_track in eligible_tracks:
                print(f"      Eligible track: {e_track.artist} - {e_track.song}")

            

        if not track:
            logger.info(f"    WARNING: Resetting category: {category}")
            self._reset_category(category)
            return self._get_next_track(category)
        print(f"       Selected {track.artist} - {track.song} ")
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
        # track.last_play_dt = datetime.utcnow()
        
        # Update in-memory play counts
        key = (track.song, track.artist_common_name)
        self.play_counts[key] += 1
        
        # Ensure the artist is in the artist_last_played dictionary
        self.artist_last_played.setdefault(track.artist_common_name, {"last_played": -1, "category": category})
        
        # Update artist_last_played for all categories
        self.artist_last_played[track.artist_common_name]["last_played"] = len(self.playlist)
        
        # Print debug information
        if category == 'RecentAdd':
            print(f"        Updated last_played for Artist: {track.artist_common_name} last played position: {self.artist_last_played[track.artist_common_name]['last_played']}")
        
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