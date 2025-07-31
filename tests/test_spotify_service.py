import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import pytz
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import Flask for minimal app context
from flask import Flask

from services.spotify_service import (
    get_listening_history_with_playlist_context,
    determine_track_position_from_context,
    _get_surrounding_tracks,
    _analyze_position_context,
    _check_sequence_patterns,
    _format_track_data,
    _format_relative_time,
    _get_time_period_stats,
    normalize_text
)


class TestSpotifyServiceFunctions(unittest.TestCase):
    """Test suite for Spotify service functions related to listening history"""

    def setUp(self):
        """Set up test fixtures"""
        # Create minimal Flask app for context
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        self.pacific_tz = pytz.timezone('America/Los_Angeles')
        self.base_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=self.pacific_tz)
        
        # Create mock played tracks (without spec to avoid SQLAlchemy issues)
        self.mock_played_tracks = []
        for i in range(5):
            track = Mock()
            track.id = i + 1
            track.artist = f"Artist {i + 1}"
            track.song = f"Song {i + 1}"
            track.played_at = self.base_time + timedelta(minutes=i * 5)
            track.category = "Test"
            track.playlist_name = None
            track.spotify_id = f"spotify_id_{i + 1}"
            self.mock_played_tracks.append(track)
        
        # Create mock playlist data
        self.mock_playlist_data = []
        for i in range(10):
            playlist_track = Mock()
            playlist_track.id = i + 1
            playlist_track.track_position = i + 1
            playlist_track.artist = f"Artist {i + 1}"
            playlist_track.song = f"Song {i + 1}"
            playlist_track.playlist_name = "KRUG FM 96.2"
            playlist_track.playlist_date = self.base_time.date()
            self.mock_playlist_data.append(playlist_track)

    def tearDown(self):
        """Clean up test fixtures"""
        self.app_context.pop()

    def test_get_surrounding_tracks_normal_case(self):
        """Test _get_surrounding_tracks with normal parameters"""
        result = _get_surrounding_tracks(self.mock_played_tracks, 2, window_size=2)
        
        self.assertIn('before', result)
        self.assertIn('after', result)
        self.assertEqual(len(result['before']), 2)  # tracks 0, 1
        self.assertEqual(len(result['after']), 2)   # tracks 3, 4
        self.assertEqual(result['before'][0].id, 1)
        self.assertEqual(result['after'][0].id, 4)

    def test_get_surrounding_tracks_edge_cases(self):
        """Test _get_surrounding_tracks with edge cases"""
        # Test at beginning of list
        result = _get_surrounding_tracks(self.mock_played_tracks, 0, window_size=2)
        self.assertEqual(len(result['before']), 0)
        self.assertEqual(len(result['after']), 2)
        
        # Test at end of list
        result = _get_surrounding_tracks(self.mock_played_tracks, 4, window_size=2)
        self.assertEqual(len(result['before']), 2)
        self.assertEqual(len(result['after']), 0)
        
        # Test with invalid index
        result = _get_surrounding_tracks(self.mock_played_tracks, -1, window_size=2)
        self.assertEqual(result, {'before': [], 'after': []})
        
        # Test with empty list
        result = _get_surrounding_tracks([], 0, window_size=2)
        self.assertEqual(result, {'before': [], 'after': []})

    def test_format_relative_time(self):
        """Test _format_relative_time function"""
        # Test with None
        self.assertEqual(_format_relative_time(None), 'Unknown')
        
        # Test basic functionality - just ensure it returns a string
        test_time = datetime(2024, 1, 15, 11, 0, 0, tzinfo=self.pacific_tz)
        result = _format_relative_time(test_time)
        self.assertIsInstance(result, str)
        self.assertNotEqual(result, 'Unknown')  # Should not be unknown for valid datetime

    def test_get_time_period_stats(self):
        """Test _get_time_period_stats function"""
        # Test with normal data
        result = _get_time_period_stats(self.mock_played_tracks)
        
        self.assertEqual(result['total_tracks_in_period'], 5)
        self.assertIsNotNone(result['time_period_start'])
        self.assertIsNotNone(result['time_period_end'])
        self.assertIn('period_description', result)
        
        # Test with empty list
        result = _get_time_period_stats([])
        self.assertEqual(result['total_tracks_in_period'], 0)
        self.assertIsNone(result['time_period_start'])
        self.assertIsNone(result['time_period_end'])
        self.assertEqual(result['period_description'], 'No tracks')

    def test_format_track_data_basic(self):
        """Test _format_track_data with basic track data"""
        track = self.mock_played_tracks[0]
        
        with patch('services.spotify_service.Track') as mock_track_model:
            mock_track_model.query.filter_by.return_value.first.return_value = None
            
            result = _format_track_data(track)
            
            self.assertEqual(result['id'], track.id)
            self.assertEqual(result['artist'], track.artist)
            self.assertEqual(result['song'], track.song)
            self.assertEqual(result['played_at'], track.played_at)
            self.assertFalse(result['from_krug_playlist'])
            self.assertIsNone(result['track_position'])

    def test_format_track_data_with_playlist_context(self):
        """Test _format_track_data with playlist context"""
        track = self.mock_played_tracks[0]
        position_info = {
            'position': 5,
            'confidence': 'high',
            'method': 'Single match in playlist'
        }
        
        with patch('services.spotify_service.Track') as mock_track_model:
            mock_track_model.query.filter_by.return_value.first.return_value = None
            
            result = _format_track_data(
                track,
                from_krug_playlist=True,
                track_position=5,
                position_confidence='high',
                position_method='Single match in playlist',
                position_info=position_info
            )
            
            self.assertTrue(result['from_krug_playlist'])
            self.assertEqual(result['track_position'], 5)
            self.assertEqual(result['position_confidence'], 'high')
            self.assertEqual(result['position_display'], 'Track #5')

    def test_check_sequence_patterns(self):
        """Test _check_sequence_patterns function"""
        # Create playlist lookup
        playlist_by_position = {}
        for i, track in enumerate(self.mock_playlist_data):
            playlist_by_position[i + 1] = {
                'artist': track.artist,
                'song': track.song
            }
        
        # Create surrounding tracks that match playlist sequence
        surrounding_tracks = {
            'before': [self.mock_played_tracks[0], self.mock_played_tracks[1]],  # positions 1, 2
            'after': [self.mock_played_tracks[3], self.mock_played_tracks[4]]    # positions 4, 5
        }
        
        # Test position 3 (should find sequence matches)
        score = _check_sequence_patterns(3, surrounding_tracks, playlist_by_position)
        self.assertGreater(score, 0)
        
        # Test with no sequence matches
        non_matching_tracks = {
            'before': [Mock(artist="Different Artist", song="Different Song")],
            'after': [Mock(artist="Another Artist", song="Another Song")]
        }
        score = _check_sequence_patterns(3, non_matching_tracks, playlist_by_position)
        self.assertEqual(score, 0)

    def test_analyze_position_context(self):
        """Test _analyze_position_context function"""
        # Create playlist lookup
        playlist_by_position = {}
        for i, track in enumerate(self.mock_playlist_data):
            playlist_by_position[i + 1] = {
                'artist': track.artist,
                'song': track.song
            }
        
        # Create surrounding tracks that match playlist positions
        surrounding_tracks = {
            'before': [self.mock_played_tracks[1]],  # Should match position 2
            'after': [self.mock_played_tracks[3]]    # Should match position 4
        }
        
        # Test position 3
        score, method = _analyze_position_context(
            3, surrounding_tracks, playlist_by_position, self.base_time
        )
        
        self.assertGreater(score, 0)
        self.assertIsInstance(method, str)
        self.assertGreater(len(method), 0)

    def test_determine_track_position_from_context_single_match(self):
        """Test determine_track_position_from_context with single playlist match"""
        # Create playlist data with single occurrence of the track
        single_match_playlist = [self.mock_playlist_data[0]]  # Only one track
        
        result = determine_track_position_from_context(
            "Artist 1", "Song 1", self.base_time,
            {'before': [], 'after': []}, single_match_playlist
        )
        
        self.assertEqual(result['position'], 1)
        self.assertEqual(result['confidence'], 'high')
        self.assertEqual(result['method'], 'Single occurrence in playlist')

    def test_determine_track_position_from_context_multiple_matches(self):
        """Test determine_track_position_from_context with multiple playlist matches"""
        # Create playlist data with duplicate tracks
        duplicate_playlist = []
        for i in [1, 5, 8]:  # Same track at positions 1, 5, 8
            track = Mock()
            track.track_position = i
            track.artist = "Duplicate Artist"
            track.song = "Duplicate Song"
            duplicate_playlist.append(track)
        
        # Add other tracks to fill the playlist
        for i in [2, 3, 4, 6, 7, 9]:
            track = Mock()
            track.track_position = i
            track.artist = f"Other Artist {i}"
            track.song = f"Other Song {i}"
            duplicate_playlist.append(track)
        
        # Create surrounding tracks that would match position 5
        surrounding_tracks = {
            'before': [Mock(artist="Other Artist 4", song="Other Song 4")],
            'after': [Mock(artist="Other Artist 6", song="Other Song 6")]
        }
        
        result = determine_track_position_from_context(
            "Duplicate Artist", "Duplicate Song", self.base_time,
            surrounding_tracks, duplicate_playlist
        )
        
        self.assertIn(result['position'], [1, 5, 8])
        self.assertIn(result['confidence'], ['high', 'medium', 'low', 'unknown'])
        self.assertIsInstance(result['method'], str)

    def test_determine_track_position_from_context_not_found(self):
        """Test determine_track_position_from_context with track not in playlist"""
        result = determine_track_position_from_context(
            "Non-existent Artist", "Non-existent Song", self.base_time,
            {'before': [], 'after': []}, self.mock_playlist_data
        )
        
        self.assertIsNone(result['position'])
        self.assertEqual(result['confidence'], 'unknown')
        self.assertEqual(result['method'], 'Track not found in playlist')

    @patch('services.spotify_service.db')
    @patch('services.spotify_service.current_app')
    def test_get_listening_history_with_playlist_context_success(self, mock_app, mock_db):
        """Test get_listening_history_with_playlist_context with successful execution"""
        # Setup mocks
        mock_app.logger = Mock()
        
        # Create a more complex mock for database queries
        count_query = Mock()
        count_query.filter.return_value.scalar.return_value = 5
        
        tracks_query = Mock()
        tracks_query.filter.return_value.order_by.return_value.limit.return_value.offset.return_value.all.return_value = self.mock_played_tracks
        
        playlist_date_query = Mock()
        playlist_date_query.filter.return_value.scalar.return_value = self.base_time.date()
        
        playlist_data_query = Mock()
        playlist_data_query.filter.return_value.order_by.return_value.all.return_value = self.mock_playlist_data
        
        # Mock db.session.query to return different mocks based on call order
        query_call_count = 0
        def mock_query(*args):
            nonlocal query_call_count
            query_call_count += 1
            if query_call_count == 1:  # First call for count
                return count_query
            elif query_call_count == 2:  # Second call for tracks
                return tracks_query
            elif query_call_count == 3:  # Third call for playlist date
                return playlist_date_query
            else:  # Fourth call for playlist data
                return playlist_data_query
        
        mock_db.session.query.side_effect = mock_query
        
        # Mock cache functions from the cache service module
        with patch('services.cache_service.get_cached_playlist_data', return_value=None):
            with patch('services.cache_service.cache_playlist_data'):
                with patch('services.cache_service.get_cached_playlist_lookup', return_value=None):
                    with patch('services.cache_service.cache_playlist_lookup'):
                        result = get_listening_history_with_playlist_context(limit=5, offset=0)
        
        listening_data, total_count, error_message = result
        
        self.assertEqual(total_count, 5)
        self.assertIsInstance(listening_data, list)
        # Error message might be None or a string depending on processing
        self.assertTrue(error_message is None or isinstance(error_message, str))

    @patch('services.spotify_service.db')
    @patch('services.spotify_service.current_app')
    def test_get_listening_history_with_playlist_context_database_error(self, mock_app, mock_db):
        """Test get_listening_history_with_playlist_context with database error"""
        # Setup mocks
        mock_app.logger = Mock()
        
        # Mock database error on the first query (count query)
        count_query = Mock()
        count_query.filter.return_value.scalar.side_effect = Exception("Database connection error")
        mock_db.session.query.return_value = count_query
        
        result = get_listening_history_with_playlist_context(limit=5, offset=0)
        listening_data, total_count, error_message = result
        
        self.assertEqual(listening_data, [])
        self.assertEqual(total_count, 0)
        self.assertIn("Error retrieving listening history count", error_message)

    @patch('services.spotify_service.db')
    @patch('services.spotify_service.current_app')
    def test_get_listening_history_with_playlist_context_no_playlist(self, mock_app, mock_db):
        """Test get_listening_history_with_playlist_context with no KRUG FM playlist"""
        # Setup mocks
        mock_app.logger = Mock()
        
        # Create separate mocks for different queries
        count_query = Mock()
        count_query.filter.return_value.scalar.return_value = 3
        
        tracks_query = Mock()
        tracks_query.filter.return_value.order_by.return_value.limit.return_value.offset.return_value.all.return_value = self.mock_played_tracks[:3]
        
        playlist_date_query = Mock()
        playlist_date_query.filter.return_value.scalar.return_value = None
        
        # Mock db.session.query to return different mocks based on call order
        query_call_count = 0
        def mock_query(*args):
            nonlocal query_call_count
            query_call_count += 1
            if query_call_count == 1:  # First call for count
                return count_query
            elif query_call_count == 2:  # Second call for tracks
                return tracks_query
            else:  # Third call for playlist date
                return playlist_date_query
        
        mock_db.session.query.side_effect = mock_query
        
        result = get_listening_history_with_playlist_context(limit=5, offset=0)
        listening_data, total_count, error_message = result
        
        self.assertEqual(total_count, 3)
        self.assertEqual(len(listening_data), 3)
        self.assertIn("No KRUG FM 96.2 playlist found", error_message)
        
        # All tracks should be marked as not from KRUG playlist
        for track_data in listening_data:
            self.assertFalse(track_data['from_krug_playlist'])

    def test_get_listening_history_pagination_validation(self):
        """Test pagination parameter validation"""
        # Test with valid parameters
        with patch('services.spotify_service.db') as mock_db:
            with patch('services.spotify_service.current_app') as mock_app:
                mock_app.logger = Mock()
                mock_db.session.query.return_value.filter.return_value.scalar.return_value = 0
                mock_db.session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.offset.return_value.all.return_value = []
                
                # Test normal pagination
                result = get_listening_history_with_playlist_context(limit=50, offset=0)
                self.assertIsInstance(result, tuple)
                self.assertEqual(len(result), 3)
                
                # Test with different pagination
                result = get_listening_history_with_playlist_context(limit=25, offset=25)
                self.assertIsInstance(result, tuple)
                self.assertEqual(len(result), 3)

    def test_normalize_text_consistency(self):
        """Test that normalize_text produces consistent results for matching"""
        test_cases = [
            ("The Beatles", "beatles"),
            ("Led Zeppelin", "led zeppelin"),
            ("Pink Floyd", "pink floyd"),
            ("AC/DC", "acdc"),
            ("Guns N' Roses", "guns n roses"),
            ("Twenty One Pilots", "twenty one pilots"),
        ]
        
        for original, expected in test_cases:
            with self.subTest(original=original):
                result = normalize_text(original)
                self.assertEqual(result, expected)

    def test_error_handling_in_helper_functions(self):
        """Test error handling in helper functions"""
        # Test _format_track_data with invalid track
        invalid_track = Mock()
        invalid_track.id = None
        invalid_track.artist = None
        invalid_track.song = None
        invalid_track.played_at = None
        invalid_track.category = None
        invalid_track.playlist_name = None
        
        with patch('services.spotify_service.Track') as mock_track_model:
            mock_track_model.query.filter_by.side_effect = Exception("Database error")
            
            result = _format_track_data(invalid_track)
            
            # Should return safe defaults
            self.assertEqual(result['artist'], 'Unknown Artist')
            self.assertEqual(result['song'], 'Unknown Song')
            self.assertEqual(result['played_at_formatted'], 'Unknown')

    def test_context_analysis_edge_cases(self):
        """Test context analysis with edge cases"""
        # Test with empty surrounding tracks
        empty_surrounding = {'before': [], 'after': []}
        playlist_by_position = {1: {'artist': 'Test', 'song': 'Test'}}
        
        score, method = _analyze_position_context(
            1, empty_surrounding, playlist_by_position, self.base_time
        )
        
        self.assertEqual(score, 0)
        self.assertEqual(method, 'No context matches')
        
        # Test with invalid playlist data
        score, method = _analyze_position_context(
            1, empty_surrounding, {}, self.base_time
        )
        
        self.assertEqual(score, 0)
        self.assertIn("Invalid input data", method)


    def test_pagination_parameter_edge_cases(self):
        """Test pagination with various edge case parameters"""
        with patch('services.spotify_service.db') as mock_db:
            with patch('services.spotify_service.current_app') as mock_app:
                mock_app.logger = Mock()
                
                # Mock empty result
                count_query = Mock()
                count_query.filter.return_value.scalar.return_value = 0
                tracks_query = Mock()
                tracks_query.filter.return_value.order_by.return_value.limit.return_value.offset.return_value.all.return_value = []
                
                query_call_count = 0
                def mock_query(*args):
                    nonlocal query_call_count
                    query_call_count += 1
                    if query_call_count == 1:
                        return count_query
                    else:
                        return tracks_query
                
                mock_db.session.query.side_effect = mock_query
                
                # Test with zero limit
                result = get_listening_history_with_playlist_context(limit=0, offset=0)
                self.assertEqual(len(result), 3)  # Should return tuple
                
                # Test with large offset
                query_call_count = 0  # Reset counter
                result = get_listening_history_with_playlist_context(limit=50, offset=1000)
                self.assertEqual(len(result), 3)  # Should return tuple

    def test_playlist_correlation_with_special_characters(self):
        """Test playlist correlation with tracks containing special characters"""
        # Create tracks with special characters
        special_tracks = []
        special_track = Mock()
        special_track.id = 1
        special_track.artist = "AC/DC"
        special_track.song = "T.N.T."
        special_track.played_at = self.base_time
        special_track.category = "Rock"
        special_track.playlist_name = None
        special_track.spotify_id = "special_id_1"
        special_tracks.append(special_track)
        
        # Create matching playlist data
        special_playlist = []
        playlist_track = Mock()
        playlist_track.id = 1
        playlist_track.track_position = 1
        playlist_track.artist = "AC/DC"
        playlist_track.song = "T.N.T."
        playlist_track.playlist_name = "KRUG FM 96.2"
        playlist_track.playlist_date = self.base_time.date()
        special_playlist.append(playlist_track)
        
        with patch('services.spotify_service.db') as mock_db:
            with patch('services.spotify_service.current_app') as mock_app:
                mock_app.logger = Mock()
                
                # Setup database mocks
                count_query = Mock()
                count_query.filter.return_value.scalar.return_value = 1
                
                tracks_query = Mock()
                tracks_query.filter.return_value.order_by.return_value.limit.return_value.offset.return_value.all.return_value = special_tracks
                
                playlist_date_query = Mock()
                playlist_date_query.filter.return_value.scalar.return_value = self.base_time.date()
                
                playlist_data_query = Mock()
                playlist_data_query.filter.return_value.order_by.return_value.all.return_value = special_playlist
                
                query_call_count = 0
                def mock_query(*args):
                    nonlocal query_call_count
                    query_call_count += 1
                    if query_call_count == 1:
                        return count_query
                    elif query_call_count == 2:
                        return tracks_query
                    elif query_call_count == 3:
                        return playlist_date_query
                    else:
                        return playlist_data_query
                
                mock_db.session.query.side_effect = mock_query
                
                # Mock cache functions
                with patch('services.cache_service.get_cached_playlist_data', return_value=None):
                    with patch('services.cache_service.cache_playlist_data'):
                        with patch('services.cache_service.get_cached_playlist_lookup', return_value=None):
                            with patch('services.cache_service.cache_playlist_lookup'):
                                result = get_listening_history_with_playlist_context(limit=5, offset=0)
                
                listening_data, total_count, error_message = result
                
                self.assertEqual(total_count, 1)
                self.assertEqual(len(listening_data), 1)
                # Should find the track in playlist despite special characters
                self.assertTrue(listening_data[0]['from_krug_playlist'])

    def test_context_analysis_with_missing_played_at(self):
        """Test context analysis when some tracks have missing played_at timestamps"""
        # Create tracks with missing played_at
        tracks_with_missing_time = []
        for i in range(3):
            track = Mock()
            track.id = i + 1
            track.artist = f"Artist {i + 1}"
            track.song = f"Song {i + 1}"
            track.played_at = self.base_time + timedelta(minutes=i * 5) if i != 1 else None  # Middle track has no time
            track.category = "Test"
            track.playlist_name = None
            track.spotify_id = f"spotify_id_{i + 1}"
            tracks_with_missing_time.append(track)
        
        # Test surrounding tracks function
        result = _get_surrounding_tracks(tracks_with_missing_time, 1, window_size=1)
        self.assertIn('before', result)
        self.assertIn('after', result)
        self.assertEqual(len(result['before']), 1)
        self.assertEqual(len(result['after']), 1)

    def test_sequence_pattern_detection_edge_cases(self):
        """Test sequence pattern detection with various edge cases"""
        # Create minimal playlist
        minimal_playlist = {1: {'artist': 'Test Artist', 'song': 'Test Song'}}
        
        # Test with empty surrounding tracks
        empty_surrounding = {'before': [], 'after': []}
        score = _check_sequence_patterns(1, empty_surrounding, minimal_playlist)
        self.assertEqual(score, 0)
        
        # Test with None values
        score = _check_sequence_patterns(1, None, minimal_playlist)
        self.assertEqual(score, 0)
        
        # Test with invalid position
        score = _check_sequence_patterns(999, empty_surrounding, minimal_playlist)
        self.assertEqual(score, 0)

    def test_normalize_text_edge_cases(self):
        """Test normalize_text with various edge cases"""
        edge_cases = [
            ("", ""),
            (None, ""),
            ("   ", ""),
            ("THE BEATLES", "beatles"),
            ("A Day in the Life", "day in the life"),
            ("An American Pie", "american pie"),
            ("Song (feat. Artist)", "song feat artist"),
            ("Song ft. Artist", "song feat artist"),
            ("Song featuring Artist", "song feat artist"),
            ("Song & Artist", "song and artist"),
            ("Multiple   Spaces", "multiple spaces"),
            ("Punctuation!@#$%", "punctuation"),
        ]
        
        for input_text, expected in edge_cases:
            with self.subTest(input_text=input_text):
                result = normalize_text(input_text)
                self.assertEqual(result, expected)

    def test_track_data_formatting_with_missing_fields(self):
        """Test track data formatting when track has missing or None fields"""
        incomplete_track = Mock()
        incomplete_track.id = 1
        incomplete_track.artist = None
        incomplete_track.song = None
        incomplete_track.played_at = None
        incomplete_track.category = None
        incomplete_track.playlist_name = None
        incomplete_track.spotify_id = None
        
        with patch('services.spotify_service.Track') as mock_track_model:
            mock_track_model.query.filter_by.return_value.first.return_value = None
            
            result = _format_track_data(incomplete_track)
            
            # Should handle None values gracefully
            self.assertEqual(result['artist'], 'Unknown Artist')
            self.assertEqual(result['song'], 'Unknown Song')
            self.assertEqual(result['played_at_formatted'], 'Unknown')
            self.assertEqual(result['category'], 'Unknown')
            self.assertIsNone(result['playlist_name'])

    def test_performance_edge_cases(self):
        """Test performance-related edge cases"""
        # Test with very large mock dataset
        large_track_list = []
        for i in range(1000):  # Large number of tracks
            track = Mock()
            track.id = i + 1
            track.artist = f"Artist {i + 1}"
            track.song = f"Song {i + 1}"
            track.played_at = self.base_time + timedelta(minutes=i)
            large_track_list.append(track)
        
        # Test surrounding tracks with large dataset
        result = _get_surrounding_tracks(large_track_list, 500, window_size=10)
        self.assertEqual(len(result['before']), 10)
        self.assertEqual(len(result['after']), 10)
        
        # Test time period stats with large dataset
        stats = _get_time_period_stats(large_track_list)
        self.assertEqual(stats['total_tracks_in_period'], 1000)
        self.assertIsNotNone(stats['time_period_start'])
        self.assertIsNotNone(stats['time_period_end'])


if __name__ == '__main__':
    unittest.main()