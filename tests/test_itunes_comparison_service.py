"""
Unit tests for the iTunes Comparison Service.

Tests the functionality of comparing duplicate songs with iTunes XML catalog,
including match finding, metadata comparison, and confidence scoring.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from services.itunes_comparison_service import (
    ITunesComparisonService, ITunesTrack, ITunesMatch, MetadataComparison
)
from services.duplicate_detection_service import DuplicateGroup


class TestITunesComparisonService(unittest.TestCase):
    """Test cases for ITunesComparisonService."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create mock tracks
        self.db_track = Mock()
        self.db_track.id = 1
        self.db_track.song = "I Got"
        self.db_track.artist = "Artist Name"
        self.db_track.album = "Test Album"
        self.db_track.play_cnt = 10
        self.db_track.last_play_dt = datetime.now() - timedelta(days=1)
        self.db_track.date_added = datetime.now() - timedelta(days=30)
        
        # Create mock iTunes track
        self.itunes_track = ITunesTrack(
            name="I Got",
            artist="Artist Name",
            album="Test Album",
            location="/path/to/song.mp3",
            play_count=12,
            last_played=datetime.now() - timedelta(days=2),
            date_added=datetime.now() - timedelta(days=25),
            genre="Pop"
        )
        
        # Create service with mocked library
        self.service = ITunesComparisonService()
        self.service.library = Mock()
        self.service.itunes_tracks_cache = {
            ("i got", "artist name"): self.itunes_track
        }
    
    def test_is_available_with_library(self):
        """Test is_available returns True when library is loaded."""
        self.assertTrue(self.service.is_available())
    
    def test_is_available_without_library(self):
        """Test is_available returns False when library is not loaded."""
        service = ITunesComparisonService()
        service.library = None
        service.itunes_tracks_cache = {}
        self.assertFalse(service.is_available())
    
    def test_find_itunes_match_exact(self):
        """Test finding exact iTunes match."""
        match = self.service.find_itunes_match(self.db_track)
        
        self.assertTrue(match.found)
        self.assertEqual(match.match_type, 'exact')
        self.assertEqual(match.confidence_score, 1.0)
        self.assertEqual(match.itunes_track.name, "I Got")
        self.assertEqual(match.itunes_track.artist, "Artist Name")
    
    def test_find_itunes_match_no_match(self):
        """Test finding iTunes match when no match exists."""
        no_match_track = Mock()
        no_match_track.song = "Nonexistent Song"
        no_match_track.artist = "Unknown Artist"
        
        match = self.service.find_itunes_match(no_match_track)
        
        self.assertFalse(match.found)
        self.assertEqual(match.match_type, 'none')
        self.assertEqual(match.confidence_score, 0.0)
        self.assertIsNone(match.itunes_track)
    
    def test_find_itunes_match_fuzzy(self):
        """Test finding fuzzy iTunes match."""
        # Add a similar track to cache for fuzzy matching
        similar_itunes_track = ITunesTrack(
            name="I Got You",
            artist="Artist Name",
            album="Test Album",
            location="/path/to/song2.mp3",
            play_count=8,
            last_played=datetime.now() - timedelta(days=3),
            date_added=datetime.now() - timedelta(days=20),
            genre="Pop"
        )
        self.service.itunes_tracks_cache[("i got you", "artist name")] = similar_itunes_track
        
        fuzzy_track = Mock()
        fuzzy_track.song = "I Got U"  # Similar but not exact
        fuzzy_track.artist = "Artist Name"
        
        match = self.service.find_itunes_match(fuzzy_track)
        
        # Should find the fuzzy match
        self.assertTrue(match.found)
        self.assertEqual(match.match_type, 'fuzzy')
        self.assertGreater(match.confidence_score, 0.8)
        self.assertEqual(match.itunes_track.name, "I Got You")
    
    def test_find_itunes_match_invalid_input(self):
        """Test finding iTunes match with invalid input."""
        invalid_track = Mock()
        invalid_track.song = None
        invalid_track.artist = None
        
        match = self.service.find_itunes_match(invalid_track)
        
        self.assertFalse(match.found)
        self.assertEqual(match.match_type, 'none')
    
    def test_get_itunes_metadata_found(self):
        """Test getting iTunes metadata when track exists."""
        metadata = self.service.get_itunes_metadata("I Got", "Artist Name")
        
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.name, "I Got")
        self.assertEqual(metadata.artist, "Artist Name")
        self.assertEqual(metadata.genre, "Pop")
    
    def test_get_itunes_metadata_not_found(self):
        """Test getting iTunes metadata when track doesn't exist."""
        metadata = self.service.get_itunes_metadata("Nonexistent", "Unknown")
        
        self.assertIsNone(metadata)
    
    def test_compare_metadata_identical(self):
        """Test metadata comparison with identical tracks."""
        # Create identical iTunes track
        identical_itunes = ITunesTrack(
            name=self.db_track.song,
            artist=self.db_track.artist,
            album=self.db_track.album,
            location="/path/to/song.mp3",
            play_count=self.db_track.play_cnt,
            last_played=self.db_track.last_play_dt,
            date_added=self.db_track.date_added,
            genre="Pop"
        )
        
        comparison = self.service.compare_metadata(self.db_track, identical_itunes)
        
        self.assertEqual(len(comparison.differences), 0)
        self.assertGreater(len(comparison.similarities), 0)
        self.assertGreater(comparison.confidence_score, 0.8)
        self.assertIn("High confidence", comparison.recommendation)
    
    def test_compare_metadata_different(self):
        """Test metadata comparison with different tracks."""
        different_itunes = ITunesTrack(
            name="Different Song",
            artist="Different Artist",
            album="Different Album",
            location="/path/to/different.mp3",
            play_count=50,
            last_played=datetime.now(),
            date_added=datetime.now(),
            genre="Rock"
        )
        
        comparison = self.service.compare_metadata(self.db_track, different_itunes)
        
        self.assertGreater(len(comparison.differences), 0)
        self.assertLess(comparison.confidence_score, 0.5)
        self.assertIn("Low confidence", comparison.recommendation)
    
    def test_find_itunes_matches_duplicate_group(self):
        """Test finding iTunes matches for a duplicate group."""
        # Create duplicate group
        duplicate1 = Mock()
        duplicate1.id = 2
        duplicate1.song = "I Got - Remaster"
        duplicate1.artist = "Artist Name"
        
        duplicate_group = DuplicateGroup(
            canonical_song=self.db_track,
            duplicates=[duplicate1],
            similarity_scores={1: 1.0, 2: 0.95},
            suggested_action='keep_canonical'
        )
        
        matches = self.service.find_itunes_matches(duplicate_group)
        
        # Should have matches for both tracks
        self.assertIn(self.db_track.id, matches)
        self.assertIn(duplicate1.id, matches)
        
        # Canonical should have exact match
        canonical_match = matches[self.db_track.id]
        self.assertTrue(canonical_match.found)
        self.assertEqual(canonical_match.match_type, 'exact')
    
    def test_get_itunes_statistics_available(self):
        """Test getting iTunes statistics when library is available."""
        stats = self.service.get_itunes_statistics()
        
        self.assertTrue(stats['available'])
        self.assertEqual(stats['total_tracks'], 1)
        self.assertIn('tracks_with_play_count', stats)
        self.assertIn('tracks_with_last_played', stats)
        self.assertIn('unique_genres', stats)
        self.assertIn('top_genres', stats)
    
    def test_get_itunes_statistics_unavailable(self):
        """Test getting iTunes statistics when library is unavailable."""
        service = ITunesComparisonService()
        service.library = None
        service.itunes_tracks_cache = {}
        
        stats = service.get_itunes_statistics()
        
        self.assertFalse(stats['available'])
        self.assertEqual(stats['total_tracks'], 0)
        self.assertIn('error', stats)


