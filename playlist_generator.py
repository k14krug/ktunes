# playlist_generator.py
from typing import List, Dict, Tuple, Any
from sqlalchemy.sql import func
from sqlalchemy import text, or_, tuple_
from sqlalchemy.orm import joinedload
from models import db, Track, Playlist
from datetime import datetime, timedelta
import numpy as np
import logging
import os
from collections import defaultdict
from pytz import timezone
from tzlocal import get_localzone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PlaylistGenerator:
    def __init__(self, playlist_name: str, playlist_length: int, minimum_recent_add_playcount: int, categories: List[Dict[str, Any]], username: str):

        # Load all tracks into memory once during initialization
        self.all_tracks = {track.id: track for track in db.session.query(Track).all()}
        # Create a mapping for each category to tracks, so we can quickly filter by category
        self.category_tracks = defaultdict(list)
        for track in self.all_tracks.values():
            self.category_tracks[track.category].append(track)

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
       
        self._prepare_virtual_categories()
        
        # Initialize artist_last_played from the most recent playlist is now done when the index page is initially displayed
        # The flask app stores them in session variables. When the user actually generates a playlist, the session variables are passed to this function
        #self._initialize_artist_last_played()
        
        category_distribution = self._generate_category_distribution()
        # Reset all tracks to 'played' = False at the start of a run
        Track.query.update({'played': False})
        
        for position, category in enumerate(category_distribution):
            # Find the next eligible track for the category
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
        start_save_time = datetime.now()
        self._create_m3u_file()
        end_save_time = datetime.now()
        save_time = end_save_time - start_save_time
        print(f"Time to save playlist to M3U file: {save_time}")
        
        return self.playlist, self._get_statistics()
    
    def find_stop_point_in_playlist(self, playlist, recently_played_tracks):
        """Find where the sequence of recently played tracks matches in the playlist."""
        stop_point = None
        # Go through the playlist and look for where the sequence matches
        for i in range(len(playlist) - 2):  # Minus 2 to avoid going out of bounds
            #print range we are looking at
            #print(f"Comparing: {playlist[i].song} to {recently_played_tracks[0].song} and {playlist[i+1].song} to {recently_played_tracks[1].song} and {playlist[i+2].song} to {recently_played_tracks[2].song}")      
            
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
        so they can decide whether to use this data for initializing artist_last_played. If used, the
        artist_last_played dictionary will be updated to reflect the last played position of each artist
        in the most recent playlist when the user submits the playlist generation form.
        
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

    def _prepare_virtual_categories(self) -> None:
        """Prepare virtual categories by moving tracks between categories based on play count and age."""
        logger.info("Starting _prepare_virtual_categories")
        
        # Debug: Print all categories
        logger.info(f"Available categories: {list(self.categories.keys())}")
        
        first_category = list(self.categories.keys())[1]
        second_category = list(self.categories.keys())[2]
        
        logger.info(f"First category: {first_category}")
        logger.info(f"Second category: {second_category}")

        # Measure the time to query and modify recent tracks
        start_recent_tracks_time = datetime.now()
        recent_tracks = Track.query.filter(
            Track.category == first_category,
            or_(Track.play_cnt < self.minimum_recent_add_playcount, Track.play_cnt == None)
        ).all()
        query_time_recent = datetime.now() - start_recent_tracks_time
        logger.info(f"Time to query recent tracks: {query_time_recent}")

        modify_recent_tracks_time = datetime.now()
        for track in recent_tracks:
            track.category = 'RecentAdd'
        update_time_recent = datetime.now() - modify_recent_tracks_time
        logger.info(f"Time to update category for recent tracks: {update_time_recent}")

        # Measure the time to query and modify old tracks
        eighteen_months_ago = datetime.now() - timedelta(days=18*30)  # Approximation of 18 months
        start_old_tracks_time = datetime.now()
        old_tracks = Track.query.filter(
            Track.category == first_category,
            Track.date_added < eighteen_months_ago
        ).all()
        query_time_old = datetime.now() - start_old_tracks_time
        logger.info(f"Time to query old tracks: {query_time_old}")

        modify_old_tracks_time = datetime.now()
        for track in old_tracks:
            track.category = second_category
        update_time_old = datetime.now() - modify_old_tracks_time
        logger.info(f"Time to update category for old tracks: {update_time_old}")

        # Commit changes to the database and measure the time
        start_commit_time = datetime.now()
        #db.session.commit()
        commit_time = datetime.now() - start_commit_time
        logger.info(f"Time to commit changes: {commit_time}")

        # Incrementally update in-memory category tracks for only the moved tracks
        start_memory_update_time = datetime.now()

        # Remove moved tracks from their old categories
        for track in recent_tracks:
            if first_category in self.category_tracks and track in self.category_tracks[first_category]:
                self.category_tracks[first_category].remove(track)
        for track in old_tracks:
            if first_category in self.category_tracks and track in self.category_tracks[first_category]:
                self.category_tracks[first_category].remove(track)

        # Add the moved tracks to their new categories
        for track in recent_tracks:
            self.category_tracks['RecentAdd'].append(track)
        for track in old_tracks:
            self.category_tracks[second_category].append(track)

        memory_update_time = datetime.now() - start_memory_update_time
        logger.info(f"Time to update in-memory categories incrementally: {memory_update_time}")

        logger.info("Finished _prepare_virtual_categories")

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
        
        #db.session.commit()
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
    

    def _get_next_track(self, category: str, attempt: int = 0) -> Track:
        # Retrieve tracks in the specified category from memory
        category_tracks = self.category_tracks.get(category, [])
        
        # Filter tracks based on the played status
        filtered_tracks = [track for track in category_tracks if not track.played]
        
        # Apply the existing artist repeat interval logic
        current_position = len(self.playlist)  # Current position in the playlist

        # Remove artists that have been played too recently based on repeat intervals
        for artist, data in self.artist_last_played.items():
            last_played = data["last_played"]
            if last_played != 0 and data["category"] == category:
                repeat_interval = self.artist_max_repeat_interval.get(artist, 0)
                if current_position - last_played < repeat_interval:
                    # Filter out the artist
                    filtered_tracks = [track for track in filtered_tracks if track.artist_common_name != artist]
        
        # Further refine the filtered tracks based on last played date
        filtered_tracks.sort(key=lambda track: track.last_play_dt or datetime.min)
        
        # Select the first track that meets all conditions
        track = filtered_tracks[0] if filtered_tracks else None

        # If no track is found, handle reset logic
        if not track:
            logger.info(f"    WARNING: Resetting category: {category}")
            if attempt >= 1:
                logger.error(f"    ERROR: Could not find a track for category: {category} after reset")
                raise RuntimeError(f"Could not find a track for category: {category} after reset")

            self._reset_category(category)
            return self._get_next_track(category, attempt + 1)

        # Mark track as played in-memory
        track.played = True
        #print(f"       # #  #   S E L E C T E D    # # # {track.artist} - {track.song}  category: {category}")
        return track










        # and also have a dictionary of artist_max_repeat_interval that contains the maximum repeat interval for each artist
        # We will filter out artists that have been played too recently based on the current position and their max repeat interval
        
        for artist, data in self.artist_last_played.items():
            last_played = data["last_played"]
            # If last_played is 0, it means the artist has not been added to the playlist yet
            if last_played != 0:
                if data["category"] == category:
                    repeat_interval = self.artist_max_repeat_interval.get(artist, 0)
                    if current_position - last_played < repeat_interval:
                        # Filter out the artist
                        query = query.filter(Track.artist_common_name != artist)
                else:
                    # This artist may be eligble, but lets check the other category.
                    # Search self.playlist to find the last time the artist was played. If it was played too recently, filter it.
                    for track in self.playlist:
                        if track['artist_common_name'] == artist:
                            if current_position - track['position'] < self.categories[data["category"]]['artist_repeat']:
                                query = query.filter(Track.artist_common_name != artist)
                                break

        # Now that we've filtered out artists that have been played too recently, get the first track from the query when you sort by last_play_dt
        track = query.order_by(func.coalesce(Track.last_play_dt, datetime.min).asc()).first()
  
        if not track:
            logger.info(f"    WARNING: Resetting category: {category}")
            if attempt >= 1:
                logger.error(f"    ERROR: Could not find a track for category: {category} after reset")
                raise RuntimeError(f"Could not find a track for category: {category} after reset")

            self._reset_category(category)
            return self._get_next_track(category, attempt + 1)
        print(f"       # #  #   S E L E C T E D    # # # {track.artist} - {track.song}  category: {category}")
        return track

    def _get_next_category(self, current_category: str) -> str:
        """Get the next category in the rotation."""
        categories = list(self.category_counts.keys())
        current_index = categories.index(current_category)
        return categories[(current_index + 1) % len(categories)]


    def _reset_category(self, category: str) -> None:
        """Reset the 'played' status for all tracks in a category."""
        for track in self.category_tracks.get(category, []):
            track.played = False





    def _update_play_counts(self, track: Track, category: str) -> None:
        # At this point, we have selected a track to add to the playlist. Mark it as played and update the play counts
        
        track.played = True

        # Update artist_last_played for the artist but first need to insure the artist is in the dictionary. Else you get key error
        self.artist_last_played.setdefault(track.artist_common_name, {"last_played": -1, "category": category})
        #self.artist_last_played[track.artist_common_name]["last_played"] = len(self.playlist)
        self.artist_last_played[track.artist_common_name].update({"last_played": len(self.playlist),"category": category})
        
        # Update artist_max_repeat_interval
        current_repeat_interval = self.categories[category]['artist_repeat']
        self.artist_max_repeat_interval[track.artist_common_name] = max(
            self.artist_max_repeat_interval.get(track.artist_common_name, 0),
            current_repeat_interval
        )

    def _save_playlist_to_database(self) -> None:
        """Save the generated playlist to the database and update the most_recent_playlist field."""
        # Track time it takes to save playlist to database
        start_save_time = datetime.now()
        print("Saving playlist to database")
        now = datetime.now(self.local_tz)  # Get current time in local timezone

        # Create a list of playlist entries to add
        playlist_entries = []
        track_identifiers = [(track['artist'], track['song']) for track in self.playlist]

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
            playlist_entries.append(playlist_entry)

        # Add all playlist entries in a single bulk operation
        db.session.bulk_save_objects(playlist_entries)

        # Fetch all relevant tracks in a single query
        db_tracks = db.session.query(Track).filter(
            tuple_(Track.artist, Track.song).in_(track_identifiers)
        ).all()

        # Update the most_recent_playlist field for all fetched tracks
        for db_track in db_tracks:
            db_track.most_recent_playlist = self.playlist_name

        end_save_time = datetime.now()
        save_time = end_save_time - start_save_time
        db.session.commit()
        final_save_time = datetime.now() - end_save_time
        print(f"Time to save playlist to database: {save_time}")
        print(f"Time to commit playlist to database: {final_save_time}")


    def _create_m3u_file(self) -> None:
        """Create an M3U file for the generated playlist."""
        # Ensure the playlists directory exists
        playlists_dir = os.path.join(os.getcwd(), 'playlists')
        os.makedirs(playlists_dir, exist_ok=True)

        # Step 1: Batch load all relevant tracks into a dictionary
        track_keys = [(track['artist'], track['song']) for track in self.playlist]
        # Use a single query to fetch all tracks matching the artist and song in the playlist
        track_objs = Track.query.filter(tuple_(Track.artist, Track.song).in_(track_keys)).all()

        # Create a lookup dictionary for quick access
        track_dict = {(track.artist, track.song): track for track in track_objs}

        # Step 2: Build the M3U file content in memory
        m3u_content = ["#EXTM3U"]
        for track in self.playlist:
            track_obj = track_dict.get((track['artist'], track['song']))
            if track_obj:
                m3u_content.append(f"#EXTINF:{track['play_cnt']},{track['artist']} - {track['song']}")
                m3u_content.append(f"#{track['category']}")
                m3u_content.append(f"{track_obj.location}")
            else:
                logger.warning(f"Track not found in database: {track['artist']} - {track['song']}")

        # Step 3: Write the M3U content to file in one go
        m3u_file_path = os.path.join(playlists_dir, f"{self.playlist_name}.m3u")
        with open(m3u_file_path, "w") as m3u_file:
            m3u_file.write("\n".join(m3u_content))
        print(f"M3U file saved to {m3u_file_path}")



    def _get_statistics(self) -> Dict[str, Any]:
        """Get statistics for the generated playlist."""
        category_stats = {cat: 0 for cat in self.categories}
        for track in self.playlist:
            category_stats[track['category']] += 1
        return {
            "total_songs": len(self.playlist),
            "category_distribution": category_stats
        }