"""
Tests for duplicate resolution tracking and impact management functionality.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import os
import sys

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from models import (
    DuplicateAnalysisResult, 
    DuplicateAnalysisGroup, 
    DuplicateAnalysisTrack,
    Track,
    User
)
from services.duplicate_persistence_service import DuplicatePersistenceService


class TestDuplicateResolutionTracking(unittest.TestCase):
    """Test cases for duplicate resolution tracking functionality."""
    
    def setUp(self):
        """Set up test environment."""
        # Create a minimal Flask app for testing
        from flask import Flask
        from flask_sqlalchemy import SQLAlchemy
        
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        
        # Initialize db with the test app
        db.init_app(self.app)
        
        with self.app.app_context():
            db.create_all()
            
            # Create test user
            self.test_user = User(
                username='testuser',
                password='hashed_password'
            )
            db.session.add(self.test_user)
            db.session.commit()
            
            # Create test tracks
            self.test_tracks = []
            for i in range(5):
                track = Track(
                    song=f'Test Song {i}',
                    artist=f'Test Artist {i}',
                    album=f'Test Album {i}',
                    play_cnt=i * 10,
                    date_added=datetime.now() - timedelta(days=i)
                )
                self.test_tracks.append(track)
                db.session.add(track)
            
            db.session.commit()
            
            # Create test analysis result
            self.analysis_result = DuplicateAnalysisResult(
                analysis_id='test-analysis-123',
                user_id=self.test_user.id,
                created_at=datetime.now() - timedelta(hours=2),
                completed_at=datetime.now() - timedelta(hours=2),
                status='completed',
                search_term=None,
                sort_by='artist',
                min_confidence=0.0,
                total_tracks_analyzed=100,
                total_groups_found=2,
                total_duplicates_found=3,
                average_similarity_score=0.85,
                processing_time_seconds=30.0,
                library_track_count=100,
                library_last_modified=datetime.now() - timedelta(days=1)
            )
            db.session.add(self.analysis_result)
            db.session.commit()
            
            # Create test duplicate groups
            self.group1 = DuplicateAnalysisGroup(
                analysis_id='test-analysis-123',
                group_index=0,
                canonical_track_id=self.test_tracks[0].id,
                duplicate_count=2,
                average_similarity_score=0.9,
                suggested_action='delete_duplicates'
            )
            
            self.group2 = DuplicateAnalysisGroup(
                analysis_id='test-analysis-123',
                group_index=1,
                canonical_track_id=self.test_tracks[2].id,
                duplicate_count=2,
                average_similarity_score=0.8,
                suggested_action='delete_duplicates'
            )
            
            db.session.add(self.group1)
            db.session.add(self.group2)
            db.session.commit()
            
            # Create test analysis tracks
            # Group 1: canonical + 1 duplicate
            self.track1_canonical = DuplicateAnalysisTrack(
                group_id=self.group1.id,
                track_id=self.test_tracks[0].id,
                song_name=self.test_tracks[0].song,
                artist_name=self.test_tracks[0].artist,
                album_name=self.test_tracks[0].album,
                similarity_score=1.0,
                is_canonical=True
            )
            
            self.track1_duplicate = DuplicateAnalysisTrack(
                group_id=self.group1.id,
                track_id=self.test_tracks[1].id,
                song_name=self.test_tracks[1].song,
                artist_name=self.test_tracks[1].artist,
                album_name=self.test_tracks[1].album,
                similarity_score=0.9,
                is_canonical=False
            )
            
            # Group 2: canonical + 1 duplicate
            self.track2_canonical = DuplicateAnalysisTrack(
                group_id=self.group2.id,
                track_id=self.test_tracks[2].id,
                song_name=self.test_tracks[2].song,
                artist_name=self.test_tracks[2].artist,
                album_name=self.test_tracks[2].album,
                similarity_score=1.0,
                is_canonical=True
            )
            
            self.track2_duplicate = DuplicateAnalysisTrack(
                group_id=self.group2.id,
                track_id=self.test_tracks[3].id,
                song_name=self.test_tracks[3].song,
                artist_name=self.test_tracks[3].artist,
                album_name=self.test_tracks[3].album,
                similarity_score=0.8,
                is_canonical=False
            )
            
            db.session.add_all([
                self.track1_canonical, self.track1_duplicate,
                self.track2_canonical, self.track2_duplicate
            ])
            db.session.commit()
            
            self.persistence_service = DuplicatePersistenceService()
    
    def tearDown(self):
        """Clean up test environment."""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
    
    def test_update_resolution_status_on_duplicate_deletion(self):
        """Test updating resolution status when duplicate tracks are deleted."""
        with self.app.app_context():
            # Delete a duplicate track (not canonical)
            deleted_track_ids = [self.test_tracks[1].id]  # First duplicate
            
            result = self.persistence_service.update_resolution_status_on_track_deletion(
                deleted_track_ids, 
                user_id=self.test_user.id
            )
            
            # Verify result
            self.assertEqual(result['updated_tracks'], 1)
            self.assertEqual(result['updated_groups'], 1)
            self.assertEqual(result['deleted_track_count'], 1)
            self.assertEqual(result['resolution_summary']['fully_resolved'], 1)
            
            # Verify database changes
            updated_track = db.session.query(DuplicateAnalysisTrack)\
                .filter(DuplicateAnalysisTrack.track_id == self.test_tracks[1].id)\
                .first()
            
            self.assertFalse(updated_track.still_exists)
            self.assertIsNotNone(updated_track.deleted_at)
            
            # Verify group is marked as resolved
            updated_group = db.session.query(DuplicateAnalysisGroup)\
                .filter(DuplicateAnalysisGroup.id == self.group1.id)\
                .first()
            
            self.assertTrue(updated_group.resolved)
            self.assertEqual(updated_group.resolution_action, 'duplicates_deleted')
            self.assertIsNotNone(updated_group.resolved_at)
    
    def test_update_resolution_status_on_canonical_deletion(self):
        """Test updating resolution status when canonical track is deleted."""
        with self.app.app_context():
            # Delete a canonical track
            deleted_track_ids = [self.test_tracks[0].id]  # First canonical
            
            result = self.persistence_service.update_resolution_status_on_track_deletion(
                deleted_track_ids, 
                user_id=self.test_user.id
            )
            
            # Verify result
            self.assertEqual(result['updated_tracks'], 1)
            self.assertEqual(result['updated_groups'], 1)
            self.assertEqual(result['resolution_summary']['canonical_deleted'], 1)
            
            # Verify group is marked as resolved (only one track remains)
            updated_group = db.session.query(DuplicateAnalysisGroup)\
                .filter(DuplicateAnalysisGroup.id == self.group1.id)\
                .first()
            
            self.assertTrue(updated_group.resolved)
            self.assertEqual(updated_group.resolution_action, 'canonical_deleted')
    
    def test_get_impact_summary(self):
        """Test getting impact summary for an analysis."""
        with self.app.app_context():
            # First, delete a duplicate to create some impact
            deleted_track_ids = [self.test_tracks[1].id]
            self.persistence_service.update_resolution_status_on_track_deletion(
                deleted_track_ids, 
                user_id=self.test_user.id
            )
            
            # Get impact summary
            impact_summary = self.persistence_service.get_impact_summary('test-analysis-123')
            
            # Verify summary structure
            self.assertIn('analysis_id', impact_summary)
            self.assertIn('original_stats', impact_summary)
            self.assertIn('current_stats', impact_summary)
            self.assertIn('resolution_breakdown', impact_summary)
            self.assertIn('cleanup_effectiveness', impact_summary)
            self.assertIn('recommendations', impact_summary)
            
            # Verify original stats
            self.assertEqual(impact_summary['original_stats']['total_groups'], 2)
            self.assertEqual(impact_summary['original_stats']['total_duplicates'], 3)
            
            # Verify current stats show the deletion
            self.assertEqual(impact_summary['current_stats']['resolved_groups'], 1)
            self.assertEqual(impact_summary['current_stats']['tracks_deleted'], 1)
            self.assertEqual(impact_summary['current_stats']['duplicate_tracks_deleted'], 1)
            
            # Verify effectiveness calculation
            self.assertEqual(impact_summary['cleanup_effectiveness']['groups_resolved_percentage'], 50.0)
    
    def test_suggest_new_analysis_after_cleanup(self):
        """Test suggesting new analysis after significant cleanup."""
        with self.app.app_context():
            # Delete multiple tracks to simulate significant cleanup
            deleted_track_ids = [self.test_tracks[1].id, self.test_tracks[3].id]
            self.persistence_service.update_resolution_status_on_track_deletion(
                deleted_track_ids, 
                user_id=self.test_user.id
            )
            
            # Get suggestion with low threshold to trigger recommendation
            suggestion = self.persistence_service.suggest_new_analysis_after_cleanup(
                'test-analysis-123',
                cleanup_threshold_percentage=10.0
            )
            
            # Verify suggestion structure
            self.assertIn('should_run_new_analysis', suggestion)
            self.assertIn('confidence', suggestion)
            self.assertIn('reasons', suggestion)
            self.assertIn('benefits', suggestion)
            self.assertIn('timing_recommendation', suggestion)
            
            # Should recommend new analysis due to cleanup
            self.assertTrue(suggestion['should_run_new_analysis'])
            self.assertGreater(len(suggestion['reasons']), 0)
            self.assertGreater(len(suggestion['benefits']), 0)
    
    def test_get_cleanup_history_summary(self):
        """Test getting cleanup history summary."""
        with self.app.app_context():
            # Delete some tracks to create history
            deleted_track_ids = [self.test_tracks[1].id]
            self.persistence_service.update_resolution_status_on_track_deletion(
                deleted_track_ids, 
                user_id=self.test_user.id
            )
            
            # Get cleanup history
            history = self.persistence_service.get_cleanup_history_summary(
                user_id=self.test_user.id,
                days_back=30
            )
            
            # Verify history structure
            self.assertIn('cleanup_summary', history)
            self.assertIn('effectiveness_trends', history)
            self.assertIn('effectiveness_data', history)
            self.assertIn('recommendations', history)
            
            # Verify cleanup summary
            cleanup_summary = history['cleanup_summary']
            self.assertEqual(cleanup_summary['total_analyses'], 1)
            self.assertEqual(cleanup_summary['analyses_with_cleanup'], 1)
            self.assertGreater(cleanup_summary['average_resolution_rate'], 0)
    
    def test_bulk_resolution_tracking(self):
        """Test bulk update of resolution tracking for multiple tracks."""
        with self.app.app_context():
            # Delete multiple tracks at once
            deleted_track_ids = [self.test_tracks[1].id, self.test_tracks[3].id]
            
            result = self.persistence_service.update_resolution_status_on_track_deletion(
                deleted_track_ids, 
                user_id=self.test_user.id
            )
            
            # Verify both groups are affected
            self.assertEqual(result['updated_tracks'], 2)
            self.assertEqual(result['updated_groups'], 2)
            self.assertEqual(result['deleted_track_count'], 2)
            
            # Both groups should be resolved (duplicates deleted)
            self.assertEqual(result['resolution_summary']['fully_resolved'], 2)
            
            # Verify both groups are marked as resolved
            resolved_groups = db.session.query(DuplicateAnalysisGroup)\
                .filter(DuplicateAnalysisGroup.resolved == True)\
                .count()
            
            self.assertEqual(resolved_groups, 2)


if __name__ == '__main__':
    unittest.main()