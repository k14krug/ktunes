#!/usr/bin/env python3
"""
Simple test for duplicate resolution tracking functionality.
"""

import sys
import os
from datetime import datetime, timedelta

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from extensions import db
from models import (
    DuplicateAnalysisResult, 
    DuplicateAnalysisGroup, 
    DuplicateAnalysisTrack,
    Track,
    User
)
from services.duplicate_persistence_service import DuplicatePersistenceService


def test_resolution_tracking():
    """Test the resolution tracking functionality."""
    print("Testing duplicate resolution tracking...")
    
    # Create a minimal Flask app for testing
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Initialize db with the test app
    db.init_app(app)
    
    with app.app_context():
        db.create_all()
        
        # Create test user
        test_user = User(
            username='testuser',
            password='hashed_password'
        )
        db.session.add(test_user)
        db.session.commit()
        
        # Create test tracks
        test_tracks = []
        for i in range(4):
            track = Track(
                song=f'Test Song {i}',
                artist=f'Test Artist {i}',
                album=f'Test Album {i}',
                play_cnt=i * 10,
                date_added=datetime.now() - timedelta(days=i)
            )
            test_tracks.append(track)
            db.session.add(track)
        
        db.session.commit()
        
        # Create test analysis result
        analysis_result = DuplicateAnalysisResult(
            analysis_id='test-analysis-123',
            user_id=test_user.id,
            created_at=datetime.now() - timedelta(hours=2),
            completed_at=datetime.now() - timedelta(hours=2),
            status='completed',
            search_term=None,
            sort_by='artist',
            min_confidence=0.0,
            total_tracks_analyzed=100,
            total_groups_found=1,
            total_duplicates_found=2,
            average_similarity_score=0.85,
            processing_time_seconds=30.0,
            library_track_count=100,
            library_last_modified=datetime.now() - timedelta(days=1)
        )
        db.session.add(analysis_result)
        db.session.commit()
        
        # Create test duplicate group
        group = DuplicateAnalysisGroup(
            analysis_id='test-analysis-123',
            group_index=0,
            canonical_track_id=test_tracks[0].id,
            duplicate_count=2,
            average_similarity_score=0.9,
            suggested_action='delete_duplicates'
        )
        db.session.add(group)
        db.session.commit()
        
        # Create test analysis tracks
        canonical_track = DuplicateAnalysisTrack(
            group_id=group.id,
            track_id=test_tracks[0].id,
            song_name=test_tracks[0].song,
            artist_name=test_tracks[0].artist,
            album_name=test_tracks[0].album,
            similarity_score=1.0,
            is_canonical=True
        )
        
        duplicate_track = DuplicateAnalysisTrack(
            group_id=group.id,
            track_id=test_tracks[1].id,
            song_name=test_tracks[1].song,
            artist_name=test_tracks[1].artist,
            album_name=test_tracks[1].album,
            similarity_score=0.9,
            is_canonical=False
        )
        
        db.session.add_all([canonical_track, duplicate_track])
        db.session.commit()
        
        # Test the resolution tracking
        persistence_service = DuplicatePersistenceService()
        
        print("✓ Test data created successfully")
        
        # Test 1: Update resolution status when duplicate is deleted
        print("\nTest 1: Deleting duplicate track...")
        deleted_track_ids = [test_tracks[1].id]  # Delete the duplicate
        
        result = persistence_service.update_resolution_status_on_track_deletion(
            deleted_track_ids, 
            user_id=test_user.id
        )
        
        print(f"✓ Resolution update result: {result}")
        
        # Verify the track is marked as deleted
        updated_track = db.session.query(DuplicateAnalysisTrack)\
            .filter(DuplicateAnalysisTrack.track_id == test_tracks[1].id)\
            .first()
        
        assert not updated_track.still_exists, "Track should be marked as not existing"
        assert updated_track.deleted_at is not None, "Track should have deletion timestamp"
        print("✓ Track marked as deleted correctly")
        
        # Verify the group is marked as resolved
        updated_group = db.session.query(DuplicateAnalysisGroup)\
            .filter(DuplicateAnalysisGroup.id == group.id)\
            .first()
        
        assert updated_group.resolved, "Group should be marked as resolved"
        assert updated_group.resolution_action == 'duplicates_deleted', f"Expected 'duplicates_deleted', got '{updated_group.resolution_action}'"
        print("✓ Group marked as resolved correctly")
        
        # Test 2: Get impact summary
        print("\nTest 2: Getting impact summary...")
        impact_summary = persistence_service.get_impact_summary('test-analysis-123')
        
        print(f"✓ Impact summary generated: {len(impact_summary)} keys")
        assert 'analysis_id' in impact_summary, "Impact summary should contain analysis_id"
        assert 'current_stats' in impact_summary, "Impact summary should contain current_stats"
        assert impact_summary['current_stats']['resolved_groups'] == 1, "Should show 1 resolved group"
        assert impact_summary['current_stats']['tracks_deleted'] == 1, "Should show 1 deleted track"
        print("✓ Impact summary is correct")
        
        # Test 3: Get new analysis suggestion
        print("\nTest 3: Getting new analysis suggestion...")
        suggestion = persistence_service.suggest_new_analysis_after_cleanup(
            'test-analysis-123',
            cleanup_threshold_percentage=10.0
        )
        
        print(f"✓ New analysis suggestion generated")
        assert 'should_run_new_analysis' in suggestion, "Suggestion should contain recommendation"
        print(f"✓ Should run new analysis: {suggestion['should_run_new_analysis']}")
        
        print("\n🎉 All tests passed! Resolution tracking is working correctly.")


if __name__ == '__main__':
    test_resolution_tracking()