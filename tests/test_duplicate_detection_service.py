"""
Unit tests for the Duplicate Detection Service.

Tests the core functionality of duplicate detection including similarity algorithms,
suffix detection patterns, and canonical version suggestion logic.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from services.duplicate_detection_service import DuplicateDetectionService, DuplicateGroup


class TestDuplicateDetectionService(unittest.TestCase):
    """Test cases for DuplicateDetectionService."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = DuplicateDetectionService()
        
        # Create mock tracks for testing
        self.track1 = Mock()
        self.track1.id = 1
        self.track1.song = "I Got"
        self.track1.artist = "Artist Name"
        self.track1.play_cnt = 10
        self.track1.last_play_dt = datetime.now() - timedelta(days=1)
        self.track1.date_added = datetime.now() - timedelta(days=30)
        
        self.track2 = Mock()
        self.track2.id = 2
        self.track2.song = "I Got - 2020 Remaster"
        self.track2.artist = "Artist Name"
        self.track2.play_cnt = 5
        self.track2.last_play_dt = datetime.now() - timedelta(days=5)
        self.track2.date_added = datetime.now() - timedelta(days=10)
        
        self.track3 = Mock()
        self.track3.id = 3
        self.track3.song = "I Got (Radio Edit)"
        self.track3.artist = "Artist Name"
        self.track3.play_cnt = 3
        self.track3.last_play_dt = datetime.now() - timedelta(days=10)
        self.track3.date_added = datetime.now() - timedelta(days=20)
        
        self.different_track = Mock()
        self.different_track.id = 4
        self.different_track.song = "Different Song"
        self.different_track.artist = "Different Artist"
        self.different_track.play_cnt = 15
        self.different_track.last_play_dt = datetime.now()
        self.different_track.date_added = datetime.now() - timedelta(days=5)
    
    def test_normalize_string_removes_remaster_suffix(self):
        """Test that normalize_string removes remaster suffixes."""
        test_cases = [
            ("I Got - 2020 Remaster", "i got"),
            ("Song Name - Remastered", "song name"),
            ("Track (Remaster 2021)", "track"),
            ("Music - Deluxe Edition", "music"),
            ("Hit Song (Radio Edit)", "hit song"),
            ("Original Track", "original track"),
        ]
        
        for input_str, expected in test_cases:
            with self.subTest(input_str=input_str):
                result = self.service.normalize_string(input_str)
                self.assertEqual(result, expected)
    
    def test_normalize_string_handles_empty_input(self):
        """Test that normalize_string handles empty or None input."""
        self.assertEqual(self.service.normalize_string(""), "")
        self.assertEqual(self.service.normalize_string(None), "")
        self.assertEqual(self.service.normalize_string("   "), "")
    
    def test_get_similarity_score_identical_songs(self):
        """Test similarity score for identical songs."""
        track_copy = Mock()
        track_copy.song = self.track1.song
        track_copy.artist = self.track1.artist
        
        score = self.service.get_similarity_score(self.track1, track_copy)
        self.assertEqual(score, 1.0)
    
    def test_get_similarity_score_similar_songs(self):
        """Test similarity score for similar songs with suffixes."""
        score = self.service.get_similarity_score(self.track1, self.track2)
        self.assertGreater(score, 0.8)  # Should be high similarity
        
        score2 = self.service.get_similarity_score(self.track1, self.track3)
        self.assertGreater(score2, 0.8)  # Should be high similarity
    
    def test_get_similarity_score_different_songs(self):
        """Test similarity score for completely different songs."""
        score = self.service.get_similarity_score(self.track1, self.different_track)
        self.assertLess(score, 0.3)  # Should be low similarity
    
    def test_get_similarity_score_handles_none_input(self):
        """Test that get_similarity_score handles None input gracefully."""
        self.assertEqual(self.service.get_similarity_score(None, self.track1), 0.0)
        self.assertEqual(self.service.get_similarity_score(self.track1, None), 0.0)
        self.assertEqual(self.service.get_similarity_score(None, None), 0.0)
    
    def test_detect_suffix_variations_true_cases(self):
        """Test suffix variation detection for positive cases."""
        # Test remaster variation
        self.assertTrue(self.service.detect_suffix_variations(self.track1, self.track2))
        
        # Test radio edit variation
        self.assertTrue(self.service.detect_suffix_variations(self.track1, self.track3))
    
    def test_detect_suffix_variations_false_cases(self):
        """Test suffix variation detection for negative cases."""
        # Different songs should not be detected as variations
        self.assertFalse(self.service.detect_suffix_variations(self.track1, self.different_track))
        
        # Test with different artists
        different_artist_track = Mock()
        different_artist_track.song = "I Got - 2020 Remaster"
        different_artist_track.artist = "Different Artist"
        self.assertFalse(self.service.detect_suffix_variations(self.track1, different_artist_track))
    
    def test_detect_suffix_variations_handles_none_input(self):
        """Test that detect_suffix_variations handles None input."""
        self.assertFalse(self.service.detect_suffix_variations(None, self.track1))
        self.assertFalse(self.service.detect_suffix_variations(self.track1, None))
        
        # Test with None song titles
        track_no_song = Mock()
        track_no_song.song = None
        track_no_song.artist = "Artist"
        self.assertFalse(self.service.detect_suffix_variations(self.track1, track_no_song))
    
    def test_suggest_canonical_version_by_play_count(self):
        """Test canonical version suggestion based on play count."""
        songs = [self.track1, self.track2, self.track3]  # play counts: 10, 5, 3
        canonical = self.service.suggest_canonical_version(songs)
        self.assertEqual(canonical.id, self.track1.id)  # Highest play count
    
    def test_suggest_canonical_version_by_title_length(self):
        """Test canonical version suggestion based on title length (shorter preferred)."""
        # Create tracks with same play count but different title lengths
        short_title = Mock()
        short_title.id = 10
        short_title.song = "Short"
        short_title.artist = "Artist"
        short_title.play_cnt = 5
        short_title.last_play_dt = datetime.now()
        short_title.date_added = datetime.now()
        
        long_title = Mock()
        long_title.id = 11
        long_title.song = "Short - Extended Deluxe Remastered Version"
        long_title.artist = "Artist"
        long_title.play_cnt = 5
        long_title.last_play_dt = datetime.now()
        long_title.date_added = datetime.now()
        
        songs = [long_title, short_title]
        canonical = self.service.suggest_canonical_version(songs)
        self.assertEqual(canonical.id, short_title.id)  # Shorter title preferred
    
    def test_suggest_canonical_version_handles_empty_list(self):
        """Test canonical version suggestion with empty list."""
        self.assertIsNone(self.service.suggest_canonical_version([]))
    
    def test_suggest_canonical_version_single_song(self):
        """Test canonical version suggestion with single song."""
        result = self.service.suggest_canonical_version([self.track1])
        self.assertEqual(result, self.track1)
    
    @patch('services.duplicate_detection_service.db')
    def test_find_duplicates_basic_functionality(self, mock_db):
        """Test basic duplicate finding functionality."""
        # Mock database session and query
        mock_session = MagicMock()
        mock_db.session = mock_session
        mock_db.or_ = Mock()
        
        # Mock query chain
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [self.track1, self.track2, self.track3, self.different_track]
        
        # Run the test
        result = self.service.find_duplicates()
        
        # Verify results
        self.assertIsInstance(result, list)
        # Should find one group with track1, track2, track3 as duplicates
        # and different_track should be separate
    
    @patch('services.duplicate_detection_service.db')
    def test_find_duplicates_with_search_term(self, mock_db):
        """Test duplicate finding with search term filtering."""
        # Mock database session and query
        mock_session = MagicMock()
        mock_db.session = mock_session
        mock_db.or_ = Mock()
        
        # Mock query chain
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [self.track1, self.track2]
        
        # Run the test with search term
        result = self.service.find_duplicates(search_term="I Got")
        
        # Verify that filter was called
        mock_query.filter.assert_called_once()
        self.assertIsInstance(result, list)
    
    def test_analyze_duplicate_group_basic_stats(self):
        """Test duplicate group analysis for basic statistics."""
        songs = [self.track1, self.track2, self.track3]
        analysis = self.service.analyze_duplicate_group(songs)
        
        # Check basic structure
        self.assertIn('total_songs', analysis)
        self.assertIn('canonical_suggestion', analysis)
        self.assertIn('play_count_stats', analysis)
        self.assertIn('date_range', analysis)
        self.assertIn('title_variations', analysis)
        self.assertIn('similarity_matrix', analysis)
        
        # Check values
        self.assertEqual(analysis['total_songs'], 3)
        self.assertEqual(analysis['play_count_stats']['total'], 18)  # 10 + 5 + 3
        self.assertEqual(analysis['play_count_stats']['max'], 10)
        self.assertEqual(analysis['play_count_stats']['min'], 3)
        self.assertEqual(analysis['play_count_stats']['avg'], 6.0)  # 18/3
    
    def test_analyze_duplicate_group_empty_list(self):
        """Test duplicate group analysis with empty list."""
        result = self.service.analyze_duplicate_group([])
        self.assertEqual(result, {})
    
    def test_analyze_duplicate_group_title_variations(self):
        """Test that title variations are correctly captured."""
        songs = [self.track1, self.track2, self.track3]
        analysis = self.service.analyze_duplicate_group(songs)
        
        expected_titles = ["I Got", "I Got - 2020 Remaster", "I Got (Radio Edit)"]
        self.assertEqual(set(analysis['title_variations']), set(expected_titles))
    
    def test_analyze_duplicate_group_similarity_matrix(self):
        """Test that similarity matrix is generated correctly."""
        songs = [self.track1, self.track2]
        analysis = self.service.analyze_duplicate_group(songs)
        
        # Should have entries for both directions
        self.assertIn('1-2', analysis['similarity_matrix'])
        self.assertIn('2-1', analysis['similarity_matrix'])
        
        # Similarity scores should be the same in both directions
        score_1_2 = analysis['similarity_matrix']['1-2']
        score_2_1 = analysis['similarity_matrix']['2-1']
        self.assertEqual(score_1_2, score_2_1)
        self.assertGreater(score_1_2, 0.8)  # Should be high similarity


