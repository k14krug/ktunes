"""
Tests for duplicate persistence service age calculation and library change detection.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from services.duplicate_persistence_service import DuplicatePersistenceService
from models import DuplicateAnalysisResult, UserPreferences


class TestDuplicatePersistenceAgeDetection(unittest.TestCase):
    """Test age calculation and staleness detection functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = DuplicatePersistenceService()
    
    def test_get_staleness_level_fresh(self):
        """Test staleness level for fresh analysis (< 1 hour)."""
        # Create analysis result from 30 minutes ago
        analysis_result = MagicMock()
        analysis_result.created_at = datetime.now() - timedelta(minutes=30)
        
        staleness_level = self.service.get_staleness_level(analysis_result)
        self.assertEqual(staleness_level, 'fresh')
    
    def test_get_staleness_level_moderate(self):
        """Test staleness level for moderate analysis (1-24 hours)."""
        # Create analysis result from 12 hours ago
        analysis_result = MagicMock()
        analysis_result.created_at = datetime.now() - timedelta(hours=12)
        
        staleness_level = self.service.get_staleness_level(analysis_result)
        self.assertEqual(staleness_level, 'moderate')
    
    def test_get_staleness_level_stale(self):
        """Test staleness level for stale analysis (1-7 days)."""
        # Create analysis result from 3 days ago
        analysis_result = MagicMock()
        analysis_result.created_at = datetime.now() - timedelta(days=3)
        
        staleness_level = self.service.get_staleness_level(analysis_result)
        self.assertEqual(staleness_level, 'stale')
    
    def test_get_staleness_level_very_stale(self):
        """Test staleness level for very stale analysis (> 7 days)."""
        # Create analysis result from 10 days ago
        analysis_result = MagicMock()
        analysis_result.created_at = datetime.now() - timedelta(days=10)
        
        staleness_level = self.service.get_staleness_level(analysis_result)
        self.assertEqual(staleness_level, 'very_stale')
    
    def test_get_staleness_level_none(self):
        """Test staleness level for None analysis result."""
        staleness_level = self.service.get_staleness_level(None)
        self.assertEqual(staleness_level, 'very_stale')
    
    def test_get_analysis_age_info_fresh(self):
        """Test age info for fresh analysis."""
        # Create analysis result from 30 minutes ago
        analysis_result = MagicMock()
        analysis_result.created_at = datetime.now() - timedelta(minutes=30)
        
        age_info = self.service.get_analysis_age_info(analysis_result)
        
        self.assertEqual(age_info['staleness_level'], 'fresh')
        self.assertEqual(age_info['color_class'], 'text-success')
        self.assertEqual(age_info['icon'], 'fas fa-check-circle')
        self.assertFalse(age_info['needs_refresh'])
        self.assertIn('minutes ago', age_info['age_text'])
    
    def test_get_analysis_age_info_stale(self):
        """Test age info for stale analysis."""
        # Create analysis result from 3 days ago
        analysis_result = MagicMock()
        analysis_result.created_at = datetime.now() - timedelta(days=3)
        
        age_info = self.service.get_analysis_age_info(analysis_result)
        
        self.assertEqual(age_info['staleness_level'], 'stale')
        self.assertEqual(age_info['color_class'], 'text-warning')
        self.assertEqual(age_info['icon'], 'fas fa-exclamation-triangle')
        self.assertTrue(age_info['needs_refresh'])
        self.assertIn('days ago', age_info['age_text'])
    
    def test_is_analysis_stale_true(self):
        """Test is_analysis_stale returns True for old analysis."""
        # Create analysis result from 48 hours ago
        analysis_result = MagicMock()
        analysis_result.created_at = datetime.now() - timedelta(hours=48)
        
        is_stale = self.service.is_analysis_stale(analysis_result, staleness_hours=24)
        self.assertTrue(is_stale)
    
    def test_is_analysis_stale_false(self):
        """Test is_analysis_stale returns False for recent analysis."""
        # Create analysis result from 12 hours ago
        analysis_result = MagicMock()
        analysis_result.created_at = datetime.now() - timedelta(hours=12)
        
        is_stale = self.service.is_analysis_stale(analysis_result, staleness_hours=24)
        self.assertFalse(is_stale)
    
    @patch('services.duplicate_persistence_service.db.session')
    def test_get_library_change_summary(self, mock_session):
        """Test library change summary calculation."""
        # Mock analysis result from 2 days ago
        analysis_result = MagicMock()
        analysis_result.created_at = datetime.now() - timedelta(days=2)
        analysis_result.library_track_count = 1000
        
        # Mock database queries
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.count.side_effect = [1100, 50, 20]  # current_count, tracks_added, tracks_modified
        mock_query.filter.return_value = mock_query
        
        change_summary = self.service.get_library_change_summary(analysis_result)
        
        self.assertEqual(change_summary['current_track_count'], 1100)
        self.assertEqual(change_summary['last_analysis_track_count'], 1000)
        self.assertEqual(change_summary['tracks_added'], 50)
        self.assertEqual(change_summary['tracks_modified'], 20)
        self.assertEqual(change_summary['tracks_deleted'], 0)  # No tracks deleted in this scenario
        self.assertEqual(change_summary['total_changes'], 70)
        self.assertEqual(change_summary['change_percentage'], 7.0)
        self.assertTrue(change_summary['significant_change'])  # > 50 tracks is significant
    
    @patch('services.duplicate_persistence_service.db.session')
    def test_get_refresh_recommendations_high_urgency(self, mock_session):
        """Test refresh recommendations for high urgency scenario."""
        # Mock very stale analysis with significant library changes
        analysis_result = MagicMock()
        analysis_result.created_at = datetime.now() - timedelta(days=10)
        analysis_result.library_track_count = 1000
        
        # Mock database queries for significant library changes
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.count.side_effect = [1300, 200, 100]  # current_count, tracks_added, tracks_modified
        mock_query.filter.return_value = mock_query
        
        recommendations = self.service.get_refresh_recommendations(analysis_result)
        
        self.assertTrue(recommendations['should_refresh'])
        self.assertEqual(recommendations['urgency'], 'high')
        self.assertEqual(recommendations['suggested_action'], 'refresh')
        self.assertIn('very outdated', ' '.join(recommendations['reasons']))
        self.assertIn('strongly recommend', recommendations['message'])
    
    @patch('services.duplicate_persistence_service.db.session')
    def test_get_staleness_warnings(self, mock_session):
        """Test staleness warnings generation."""
        # Mock stale analysis
        analysis_result = MagicMock()
        analysis_result.created_at = datetime.now() - timedelta(days=2)
        analysis_result.library_track_count = 1000
        
        # Mock database queries
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.count.side_effect = [1150, 100, 50]  # current_count, tracks_added, tracks_modified
        mock_query.filter.return_value = mock_query
        
        warnings = self.service.get_staleness_warnings(analysis_result)
        
        self.assertTrue(warnings['has_warnings'])
        self.assertTrue(warnings['show_banner'])
        self.assertIsNotNone(warnings['age_warning'])
        self.assertIsNotNone(warnings['change_warning'])
        self.assertEqual(warnings['warning_level'], 'warning')
        self.assertTrue(len(warnings['suggested_actions']) > 0)


if __name__ == '__main__':
    unittest.main()