class TestITunesDataObjects(unittest.TestCase):
    """Test cases for iTunes data transfer objects."""
    
    def test_itunes_track_creation(self):
        """Test creating ITunesTrack object."""
        track = ITunesTrack(
            name="Test Song",
            artist="Test Artist",
            album="Test Album",
            location="/path/to/song.mp3",
            play_count=5,
            last_played=datetime.now(),
            date_added=datetime.now() - timedelta(days=10),
            genre="Pop"
        )
        
        self.assertEqual(track.name, "Test Song")
        self.assertEqual(track.artist, "Test Artist")
        self.assertEqual(track.genre, "Pop")
        self.assertEqual(track.play_count, 5)
    
    def test_itunes_match_creation(self):
        """Test creating ITunesMatch object."""
        track = ITunesTrack(
            name="Test Song",
            artist="Test Artist",
            album=None,
            location=None,
            play_count=None,
            last_played=None,
            date_added=None,
            genre=None
        )
        
        match = ITunesMatch(
            found=True,
            itunes_track=track,
            confidence_score=0.95,
            metadata_differences=["Play count: 10 vs 5"],
            match_type='fuzzy'
        )
        
        self.assertTrue(match.found)
        self.assertEqual(match.confidence_score, 0.95)
        self.assertEqual(match.match_type, 'fuzzy')
        self.assertEqual(len(match.metadata_differences), 1)
    
    def test_metadata_comparison_creation(self):
        """Test creating MetadataComparison object."""
        comparison = MetadataComparison(
            differences=["Song title: 'A' vs 'B'"],
            similarities=["Artist matches"],
            confidence_score=0.75,
            recommendation="Good match"
        )
        
        self.assertEqual(len(comparison.differences), 1)
        self.assertEqual(len(comparison.similarities), 1)
        self.assertEqual(comparison.confidence_score, 0.75)
        self.assertEqual(comparison.recommendation, "Good match")


