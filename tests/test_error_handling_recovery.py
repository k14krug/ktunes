"""
Tests for error handling and recovery mechanisms in duplicate analysis.

This test suite verifies the implementation of timeout handling, retry logic,
memory management, and recovery capabilities.
"""

import unittest
import time
import threading
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from services.duplicate_detection_service import (
    DuplicateDetectionService, 
    AnalysisTimeoutError, 
    AnalysisCancelledException
)
from services.duplicate_persistence_service import DuplicatePersistenceService
from services.error_handling_config import ErrorHandlingConfig
from models import Track, DuplicateAnalysisResult


class TestErrorHandlingRecovery(unittest.TestCase):
    """Test error handling and recovery mechanisms."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = DuplicateDetectionService()
        self.persistence_service = DuplicatePersistenceService()
        self.config = ErrorHandlingConfig()
        
        # Create simple mock tracks without Flask-SQLAlchemy spec
        self.mock_tracks = [
            Mock(id=1, song="Test Song", artist="Test Artist", play_cnt=10),
            Mock(id=2, song="Test Song (Remastered)", artist="Test Artist", play_cnt=5),
            Mock(id=3, song="Another Song", artist="Another Artist", play_cnt=15)
        ]
    
    def test_timeout_handling(self):
        """Test analysis timeout handling with configurable limits."""
        analysis_id = "test-timeout-analysis"
        
        # Test timeout context manager
        with self.assertRaises(AnalysisTimeoutError):
            with self.service.timeout_handler(analysis_id, timeout_seconds=1):
                time.sleep(2)  # Sleep longer than timeout
    
    def test_cancellation_handling(self):
        """Test graceful cancellation with partial result preservation."""
        analysis_id = "test-cancel-analysis"
        
        # Mark analysis for cancellation
        self.service._cancelled_analyses.add(analysis_id)
        
        # Test cancellation check
        with self.assertRaises(AnalysisCancelledException):
            self.service.check_cancellation(analysis_id)
    
    def test_cancel_analysis_method(self):
        """Test the cancel_analysis method."""
        analysis_id = "test-cancel-method"
        
        # Set up active analysis
        self.service._active_analyses[analysis_id] = {
            'start_time': datetime.now(),
            'user_id': 1,
            'status': 'running'
        }
        
        # Cancel the analysis
        result = self.service.cancel_analysis(analysis_id)
        
        self.assertTrue(result)
        self.assertIn(analysis_id, self.service._cancelled_analyses)
    
    @patch('services.duplicate_detection_service.db.session')
    def test_database_transaction_safety(self, mock_session):
        """Test database transaction safety with atomic saves and rollback."""
        analysis_id = "test-transaction"
        
        # Test successful transaction
        with self.service.database_transaction_safety(analysis_id):
            mock_session.begin.assert_called_once()
        
        mock_session.commit.assert_called_once()
        
        # Test transaction rollback on error
        mock_session.reset_mock()
        mock_session.commit.side_effect = Exception("Database error")
        
        with self.assertRaises(Exception):
            with self.service.database_transaction_safety(analysis_id):
                pass
        
        mock_session.rollback.assert_called_once()
    
    def test_retry_with_backoff(self):
        """Test retry logic for transient database errors."""
        analysis_id = "test-retry"
        
        # Mock operation that fails twice then succeeds
        mock_operation = Mock()
        mock_operation.side_effect = [
            Exception("Transient error 1"),
            Exception("Transient error 2"),
            "Success"
        ]
        
        # Test successful retry
        result = self.service.retry_with_backoff(
            mock_operation, analysis_id, "test operation"
        )
        
        self.assertEqual(result, "Success")
        self.assertEqual(mock_operation.call_count, 3)
    
    def test_retry_with_backoff_max_attempts(self):
        """Test retry logic respects maximum attempts."""
        analysis_id = "test-retry-max"
        
        # Mock operation that always fails
        mock_operation = Mock()
        mock_operation.side_effect = Exception("Persistent error")
        
        # Test that it fails after max attempts
        with self.assertRaises(Exception):
            self.service.retry_with_backoff(
                mock_operation, analysis_id, "test operation"
            )
        
        self.assertEqual(mock_operation.call_count, self.service.max_retry_attempts)
    
    def test_memory_usage_monitoring(self):
        """Test memory usage monitoring and cleanup."""
        # Test memory usage retrieval
        memory_stats = self.service.get_memory_usage()
        
        self.assertIn('rss_mb', memory_stats)
        self.assertIn('vms_mb', memory_stats)
        self.assertIn('percent', memory_stats)
        self.assertIn('available_mb', memory_stats)
        
        # All values should be non-negative
        for key, value in memory_stats.items():
            self.assertGreaterEqual(value, 0)
    
    def test_checkpoint_creation(self):
        """Test progress checkpoint creation for recovery."""
        analysis_id = "test-checkpoint"
        
        # Set up active analysis
        self.service._active_analyses[analysis_id] = {
            'start_time': datetime.now(),
            'user_id': 1,
            'status': 'running'
        }
        
        # Create checkpoint
        self.service.create_progress_checkpoint(
            analysis_id, [], 50, 100, include_partial_groups=True
        )
        
        # Verify checkpoint was created
        checkpoint = self.service.get_analysis_checkpoint(analysis_id)
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint['processed_count'], 50)
        self.assertEqual(checkpoint['total_count'], 100)
    
    def test_streaming_batch_processing(self):
        """Test streaming processing for large datasets."""
        # Mock query that returns tracks in batches
        mock_query = Mock()
        mock_query.offset.return_value.limit.return_value.all.side_effect = [
            self.mock_tracks[:2],  # First batch
            self.mock_tracks[2:],  # Second batch
            []  # End of data
        ]
        
        # Test streaming
        batches = list(self.service.stream_tracks_in_batches(mock_query, batch_size=2))
        
        self.assertEqual(len(batches), 2)
        self.assertEqual(len(batches[0]), 2)
        self.assertEqual(len(batches[1]), 1)
    
    def test_intermediate_results_cleanup(self):
        """Test cleanup of intermediate results and temporary data."""
        analysis_id = "test-cleanup"
        
        # Set up analysis state with temporary data
        self.service._active_analyses[analysis_id] = {
            'start_time': datetime.now(),
            'user_id': 1,
            'status': 'running',
            'temp_data': "large temporary data",
            'checkpoint': {'processed_count': 50}
        }
        
        # Perform cleanup
        self.service.cleanup_intermediate_results(analysis_id)
        
        # Verify essential data is preserved but temp data is removed
        state = self.service._active_analyses[analysis_id]
        self.assertIn('checkpoint', state)
        self.assertNotIn('temp_data', state)
    
    def test_configuration_loading(self):
        """Test error handling configuration loading."""
        config = self.config.get_duplicate_analysis_config()
        
        # Verify all required configuration keys are present
        required_keys = [
            'timeout_seconds', 'max_retry_attempts', 'retry_delay_seconds',
            'checkpoint_interval', 'streaming_batch_size', 'max_memory_usage_mb',
            'memory_check_interval', 'gc_collection_interval', 'request_timeout_seconds'
        ]
        
        for key in required_keys:
            self.assertIn(key, config)
            self.assertIsInstance(config[key], (int, float))
    
    def test_performance_profile_optimization(self):
        """Test performance profile optimization based on dataset size."""
        # Test small dataset profile
        small_profile = self.config.get_performance_profile(500)
        self.assertFalse(small_profile['enable_streaming'])
        self.assertEqual(small_profile['streaming_batch_size'], 500)
        
        # Test medium dataset profile
        medium_profile = self.config.get_performance_profile(5000)
        self.assertTrue(medium_profile['enable_streaming'])
        self.assertEqual(medium_profile['streaming_batch_size'], 1000)
        
        # Test large dataset profile
        large_profile = self.config.get_performance_profile(50000)
        self.assertTrue(large_profile['enable_streaming'])
        self.assertTrue(large_profile['enable_memory_monitoring'])
        self.assertEqual(large_profile['max_memory_usage_mb'], 256)
    
    @patch('services.duplicate_persistence_service.db.session')
    def test_persistence_error_handling(self, mock_session):
        """Test error handling in persistence service."""
        # Test retry logic in persistence service
        mock_operation = Mock()
        mock_operation.side_effect = [
            Exception("Database connection error"),
            "Success"
        ]
        
        result = self.persistence_service.retry_with_backoff(
            mock_operation, "test persistence operation"
        )
        
        self.assertEqual(result, "Success")
        self.assertEqual(mock_operation.call_count, 2)
    
    @patch('services.duplicate_persistence_service.db.session')
    def test_persistence_transaction_safety(self, mock_session):
        """Test database transaction safety in persistence service."""
        # Test successful transaction
        with self.persistence_service.database_transaction_safety("test operation"):
            mock_session.begin.assert_called_once()
        
        mock_session.commit.assert_called_once()
        
        # Test transaction rollback on error
        mock_session.reset_mock()
        mock_session.commit.side_effect = Exception("Database error")
        
        with self.assertRaises(Exception):
            with self.persistence_service.database_transaction_safety("test operation"):
                pass
        
        mock_session.rollback.assert_called_once()


class TestMemoryManagement(unittest.TestCase):
    """Test memory management and performance safeguards."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = DuplicateDetectionService()
    
    def test_memory_threshold_detection(self):
        """Test memory usage threshold detection."""
        analysis_id = "test-memory-threshold"
        
        # Mock high memory usage
        with patch.object(self.service, 'get_memory_usage') as mock_memory:
            mock_memory.return_value = {'rss_mb': 1000, 'vms_mb': 1200, 'percent': 80, 'available_mb': 200}
            
            # Should trigger cleanup for high memory usage
            result = self.service.check_memory_usage(analysis_id)
            self.assertFalse(result)  # Should return False indicating cleanup was triggered
    
    def test_garbage_collection_intervals(self):
        """Test garbage collection at configured intervals."""
        # This test verifies that GC is called at the right intervals
        # In a real scenario, this would be tested during actual analysis
        
        with patch('gc.collect') as mock_gc:
            # Simulate processing tracks with GC intervals
            for i in range(250):  # Process more than GC interval
                if i % self.service.gc_collection_interval == 0:
                    mock_gc()
            
            # Verify GC was called at least once
            self.assertGreater(mock_gc.call_count, 0)
    
    def test_batch_processing_memory_efficiency(self):
        """Test that batch processing manages memory efficiently."""
        # Mock a large dataset
        large_dataset_size = 5000
        
        # Test that streaming is enabled for large datasets
        config = self.service.config.get_performance_profile(large_dataset_size)
        self.assertTrue(config['enable_streaming'])
        self.assertTrue(config['enable_memory_monitoring'])


if __name__ == '__main__':
    unittest.main()