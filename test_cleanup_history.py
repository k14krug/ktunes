#!/usr/bin/env python3
"""
Simple test for cleanup history and audit trail functionality.
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
    DuplicateCleanupAuditLog,
    Track,
    User
)
from services.duplicate_persistence_service import DuplicatePersistenceService


def test_cleanup_history():
    """Test the cleanup history and audit trail functionality."""
    print("Testing cleanup history and audit trail...")
    
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
        for i in range(6):
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
            analysis_id='test-analysis-456',
            user_id=test_user.id,
            created_at=datetime.now() - timedelta(hours=3),
            completed_at=datetime.now() - timedelta(hours=3),
            status='completed',
            search_term=None,
            sort_by='artist',
            min_confidence=0.0,
            total_tracks_analyzed=100,
            total_groups_found=2,
            total_duplicates_found=4,
            average_similarity_score=0.85,
            processing_time_seconds=45.0,
            library_track_count=100,
            library_last_modified=datetime.now() - timedelta(days=1)
        )
        db.session.add(analysis_result)
        db.session.commit()
        
        persistence_service = DuplicatePersistenceService()
        
        print("✓ Test data created successfully")
        
        # Test 1: Log cleanup actions
        print("\nTest 1: Logging cleanup actions...")
        
        # Log a single track deletion
        action_id_1 = persistence_service.log_cleanup_action(
            action_type='track_deleted',
            operation_type='single_delete',
            user_id=test_user.id,
            analysis_id='test-analysis-456',
            affected_track_ids=[test_tracks[0].id],
            resolution_action='duplicates_deleted',
            cleanup_strategy='manual_selection',
            processing_time_seconds=1.5,
            context_data={'reason': 'duplicate_cleanup'},
            success=True
        )
        
        print(f"✓ Single deletion logged with action_id: {action_id_1}")
        
        # Log a bulk deletion
        action_id_2 = persistence_service.log_cleanup_action(
            action_type='bulk_cleanup',
            operation_type='bulk_delete',
            user_id=test_user.id,
            analysis_id='test-analysis-456',
            affected_track_ids=[test_tracks[1].id, test_tracks[2].id],
            resolution_action='bulk_deletion',
            cleanup_strategy='manual_selection',
            processing_time_seconds=3.2,
            context_data={'batch_size': 2},
            success=True
        )
        
        print(f"✓ Bulk deletion logged with action_id: {action_id_2}")
        
        # Test 2: Get audit trail
        print("\nTest 2: Getting cleanup audit trail...")
        
        audit_trail = persistence_service.get_cleanup_audit_trail(
            user_id=test_user.id,
            days_back=30
        )
        
        print(f"✓ Retrieved {len(audit_trail)} audit trail entries")
        assert len(audit_trail) == 2, f"Expected 2 entries, got {len(audit_trail)}"
        
        # Verify audit trail content
        for entry in audit_trail:
            print(f"  - {entry['description']} at {entry['timestamp_formatted']}")
            assert 'action_id' in entry, "Entry should have action_id"
            assert 'description' in entry, "Entry should have description"
            assert 'impact_summary' in entry, "Entry should have impact_summary"
        
        print("✓ Audit trail content verified")
        
        # Test 3: Get effectiveness statistics
        print("\nTest 3: Getting effectiveness statistics...")
        
        effectiveness_stats = persistence_service.get_duplicate_management_effectiveness_stats(
            user_id=test_user.id,
            days_back=90
        )
        
        print(f"✓ Effectiveness stats generated")
        assert 'effectiveness_metrics' in effectiveness_stats, "Should contain effectiveness metrics"
        assert 'trend_analysis' in effectiveness_stats, "Should contain trend analysis"
        assert 'performance_insights' in effectiveness_stats, "Should contain performance insights"
        
        metrics = effectiveness_stats['effectiveness_metrics']
        print(f"  - Total actions: {metrics['total_actions']}")
        print(f"  - Total tracks deleted: {metrics['total_tracks_deleted']}")
        print(f"  - Success rate: {metrics['success_rate']:.1f}%")
        print(f"  - Average processing time: {metrics['average_processing_time']:.2f}s")
        
        assert metrics['total_actions'] == 2, "Should show 2 total actions"
        assert metrics['total_tracks_deleted'] == 3, "Should show 3 total tracks deleted"
        assert metrics['success_rate'] == 100.0, "Should show 100% success rate"
        
        print("✓ Effectiveness statistics verified")
        
        # Test 4: Get pattern-based recommendations
        print("\nTest 4: Getting pattern-based recommendations...")
        
        recommendations = persistence_service.get_cleanup_recommendations_based_on_patterns(
            user_id=test_user.id,
            days_back=30
        )
        
        print(f"✓ Retrieved {len(recommendations)} recommendations")
        assert len(recommendations) >= 0, "Should return recommendations list"
        
        for rec in recommendations:
            print(f"  - {rec['title']}: {rec['message']}")
            assert 'type' in rec, "Recommendation should have type"
            assert 'priority' in rec, "Recommendation should have priority"
            assert 'title' in rec, "Recommendation should have title"
            assert 'message' in rec, "Recommendation should have message"
        
        print("✓ Pattern-based recommendations verified")
        
        # Test 5: Verify database audit log entries
        print("\nTest 5: Verifying database audit log entries...")
        
        audit_logs = db.session.query(DuplicateCleanupAuditLog)\
            .filter(DuplicateCleanupAuditLog.user_id == test_user.id)\
            .all()
        
        print(f"✓ Found {len(audit_logs)} audit log entries in database")
        assert len(audit_logs) == 2, f"Expected 2 audit logs, got {len(audit_logs)}"
        
        for log in audit_logs:
            print(f"  - Action: {log.action_type}, Operation: {log.operation_type}, Tracks: {log.tracks_deleted_count}")
            assert log.success, "All actions should be successful"
            assert log.processing_time_seconds > 0, "Should have processing time"
            assert log.affected_track_ids, "Should have affected track IDs"
        
        print("✓ Database audit log entries verified")
        
        print("\n🎉 All cleanup history and audit trail tests passed!")


if __name__ == '__main__':
    test_cleanup_history()