class TestSuffixPatterns(unittest.TestCase):
    """Test cases for suffix pattern detection."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = DuplicateDetectionService()
    
    def test_remaster_patterns(self):
        """Test various remaster suffix patterns."""
        test_cases = [
            "Song - 2020 Remaster",
            "Song - Remastered",
            "Song - Remaster 2021",
            "Song (Remaster)",
            "Song (Remastered 2020)",
        ]
        
        for title in test_cases:
            with self.subTest(title=title):
                normalized = self.service.normalize_string(title)
                self.assertEqual(normalized, "song")
    
    def test_deluxe_patterns(self):
        """Test various deluxe edition patterns."""
        test_cases = [
            "Album - Deluxe Edition",
            "Album - Deluxe Version",
            "Album - Deluxe",
            "Album (Deluxe Edition)",
            "Album (Deluxe)",
        ]
        
        for title in test_cases:
            with self.subTest(title=title):
                normalized = self.service.normalize_string(title)
                self.assertEqual(normalized, "album")
    
    def test_radio_edit_patterns(self):
        """Test radio edit patterns."""
        test_cases = [
            "Song - Radio Edit",
            "Song (Radio Edit)",
        ]
        
        for title in test_cases:
            with self.subTest(title=title):
                normalized = self.service.normalize_string(title)
                self.assertEqual(normalized, "song")
    
    def test_featuring_patterns(self):
        """Test featuring artist patterns."""
        test_cases = [
            "Song (feat. Other Artist)",
            "Song (featuring Other Artist)",
            "Song (feat Other Artist)",
        ]
        
        for title in test_cases:
            with self.subTest(title=title):
                normalized = self.service.normalize_string(title)
                self.assertEqual(normalized, "song")
    
    def test_version_patterns(self):
        """Test various version patterns."""
        test_cases = [
            "Song - Extended Version",
            "Song - Single Version",
            "Song - Album Version",
            "Song - Live Version",
            "Song - Acoustic Version",
            "Song (Extended Mix)",
            "Song (Single Edit)",
            "Song (Live)",
            "Song (Acoustic)",
        ]
        
        for title in test_cases:
            with self.subTest(title=title):
                normalized = self.service.normalize_string(title)
                self.assertEqual(normalized, "song")
    
    def test_explicit_clean_patterns(self):
        """Test explicit/clean version patterns."""
        test_cases = [
            "Song - Explicit Version",
            "Song - Clean Version",
            "Song (Explicit)",
            "Song (Clean)",
        ]
        
        for title in test_cases:
            with self.subTest(title=title):
                normalized = self.service.normalize_string(title)
                self.assertEqual(normalized, "song")


class TestDuplicateGroupingAndAnalysis(unittest.TestCase):
    """Test cases for duplicate grouping and analysis functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = DuplicateDetectionService()
        
        # Create mock duplicate group
        self.canonical_track = Mock()
        self.canonical_track.id = 1
        self.canonical_track.song = "I Got"
        self.canonical_track.artist = "Artist Name"
        self.canonical_track.play_cnt = 10
        self.canonical_track.last_play_dt = datetime.now()
        self.canonical_track.date_added = datetime.now() - timedelta(days=30)
        
        self.duplicate1 = Mock()
        self.duplicate1.id = 2
        self.duplicate1.song = "I Got - 2020 Remaster"
        self.duplicate1.artist = "Artist Name"
        self.duplicate1.play_cnt = 5
        self.duplicate1.last_play_dt = datetime.now() - timedelta(days=5)
        self.duplicate1.date_added = datetime.now() - timedelta(days=10)
        
        self.duplicate2 = Mock()
        self.duplicate2.id = 3
        self.duplicate2.song = "I Got (Radio Edit)"
        self.duplicate2.artist = "Artist Name"
        self.duplicate2.play_cnt = 2
        self.duplicate2.last_play_dt = datetime.now() - timedelta(days=10)
        self.duplicate2.date_added = datetime.now() - timedelta(days=20)
        
        from services.duplicate_detection_service import DuplicateGroup
        self.duplicate_group = DuplicateGroup(
            canonical_song=self.canonical_track,
            duplicates=[self.duplicate1, self.duplicate2],
            similarity_scores={1: 1.0, 2: 0.95, 3: 0.92},
            suggested_action='keep_canonical'
        )
    
    def test_get_overall_analysis_with_groups(self):
        """Test overall analysis with duplicate groups."""
        duplicate_groups = [self.duplicate_group]
        analysis = self.service.get_overall_analysis(duplicate_groups)
        
        self.assertEqual(analysis.total_groups, 1)
        self.assertEqual(analysis.total_duplicates, 2)
        self.assertEqual(analysis.potential_deletions, 2)
        self.assertEqual(analysis.groups_with_high_confidence, 1)  # avg similarity > 0.9
        self.assertGreater(analysis.average_similarity_score, 0.9)
        self.assertIn("MB", analysis.estimated_space_savings)
    
    def test_get_overall_analysis_empty_groups(self):
        """Test overall analysis with empty groups list."""
        analysis = self.service.get_overall_analysis([])
        
        self.assertEqual(analysis.total_groups, 0)
        self.assertEqual(analysis.total_duplicates, 0)
        self.assertEqual(analysis.potential_deletions, 0)
        self.assertEqual(analysis.groups_with_high_confidence, 0)
        self.assertEqual(analysis.average_similarity_score, 0.0)
        self.assertEqual(analysis.estimated_space_savings, "0 MB")
    
    def test_get_duplicate_recommendations_basic(self):
        """Test basic duplicate recommendations."""
        recommendations = self.service.get_duplicate_recommendations(self.duplicate_group)
        
        # Check structure
        self.assertIn('keep_canonical', recommendations)
        self.assertIn('delete_candidates', recommendations)
        self.assertIn('manual_review_needed', recommendations)
        self.assertIn('risk_level', recommendations)
        
        # Check canonical recommendation
        self.assertEqual(recommendations['keep_canonical']['song'], self.canonical_track)
        self.assertEqual(recommendations['keep_canonical']['confidence'], 'high')
        
        # Check delete candidates
        self.assertEqual(len(recommendations['delete_candidates']), 2)
        
        # Should be low risk since similarities are high and play counts are reasonable
        self.assertEqual(recommendations['risk_level'], 'low')
    
    def test_get_duplicate_recommendations_high_risk_scenario(self):
        """Test recommendations for high-risk scenario (duplicate has more plays)."""
        # Create a scenario where duplicate has more plays than canonical
        high_play_duplicate = Mock()
        high_play_duplicate.id = 4
        high_play_duplicate.song = "I Got - Deluxe"
        high_play_duplicate.artist = "Artist Name"
        high_play_duplicate.play_cnt = 20  # More than canonical (10)
        high_play_duplicate.last_play_dt = datetime.now()
        high_play_duplicate.date_added = datetime.now() - timedelta(days=5)
        
        from services.duplicate_detection_service import DuplicateGroup
        risky_group = DuplicateGroup(
            canonical_song=self.canonical_track,
            duplicates=[high_play_duplicate],
            similarity_scores={1: 1.0, 4: 0.88},
            suggested_action='keep_canonical'
        )
        
        recommendations = self.service.get_duplicate_recommendations(risky_group)
        
        # Should flag as high risk and need manual review
        self.assertEqual(recommendations['risk_level'], 'high')
        self.assertTrue(recommendations['manual_review_needed'])
        
        # Check that the warning is in the reasons
        delete_candidate = recommendations['delete_candidates'][0]
        reasons = delete_candidate['reasons']
        warning_found = any('WARNING' in reason for reason in reasons)
        self.assertTrue(warning_found)
    
    def test_get_duplicate_recommendations_low_similarity(self):
        """Test recommendations for low similarity scenario."""
        # Create a scenario with low similarity
        low_sim_duplicate = Mock()
        low_sim_duplicate.id = 5
        low_sim_duplicate.song = "I Got Something"
        low_sim_duplicate.artist = "Artist Name"
        low_sim_duplicate.play_cnt = 3
        low_sim_duplicate.last_play_dt = datetime.now() - timedelta(days=15)
        low_sim_duplicate.date_added = datetime.now() - timedelta(days=25)
        
        from services.duplicate_detection_service import DuplicateGroup
        low_sim_group = DuplicateGroup(
            canonical_song=self.canonical_track,
            duplicates=[low_sim_duplicate],
            similarity_scores={1: 1.0, 5: 0.75},  # Low similarity
            suggested_action='keep_canonical'
        )
        
        recommendations = self.service.get_duplicate_recommendations(low_sim_group)
        
        # Should flag for manual review due to low similarity
        self.assertTrue(recommendations['manual_review_needed'])
        self.assertEqual(recommendations['risk_level'], 'medium')
        
        # Check that manual review is suggested in reasons
        delete_candidate = recommendations['delete_candidates'][0]
        reasons = delete_candidate['reasons']
        manual_review_found = any('manual review' in reason.lower() for reason in reasons)
        self.assertTrue(manual_review_found)
    
    def test_analyze_duplicate_group_comprehensive(self):
        """Test comprehensive duplicate group analysis."""
        songs = [self.canonical_track, self.duplicate1, self.duplicate2]
        analysis = self.service.analyze_duplicate_group(songs)
        
        # Verify all expected keys are present
        expected_keys = [
            'total_songs', 'canonical_suggestion', 'play_count_stats',
            'date_range', 'title_variations', 'similarity_matrix'
        ]
        for key in expected_keys:
            self.assertIn(key, analysis)
        
        # Verify play count statistics
        stats = analysis['play_count_stats']
        self.assertEqual(stats['total'], 17)  # 10 + 5 + 2
        self.assertEqual(stats['max'], 10)
        self.assertEqual(stats['min'], 2)
        self.assertAlmostEqual(stats['avg'], 17/3, places=2)
        
        # Verify title variations
        expected_titles = {"I Got", "I Got - 2020 Remaster", "I Got (Radio Edit)"}
        actual_titles = set(analysis['title_variations'])
        self.assertEqual(actual_titles, expected_titles)
        
        # Verify similarity matrix has entries
        self.assertGreater(len(analysis['similarity_matrix']), 0)
        
        # Verify canonical suggestion
        self.assertEqual(analysis['canonical_suggestion'], self.canonical_track)


if __name__ == '__main__':
    unittest.main()