class TestITunesServiceIntegration(unittest.TestCase):
    """Integration tests for iTunes service functionality."""
    
    @patch('services.itunes_comparison_service.ITunesXMLParser')
    @patch('os.path.exists')
    def test_initialization_with_valid_path(self, mock_exists, mock_parser):
        """Test service initialization with valid XML path."""
        mock_exists.return_value = True
        mock_library = Mock()
        mock_library.songs = {
            1: Mock(name="Test Song", artist="Test Artist", album="Test Album",
                   location="/path", play_count=5, lastplayed=None, date_added=None, genre="Pop")
        }
        mock_parser_instance = Mock()
        mock_parser_instance.library = mock_library
        mock_parser.return_value = mock_parser_instance
        
        service = ITunesComparisonService("/fake/path/to/library.xml")
        
        self.assertIsNotNone(service.library)
        mock_parser.assert_called_once_with("/fake/path/to/library.xml")
    
    @patch('os.path.exists')
    def test_initialization_with_invalid_path(self, mock_exists):
        """Test service initialization with invalid XML path."""
        mock_exists.return_value = False
        
        service = ITunesComparisonService("/fake/invalid/path.xml")
        
        self.assertIsNone(service.library)
        self.assertEqual(len(service.itunes_tracks_cache), 0)
    
    @patch('services.itunes_comparison_service.load_config')
    @patch('os.path.exists')
    def test_initialization_from_config(self, mock_exists, mock_load_config):
        """Test service initialization using application config."""
        mock_exists.return_value = False
        mock_load_config.return_value = {
            'itunes_dir': '/fake/dir',
            'itunes_lib': 'library.xml'
        }
        
        service = ITunesComparisonService()
        
        # Should attempt to load from config path
        mock_load_config.assert_called_once()
        self.assertEqual(service.xml_path, '/fake/dir/library.xml')


if __name__ == '__main__':
    unittest.main()
