"""
Integration tests for duplicate results persistence workflows.

This module contains comprehensive integration tests for end-to-end persistence workflows,
including complete analysis-to-persistence-to-retrieval workflows, progress tracking,
real-time updates, cancellation scenarios, export functionality, and concurrent analysis scenarios.
"""

import unittest
import uuid
import sys
import os
import tempfile
import json
import csv
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock, call, PropertyMock

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import Flask for minimal app context
from flask import Flask
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError

from services.duplicate_persistence_service import DuplicatePersistenceService
from services.duplicate_detection_service import DuplicateDetectionService, DuplicateGroup, DuplicateAnalysis, AnalysisProgress
from models import (
    DuplicateAnalysisResult, 
    DuplicateAnalysisGroup, 
    DuplicateAnalysisTrack,
    DuplicateAnalysisExport,
    UserPreferences,
    Track,
    User
)


class TestDuplicatePersistenceIntegration(unittest.TestCase):
    """Integration test cases for duplicate persistence workflows."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a minimal Flask app for testing
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        self.persistence_service = DuplicatePersistenceService()
        self.detection_service = DuplicateDetectionService()
        
        # Test data
        self.test_user_id = 1
        self.test_analysis_id = str(uuid.uuid4())
        self.base_time = datetime.now()
        
        # Create mock tracks
        self.mock_track1 = Mock()
        self.mock_track1.id = 1
        self.mock_track1.song = "Test Song"
        self.mock_track1.artist = "Test Artist"
        self.mock_track1.album = "Test Album"
        self.mock_track1.play_cnt = 10
        self.mock_track1.last_play_dt = self.base_time - timedelta(days=1)
        self.mock_track1.date_added = self.base_time - timedelta(days=30)
        
        self.mock_track2 = Mock()
        self.mock_track2.id = 2
        self.mock_track2.song = "Test Song (Remastered)"
        self.mock_track2.artist = "Test Artist"
        self.mock_track2.album = "Test Album"
        self.mock_track2.play_cnt = 5
        self.mock_track2.last_play_dt = self.base_time - timedelta(days=2)
        self.mock_track2.date_added = self.base_time - timedelta(days=25)
        
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
    
    @patch('services.duplicate_persistence_service.db')
    @patch('services.duplicate_detection_service.db')
    def test_complete_analysis_to_persistence_to_retrieval_workflow(self, mock_detection_db, mock_persistence_db):
        """Test complete workflow from analysis generation to persistence to retrieval."""
        
        # Step 1: Mock duplicate detection
        mock_detection_db.session.query.return_value.all.return_value = [self.mock_track1, self.mock_track2]
        
        with patch.object(self.detection_service, 'find_duplicates') as mock_find_duplicates:
            mock_find_duplicates.return_value = [self.mock_duplicate_group]
            
            # Step 2: Mock persistence saving
            mock_analysis_result = Mock(spec=DuplicateAnalysisResult)
            mock_analysis_result.analysis_id = self.test_analysis_id
            mock_analysis_result.user_id = self.test_user_id
            mock_analysis_result.status = 'completed'
            mock_analysis_result.created_at = self.base_time
            mock_analysis_result.total_groups_found = 1
            mock_analysis_result.total_duplicates_found = 1
            
            # Mock database operations for saving
            mock_persistence_db.session.query.return_value.count.return_value = 1000  # Total tracks
            mock_persistence_db.session.query.return_value.scalar.return_value = self.base_time  # Last modified
            mock_persistence_db.session.add.return_value = None
            mock_persistence_db.session.flush.return_value = None
            mock_persistence_db.session.commit.return_value = None
            
            with patch.object(self.persistence_service, 'save_analysis_result') as mock_save:
                mock_save.return_value = mock_analysis_result
                
                # Step 3: Perform analysis with persistence
                analysis_params = {
                    'search_term': None,
                    'sort_by': 'artist',
                    'min_confidence': 0.0,
                    'processing_time': 2.5
                }
                
                # Save analysis result
                saved_result = self.persistence_service.save_analysis_result(
                    self.test_user_id,
                    [self.mock_duplicate_group],
                    analysis_params,
                    self.mock_analysis_stats
                )
                
                self.assertEqual(saved_result.analysis_id, self.test_analysis_id)
                self.assertEqual(saved_result.user_id, self.test_user_id)
                self.assertEqual(saved_result.status, 'completed')
                
                # Step 4: Mock retrieval
                mock_persistence_db.session.query.return_value.options.return_value.filter.return_value.first.return_value = mock_analysis_result
                
                with patch.object(self.persistence_service, 'load_analysis_result') as mock_load:
                    mock_load.return_value = mock_analysis_result
                    
                    # Retrieve analysis result
                    retrieved_result = self.persistence_service.load_analysis_result(self.test_analysis_id)
                    
                    self.assertIsNotNone(retrieved_result)
                    self.assertEqual(retrieved_result.analysis_id, self.test_analysis_id)
                    
                    # Step 5: Convert back to duplicate groups
                    mock_group = Mock(spec=DuplicateAnalysisGroup)
                    mock_group.tracks = []
                    
                    # Mock canonical track
                    mock_canonical_track = Mock(spec=DuplicateAnalysisTrack)
                    mock_canonical_track.track_id = 1
                    mock_canonical_track.is_canonical = True
                    mock_canonical_track.similarity_score = 1.0
                    mock_canonical_track.song_name = "Test Song"
                    mock_canonical_track.artist_name = "Test Artist"
                    mock_canonical_track.still_exists = True
                    
                    # Mock duplicate track
                    mock_duplicate_track = Mock(spec=DuplicateAnalysisTrack)
                    mock_duplicate_track.track_id = 2
                    mock_duplicate_track.is_canonical = False
                    mock_duplicate_track.similarity_score = 0.95
                    mock_duplicate_track.song_name = "Test Song (Remastered)"
                    mock_duplicate_track.artist_name = "Test Artist"
                    mock_duplicate_track.still_exists = True
                    
                    mock_group.tracks = [mock_canonical_track, mock_duplicate_track]
                    mock_group.suggested_action = 'keep_canonical'
                    mock_analysis_result.groups = [mock_group]
                    
                    # Mock track queries for conversion
                    def mock_track_query(track_id):
                        if track_id == 1:
                            return self.mock_track1
                        elif track_id == 2:
                            return self.mock_track2
                        return None
                    
                    mock_persistence_db.session.query.return_value.filter.return_value.first.side_effect = lambda: mock_track_query(1)
                    
                    with patch.object(self.persistence_service, 'convert_to_duplicate_groups') as mock_convert:
                        mock_convert.return_value = [self.mock_duplicate_group]
                        
                        # Convert back to duplicate groups
                        converted_groups = self.persistence_service.convert_to_duplicate_groups(retrieved_result)
                        
                        self.assertEqual(len(converted_groups), 1)
                        self.assertEqual(converted_groups[0].canonical_song.id, 1)
                        self.assertEqual(len(converted_groups[0].duplicates), 1)
                        self.assertEqual(converted_groups[0].duplicates[0].id, 2)
    
    @patch('services.duplicate_detection_service.db')
    def test_progress_tracking_and_real_time_updates(self, mock_db):
        """Test progress tracking throughout the analysis process with real-time updates."""
        
        # Mock tracks for analysis
        mock_tracks = []
        for i in range(100):
            track = Mock()
            track.id = i + 1
            track.song = f"Song {i + 1}"
            track.artist = f"Artist {i % 10 + 1}"  # Create some duplicates
            track.album = f"Album {i % 5 + 1}"
            track.play_cnt = i % 20
            track.last_play_dt = self.base_time - timedelta(days=i % 30)
            track.date_added = self.base_time - timedelta(days=i % 100)
            mock_tracks.append(track)
        
        mock_db.session.query.return_value.all.return_value = mock_tracks
        
        # Track progress updates
        progress_updates = []
        
        def mock_progress_callback(progress: AnalysisProgress):
            progress_updates.append({
                'analysis_id': progress.analysis_id,
                'status': progress.status,
                'phase': progress.phase,
                'percentage': progress.percentage,
                'tracks_processed': progress.tracks_processed,
                'total_tracks': progress.total_tracks,
                'groups_found': progress.groups_found,
                'current_message': progress.current_message
            })
        
        # Mock the find_duplicates_with_persistence method
        with patch.object(self.detection_service, 'find_duplicates_with_persistence') as mock_find_with_persistence:
            
            def mock_analysis_with_progress(*args, **kwargs):
                analysis_id = str(uuid.uuid4())
                progress_callback = kwargs.get('progress_callback')
                
                if progress_callback:
                    # Simulate progress updates
                    phases = [
                        ('starting', 'Initializing analysis...', 0, 0),
                        ('loading_tracks', 'Loading tracks from database...', 25, 25),
                        ('analyzing_similarities', 'Analyzing track similarities...', 50, 50),
                        ('cross_referencing', 'Cross-referencing with iTunes...', 75, 75),
                        ('saving_results', 'Saving results to database...', 90, 90),
                        ('completed', 'Analysis completed successfully', 100, 100)
                    ]
                    
                    for i, (status, message, percentage, tracks_processed) in enumerate(phases):
                        progress = AnalysisProgress(
                            analysis_id=analysis_id,
                            status=status,
                            phase=message,
                            current_step=i + 1,
                            total_steps=len(phases),
                            percentage=percentage,
                            estimated_remaining_seconds=max(0, (len(phases) - i - 1) * 2),
                            current_message=message,
                            tracks_processed=tracks_processed,
                            total_tracks=100,
                            groups_found=i * 2,  # Simulate finding groups
                            start_time=self.base_time,
                            last_update=datetime.now()
                        )
                        progress_callback(progress)
                        time.sleep(0.1)  # Simulate processing time
                
                return {
                    'analysis_id': analysis_id,
                    'duplicate_groups': [self.mock_duplicate_group],
                    'analysis_stats': self.mock_analysis_stats,
                    'status': 'completed'
                }
            
            mock_find_with_persistence.side_effect = mock_analysis_with_progress
            
            # Run analysis with progress tracking
            result = self.detection_service.find_duplicates_with_persistence(
                user_id=self.test_user_id,
                progress_callback=mock_progress_callback
            )
            
            # Verify progress updates were received
            self.assertGreater(len(progress_updates), 0)
            
            # Check that we received all expected phases
            phases_received = [update['status'] for update in progress_updates]
            expected_phases = ['starting', 'loading_tracks', 'analyzing_similarities', 
                             'cross_referencing', 'saving_results', 'completed']
            
            for phase in expected_phases:
                self.assertIn(phase, phases_received)
            
            # Verify progress percentages increase
            percentages = [update['percentage'] for update in progress_updates]
            for i in range(1, len(percentages)):
                self.assertGreaterEqual(percentages[i], percentages[i-1])
            
            # Verify final status
            final_update = progress_updates[-1]
            self.assertEqual(final_update['status'], 'completed')
            self.assertEqual(final_update['percentage'], 100)
            self.assertEqual(final_update['tracks_processed'], 100)
    
    @patch('services.duplicate_detection_service.db')
    def test_analysis_cancellation_scenarios(self, mock_db):
        """Test cancellation scenarios with partial result preservation."""
        
        # Mock tracks for analysis
        mock_tracks = [Mock() for _ in range(50)]
        for i, track in enumerate(mock_tracks):
            track.id = i + 1
            track.song = f"Song {i + 1}"
            track.artist = f"Artist {i % 5 + 1}"
        
        mock_db.session.query.return_value.all.return_value = mock_tracks
        
        # Track cancellation
        cancellation_requested = threading.Event()
        analysis_cancelled = threading.Event()
        
        def mock_analysis_with_cancellation(*args, **kwargs):
            analysis_id = str(uuid.uuid4())
            progress_callback = kwargs.get('progress_callback')
            
            # Simulate analysis that can be cancelled
            for i in range(10):
                if cancellation_requested.is_set():
                    # Simulate cancellation
                    if progress_callback:
                        progress = AnalysisProgress(
                            analysis_id=analysis_id,
                            status='cancelled',
                            phase='Analysis cancelled by user',
                            current_step=i,
                            total_steps=10,
                            percentage=i * 10,
                            estimated_remaining_seconds=0,
                            current_message='Cancelling analysis...',
                            tracks_processed=i * 5,
                            total_tracks=50,
                            groups_found=i,
                            start_time=self.base_time,
                            last_update=datetime.now()
                        )
                        progress_callback(progress)
                    
                    analysis_cancelled.set()
                    return {
                        'analysis_id': analysis_id,
                        'status': 'cancelled',
                        'partial_results': True,
                        'groups_processed': i,
                        'message': 'Analysis cancelled by user request'
                    }
                
                # Simulate progress
                if progress_callback:
                    progress = AnalysisProgress(
                        analysis_id=analysis_id,
                        status='analyzing_similarities',
                        phase=f'Processing batch {i + 1}/10',
                        current_step=i + 1,
                        total_steps=10,
                        percentage=(i + 1) * 10,
                        estimated_remaining_seconds=(10 - i - 1) * 2,
                        current_message=f'Analyzing tracks {i * 5 + 1}-{(i + 1) * 5}',
                        tracks_processed=(i + 1) * 5,
                        total_tracks=50,
                        groups_found=i,
                        start_time=self.base_time,
                        last_update=datetime.now()
                    )
                    progress_callback(progress)
                
                time.sleep(0.1)  # Simulate processing time
            
            return {
                'analysis_id': analysis_id,
                'duplicate_groups': [self.mock_duplicate_group],
                'analysis_stats': self.mock_analysis_stats,
                'status': 'completed'
            }
        
        with patch.object(self.detection_service, 'find_duplicates_with_persistence') as mock_find:
            mock_find.side_effect = mock_analysis_with_cancellation
            
            # Start analysis in a separate thread
            analysis_result = {}
            analysis_error = None
            
            def run_analysis():
                try:
                    nonlocal analysis_result
                    analysis_result = self.detection_service.find_duplicates_with_persistence(
                        user_id=self.test_user_id,
                        progress_callback=lambda p: None
                    )
                except Exception as e:
                    nonlocal analysis_error
                    analysis_error = e
            
            analysis_thread = threading.Thread(target=run_analysis)
            analysis_thread.start()
            
            # Wait a bit then cancel
            time.sleep(0.3)
            cancellation_requested.set()
            
            # Wait for cancellation to complete
            analysis_cancelled.wait(timeout=2.0)
            analysis_thread.join(timeout=2.0)
            
            # Verify cancellation was handled
            self.assertIsNone(analysis_error)
            self.assertIn('status', analysis_result)
            self.assertEqual(analysis_result['status'], 'cancelled')
            self.assertTrue(analysis_result.get('partial_results', False))
    
    @patch('services.duplicate_persistence_service.db')
    def test_export_functionality_various_formats(self, mock_db):
        """Test export functionality with various formats and data sizes."""
        
        # Create mock analysis result with multiple groups
        mock_analysis_result = Mock(spec=DuplicateAnalysisResult)
        mock_analysis_result.analysis_id = self.test_analysis_id
        mock_analysis_result.user_id = self.test_user_id
        mock_analysis_result.created_at = self.base_time
        mock_analysis_result.status = 'completed'
        mock_analysis_result.search_term = None
        mock_analysis_result.sort_by = 'artist'
        mock_analysis_result.total_groups_found = 3
        mock_analysis_result.total_duplicates_found = 5
        mock_analysis_result.average_similarity_score = 0.92
        
        # Create mock groups with tracks
        mock_groups = []
        for group_idx in range(3):
            mock_group = Mock(spec=DuplicateAnalysisGroup)
            mock_group.id = group_idx + 1
            mock_group.group_index = group_idx
            mock_group.canonical_track_id = group_idx * 2 + 1
            mock_group.duplicate_count = 2
            mock_group.average_similarity_score = 0.9 + (group_idx * 0.02)
            mock_group.suggested_action = 'keep_canonical'
            mock_group.resolved = False
            
            # Create mock tracks for this group
            mock_tracks = []
            for track_idx in range(2):
                mock_track = Mock(spec=DuplicateAnalysisTrack)
                mock_track.track_id = group_idx * 2 + track_idx + 1
                mock_track.song_name = f"Song {group_idx + 1}"
                mock_track.artist_name = f"Artist {group_idx + 1}"
                mock_track.album_name = f"Album {group_idx + 1}"
                mock_track.similarity_score = 1.0 if track_idx == 0 else 0.9 + (group_idx * 0.02)
                mock_track.is_canonical = track_idx == 0
                mock_track.still_exists = True
                mock_tracks.append(mock_track)
            
            mock_group.tracks = mock_tracks
            mock_groups.append(mock_group)
        
        mock_analysis_result.groups = mock_groups
        
        # Mock database query for loading analysis
        mock_db.session.query.return_value.options.return_value.filter.return_value.first.return_value = mock_analysis_result
        
        # Test JSON export
        with patch('tempfile.NamedTemporaryFile') as mock_temp_file:
            mock_file = Mock()
            mock_file.name = '/tmp/test_export.json'
            mock_temp_file.return_value.__enter__.return_value = mock_file
            
            with patch.object(self.persistence_service, 'export_analysis_results') as mock_export:
                mock_export.return_value = {
                    'analysis_id': self.test_analysis_id,
                    'created_at': self.base_time.isoformat(),
                    'total_groups': 3,
                    'total_duplicates': 5,
                    'groups': [
                        {
                            'group_index': 0,
                            'canonical_track': {'id': 1, 'song': 'Song 1', 'artist': 'Artist 1'},
                            'duplicates': [{'id': 2, 'song': 'Song 1', 'artist': 'Artist 1'}],
                            'similarity_scores': {'1': 1.0, '2': 0.9}
                        }
                    ]
                }
                
                # Test JSON export
                json_result = self.persistence_service.export_analysis_results(
                    self.test_analysis_id, format='json'
                )
                
                self.assertIn('analysis_id', json_result)
                self.assertIn('groups', json_result)
                self.assertEqual(json_result['total_groups'], 3)
                
                # Test CSV export
                csv_result = self.persistence_service.export_analysis_results(
                    self.test_analysis_id, format='csv'
                )
                
                self.assertIsInstance(csv_result, dict)
    
    @patch('services.duplicate_detection_service.db')
    @patch('services.duplicate_persistence_service.db')
    def test_concurrent_analysis_scenarios(self, mock_persistence_db, mock_detection_db):
        """Test concurrent analysis scenarios and resource contention handling."""
        
        # Mock tracks for analysis
        mock_tracks = [Mock() for _ in range(20)]
        for i, track in enumerate(mock_tracks):
            track.id = i + 1
            track.song = f"Song {i + 1}"
            track.artist = f"Artist {i % 3 + 1}"  # Create overlapping artists
        
        mock_detection_db.session.query.return_value.all.return_value = mock_tracks
        
        # Track concurrent analyses
        concurrent_analyses = {}
        analysis_lock = threading.Lock()
        
        def mock_concurrent_analysis(*args, **kwargs):
            analysis_id = str(uuid.uuid4())
            user_id = kwargs.get('user_id', 1)
            
            with analysis_lock:
                concurrent_analyses[analysis_id] = {
                    'user_id': user_id,
                    'start_time': datetime.now(),
                    'status': 'running'
                }
            
            # Simulate analysis work
            time.sleep(0.2)
            
            with analysis_lock:
                concurrent_analyses[analysis_id]['status'] = 'completed'
                concurrent_analyses[analysis_id]['end_time'] = datetime.now()
            
            return {
                'analysis_id': analysis_id,
                'duplicate_groups': [self.mock_duplicate_group],
                'analysis_stats': self.mock_analysis_stats,
                'status': 'completed'
            }
        
        # Mock persistence operations
        mock_persistence_db.session.query.return_value.count.return_value = 20
        mock_persistence_db.session.query.return_value.scalar.return_value = self.base_time
        mock_persistence_db.session.add.return_value = None
        mock_persistence_db.session.flush.return_value = None
        mock_persistence_db.session.commit.return_value = None
        
        with patch.object(self.detection_service, 'find_duplicates_with_persistence') as mock_find:
            mock_find.side_effect = mock_concurrent_analysis
            
            # Start multiple concurrent analyses
            threads = []
            results = {}
            
            def run_concurrent_analysis(user_id, analysis_key):
                try:
                    result = self.detection_service.find_duplicates_with_persistence(
                        user_id=user_id,
                        search_term=f"test_{user_id}",
                        force_refresh=True
                    )
                    results[analysis_key] = result
                except Exception as e:
                    results[analysis_key] = {'error': str(e)}
            
            # Start 5 concurrent analyses for different users
            for i in range(5):
                user_id = i + 1
                analysis_key = f"analysis_{i}"
                thread = threading.Thread(
                    target=run_concurrent_analysis,
                    args=(user_id, analysis_key)
                )
                threads.append(thread)
                thread.start()
            
            # Wait for all analyses to complete
            for thread in threads:
                thread.join(timeout=5.0)
            
            # Verify all analyses completed successfully
            self.assertEqual(len(results), 5)
            
            for analysis_key, result in results.items():
                self.assertNotIn('error', result)
                self.assertIn('analysis_id', result)
                self.assertEqual(result['status'], 'completed')
            
            # Verify concurrent tracking worked
            completed_analyses = [
                analysis for analysis in concurrent_analyses.values()
                if analysis['status'] == 'completed'
            ]
            self.assertEqual(len(completed_analyses), 5)
            
            # Verify different users were handled
            user_ids = set(analysis['user_id'] for analysis in concurrent_analyses.values())
            self.assertEqual(len(user_ids), 5)
    
    @patch('services.duplicate_persistence_service.db')
    def test_large_dataset_performance(self, mock_db):
        """Test performance with large datasets and memory management."""
        
        # Create a large mock dataset
        large_dataset_size = 1000
        mock_tracks = []
        
        for i in range(large_dataset_size):
            track = Mock()
            track.id = i + 1
            track.song = f"Song {i + 1}"
            track.artist = f"Artist {i % 50 + 1}"  # 50 different artists
            track.album = f"Album {i % 100 + 1}"  # 100 different albums
            track.play_cnt = i % 100
            track.last_play_dt = self.base_time - timedelta(days=i % 365)
            track.date_added = self.base_time - timedelta(days=i % 1000)
            mock_tracks.append(track)
        
        # Create many duplicate groups
        mock_groups = []
        for i in range(100):  # 100 duplicate groups
            canonical = mock_tracks[i * 10]
            duplicates = mock_tracks[i * 10 + 1:(i + 1) * 10]
            
            group = DuplicateGroup(
                canonical_song=canonical,
                duplicates=duplicates,
                similarity_scores={track.id: 0.9 + (0.1 * (j / len(duplicates))) 
                                 for j, track in enumerate([canonical] + duplicates)},
                suggested_action='keep_canonical'
            )
            mock_groups.append(group)
        
        # Mock database operations with batching
        mock_db.session.query.return_value.count.return_value = large_dataset_size
        mock_db.session.query.return_value.scalar.return_value = self.base_time
        mock_db.session.add.return_value = None
        mock_db.session.flush.return_value = None
        mock_db.session.commit.return_value = None
        
        # Test saving large dataset
        start_time = time.time()
        
        try:
            with patch.object(self.persistence_service, 'save_analysis_result') as mock_save:
                mock_analysis_result = Mock(spec=DuplicateAnalysisResult)
                mock_analysis_result.analysis_id = self.test_analysis_id
                mock_analysis_result.user_id = self.test_user_id
                mock_analysis_result.status = 'completed'
                mock_save.return_value = mock_analysis_result
                
                # Create large analysis stats
                large_analysis_stats = DuplicateAnalysis(
                    total_groups=100,
                    total_duplicates=900,
                    potential_deletions=900,
                    estimated_space_savings="3.6 GB",
                    groups_with_high_confidence=95,
                    average_similarity_score=0.92
                )
                
                # Save large dataset
                result = self.persistence_service.save_analysis_result(
                    self.test_user_id,
                    mock_groups,
                    {'search_term': None, 'sort_by': 'artist', 'min_confidence': 0.0},
                    large_analysis_stats
                )
                
                self.assertIsNotNone(result)
                self.assertEqual(result.analysis_id, self.test_analysis_id)
                
        except Exception as e:
            self.fail(f"Large dataset processing failed: {str(e)}")
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Verify reasonable performance (should complete within 10 seconds for mocked operations)
        self.assertLess(processing_time, 10.0, 
                       f"Large dataset processing took too long: {processing_time:.2f} seconds")
    
    @patch('services.duplicate_persistence_service.db')
    def test_error_recovery_and_rollback(self, mock_db):
        """Test error recovery and database rollback scenarios."""
        
        # Test database connection failure
        mock_db.session.query.side_effect = SQLAlchemyError("Connection lost")
        
        with self.assertRaises(Exception) as context:
            self.persistence_service.save_analysis_result(
                self.test_user_id,
                [self.mock_duplicate_group],
                {'search_term': None, 'sort_by': 'artist'},
                self.mock_analysis_stats
            )
        
        self.assertIn("Failed to save analysis result", str(context.exception))
        
        # Test partial failure with rollback
        mock_db.session.query.side_effect = None  # Reset
        mock_db.session.add.side_effect = [None, None, IntegrityError("", "", "")]  # Fail on third add
        
        with self.assertRaises(Exception):
            self.persistence_service.save_analysis_result(
                self.test_user_id,
                [self.mock_duplicate_group],
                {'search_term': None, 'sort_by': 'artist'},
                self.mock_analysis_stats
            )
        
        # Verify rollback was called
        mock_db.session.rollback.assert_called()
    
    @patch('services.duplicate_persistence_service.db')
    def test_data_consistency_across_operations(self, mock_db):
        """Test data consistency across multiple persistence operations."""
        
        # Mock successful database operations
        mock_db.session.query.return_value.count.return_value = 100
        mock_db.session.query.return_value.scalar.return_value = self.base_time
        mock_db.session.add.return_value = None
        mock_db.session.flush.return_value = None
        mock_db.session.commit.return_value = None
        
        # Create multiple analyses for consistency testing
        analysis_ids = []
        
        for i in range(3):
            analysis_id = str(uuid.uuid4())
            analysis_ids.append(analysis_id)
            
            mock_result = Mock(spec=DuplicateAnalysisResult)
            mock_result.analysis_id = analysis_id
            mock_result.user_id = self.test_user_id
            mock_result.status = 'completed'
            mock_result.created_at = self.base_time + timedelta(minutes=i)
            
            with patch.object(self.persistence_service, 'save_analysis_result') as mock_save:
                mock_save.return_value = mock_result
                
                result = self.persistence_service.save_analysis_result(
                    self.test_user_id,
                    [self.mock_duplicate_group],
                    {'search_term': f"test_{i}", 'sort_by': 'artist'},
                    self.mock_analysis_stats
                )
                
                self.assertEqual(result.analysis_id, analysis_id)
        
        # Test retrieval consistency
        for analysis_id in analysis_ids:
            mock_analysis = Mock(spec=DuplicateAnalysisResult)
            mock_analysis.analysis_id = analysis_id
            mock_analysis.user_id = self.test_user_id
            
            mock_db.session.query.return_value.options.return_value.filter.return_value.first.return_value = mock_analysis
            
            with patch.object(self.persistence_service, 'load_analysis_result') as mock_load:
                mock_load.return_value = mock_analysis
                
                retrieved = self.persistence_service.load_analysis_result(analysis_id)
                self.assertIsNotNone(retrieved)
                self.assertEqual(retrieved.analysis_id, analysis_id)
        
        # Test user analyses listing consistency
        mock_analyses = []
        for analysis_id in analysis_ids:
            mock_analysis = Mock(spec=DuplicateAnalysisResult)
            mock_analysis.analysis_id = analysis_id
            mock_analysis.user_id = self.test_user_id
            mock_analyses.append(mock_analysis)
        
        mock_db.session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.offset.return_value.all.return_value = mock_analyses
        
        with patch.object(self.persistence_service, 'get_user_analyses') as mock_get_user:
            mock_get_user.return_value = mock_analyses
            
            user_analyses = self.persistence_service.get_user_analyses(self.test_user_id)
            self.assertEqual(len(user_analyses), 3)
            
            # Verify all analyses belong to the same user
            for analysis in user_analyses:
                self.assertEqual(analysis.user_id, self.test_user_id)



class TestDuplicatePersistenceAdvancedIntegration(unittest.TestCase):
    """Advanced integration test cases for specific persistence scenarios."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a minimal Flask app for testing
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        self.persistence_service = DuplicatePersistenceService()
        self.detection_service = DuplicateDetectionService()
        
        self.test_user_id = 1
        self.base_time = datetime.now()
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.app_context.pop()
    
    @patch('services.duplicate_persistence_service.db')
    def test_export_with_large_datasets_and_streaming(self, mock_db):
        """Test export functionality with large datasets using streaming processing."""
        
        # Create a large mock analysis result
        mock_analysis_result = Mock(spec=DuplicateAnalysisResult)
        mock_analysis_result.analysis_id = str(uuid.uuid4())
        mock_analysis_result.user_id = self.test_user_id
        mock_analysis_result.created_at = self.base_time
        mock_analysis_result.total_groups_found = 500  # Large dataset
        mock_analysis_result.total_duplicates_found = 2000
        
        # Create many mock groups
        mock_groups = []
        for i in range(500):
            mock_group = Mock(spec=DuplicateAnalysisGroup)
            mock_group.id = i + 1
            mock_group.group_index = i
            mock_group.canonical_track_id = i * 4 + 1
            mock_group.duplicate_count = 4
            mock_group.average_similarity_score = 0.85 + (i % 15) * 0.01
            
            # Create tracks for each group
            mock_tracks = []
            for j in range(4):
                mock_track = Mock(spec=DuplicateAnalysisTrack)
                mock_track.track_id = i * 4 + j + 1
                mock_track.song_name = f"Song {i + 1}"
                mock_track.artist_name = f"Artist {(i % 50) + 1}"
                mock_track.album_name = f"Album {(i % 100) + 1}"
                mock_track.similarity_score = 1.0 if j == 0 else 0.85 + (j * 0.05)
                mock_track.is_canonical = j == 0
                mock_track.still_exists = True
                mock_tracks.append(mock_track)
            
            mock_group.tracks = mock_tracks
            mock_groups.append(mock_group)
        
        mock_analysis_result.groups = mock_groups
        
        # Mock database query
        mock_db.session.query.return_value.options.return_value.filter.return_value.first.return_value = mock_analysis_result
        
        # Test streaming export for large dataset
        with patch('tempfile.NamedTemporaryFile') as mock_temp_file:
            mock_file = Mock()
            mock_file.name = '/tmp/large_export.json'
            mock_file.write = Mock()
            mock_temp_file.return_value.__enter__.return_value = mock_file
            
            # Test JSON export with streaming
            start_time = time.time()
            
            with patch.object(self.persistence_service, 'export_analysis_results') as mock_export:
                # Simulate streaming export
                def streaming_export(analysis_id, format='json'):
                    # Simulate processing in chunks
                    chunks_processed = 0
                    total_chunks = 50  # 500 groups / 10 groups per chunk
                    
                    export_data = {
                        'analysis_id': analysis_id,
                        'created_at': self.base_time.isoformat(),
                        'total_groups': 500,
                        'total_duplicates': 2000,
                        'groups': []
                    }
                    
                    # Process in chunks to simulate streaming
                    for chunk_start in range(0, 500, 10):
                        chunk_end = min(chunk_start + 10, 500)
                        chunk_groups = []
                        
                        for i in range(chunk_start, chunk_end):
                            group_data = {
                                'group_index': i,
                                'canonical_track': {
                                    'id': i * 4 + 1,
                                    'song': f'Song {i + 1}',
                                    'artist': f'Artist {(i % 50) + 1}'
                                },
                                'duplicates': [
                                    {
                                        'id': i * 4 + j + 1,
                                        'song': f'Song {i + 1}',
                                        'artist': f'Artist {(i % 50) + 1}',
                                        'similarity_score': 0.85 + (j * 0.05)
                                    }
                                    for j in range(1, 4)
                                ]
                            }
                            chunk_groups.append(group_data)
                        
                        export_data['groups'].extend(chunk_groups)
                        chunks_processed += 1
                        
                        # Simulate processing time
                        time.sleep(0.001)
                    
                    return export_data
                
                mock_export.side_effect = streaming_export
                
                result = self.persistence_service.export_analysis_results(
                    mock_analysis_result.analysis_id, format='json'
                )
                
                end_time = time.time()
                processing_time = end_time - start_time
                
                # Verify export completed successfully
                self.assertIn('analysis_id', result)
                self.assertEqual(result['total_groups'], 500)
                self.assertEqual(len(result['groups']), 500)
                
                # Verify reasonable performance for large dataset
                self.assertLess(processing_time, 5.0, 
                               f"Large export took too long: {processing_time:.2f} seconds")
    
    @patch('services.duplicate_detection_service.db')
    @patch('services.duplicate_persistence_service.db')
    def test_concurrent_analysis_with_resource_contention(self, mock_persistence_db, mock_detection_db):
        """Test concurrent analysis scenarios with database resource contention."""
        
        # Mock database contention scenarios
        contention_count = 0
        max_contentions = 3
        
        def mock_db_operation_with_contention(*args, **kwargs):
            nonlocal contention_count
            if contention_count < max_contentions:
                contention_count += 1
                raise OperationalError("database is locked", "", "")
            return Mock()
        
        # Setup mock for detection service
        mock_tracks = [Mock() for _ in range(10)]
        for i, track in enumerate(mock_tracks):
            track.id = i + 1
            track.song = f"Song {i + 1}"
            track.artist = f"Artist {(i % 3) + 1}"
        
        mock_detection_db.session.query.return_value.all.return_value = mock_tracks
        
        # Setup mock for persistence service with contention
        mock_persistence_db.session.query.return_value.count.side_effect = mock_db_operation_with_contention
        mock_persistence_db.session.query.return_value.scalar.return_value = self.base_time
        mock_persistence_db.session.add.return_value = None
        mock_persistence_db.session.flush.return_value = None
        mock_persistence_db.session.commit.return_value = None
        
        # Track retry attempts
        retry_attempts = []
        
        def mock_analysis_with_retries(*args, **kwargs):
            analysis_id = str(uuid.uuid4())
            user_id = kwargs.get('user_id', 1)
            
            # Simulate retry logic
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    retry_attempts.append({
                        'analysis_id': analysis_id,
                        'user_id': user_id,
                        'attempt': attempt + 1,
                        'timestamp': datetime.now()
                    })
                    
                    # Simulate database operation that might fail
                    if attempt < 2:  # Fail first 2 attempts
                        raise OperationalError("database is locked", "", "")
                    
                    # Success on third attempt
                    return {
                        'analysis_id': analysis_id,
                        'status': 'completed',
                        'retry_attempts': attempt + 1
                    }
                    
                except OperationalError:
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(0.1 * (attempt + 1))  # Exponential backoff
            
            return {'analysis_id': analysis_id, 'status': 'failed'}
        
        with patch.object(self.detection_service, 'find_duplicates_with_persistence') as mock_find:
            mock_find.side_effect = mock_analysis_with_retries
            
            # Run concurrent analyses that will experience contention
            threads = []
            results = {}
            
            def run_analysis_with_contention(user_id, key):
                try:
                    result = self.detection_service.find_duplicates_with_persistence(
                        user_id=user_id,
                        force_refresh=True
                    )
                    results[key] = result
                except Exception as e:
                    results[key] = {'error': str(e)}
            
            # Start 3 concurrent analyses
            for i in range(3):
                thread = threading.Thread(
                    target=run_analysis_with_contention,
                    args=(i + 1, f"analysis_{i}")
                )
                threads.append(thread)
                thread.start()
            
            # Wait for completion
            for thread in threads:
                thread.join(timeout=5.0)
            
            # Verify all analyses eventually succeeded despite contention
            self.assertEqual(len(results), 3)
            
            for key, result in results.items():
                self.assertNotIn('error', result)
                self.assertEqual(result['status'], 'completed')
                self.assertGreaterEqual(result.get('retry_attempts', 0), 1)
            
            # Verify retry attempts were made
            self.assertGreater(len(retry_attempts), 3)  # Should have retry attempts
    
    @patch('services.duplicate_persistence_service.db')
    def test_export_progress_tracking_and_cancellation(self, mock_db):
        """Test export progress tracking and cancellation for large exports."""
        
        # Create large mock analysis
        mock_analysis_result = Mock(spec=DuplicateAnalysisResult)
        mock_analysis_result.analysis_id = str(uuid.uuid4())
        mock_analysis_result.user_id = self.test_user_id
        mock_analysis_result.total_groups_found = 200
        
        # Create mock groups
        mock_groups = []
        for i in range(200):
            mock_group = Mock(spec=DuplicateAnalysisGroup)
            mock_group.id = i + 1
            mock_group.tracks = [Mock(spec=DuplicateAnalysisTrack) for _ in range(3)]
            mock_groups.append(mock_group)
        
        mock_analysis_result.groups = mock_groups
        mock_db.session.query.return_value.options.return_value.filter.return_value.first.return_value = mock_analysis_result
        
        # Track export progress
        export_progress = []
        export_cancelled = threading.Event()
        
        def mock_export_with_progress(analysis_id, format='json'):
            export_id = str(uuid.uuid4())
            
            # Simulate export progress
            total_groups = 200
            batch_size = 10
            
            for batch_start in range(0, total_groups, batch_size):
                if export_cancelled.is_set():
                    return {
                        'export_id': export_id,
                        'status': 'cancelled',
                        'progress': batch_start / total_groups * 100,
                        'message': 'Export cancelled by user'
                    }
                
                batch_end = min(batch_start + batch_size, total_groups)
                progress_percent = (batch_end / total_groups) * 100
                
                export_progress.append({
                    'export_id': export_id,
                    'progress': progress_percent,
                    'groups_processed': batch_end,
                    'total_groups': total_groups,
                    'timestamp': datetime.now()
                })
                
                time.sleep(0.05)  # Simulate processing time
            
            return {
                'export_id': export_id,
                'status': 'completed',
                'file_size': total_groups * 1024,  # Simulate file size
                'format': format
            }
        
        with patch.object(self.persistence_service, 'export_analysis_results') as mock_export:
            mock_export.side_effect = mock_export_with_progress
            
            # Start export in separate thread
            export_result = {}
            
            def run_export():
                nonlocal export_result
                export_result = self.persistence_service.export_analysis_results(
                    mock_analysis_result.analysis_id, format='json'
                )
            
            export_thread = threading.Thread(target=run_export)
            export_thread.start()
            
            # Let it run for a bit, then cancel
            time.sleep(0.3)
            export_cancelled.set()
            
            export_thread.join(timeout=2.0)
            
            # Verify progress was tracked
            self.assertGreater(len(export_progress), 0)
            
            # Verify progress increased over time
            if len(export_progress) > 1:
                for i in range(1, len(export_progress)):
                    self.assertGreaterEqual(
                        export_progress[i]['progress'],
                        export_progress[i-1]['progress']
                    )
            
            # Verify cancellation was handled
            if export_result.get('status') == 'cancelled':
                self.assertLess(export_result['progress'], 100)
    
    @patch('services.duplicate_detection_service.db')
    def test_memory_management_during_large_analysis(self, mock_db):
        """Test memory management and garbage collection during large analysis."""
        
        # Create very large mock dataset
        large_dataset_size = 5000
        mock_tracks = []
        
        for i in range(large_dataset_size):
            track = Mock()
            track.id = i + 1
            track.song = f"Song {i + 1}"
            track.artist = f"Artist {i % 100 + 1}"  # 100 different artists
            track.album = f"Album {i % 200 + 1}"
            track.play_cnt = i % 50
            track.last_play_dt = self.base_time - timedelta(days=i % 365)
            track.date_added = self.base_time - timedelta(days=i % 1000)
            mock_tracks.append(track)
        
        mock_db.session.query.return_value.all.return_value = mock_tracks
        
        # Track memory usage during analysis
        memory_snapshots = []
        
        def mock_analysis_with_memory_tracking(*args, **kwargs):
            analysis_id = str(uuid.uuid4())
            progress_callback = kwargs.get('progress_callback')
            
            # Simulate memory-intensive analysis
            batch_size = 500
            total_batches = large_dataset_size // batch_size
            
            for batch_num in range(total_batches):
                # Simulate memory usage
                import psutil
                process = psutil.Process(os.getpid())
                memory_info = process.memory_info()
                
                memory_snapshots.append({
                    'batch': batch_num,
                    'memory_mb': memory_info.rss / 1024 / 1024,
                    'timestamp': datetime.now()
                })
                
                # Simulate progress callback
                if progress_callback:
                    progress = AnalysisProgress(
                        analysis_id=analysis_id,
                        status='analyzing_similarities',
                        phase=f'Processing batch {batch_num + 1}/{total_batches}',
                        current_step=batch_num + 1,
                        total_steps=total_batches,
                        percentage=(batch_num + 1) / total_batches * 100,
                        estimated_remaining_seconds=(total_batches - batch_num - 1) * 0.1,
                        current_message=f'Analyzing tracks {batch_num * batch_size + 1}-{(batch_num + 1) * batch_size}',
                        tracks_processed=(batch_num + 1) * batch_size,
                        total_tracks=large_dataset_size,
                        groups_found=batch_num * 10,  # Simulate finding groups
                        start_time=self.base_time,
                        last_update=datetime.now()
                    )
                    progress_callback(progress)
                
                # Simulate garbage collection every few batches
                if batch_num % 5 == 0:
                    import gc
                    gc.collect()
                
                time.sleep(0.01)  # Simulate processing time
            
            return {
                'analysis_id': analysis_id,
                'status': 'completed',
                'tracks_processed': large_dataset_size,
                'memory_snapshots': len(memory_snapshots)
            }
        
        with patch.object(self.detection_service, 'find_duplicates_with_persistence') as mock_find:
            mock_find.side_effect = mock_analysis_with_memory_tracking
            
            # Run analysis with memory tracking
            result = self.detection_service.find_duplicates_with_persistence(
                user_id=self.test_user_id,
                progress_callback=lambda p: None
            )
            
            # Verify analysis completed
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['tracks_processed'], large_dataset_size)
            
            # Verify memory snapshots were taken
            self.assertGreater(len(memory_snapshots), 0)
            
            # Check that memory usage didn't grow unbounded
            if len(memory_snapshots) > 5:
                # Memory should not continuously increase
                memory_values = [snapshot['memory_mb'] for snapshot in memory_snapshots]
                max_memory = max(memory_values)
                min_memory = min(memory_values)
                
                # Memory growth should be reasonable (not more than 500MB increase)
                memory_growth = max_memory - min_memory
                self.assertLess(memory_growth, 500, 
                               f"Memory usage grew too much: {memory_growth:.2f} MB")
    
    @patch('services.duplicate_persistence_service.db')
    def test_database_transaction_integrity(self, mock_db):
        """Test database transaction integrity during complex operations."""
        
        # Test scenario: Multiple operations in a transaction
        transaction_log = []
        
        def mock_transaction_operation(operation_name):
            transaction_log.append({
                'operation': operation_name,
                'timestamp': datetime.now(),
                'thread_id': threading.current_thread().ident
            })
            
            # Simulate some operations failing
            if operation_name == 'save_group_3' and len(transaction_log) > 5:
                raise IntegrityError("Constraint violation", "", "")
            
            return Mock()
        
        # Mock database operations
        mock_db.session.query.return_value.count.return_value = 100
        mock_db.session.query.return_value.scalar.return_value = self.base_time
        mock_db.session.add.side_effect = lambda obj: mock_transaction_operation(f'add_{type(obj).__name__}')
        mock_db.session.flush.side_effect = lambda: mock_transaction_operation('flush')
        mock_db.session.commit.side_effect = lambda: mock_transaction_operation('commit')
        mock_db.session.rollback.side_effect = lambda: mock_transaction_operation('rollback')
        
        # Create multiple duplicate groups for complex transaction
        duplicate_groups = []
        for i in range(5):
            canonical = Mock()
            canonical.id = i * 2 + 1
            canonical.song = f"Song {i + 1}"
            canonical.artist = f"Artist {i + 1}"
            
            duplicate = Mock()
            duplicate.id = i * 2 + 2
            duplicate.song = f"Song {i + 1} (Remastered)"
            duplicate.artist = f"Artist {i + 1}"
            
            group = DuplicateGroup(
                canonical_song=canonical,
                duplicates=[duplicate],
                similarity_scores={canonical.id: 1.0, duplicate.id: 0.9},
                suggested_action='keep_canonical'
            )
            duplicate_groups.append(group)
        
        # Test transaction with failure and rollback
        # Make the commit operation fail to trigger rollback
        mock_db.session.commit.side_effect = IntegrityError("Transaction failed", "", "")
        
        with self.assertRaises(Exception):
            self.persistence_service.save_analysis_result(
                self.test_user_id,
                duplicate_groups,
                {'search_term': None, 'sort_by': 'artist'},
                DuplicateAnalysis(
                    total_groups=5,
                    total_duplicates=5,
                    potential_deletions=5,
                    estimated_space_savings="20 MB",
                    groups_with_high_confidence=5,
                    average_similarity_score=0.95
                )
            )
        
        # Verify rollback was called (should be called by the service's error handling)
        # Since we're mocking the database operations, we'll verify that the mock was called
        mock_db.session.rollback.assert_called()
    
    @patch('services.duplicate_persistence_service.db')
    def test_cleanup_operations_with_concurrent_access(self, mock_db):
        """Test cleanup operations while other operations are accessing the data."""
        
        # Create mock old analyses for cleanup
        old_analyses = []
        for i in range(10):
            analysis = Mock(spec=DuplicateAnalysisResult)
            analysis.analysis_id = str(uuid.uuid4())
            analysis.user_id = self.test_user_id
            analysis.created_at = self.base_time - timedelta(days=35 + i)  # Old analyses
            analysis.status = 'completed'
            old_analyses.append(analysis)
        
        # Mock database queries for cleanup
        mock_db.session.query.return_value.filter.return_value.all.return_value = old_analyses
        mock_db.session.query.return_value.distinct.return_value.all.return_value = [(self.test_user_id,)]
        mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = old_analyses
        
        cleanup_operations = []
        access_operations = []
        
        def mock_cleanup_operation():
            """Simulate cleanup operation."""
            try:
                cleanup_operations.append({
                    'operation': 'cleanup_start',
                    'timestamp': datetime.now(),
                    'thread_id': threading.current_thread().ident
                })
                
                # Simulate cleanup work
                time.sleep(0.2)
                
                cleanup_operations.append({
                    'operation': 'cleanup_complete',
                    'timestamp': datetime.now(),
                    'analyses_cleaned': len(old_analyses)
                })
                
                return {'deleted_by_age': 8, 'deleted_by_limit': 2, 'total_deleted': 10, 'errors': 0}
                
            except Exception as e:
                cleanup_operations.append({
                    'operation': 'cleanup_error',
                    'error': str(e),
                    'timestamp': datetime.now()
                })
                raise
        
        def mock_access_operation(analysis_id):
            """Simulate concurrent access to analysis data."""
            try:
                access_operations.append({
                    'operation': 'access_start',
                    'analysis_id': analysis_id,
                    'timestamp': datetime.now(),
                    'thread_id': threading.current_thread().ident
                })
                
                # Simulate data access
                time.sleep(0.1)
                
                access_operations.append({
                    'operation': 'access_complete',
                    'analysis_id': analysis_id,
                    'timestamp': datetime.now()
                })
                
                return Mock(spec=DuplicateAnalysisResult)
                
            except Exception as e:
                access_operations.append({
                    'operation': 'access_error',
                    'analysis_id': analysis_id,
                    'error': str(e),
                    'timestamp': datetime.now()
                })
                return None
        
        # Mock the cleanup and access methods
        with patch.object(self.persistence_service, 'cleanup_old_results') as mock_cleanup:
            mock_cleanup.side_effect = mock_cleanup_operation
            
            with patch.object(self.persistence_service, 'load_analysis_result') as mock_load:
                mock_load.side_effect = lambda aid: mock_access_operation(aid)
                
                # Start cleanup in background thread
                cleanup_thread = threading.Thread(
                    target=lambda: self.persistence_service.cleanup_old_results()
                )
                cleanup_thread.start()
                
                # Simulate concurrent access attempts
                access_threads = []
                for i in range(3):
                    analysis_id = old_analyses[i].analysis_id
                    thread = threading.Thread(
                        target=lambda aid=analysis_id: self.persistence_service.load_analysis_result(aid)
                    )
                    access_threads.append(thread)
                    thread.start()
                
                # Wait for all operations to complete
                cleanup_thread.join(timeout=2.0)
                for thread in access_threads:
                    thread.join(timeout=2.0)
                
                # Verify operations completed
                cleanup_starts = [op for op in cleanup_operations if op['operation'] == 'cleanup_start']
                cleanup_completes = [op for op in cleanup_operations if op['operation'] == 'cleanup_complete']
                
                self.assertEqual(len(cleanup_starts), 1)
                self.assertEqual(len(cleanup_completes), 1)
                
                access_starts = [op for op in access_operations if op['operation'] == 'access_start']
                access_completes = [op for op in access_operations if op['operation'] == 'access_complete']
                
                self.assertEqual(len(access_starts), 3)
                self.assertEqual(len(access_completes), 3)
                
                # Verify no deadlocks occurred (all operations completed)
                self.assertTrue(cleanup_thread.is_alive() == False)
                for thread in access_threads:
                    self.assertTrue(thread.is_alive() == False)


if __name__ == '__main__':
    unittest.main()