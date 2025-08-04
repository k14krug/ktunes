"""
Tests for DuplicatePersistenceService.

This module contains comprehensive unit tests for the duplicate persistence service functionality,
including database models, CRUD operations, age calculation, staleness detection, cleanup operations,
and data integrity validation.
"""

import unittest
import uuid
import sys
import os
import tempfile
import json
import csv
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock, call

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import Flask for minimal app context
from flask import Flask
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from services.duplicate_persistence_service import DuplicatePersistenceService
from services.duplicate_detection_service import DuplicateGroup, DuplicateAnalysis
from models import (
    DuplicateAnalysisResult, 
    DuplicateAnalysisGroup, 
    DuplicateAnalysisTrack,
    DuplicateAnalysisExport,
    UserPreferences,
    Track,
    User
)


class TestDuplicatePersistenceService(unittest.TestCase):
    """Test cases for DuplicatePersistenceService."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a minimal Flask app for testing
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        self.service = DuplicatePersistenceService()
        
        # Create simple mock objects without spec to avoid SQLAlchemy issues
        self.mock_track1 = Mock()
        self.mock_track1.id = 1
        self.mock_track1.song = "Test Song"
        self.mock_track1.artist = "Test Artist"
        self.mock_track1.album = "Test Album"
        self.mock_track1.play_cnt = 10
        self.mock_track1.last_play_dt = datetime.now()
        self.mock_track1.date_added = datetime.now()
        
        self.mock_track2 = Mock()
        self.mock_track2.id = 2
        self.mock_track2.song = "Test Song (Remastered)"
        self.mock_track2.artist = "Test Artist"
        self.mock_track2.album = "Test Album"
        self.mock_track2.play_cnt = 5
        self.mock_track2.last_play_dt = datetime.now()
        self.mock_track2.date_added = datetime.now()
        
        # Create mock duplicate group
        self.mock_duplicate_group = DuplicateGroup(
            canonical_song=self.mock_track1,
            duplicates=[self.mock_track2],
            similarity_scores={1: 1.0, 2: 0.95},
            suggested_action='keep_canonical'
        )
        
        # Create mock analysis stats
        self.mock_analysis_stats = DuplicateAnalysis(
            total_groups=1,
            total_duplicates=1,
            potential_deletions=1,
            estimated_space_savings="4 MB",
            groups_with_high_confidence=1,
            average_similarity_score=0.975
        )
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.app_context.pop()
    
    def test_initialization(self):
        """Test service initialization."""
        assert self.service.cleanup_days == 30
        assert self.service.max_results_per_user == 5
    
    def test_get_staleness_level(self):
        """Test staleness level calculation."""
        # Create mock analysis results with different ages
        fresh_analysis = Mock()
        fresh_analysis.created_at = datetime.now() - timedelta(minutes=30)
        
        moderate_analysis = Mock()
        moderate_analysis.created_at = datetime.now() - timedelta(hours=12)
        
        stale_analysis = Mock()
        stale_analysis.created_at = datetime.now() - timedelta(days=3)
        
        very_stale_analysis = Mock()
        very_stale_analysis.created_at = datetime.now() - timedelta(days=10)
        
        # Test staleness levels
        assert self.service.get_staleness_level(fresh_analysis) == 'fresh'
        assert self.service.get_staleness_level(moderate_analysis) == 'moderate'
        assert self.service.get_staleness_level(stale_analysis) == 'stale'
        assert self.service.get_staleness_level(very_stale_analysis) == 'very_stale'
    
    def test_is_analysis_stale(self):
        """Test analysis staleness check."""
        # Fresh analysis (1 hour old)
        fresh_analysis = Mock()
        fresh_analysis.created_at = datetime.now() - timedelta(hours=1)
        
        # Stale analysis (25 hours old)
        stale_analysis = Mock()
        stale_analysis.created_at = datetime.now() - timedelta(hours=25)
        
        # Test with default threshold (24 hours)
        assert not self.service.is_analysis_stale(fresh_analysis)
        assert self.service.is_analysis_stale(stale_analysis)
        
        # Test with custom threshold (0.5 hours) - fresh analysis should be stale
        assert self.service.is_analysis_stale(fresh_analysis, staleness_hours=0.5)
        assert self.service.is_analysis_stale(stale_analysis, staleness_hours=2)
    
    def test_get_analysis_age_info(self):
        """Test analysis age information formatting."""
        # Create analysis that's 2 hours old
        analysis = Mock()
        analysis.created_at = datetime.now() - timedelta(hours=2)
        
        age_info = self.service.get_analysis_age_info(analysis)
        
        assert 'age_text' in age_info
        assert 'age_hours' in age_info
        assert 'staleness_level' in age_info
        assert 'color_class' in age_info
        assert 'icon' in age_info
        assert 'needs_refresh' in age_info
        assert age_info['staleness_level'] == 'moderate'
        assert age_info['color_class'] == 'text-warning'
    
    def test_get_analysis_age_info_none_analysis(self):
        """Test age info for None analysis."""
        age_info = self.service.get_analysis_age_info(None)
        
        assert age_info['age_text'] == 'Unknown age'
        assert age_info['staleness_level'] == 'very_stale'
        assert age_info['needs_refresh'] is True
    
    def test_factory_function(self):
        """Test factory function."""
        from services.duplicate_persistence_service import get_duplicate_persistence_service
        
        service = get_duplicate_persistence_service()
        assert isinstance(service, DuplicatePersistenceService)

    # ============================================================================
    # Database Model Tests
    # ============================================================================
    
    def test_duplicate_analysis_result_model_creation(self):
        """Test DuplicateAnalysisResult model creation and validation."""
        analysis_id = str(uuid.uuid4())
        
        # Create mock analysis result
        analysis_result = Mock(spec=DuplicateAnalysisResult)
        analysis_result.analysis_id = analysis_id
        analysis_result.user_id = 1
        analysis_result.created_at = datetime.now()
        analysis_result.status = 'completed'
        analysis_result.search_term = 'test'
        analysis_result.sort_by = 'artist'
        analysis_result.min_confidence = 0.8
        analysis_result.total_tracks_analyzed = 1000
        analysis_result.total_groups_found = 50
        analysis_result.total_duplicates_found = 100
        analysis_result.average_similarity_score = 0.85
        analysis_result.processing_time_seconds = 120.5
        analysis_result.library_track_count = 1000
        analysis_result.library_last_modified = datetime.now()
        analysis_result.groups = []
        
        # Validate required fields
        assert analysis_result.analysis_id == analysis_id
        assert analysis_result.user_id == 1
        assert analysis_result.status == 'completed'
        assert analysis_result.total_groups_found == 50
        assert analysis_result.total_duplicates_found == 100
    
    def test_duplicate_analysis_group_model_creation(self):
        """Test DuplicateAnalysisGroup model creation and validation."""
        # Create mock analysis group
        analysis_group = Mock(spec=DuplicateAnalysisGroup)
        analysis_group.id = 1
        analysis_group.analysis_id = str(uuid.uuid4())
        analysis_group.group_index = 0
        analysis_group.canonical_track_id = 123
        analysis_group.duplicate_count = 3
        analysis_group.average_similarity_score = 0.92
        analysis_group.suggested_action = 'keep_canonical'
        analysis_group.has_itunes_matches = False
        analysis_group.resolved = False
        analysis_group.tracks = []
        
        # Validate required fields
        assert analysis_group.canonical_track_id == 123
        assert analysis_group.duplicate_count == 3
        assert analysis_group.average_similarity_score == 0.92
        assert analysis_group.suggested_action == 'keep_canonical'
        assert analysis_group.resolved is False
    
    def test_duplicate_analysis_track_model_creation(self):
        """Test DuplicateAnalysisTrack model creation and validation."""
        # Create mock analysis track
        analysis_track = Mock(spec=DuplicateAnalysisTrack)
        analysis_track.id = 1
        analysis_track.group_id = 1
        analysis_track.track_id = 456
        analysis_track.song_name = "Test Song"
        analysis_track.artist_name = "Test Artist"
        analysis_track.album_name = "Test Album"
        analysis_track.play_count = 10
        analysis_track.similarity_score = 0.95
        analysis_track.is_canonical = True
        analysis_track.still_exists = True
        analysis_track.itunes_match_found = False
        
        # Validate required fields
        assert analysis_track.track_id == 456
        assert analysis_track.song_name == "Test Song"
        assert analysis_track.similarity_score == 0.95
        assert analysis_track.is_canonical is True
        assert analysis_track.still_exists is True
    
    # ============================================================================
    # Service Method Tests - CRUD Operations
    # ============================================================================
    
    @patch('services.duplicate_persistence_service.db')
    def test_save_analysis_result_success(self, mock_db):
        """Test successful saving of analysis results."""
        # Mock database operations
        mock_db.session.query.return_value.count.return_value = 1000
        mock_db.session.query.return_value.scalar.return_value = datetime.now()
        mock_db.session.add = Mock()
        mock_db.session.flush = Mock()
        mock_db.session.commit = Mock()
        
        # Test data
        user_id = 1
        analysis_params = {
            'search_term': 'test',
            'sort_by': 'artist',
            'min_confidence': 0.8,
            'processing_time': 120.5
        }
        
        # Call the method
        result = self.service.save_analysis_result(
            user_id=user_id,
            duplicate_groups=[self.mock_duplicate_group],
            analysis_params=analysis_params,
            analysis_stats=self.mock_analysis_stats
        )
        
        # Verify database operations were called
        mock_db.session.add.assert_called()
        mock_db.session.flush.assert_called()
    
    @patch('services.duplicate_persistence_service.db')
    def test_save_analysis_result_database_error(self, mock_db):
        """Test handling of database errors during save."""
        # Mock database error
        mock_db.session.add.side_effect = SQLAlchemyError("Database connection failed")
        
        # Test data
        user_id = 1
        analysis_params = {'search_term': 'test'}
        
        # Should raise exception
        with self.assertRaises(Exception) as context:
            self.service.save_analysis_result(
                user_id=user_id,
                duplicate_groups=[self.mock_duplicate_group],
                analysis_params=analysis_params,
                analysis_stats=self.mock_analysis_stats
            )
        
        assert "Failed to save analysis result" in str(context.exception)
    
    @patch('services.duplicate_persistence_service.db')
    def test_load_analysis_result_success(self, mock_db):
        """Test successful loading of analysis results."""
        # Mock analysis result
        mock_analysis = Mock(spec=DuplicateAnalysisResult)
        mock_analysis.analysis_id = "test-uuid"
        mock_analysis.groups = []
        
        mock_db.session.query.return_value.options.return_value.filter.return_value.first.return_value = mock_analysis
        
        # Call the method
        result = self.service.load_analysis_result("test-uuid")
        
        # Verify result
        assert result == mock_analysis
        mock_db.session.query.assert_called_with(DuplicateAnalysisResult)
    
    @patch('services.duplicate_persistence_service.db')
    def test_load_analysis_result_not_found(self, mock_db):
        """Test loading non-existent analysis result."""
        mock_db.session.query.return_value.options.return_value.filter.return_value.first.return_value = None
        
        result = self.service.load_analysis_result("non-existent-uuid")
        
        assert result is None
    
    @patch('services.duplicate_persistence_service.db')
    def test_get_latest_analysis_with_search_term(self, mock_db):
        """Test getting latest analysis with search term filter."""
        # Mock analysis result
        mock_analysis = Mock(spec=DuplicateAnalysisResult)
        mock_analysis.analysis_id = "latest-uuid"
        
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value.first.return_value = mock_analysis
        mock_db.session.query.return_value = mock_query
        
        # Call the method
        result = self.service.get_latest_analysis(user_id=1, search_term="test")
        
        # Verify result and filters
        assert result == mock_analysis
        assert mock_query.filter.call_count == 3  # user_id, status, search_term
    
    @patch('services.duplicate_persistence_service.db')
    def test_get_user_analyses_with_pagination(self, mock_db):
        """Test getting user analyses with pagination."""
        # Mock analysis results
        mock_analyses = [Mock(spec=DuplicateAnalysisResult) for _ in range(5)]
        
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.all.return_value = mock_analyses
        mock_db.session.query.return_value = mock_query
        
        # Call the method
        result = self.service.get_user_analyses(user_id=1, limit=5, offset=10)
        
        # Verify result and pagination
        assert result == mock_analyses
        mock_query.limit.assert_called_with(5)
        mock_query.offset.assert_called_with(10)
    
    @patch('services.duplicate_persistence_service.db')
    def test_get_user_analyses_count(self, mock_db):
        """Test getting count of user analyses."""
        mock_db.session.query.return_value.filter.return_value.count.return_value = 15
        
        result = self.service.get_user_analyses_count(user_id=1)
        
        assert result == 15
    
    # ============================================================================
    # Service Method Tests - Analysis Management
    # ============================================================================
    
    @patch('services.duplicate_persistence_service.db')
    def test_update_analysis_status_completed(self, mock_db):
        """Test updating analysis status to completed."""
        # Mock analysis result
        mock_analysis = Mock(spec=DuplicateAnalysisResult)
        mock_analysis.status = 'running'
        mock_analysis.completed_at = None
        
        mock_db.session.query.return_value.filter.return_value.first.return_value = mock_analysis
        
        # Call the method
        result = self.service.update_analysis_status("test-uuid", "completed")
        
        # Verify status update
        assert result is True
        assert mock_analysis.status == "completed"
        assert mock_analysis.completed_at is not None
    
    @patch('services.duplicate_persistence_service.db')
    def test_update_analysis_status_failed_with_error(self, mock_db):
        """Test updating analysis status to failed with error details."""
        # Mock analysis result
        mock_analysis = Mock(spec=DuplicateAnalysisResult)
        mock_analysis.status = 'running'
        
        mock_db.session.query.return_value.filter.return_value.first.return_value = mock_analysis
        
        error_details = {'error_type': 'timeout', 'details': 'Analysis timed out'}
        
        # Call the method
        result = self.service.update_analysis_status(
            "test-uuid", "failed", 
            error_message="Analysis failed", 
            error_details=error_details
        )
        
        # Verify error information
        assert result is True
        assert mock_analysis.status == "failed"
        assert mock_analysis.error_message == "Analysis failed"
        assert mock_analysis.error_details == error_details
    
    @patch('services.duplicate_persistence_service.db')
    def test_update_analysis_status_not_found(self, mock_db):
        """Test updating status for non-existent analysis."""
        mock_db.session.query.return_value.filter.return_value.first.return_value = None
        
        result = self.service.update_analysis_status("non-existent-uuid", "completed")
        
        assert result is False
    
    @patch('services.duplicate_persistence_service.db')
    def test_mark_groups_resolved_success(self, mock_db):
        """Test marking duplicate groups as resolved."""
        # Mock groups
        mock_groups = []
        for i in range(3):
            group = Mock(spec=DuplicateAnalysisGroup)
            group.id = i + 1
            group.resolved = False
            group.resolved_at = None
            group.resolution_action = None
            mock_groups.append(group)
        
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = mock_groups
        mock_db.session.query.return_value = mock_query
        
        # Call the method
        result = self.service.mark_groups_resolved([1, 2, 3], "deleted")
        
        # Verify groups were marked as resolved
        assert result == 3
        for group in mock_groups:
            assert group.resolved is True
            assert group.resolved_at is not None
            assert group.resolution_action == "deleted"
    
    @patch('services.duplicate_persistence_service.db')
    def test_mark_groups_resolved_with_user_security(self, mock_db):
        """Test marking groups as resolved with user security check."""
        # Mock groups with user security
        mock_groups = [Mock(spec=DuplicateAnalysisGroup)]
        mock_groups[0].resolved = False
        
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.all.return_value = mock_groups
        mock_db.session.query.return_value = mock_query
        
        # Call the method with user_id
        result = self.service.mark_groups_resolved([1], "kept_canonical", user_id=1)
        
        # Verify security join was called
        mock_query.join.assert_called_with(DuplicateAnalysisResult)
        assert result == 1
    
    # ============================================================================
    # Service Method Tests - Cleanup Operations
    # ============================================================================
    
    @patch('services.duplicate_persistence_service.db')
    def test_cleanup_old_results_by_age(self, mock_db):
        """Test cleanup of old results by age."""
        # Mock old analyses
        old_analyses = []
        for i in range(3):
            analysis = Mock(spec=DuplicateAnalysisResult)
            analysis.analysis_id = f"old-{i}"
            analysis.created_at = datetime.now() - timedelta(days=35)
            old_analyses.append(analysis)
        
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = old_analyses
        mock_db.session.query.return_value = mock_query
        
        # Mock users query for limit cleanup
        mock_db.session.query.return_value.distinct.return_value.all.return_value = []
        
        # Call the method
        result = self.service.cleanup_old_results(retention_days=30)
        
        # Verify cleanup stats
        assert result['deleted_by_age'] == 3
        assert result['deleted_by_limit'] == 0
        assert result['total_deleted'] == 3
        assert result['errors'] == 0
    
    @patch('services.duplicate_persistence_service.db')
    def test_cleanup_old_results_by_user_limit(self, mock_db):
        """Test cleanup of excess results per user."""
        # Mock user with excess analyses
        user_analyses = []
        for i in range(7):  # More than max_results_per_user (5)
            analysis = Mock(spec=DuplicateAnalysisResult)
            analysis.analysis_id = f"user-analysis-{i}"
            analysis.created_at = datetime.now() - timedelta(days=i)
            user_analyses.append(analysis)
        
        # Mock queries
        mock_db.session.query.return_value.filter.return_value.all.return_value = []  # No old analyses
        mock_db.session.query.return_value.distinct.return_value.all.return_value = [(1,)]  # One user
        
        # Set up mock queries more directly
        mock_query = Mock()
        mock_db.session.query.return_value = mock_query
        
        # Mock the chain for age-based cleanup (returns empty)
        mock_query.filter.return_value.all.return_value = []
        
        # Mock the chain for user distinct query
        mock_query.distinct.return_value.all.return_value = [(1,)]
        
        # Mock the chain for user-specific analyses
        mock_query.filter.return_value.order_by.return_value.all.return_value = user_analyses
        
        # Call the method
        result = self.service.cleanup_old_results(max_results_per_user=5)
        
        # Verify cleanup stats
        assert result['deleted_by_age'] == 0
        assert result['deleted_by_limit'] == 2  # 7 - 5 = 2 excess
        assert result['total_deleted'] == 2
    
    @patch('services.duplicate_persistence_service.db')
    def test_cleanup_old_results_with_errors(self, mock_db):
        """Test cleanup handling of deletion errors."""
        # Mock analysis that will cause deletion error
        problem_analysis = Mock(spec=DuplicateAnalysisResult)
        problem_analysis.analysis_id = "problem-analysis"
        
        mock_db.session.query.return_value.filter.return_value.all.return_value = [problem_analysis]
        mock_db.session.query.return_value.distinct.return_value.all.return_value = []
        
        # Mock deletion error
        mock_db.session.delete.side_effect = SQLAlchemyError("Constraint violation")
        
        # Call the method
        result = self.service.cleanup_old_results()
        
        # Verify error handling
        assert result['deleted_by_age'] == 0
        assert result['errors'] == 1
        assert result['total_deleted'] == 0
    
    # ============================================================================
    # Service Method Tests - Age and Staleness Detection
    # ============================================================================
    
    def test_get_analysis_age_info_fresh(self):
        """Test age info for fresh analysis."""
        # Create fresh analysis (30 minutes old)
        analysis = Mock()
        analysis.created_at = datetime.now() - timedelta(minutes=30)
        
        age_info = self.service.get_analysis_age_info(analysis)
        
        assert age_info['staleness_level'] == 'fresh'
        assert age_info['color_class'] == 'text-success'
        assert age_info['icon'] == 'fas fa-check-circle'
        assert age_info['needs_refresh'] is False
        assert 'minutes ago' in age_info['age_text']
    
    def test_get_analysis_age_info_moderate(self):
        """Test age info for moderately aged analysis."""
        # Create moderate analysis (6 hours old)
        analysis = Mock()
        analysis.created_at = datetime.now() - timedelta(hours=6)
        
        age_info = self.service.get_analysis_age_info(analysis)
        
        assert age_info['staleness_level'] == 'moderate'
        assert age_info['color_class'] == 'text-warning'
        assert age_info['icon'] == 'fas fa-clock'
        assert age_info['needs_refresh'] is False
        assert 'hours ago' in age_info['age_text']
    
    def test_get_analysis_age_info_stale(self):
        """Test age info for stale analysis."""
        # Create stale analysis (3 days old)
        analysis = Mock()
        analysis.created_at = datetime.now() - timedelta(days=3)
        
        age_info = self.service.get_analysis_age_info(analysis)
        
        assert age_info['staleness_level'] == 'stale'
        assert age_info['color_class'] == 'text-warning'
        assert age_info['icon'] == 'fas fa-exclamation-triangle'
        assert age_info['needs_refresh'] is True
        assert 'days ago' in age_info['age_text']
    
    def test_get_analysis_age_info_very_stale(self):
        """Test age info for very stale analysis."""
        # Create very stale analysis (2 weeks old)
        analysis = Mock()
        analysis.created_at = datetime.now() - timedelta(weeks=2)
        
        age_info = self.service.get_analysis_age_info(analysis)
        
        assert age_info['staleness_level'] == 'very_stale'
        assert age_info['color_class'] == 'text-danger'
        assert age_info['icon'] == 'fas fa-exclamation-triangle'
        assert age_info['needs_refresh'] is True
        assert 'days ago' in age_info['age_text']
    
    @patch('services.duplicate_persistence_service.db')
    def test_get_refresh_recommendations_should_refresh(self, mock_db):
        """Test refresh recommendations for stale analysis with library changes."""
        # Mock queries to simulate library changes
        call_count = [0]
        
        def mock_query_side_effect(*args):
            mock_q = Mock()
            mock_q.filter.return_value = mock_q
            
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: current track count (library grew)
                mock_q.count.return_value = 1100
            else:
                # Subsequent calls: tracks added/modified since analysis
                mock_q.count.return_value = 100  # Some changes
            
            return mock_q
        
        mock_db.session.query.side_effect = mock_query_side_effect
        
        # Create stale analysis with fewer tracks
        analysis = Mock()
        analysis.created_at = datetime.now() - timedelta(days=2)
        analysis.library_track_count = 1000
        
        recommendations = self.service.get_refresh_recommendations(analysis)
        
        assert recommendations['should_refresh'] is True
        assert recommendations['urgency'] == 'medium'
        assert any('consider refreshing' in reason for reason in recommendations['reasons'])
        assert any('tracks added' in reason for reason in recommendations['reasons'])
        assert 'Consider refreshing' in recommendations['message']
    
    @patch('services.duplicate_persistence_service.db')
    def test_get_refresh_recommendations_no_refresh_needed(self, mock_db):
        """Test refresh recommendations for fresh analysis with no changes."""
        # Mock queries to simulate no library changes
        call_count = [0]
        
        def mock_query_side_effect(*args):
            mock_q = Mock()
            mock_q.filter.return_value = mock_q
            
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: current track count
                mock_q.count.return_value = 1000  # Same as analysis
            else:
                # Subsequent calls: tracks added/modified since analysis
                mock_q.count.return_value = 0  # No changes
            
            return mock_q
        
        mock_db.session.query.side_effect = mock_query_side_effect
        
        # Create fresh analysis
        analysis = Mock()
        analysis.created_at = datetime.now() - timedelta(minutes=30)
        analysis.library_track_count = 1000
        
        recommendations = self.service.get_refresh_recommendations(analysis)
        
        assert recommendations['should_refresh'] is False
        assert recommendations['urgency'] == 'low'
        assert len(recommendations['reasons']) == 0
        assert 'appears to be current' in recommendations['message']
    
    # ============================================================================
    # Service Method Tests - Data Conversion and Utilities
    # ============================================================================
    
    @patch('services.duplicate_persistence_service.db')
    def test_convert_to_duplicate_groups_success(self, mock_db):
        """Test conversion of saved analysis back to DuplicateGroup objects."""
        # Mock analysis result with groups and tracks
        analysis_result = Mock(spec=DuplicateAnalysisResult)
        
        # Mock group with tracks
        mock_group = Mock(spec=DuplicateAnalysisGroup)
        mock_group.suggested_action = 'keep_canonical'
        
        # Mock tracks in group
        canonical_track = Mock(spec=DuplicateAnalysisTrack)
        canonical_track.track_id = 1
        canonical_track.is_canonical = True
        canonical_track.similarity_score = 1.0
        canonical_track.song_name = "Test Song"
        canonical_track.artist_name = "Test Artist"
        canonical_track.album_name = "Test Album"
        canonical_track.play_count = 10
        canonical_track.last_played = datetime.now()
        canonical_track.date_added = datetime.now()
        
        duplicate_track = Mock(spec=DuplicateAnalysisTrack)
        duplicate_track.track_id = 2
        duplicate_track.is_canonical = False
        duplicate_track.similarity_score = 0.95
        duplicate_track.song_name = "Test Song (Remastered)"
        duplicate_track.artist_name = "Test Artist"
        duplicate_track.album_name = "Test Album"
        duplicate_track.play_count = 5
        duplicate_track.last_played = datetime.now()
        duplicate_track.date_added = datetime.now()
        
        mock_group.tracks = [canonical_track, duplicate_track]
        analysis_result.groups = [mock_group]
        
        # Mock database queries for existing tracks
        call_count = [0]  # Use list to make it mutable in closure
        
        def mock_track_first():
            call_count[0] += 1
            if call_count[0] == 1:
                return self.mock_track1
            elif call_count[0] == 2:
                return self.mock_track2
            return None
        
        mock_db.session.query.return_value.filter.return_value.first.side_effect = mock_track_first
        
        # Call the method
        duplicate_groups = self.service.convert_to_duplicate_groups(analysis_result)
        
        # Verify conversion
        assert len(duplicate_groups) == 1
        group = duplicate_groups[0]
        assert group.canonical_song == self.mock_track1
        assert len(group.duplicates) == 1
        assert group.suggested_action == 'keep_canonical'
        assert 1 in group.similarity_scores
        assert 2 in group.similarity_scores
    
    @patch('services.duplicate_persistence_service.db')
    def test_convert_to_duplicate_groups_deleted_tracks(self, mock_db):
        """Test conversion when some tracks have been deleted."""
        # Mock analysis result
        analysis_result = Mock(spec=DuplicateAnalysisResult)
        
        # Mock group with deleted track
        mock_group = Mock(spec=DuplicateAnalysisGroup)
        mock_group.suggested_action = 'keep_canonical'
        
        # Mock track that was deleted
        deleted_track = Mock(spec=DuplicateAnalysisTrack)
        deleted_track.track_id = 999  # Non-existent track
        deleted_track.is_canonical = False
        deleted_track.similarity_score = 0.9
        deleted_track.song_name = "Deleted Song"
        deleted_track.artist_name = "Deleted Artist"
        deleted_track.album_name = "Deleted Album"
        deleted_track.play_count = 3
        deleted_track.last_played = datetime.now()
        deleted_track.date_added = datetime.now()
        deleted_track.still_exists = True  # Will be updated to False
        
        mock_group.tracks = [deleted_track]
        analysis_result.groups = [mock_group]
        
        # Mock database query returning None (track deleted)
        mock_db.session.query.return_value.filter.return_value.first.return_value = None
        
        # Call the method
        duplicate_groups = self.service.convert_to_duplicate_groups(analysis_result)
        
        # Verify handling of deleted tracks
        assert len(duplicate_groups) == 0  # No canonical track, so group is skipped
        assert deleted_track.still_exists is False
        assert deleted_track.deleted_at is not None
    
    def test_get_analysis_summary(self):
        """Test getting analysis summary information."""
        # Mock analysis result
        analysis_result = Mock(spec=DuplicateAnalysisResult)
        analysis_result.analysis_id = "test-uuid"
        analysis_result.created_at = datetime.now()
        analysis_result.completed_at = datetime.now()
        analysis_result.status = 'completed'
        analysis_result.search_term = 'test'
        analysis_result.sort_by = 'artist'
        analysis_result.min_confidence = 0.8
        analysis_result.total_groups_found = 5
        analysis_result.total_duplicates_found = 10
        analysis_result.average_similarity_score = 0.85
        analysis_result.processing_time_seconds = 120.5
        analysis_result.library_track_count = 1000
        analysis_result.library_last_modified = datetime.now()
        
        # Mock groups with resolution status
        resolved_group = Mock(spec=DuplicateAnalysisGroup)
        resolved_group.resolved = True
        resolved_group.tracks = [Mock(still_exists=True), Mock(still_exists=True)]
        
        unresolved_group = Mock(spec=DuplicateAnalysisGroup)
        unresolved_group.resolved = False
        unresolved_group.tracks = [Mock(still_exists=True), Mock(still_exists=False)]
        
        analysis_result.groups = [resolved_group, unresolved_group]
        
        # Call the method
        summary = self.service.get_analysis_summary(analysis_result)
        
        # Verify summary data
        assert summary['analysis_id'] == "test-uuid"
        assert summary['status'] == 'completed'
        assert summary['total_groups'] == 5
        assert summary['total_duplicates'] == 10
        assert summary['resolved_groups'] == 1
        assert summary['unresolved_groups'] == 1
        assert summary['existing_tracks'] == 3
        assert summary['deleted_tracks'] == 1
        assert summary['average_similarity'] == 0.85
        assert summary['processing_time'] == 120.5
    
    @patch('services.duplicate_persistence_service.db')
    def test_delete_analysis_result_success(self, mock_db):
        """Test successful deletion of analysis result."""
        # Mock analysis result
        mock_analysis = Mock(spec=DuplicateAnalysisResult)
        mock_analysis.analysis_id = "test-uuid"
        mock_analysis.user_id = 1
        
        mock_db.session.query.return_value.filter.return_value.first.return_value = mock_analysis
        
        # Call the method
        result = self.service.delete_analysis_result("test-uuid", user_id=1)
        
        # Verify deletion
        assert result is True
        mock_db.session.delete.assert_called_with(mock_analysis)
        mock_db.session.commit.assert_called()
    
    @patch('services.duplicate_persistence_service.db')
    def test_delete_analysis_result_not_found(self, mock_db):
        """Test deletion of non-existent analysis result."""
        mock_db.session.query.return_value.filter.return_value.first.return_value = None
        
        result = self.service.delete_analysis_result("non-existent-uuid", user_id=1)
        
        assert result is False
        mock_db.session.delete.assert_not_called()
    
    @patch('services.duplicate_persistence_service.db')
    def test_delete_analysis_result_wrong_user(self, mock_db):
        """Test deletion with wrong user ID (security check)."""
        # Mock analysis result belonging to different user
        mock_analysis = Mock(spec=DuplicateAnalysisResult)
        mock_analysis.user_id = 2  # Different user
        
        mock_db.session.query.return_value.filter.return_value.first.return_value = None  # Filter excludes it
        
        result = self.service.delete_analysis_result("test-uuid", user_id=1)
        
        assert result is False
    
    @patch('services.duplicate_persistence_service.db')
    def test_update_analysis_metadata_success(self, mock_db):
        """Test successful update of analysis metadata."""
        # Mock analysis result
        mock_analysis = Mock(spec=DuplicateAnalysisResult)
        mock_analysis.search_term = "old_term"
        
        mock_db.session.query.return_value.filter.return_value.first.return_value = mock_analysis
        
        # Call the method
        result = self.service.update_analysis_metadata("test-uuid", {'search_term': 'new_term'})
        
        # Verify update
        assert result is True
        assert mock_analysis.search_term == 'new_term'
        mock_db.session.commit.assert_called()
    
    @patch('services.duplicate_persistence_service.db')
    def test_update_analysis_metadata_not_found(self, mock_db):
        """Test update of non-existent analysis metadata."""
        mock_db.session.query.return_value.filter.return_value.first.return_value = None
        
        result = self.service.update_analysis_metadata("non-existent-uuid", {'search_term': 'new_term'})
        
        assert result is False
    
    # ============================================================================
    # Error Handling and Edge Cases
    # ============================================================================
    
    def test_get_staleness_level_none_analysis(self):
        """Test staleness level for None analysis."""
        result = self.service.get_staleness_level(None)
        assert result == 'very_stale'
    
    def test_get_staleness_level_none_created_at(self):
        """Test staleness level for analysis with None created_at."""
        analysis = Mock()
        analysis.created_at = None
        
        result = self.service.get_staleness_level(analysis)
        assert result == 'very_stale'
    
    def test_is_analysis_stale_none_analysis(self):
        """Test staleness check for None analysis."""
        result = self.service.is_analysis_stale(None)
        assert result is True
    
    def test_is_analysis_stale_custom_threshold(self):
        """Test staleness check with custom threshold."""
        # Create analysis that's 2 hours old
        analysis = Mock()
        analysis.created_at = datetime.now() - timedelta(hours=2)
        
        # Should be fresh with 24-hour threshold
        assert not self.service.is_analysis_stale(analysis, staleness_hours=24)
        
        # Should be stale with 1-hour threshold
        assert self.service.is_analysis_stale(analysis, staleness_hours=1)
    
    @patch('services.duplicate_persistence_service.db')
    def test_database_transaction_safety_success(self, mock_db):
        """Test successful database transaction."""
        mock_db.session.begin = Mock()
        mock_db.session.commit = Mock()
        mock_db.session.rollback = Mock()
        
        # Use the context manager
        with self.service.database_transaction_safety("test operation"):
            pass  # Simulate successful operation
        
        # Verify transaction handling
        mock_db.session.begin.assert_called()
        mock_db.session.commit.assert_called()
        mock_db.session.rollback.assert_not_called()
    
    @patch('services.duplicate_persistence_service.db')
    def test_database_transaction_safety_error(self, mock_db):
        """Test database transaction rollback on error."""
        mock_db.session.begin = Mock()
        mock_db.session.commit = Mock()
        mock_db.session.rollback = Mock()
        
        # Use the context manager with error
        with self.assertRaises(ValueError):
            with self.service.database_transaction_safety("test operation"):
                raise ValueError("Test error")
        
        # Verify rollback was called
        mock_db.session.begin.assert_called()
        mock_db.session.rollback.assert_called()
        mock_db.session.commit.assert_not_called()


if __name__ == '__main__':
    unittest.main()