clas
s TestEnhancedMetadataComparison(unittest.TestCase):
    """Test cases for enhanced metadata comparison functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = ITunesComparisonService()
        self.service.library = Mock()
        self.service.itunes_tracks_cache = {}
        
        # Create test tracks
        self.db_track = Mock()
        self.db_track.id = 1
        self.db_track.song = "Test Song"
        self.db_track.artist = "Test Artist"
        self.db_track.album = "Test Album"
        self.db_track.play_cnt = 10
        self.db_track.last_play_dt = datetime.now() - timedelta(days=5)
        self.db_track.date_added = datetime.now() - timedelta(days=30)
        self.db_track.location = "/path/to/db/song.mp3"
        self.db_track.category = "Pop"
    
    def test_compare_metadata_with_warnings(self):
        """Test metadata comparison that generates warnings."""
        # Create iTunes track with significantly different play count
        itunes_track = ITunesTrack(
            name="Test Song",
            artist="Test Artist",
            album="Test Album",
            location="/path/to/itunes/song.mp3",
            play_count=100,  # Much higher than db_track (10)
            last_played=datetime.now() - timedelta(days=5),
            date_added=datetime.now() - timedelta(days=30),
            genre="Rock"  # Different from db category
        )
        
        comparison = self.service.compare_metadata(self.db_track, itunes_track)
        
        # Should have warnings about large play count difference
        warning_found = any("WARNING" in diff for diff in comparison.differences)
        self.assertTrue(warning_found)
        
        # Should still have some similarities
        self.assertGreater(len(comparison.similarities), 0)
        
        # Confidence should be reduced due to warnings
        self.assertLess(comparison.confidence_score, 0.8)
    
    def test_compare_metadata_with_date_tolerance(self):
        """Test metadata comparison with date tolerance."""
        # Create iTunes track with dates within tolerance
        itunes_track = ITunesTrack(
            name="Test Song",
            artist="Test Artist",
            album="Test Album",
            location="/path/to/song.mp3",
            play_count=10,
            last_played=self.db_track.last_play_dt + timedelta(hours=12),  # Same day
            date_added=self.db_track.date_added + timedelta(hours=6),  # Same day
            genre="Pop"
        )
        
        comparison = self.service.compare_metadata(self.db_track, itunes_track)
        
        # Should recognize dates as matching within tolerance
        date_matches = [s for s in comparison.similarities if "date" in s.lower()]
        self.assertGreater(len(date_matches), 0)
        
        # Should have high confidence
        self.assertGreater(comparison.confidence_score, 0.8)
    
    def test_compare_metadata_null_safety(self):
        """Test metadata comparison with null/empty values."""
        # Create track with null values
        null_db_track = Mock()
        null_db_track.song = None
        null_db_track.artist = ""
        null_db_track.album = None
        null_db_track.play_cnt = None
        null_db_track.last_play_dt = None
        null_db_track.date_added = None
        
        itunes_track = ITunesTrack(
            name="Test Song",
            artist="Test Artist",
            album=None,
            location=None,
            play_count=None,
            last_played=None,
            date_added=None,
            genre=None
        )
        
        # Should not crash with null values
        comparison = self.service.compare_metadata(null_db_track, itunes_track)
        
        self.assertIsInstance(comparison, MetadataComparison)
        self.assertIsInstance(comparison.differences, list)
        self.assertIsInstance(comparison.similarities, list)
        self.assertIsInstance(comparison.confidence_score, float)
    
    def test_validate_itunes_connection_success(self):
        """Test iTunes connection validation when everything is working."""
        # Mock successful setup
        self.service.xml_path = "/fake/path/library.xml"
        self.service.library = Mock()
        self.service.itunes_tracks_cache = {
            ("song1", "artist1"): ITunesTrack("Song1", "Artist1", None, None, None, None, None, None)
        }
        
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getmtime', return_value=datetime.now().timestamp()):
            
            validation = self.service.validate_itunes_connection()
            
            self.assertTrue(validation['valid'])
            self.assertEqual(len(validation['errors']), 0)
            self.assertGreater(len(validation['info']), 0)
    
    def test_validate_itunes_connection_missing_file(self):
        """Test iTunes connection validation when XML file is missing."""
        self.service.xml_path = "/nonexistent/path.xml"
        self.service.library = None
        
        with patch('os.path.exists', return_value=False):
            validation = self.service.validate_itunes_connection()
            
            self.assertFalse(validation['valid'])
            self.assertGreater(len(validation['errors']), 0)
            self.assertIn("not found", validation['errors'][0])
    
    def test_get_match_confidence_factors_exact_match(self):
        """Test confidence factors for exact match."""
        # Create exact match
        itunes_track = ITunesTrack(
            name=self.db_track.song,
            artist=self.db_track.artist,
            album=self.db_track.album,
            location="/path/to/song.mp3",
            play_count=self.db_track.play_cnt,
            last_played=self.db_track.last_play_dt,
            date_added=self.db_track.date_added,
            genre="Pop"
        )
        
        itunes_match = ITunesMatch(
            found=True,
            itunes_track=itunes_track,
            confidence_score=1.0,
            metadata_differences=[],
            match_type='exact'
        )
        
        factors = self.service.get_match_confidence_factors(self.db_track, itunes_match)
        
        self.assertGreater(factors['overall_confidence'], 0.9)
        self.assertIn('match_type', factors['confidence_components'])
        self.assertGreater(len(factors['factors']), 0)
        self.assertEqual(len(factors['concerns']), 0)
        self.assertIn("Very high confidence", factors['recommendation'])
    
    def test_get_match_confidence_factors_no_match(self):
        """Test confidence factors when no match is found."""
        no_match = ITunesMatch(
            found=False,
            itunes_track=None,
            confidence_score=0.0,
            metadata_differences=[],
            match_type='none'
        )
        
        factors = self.service.get_match_confidence_factors(self.db_track, no_match)
        
        self.assertEqual(factors['overall_confidence'], 0.0)
        self.assertGreater(len(factors['concerns']), 0)
        self.assertEqual(factors['recommendation'], 'No match available')
    
    def test_get_match_confidence_factors_fuzzy_match(self):
        """Test confidence factors for fuzzy match with some differences."""
        # Create fuzzy match with some differences
        itunes_track = ITunesTrack(
            name="Test Song - Remaster",  # Slightly different title
            artist=self.db_track.artist,
            album=self.db_track.album,
            location="/path/to/song.mp3",
            play_count=50,  # Different play count
            last_played=self.db_track.last_play_dt + timedelta(days=10),  # Different date
            date_added=self.db_track.date_added,
            genre="Pop"
        )
        
        itunes_match = ITunesMatch(
            found=True,
            itunes_track=itunes_track,
            confidence_score=0.85,
            metadata_differences=["Play count: 10 vs 50"],
            match_type='fuzzy'
        )
        
        factors = self.service.get_match_confidence_factors(self.db_track, itunes_match)
        
        # Should have moderate confidence due to differences
        self.assertGreater(factors['overall_confidence'], 0.5)
        self.assertLess(factors['overall_confidence'], 0.9)
        
        # Should have both factors and concerns
        self.assertGreater(len(factors['factors']), 0)
        self.assertGreater(len(factors['concerns']), 0)
        
        # Should include fuzzy match information
        fuzzy_factor = any("Fuzzy match" in factor for factor in factors['factors'])
        self.assertTrue(fuzzy_factor)


if __name__ == '__main__':
    unittest.main()