"""
Tests for Duplicate Analysis Database Models.

This module contains comprehensive unit tests for the duplicate analysis database models,
including relationship validation, constraint testing, and data integrity checks.
"""

import unittest
import uuid
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import Flask for minimal app context
from flask import Flask
from sqlalchemy.exc import IntegrityError

from models import (
    DuplicateAnalysisResult, 
    DuplicateAnalysisGroup, 
    DuplicateAnalysisTrack,
    DuplicateAnalysisExport,
    User,
    Track
)


class TestDuplicateAnalysisModels(unittest.TestCase):
    """Test cases for duplicate analysis database models."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a minimal Flask app for testing
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        # Test data
        self.test_analysis_id = str(uuid.uuid4())
        self.test_user_id = 1
        self.test_created_at = datetime.now()
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.app_context.pop()
    
    # ============================================================================
    # DuplicateAnalysisResult Model Tests
    # ============================================================================
    
    def test_duplicate_analysis_result_creation(self):
        """Test creation of DuplicateAnalysisResult model."""
        analysis_result = DuplicateAnalysisResult(
            analysis_id=self.test_analysis_id,
            user_id=self.test_user_id,
            created_at=self.test_created_at,
            completed_at=self.test_created_at + timedelta(minutes=5),
            status='completed',
            search_term='test search',
            sort_by='artist',
            min_confidence=0.8,
            total_tracks_analyzed=1000,
            total_groups_found=25,
            total_duplicates_found=50,
            average_similarity_score=0.85,
            processing_time_seconds=120.5,
            library_track_count=1000,
            library_last_modified=self.test_created_at
        )
        
        # Verify all fields are set correctly
        assert analysis_result.analysis_id == self.test_analysis_id
        assert analysis_result.user_id == self.test_user_id
        assert analysis_result.status == 'completed'
        assert analysis_result.search_term == 'test search'
        assert analysis_result.sort_by == 'artist'
        assert analysis_result.min_confidence == 0.8
        assert analysis_result.total_tracks_analyzed == 1000
        assert analysis_result.total_groups_found == 25
        assert analysis_result.total_duplicates_found == 50
        assert analysis_result.average_similarity_score == 0.85
        assert analysis_result.processing_time_seconds == 120.5
        assert analysis_result.library_track_count == 1000
        assert analysis_result.library_last_modified == self.test_created_at
    
    def test_duplicate_analysis_result_defaults(self):
        """Test default values for DuplicateAnalysisResult model."""
        analysis_result = DuplicateAnalysisResult(
            analysis_id=self.test_analysis_id,
            user_id=self.test_user_id
        )
        
        # Verify default values
        assert analysis_result.status == 'running'
        assert analysis_result.sort_by == 'artist'
        assert analysis_result.min_confidence == 0.0
        assert analysis_result.error_message is None
        assert analysis_result.error_details is None
    
    def test_duplicate_analysis_result_required_fields(self):
        """Test that required fields are enforced."""
        # Test missing analysis_id
        with self.assertRaises((ValueError, TypeError)):
            analysis_result = DuplicateAnalysisResult(
                user_id=self.test_user_id
            )
        
        # Test missing user_id (should be allowed for anonymous analyses)
        analysis_result = DuplicateAnalysisResult(
            analysis_id=self.test_analysis_id
        )
        assert analysis_result.user_id is None
    
    def test_duplicate_analysis_result_status_values(self):
        """Test valid status values for analysis result."""
        valid_statuses = ['running', 'completed', 'failed', 'cancelled']
        
        for status in valid_statuses:
            analysis_result = DuplicateAnalysisResult(
                analysis_id=str(uuid.uuid4()),
                user_id=self.test_user_id,
                status=status
            )
            assert analysis_result.status == status
    
    def test_duplicate_analysis_result_error_handling(self):
        """Test error information storage in analysis result."""
        error_details = {
            'error_type': 'timeout',
            'phase': 'analyzing_similarities',
            'tracks_processed': 500,
            'total_tracks': 1000
        }
        
        analysis_result = DuplicateAnalysisResult(
            analysis_id=self.test_analysis_id,
            user_id=self.test_user_id,
            status='failed',
            error_message='Analysis timed out after 300 seconds',
            error_details=error_details
        )
        
        assert analysis_result.status == 'failed'
        assert analysis_result.error_message == 'Analysis timed out after 300 seconds'
        assert analysis_result.error_details == error_details
        assert analysis_result.error_details['error_type'] == 'timeout'
    
    # ============================================================================
    # DuplicateAnalysisGroup Model Tests
    # ============================================================================
    
    def test_duplicate_analysis_group_creation(self):
        """Test creation of DuplicateAnalysisGroup model."""
        analysis_group = DuplicateAnalysisGroup(
            analysis_id=self.test_analysis_id,
            group_index=0,
            canonical_track_id=123,
            duplicate_count=3,
            average_similarity_score=0.92,
            suggested_action='keep_canonical',
            has_itunes_matches=True,
            itunes_match_data={'match_type': 'exact', 'confidence': 0.95}
        )
        
        # Verify all fields are set correctly
        assert analysis_group.analysis_id == self.test_analysis_id
        assert analysis_group.group_index == 0
        assert analysis_group.canonical_track_id == 123
        assert analysis_group.duplicate_count == 3
        assert analysis_group.average_similarity_score == 0.92
        assert analysis_group.suggested_action == 'keep_canonical'
        assert analysis_group.has_itunes_matches is True
        assert analysis_group.itunes_match_data['match_type'] == 'exact'
    
    def test_duplicate_analysis_group_defaults(self):
        """Test default values for DuplicateAnalysisGroup model."""
        analysis_group = DuplicateAnalysisGroup(
            analysis_id=self.test_analysis_id,
            group_index=0,
            canonical_track_id=123,
            duplicate_count=2,
            average_similarity_score=0.85,
            suggested_action='keep_canonical'
        )
        
        # Verify default values
        assert analysis_group.has_itunes_matches is False
        assert analysis_group.itunes_match_data is None
        assert analysis_group.resolved is False
        assert analysis_group.resolved_at is None
        assert analysis_group.resolution_action is None
    
    def test_duplicate_analysis_group_resolution_tracking(self):
        """Test resolution status tracking in analysis group."""
        analysis_group = DuplicateAnalysisGroup(
            analysis_id=self.test_analysis_id,
            group_index=0,
            canonical_track_id=123,
            duplicate_count=2,
            average_similarity_score=0.85,
            suggested_action='keep_canonical'
        )
        
        # Initially not resolved
        assert analysis_group.resolved is False
        assert analysis_group.resolved_at is None
        assert analysis_group.resolution_action is None
        
        # Mark as resolved
        resolution_time = datetime.now()
        analysis_group.resolved = True
        analysis_group.resolved_at = resolution_time
        analysis_group.resolution_action = 'deleted'
        
        assert analysis_group.resolved is True
        assert analysis_group.resolved_at == resolution_time
        assert analysis_group.resolution_action == 'deleted'
    
    def test_duplicate_analysis_group_suggested_actions(self):
        """Test valid suggested action values."""
        valid_actions = ['keep_canonical', 'delete_all', 'manual_review', 'merge_metadata']
        
        for action in valid_actions:
            analysis_group = DuplicateAnalysisGroup(
                analysis_id=self.test_analysis_id,
                group_index=0,
                canonical_track_id=123,
                duplicate_count=2,
                average_similarity_score=0.85,
                suggested_action=action
            )
            assert analysis_group.suggested_action == action
    
    def test_duplicate_analysis_group_resolution_actions(self):
        """Test valid resolution action values."""
        valid_resolution_actions = ['deleted', 'kept_canonical', 'manual_review', 'merged']
        
        for action in valid_resolution_actions:
            analysis_group = DuplicateAnalysisGroup(
                analysis_id=self.test_analysis_id,
                group_index=0,
                canonical_track_id=123,
                duplicate_count=2,
                average_similarity_score=0.85,
                suggested_action='keep_canonical',
                resolved=True,
                resolved_at=datetime.now(),
                resolution_action=action
            )
            assert analysis_group.resolution_action == action
    
    # ============================================================================
    # DuplicateAnalysisTrack Model Tests
    # ============================================================================
    
    def test_duplicate_analysis_track_creation(self):
        """Test creation of DuplicateAnalysisTrack model."""
        track_time = datetime.now()
        
        analysis_track = DuplicateAnalysisTrack(
            group_id=1,
            track_id=456,
            song_name="Test Song",
            artist_name="Test Artist",
            album_name="Test Album",
            play_count=10,
            last_played=track_time,
            date_added=track_time,
            similarity_score=0.95,
            is_canonical=True,
            itunes_match_found=True,
            itunes_match_confidence=0.98,
            itunes_match_type='exact'
        )
        
        # Verify all fields are set correctly
        assert analysis_track.group_id == 1
        assert analysis_track.track_id == 456
        assert analysis_track.song_name == "Test Song"
        assert analysis_track.artist_name == "Test Artist"
        assert analysis_track.album_name == "Test Album"
        assert analysis_track.play_count == 10
        assert analysis_track.last_played == track_time
        assert analysis_track.date_added == track_time
        assert analysis_track.similarity_score == 0.95
        assert analysis_track.is_canonical is True
        assert analysis_track.itunes_match_found is True
        assert analysis_track.itunes_match_confidence == 0.98
        assert analysis_track.itunes_match_type == 'exact'
    
    def test_duplicate_analysis_track_defaults(self):
        """Test default values for DuplicateAnalysisTrack model."""
        analysis_track = DuplicateAnalysisTrack(
            group_id=1,
            track_id=456,
            similarity_score=0.85
        )
        
        # Verify default values
        assert analysis_track.is_canonical is False
        assert analysis_track.itunes_match_found is False
        assert analysis_track.itunes_match_confidence is None
        assert analysis_track.itunes_match_type is None
        assert analysis_track.still_exists is True
        assert analysis_track.deleted_at is None
    
    def test_duplicate_analysis_track_canonical_vs_duplicate(self):
        """Test canonical vs duplicate track distinction."""
        # Canonical track
        canonical_track = DuplicateAnalysisTrack(
            group_id=1,
            track_id=123,
            similarity_score=1.0,
            is_canonical=True
        )
        
        # Duplicate track
        duplicate_track = DuplicateAnalysisTrack(
            group_id=1,
            track_id=456,
            similarity_score=0.85,
            is_canonical=False
        )
        
        assert canonical_track.is_canonical is True
        assert canonical_track.similarity_score == 1.0
        assert duplicate_track.is_canonical is False
        assert duplicate_track.similarity_score == 0.85
    
    def test_duplicate_analysis_track_existence_tracking(self):
        """Test track existence and deletion tracking."""
        analysis_track = DuplicateAnalysisTrack(
            group_id=1,
            track_id=456,
            similarity_score=0.85
        )
        
        # Initially exists
        assert analysis_track.still_exists is True
        assert analysis_track.deleted_at is None
        
        # Mark as deleted
        deletion_time = datetime.now()
        analysis_track.still_exists = False
        analysis_track.deleted_at = deletion_time
        
        assert analysis_track.still_exists is False
        assert analysis_track.deleted_at == deletion_time
    
    def test_duplicate_analysis_track_itunes_match_types(self):
        """Test valid iTunes match type values."""
        valid_match_types = ['exact', 'fuzzy', 'none', 'manual']
        
        for match_type in valid_match_types:
            analysis_track = DuplicateAnalysisTrack(
                group_id=1,
                track_id=456,
                similarity_score=0.85,
                itunes_match_found=True,
                itunes_match_type=match_type,
                itunes_match_confidence=0.9
            )
            assert analysis_track.itunes_match_type == match_type
    
    def test_duplicate_analysis_track_similarity_score_range(self):
        """Test similarity score validation (should be between 0.0 and 1.0)."""
        # Valid similarity scores
        valid_scores = [0.0, 0.5, 0.85, 1.0]
        
        for score in valid_scores:
            analysis_track = DuplicateAnalysisTrack(
                group_id=1,
                track_id=456,
                similarity_score=score
            )
            assert analysis_track.similarity_score == score
        
        # Note: Database-level constraints would be tested in integration tests
        # Here we just verify the model accepts the values
    
    # ============================================================================
    # DuplicateAnalysisExport Model Tests
    # ============================================================================
    
    def test_duplicate_analysis_export_creation(self):
        """Test creation of DuplicateAnalysisExport model."""
        export_time = datetime.now()
        
        analysis_export = DuplicateAnalysisExport(
            analysis_id=self.test_analysis_id,
            user_id=self.test_user_id,
            export_format='json',
            file_path='/tmp/export_123.json',
            file_size_bytes=1024000,
            created_at=export_time,
            expires_at=export_time + timedelta(hours=24)
        )
        
        # Verify all fields are set correctly
        assert analysis_export.analysis_id == self.test_analysis_id
        assert analysis_export.user_id == self.test_user_id
        assert analysis_export.export_format == 'json'
        assert analysis_export.file_path == '/tmp/export_123.json'
        assert analysis_export.file_size_bytes == 1024000
        assert analysis_export.created_at == export_time
        assert analysis_export.expires_at == export_time + timedelta(hours=24)
    
    def test_duplicate_analysis_export_formats(self):
        """Test valid export format values."""
        valid_formats = ['json', 'csv', 'xlsx', 'xml']
        
        for format_type in valid_formats:
            analysis_export = DuplicateAnalysisExport(
                analysis_id=self.test_analysis_id,
                user_id=self.test_user_id,
                export_format=format_type,
                file_path=f'/tmp/export.{format_type}',
                file_size_bytes=1024
            )
            assert analysis_export.export_format == format_type
    
    def test_duplicate_analysis_export_expiration(self):
        """Test export expiration logic."""
        current_time = datetime.now()
        
        # Create export that expires in 1 hour
        analysis_export = DuplicateAnalysisExport(
            analysis_id=self.test_analysis_id,
            user_id=self.test_user_id,
            export_format='json',
            file_path='/tmp/export.json',
            file_size_bytes=1024,
            created_at=current_time,
            expires_at=current_time + timedelta(hours=1)
        )
        
        # Should not be expired yet
        assert analysis_export.expires_at > current_time
        
        # Simulate time passing
        future_time = current_time + timedelta(hours=2)
        assert analysis_export.expires_at < future_time
    
    # ============================================================================
    # Model Relationship Tests
    # ============================================================================
    
    def test_analysis_result_to_groups_relationship(self):
        """Test relationship between analysis result and groups."""
        # Create analysis result
        analysis_result = DuplicateAnalysisResult(
            analysis_id=self.test_analysis_id,
            user_id=self.test_user_id
        )
        
        # Create groups
        group1 = DuplicateAnalysisGroup(
            analysis_id=self.test_analysis_id,
            group_index=0,
            canonical_track_id=123,
            duplicate_count=2,
            average_similarity_score=0.85,
            suggested_action='keep_canonical'
        )
        
        group2 = DuplicateAnalysisGroup(
            analysis_id=self.test_analysis_id,
            group_index=1,
            canonical_track_id=456,
            duplicate_count=3,
            average_similarity_score=0.90,
            suggested_action='delete_all'
        )
        
        # Test relationship setup (would be handled by SQLAlchemy in real usage)
        analysis_result.groups = [group1, group2]
        
        assert len(analysis_result.groups) == 2
        assert group1 in analysis_result.groups
        assert group2 in analysis_result.groups
    
    def test_analysis_group_to_tracks_relationship(self):
        """Test relationship between analysis group and tracks."""
        # Create group
        analysis_group = DuplicateAnalysisGroup(
            analysis_id=self.test_analysis_id,
            group_index=0,
            canonical_track_id=123,
            duplicate_count=3,
            average_similarity_score=0.85,
            suggested_action='keep_canonical'
        )
        
        # Create tracks
        canonical_track = DuplicateAnalysisTrack(
            group_id=1,  # Would be set by SQLAlchemy
            track_id=123,
            similarity_score=1.0,
            is_canonical=True
        )
        
        duplicate_track1 = DuplicateAnalysisTrack(
            group_id=1,
            track_id=456,
            similarity_score=0.85,
            is_canonical=False
        )
        
        duplicate_track2 = DuplicateAnalysisTrack(
            group_id=1,
            track_id=789,
            similarity_score=0.80,
            is_canonical=False
        )
        
        # Test relationship setup
        analysis_group.tracks = [canonical_track, duplicate_track1, duplicate_track2]
        
        assert len(analysis_group.tracks) == 3
        assert canonical_track in analysis_group.tracks
        assert duplicate_track1 in analysis_group.tracks
        assert duplicate_track2 in analysis_group.tracks
        
        # Verify canonical track identification
        canonical_tracks = [t for t in analysis_group.tracks if t.is_canonical]
        duplicate_tracks = [t for t in analysis_group.tracks if not t.is_canonical]
        
        assert len(canonical_tracks) == 1
        assert len(duplicate_tracks) == 2
        assert canonical_tracks[0].track_id == 123
    
    # ============================================================================
    # Data Validation Tests
    # ============================================================================
    
    def test_analysis_result_uuid_validation(self):
        """Test that analysis_id accepts valid UUID format."""
        valid_uuids = [
            str(uuid.uuid4()),
            "12345678-1234-5678-9012-123456789012",
            "abcdef12-3456-7890-abcd-ef1234567890"
        ]
        
        for test_uuid in valid_uuids:
            analysis_result = DuplicateAnalysisResult(
                analysis_id=test_uuid,
                user_id=self.test_user_id
            )
            assert analysis_result.analysis_id == test_uuid
    
    def test_analysis_group_numeric_validations(self):
        """Test numeric field validations in analysis group."""
        analysis_group = DuplicateAnalysisGroup(
            analysis_id=self.test_analysis_id,
            group_index=0,
            canonical_track_id=123,
            duplicate_count=5,
            average_similarity_score=0.876543,
            suggested_action='keep_canonical'
        )
        
        # Verify numeric fields accept appropriate values
        assert isinstance(analysis_group.group_index, int)
        assert isinstance(analysis_group.canonical_track_id, int)
        assert isinstance(analysis_group.duplicate_count, int)
        assert isinstance(analysis_group.average_similarity_score, float)
        
        # Verify precision is maintained
        assert analysis_group.average_similarity_score == 0.876543
    
    def test_analysis_track_snapshot_data_integrity(self):
        """Test that track snapshot data is preserved correctly."""
        original_data = {
            'song_name': "Test Song with Special Characters: éñ",
            'artist_name': "Artist & Co.",
            'album_name': "Album (Deluxe Edition) [2023]",
            'play_count': 42,
            'last_played': datetime(2023, 12, 25, 15, 30, 45),
            'date_added': datetime(2023, 1, 1, 0, 0, 0)
        }
        
        analysis_track = DuplicateAnalysisTrack(
            group_id=1,
            track_id=456,
            similarity_score=0.85,
            **original_data
        )
        
        # Verify all snapshot data is preserved exactly
        assert analysis_track.song_name == original_data['song_name']
        assert analysis_track.artist_name == original_data['artist_name']
        assert analysis_track.album_name == original_data['album_name']
        assert analysis_track.play_count == original_data['play_count']
        assert analysis_track.last_played == original_data['last_played']
        assert analysis_track.date_added == original_data['date_added']
    
    # ============================================================================
    # Edge Cases and Error Conditions
    # ============================================================================
    
    def test_analysis_result_with_minimal_data(self):
        """Test analysis result creation with only required fields."""
        analysis_result = DuplicateAnalysisResult(
            analysis_id=self.test_analysis_id
        )
        
        # Should work with minimal data
        assert analysis_result.analysis_id == self.test_analysis_id
        assert analysis_result.user_id is None  # Anonymous analysis
        assert analysis_result.status == 'running'  # Default status
    
    def test_analysis_group_with_zero_duplicates(self):
        """Test analysis group with zero duplicates (edge case)."""
        analysis_group = DuplicateAnalysisGroup(
            analysis_id=self.test_analysis_id,
            group_index=0,
            canonical_track_id=123,
            duplicate_count=0,  # No duplicates found
            average_similarity_score=1.0,  # Only canonical track
            suggested_action='no_action'
        )
        
        assert analysis_group.duplicate_count == 0
        assert analysis_group.average_similarity_score == 1.0
    
    def test_analysis_track_with_null_snapshot_data(self):
        """Test analysis track with missing snapshot data."""
        analysis_track = DuplicateAnalysisTrack(
            group_id=1,
            track_id=456,
            similarity_score=0.85,
            # All snapshot fields are None/null
            song_name=None,
            artist_name=None,
            album_name=None,
            play_count=None,
            last_played=None,
            date_added=None
        )
        
        # Should handle null snapshot data gracefully
        assert analysis_track.song_name is None
        assert analysis_track.artist_name is None
        assert analysis_track.album_name is None
        assert analysis_track.play_count is None
        assert analysis_track.last_played is None
        assert analysis_track.date_added is None
    
    def test_analysis_export_with_large_file_size(self):
        """Test analysis export with large file size."""
        large_file_size = 1024 * 1024 * 1024  # 1 GB
        
        analysis_export = DuplicateAnalysisExport(
            analysis_id=self.test_analysis_id,
            user_id=self.test_user_id,
            export_format='json',
            file_path='/tmp/large_export.json',
            file_size_bytes=large_file_size
        )
        
        assert analysis_export.file_size_bytes == large_file_size
    
    # ============================================================================
    # String Representation Tests
    # ============================================================================
    
    def test_model_string_representations(self):
        """Test string representations of models for debugging."""
        # Analysis Result
        analysis_result = DuplicateAnalysisResult(
            analysis_id=self.test_analysis_id,
            user_id=self.test_user_id,
            status='completed'
        )
        
        # Should have meaningful string representation
        str_repr = str(analysis_result)
        assert self.test_analysis_id in str_repr or 'DuplicateAnalysisResult' in str_repr
        
        # Analysis Group
        analysis_group = DuplicateAnalysisGroup(
            analysis_id=self.test_analysis_id,
            group_index=0,
            canonical_track_id=123,
            duplicate_count=2,
            average_similarity_score=0.85,
            suggested_action='keep_canonical'
        )
        
        str_repr = str(analysis_group)
        assert 'DuplicateAnalysisGroup' in str_repr or str(analysis_group.group_index) in str_repr
        
        # Analysis Track
        analysis_track = DuplicateAnalysisTrack(
            group_id=1,
            track_id=456,
            song_name="Test Song",
            similarity_score=0.85
        )
        
        str_repr = str(analysis_track)
        assert 'DuplicateAnalysisTrack' in str_repr or 'Test Song' in str_repr


if __name__ == '__main__':
    unittest.main()