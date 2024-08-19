from sqlalchemy.sql import func
from models import db, Track, Playlist
from datetime import datetime, timedelta
import random

class PlaylistGenerator:
    def __init__(self, playlist_name, playlist_length, minimum_recent_add_playcount, categories, username):
        self.playlist_name = playlist_name
        self.playlist_length = playlist_length
        self.minimum_recent_add_playcount = minimum_recent_add_playcount
        self.categories = categories
        self.username = username
        self.total_songs = int(playlist_length * 60 / 4)  # Assuming average song length of 4 minutes
        self.playlist = []
        self.artist_last_played = {}
        self.category_counts = {cat['name']: int(self.total_songs * cat['percentage'] / 100) for cat in categories}
        self.category_spacing = {cat['name']: max(1, self.total_songs // self.category_counts[cat['name']]) for cat in categories}

    def generate(self):
        self._prepare_virtual_categories()
        self._generate_playlist()
        self._save_playlist_to_database()
        self._create_m3u_file()
        return self.playlist, self._get_statistics()

    def _prepare_virtual_categories(self):
        # Move tracks from first category to RecentAdd if play count is below minimum
        recent_tracks = Track.query.filter(
            Track.category == self.categories[1]['name'],
            Track.play_cnt < self.minimum_recent_add_playcount
        ).all()
        for track in recent_tracks:
            track.category = 'RecentAdd'
        
        # Move tracks older than 18 months from first to second category
        #eighteen_months_ago = (datetime.now() - timedelta(days=540)).strftime("%Y-%m-%dT%H:%M:%SZ")
        eighteen_months_ago = datetime.now() - timedelta(days=18*30)  # Approximation of 18 months
        print("before old_tracks")
        old_tracks = Track.query.filter(
            Track.category == self.categories[1]['name'],
            Track.date_added < eighteen_months_ago
        ).all()
        print('After old_tracks')
        for track in old_tracks:
            track.category = self.categories[2]['name']
        
        db.session.commit()

    def _generate_playlist(self):
        for position in range(self.total_songs):
            category = self._get_next_category(position)
            print(f"_generate_playlist - Category: {category}")
            track = self._get_next_track(category)
            if track:
                self.playlist.append({
                    'position': position + 1,
                    'artist': track.artist,
                    'song': track.song,
                    'category': category,
                    'play_cnt': track.play_cnt,
                    'artist_common_name': track.artist_common_name
                })
                # Update the artist_last_played dictionary
                self.artist_last_played[track.artist_common_name] = position
            else:
                print(f"Warning: No suitable track found for category {category} at position {position + 1}")

    def _get_next_category(self, position):
        for category in self.categories:
            if position % self.category_spacing[category['name']] == 0 and self.category_counts[category['name']] > 0:
                self.category_counts[category['name']] -= 1
                return category['name']
        return random.choice(self.categories)['name']  # Fallback to random category if all quotas are met

    def _get_next_track(self, category):
        #print(f"_get_next_track called for category: {category}")
        artist_repeat = next(cat['artist_repeat'] for cat in self.categories if cat['name'] == category)
        #print(f"Artist repeat for category {category}: {artist_repeat}")
        query = Track.query.filter(Track.category == category)
        #print(f"Initial query: {query} query.count(): {query.count()}")

        # Create a dictionary to keep track of artist appearances
        artist_appearances = {}

        for track in self.playlist:
            artist_appearances[track['artist_common_name']] = artist_appearances.get(track['artist_common_name'], 0) + 1
            #print(f"Artist appearances: {artist_appearances}")

        for artist, appearances in artist_appearances.items():
            if appearances < artist_repeat:
                query = query.filter(Track.artist_common_name != artist)
                #print(f"Filtering query to exclude artist: {artist}")

        #print(f"Final query: {query}")
        track_count = query.count()
        #print(f"Number of tracks returned by query: {track_count}")
        track = query.order_by(Track.last_play_dt.asc()).first()
        if track:
            print(f"Selected track: {track.song} by {track.artist}")
        else:
            print("No suitable track found")
        return track
    
    def _save_playlist_to_database(self):
        for track in self.playlist:
            playlist_entry = Playlist(
                playlist_name=self.playlist_name,
                playlist_date=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
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

    def _create_m3u_file(self):
        with open(f"{self.playlist_name}.m3u", "w") as m3u_file:
            m3u_file.write("#EXTM3U\n")
            for track in self.playlist:
                track_obj = Track.query.filter_by(artist=track['artist'], song=track['song']).first()
                m3u_file.write(f"#EXTINF:{track['play_cnt']},{track['artist']} - {track['song']}\n")
                m3u_file.write(f"#{track['category']}\n")
                m3u_file.write(f"{track_obj.location}\n")

    def _get_statistics(self):
        category_stats = {cat['name']: 0 for cat in self.categories}
        for track in self.playlist:
            category_stats[track['category']] += 1
        return {
            "total_songs": len(self.playlist),
            "category_distribution": category_stats
        }