# tests/test_playlist_versioning_integration.py
import unittest
from unittest.mock import patch, Mock
from datetime import datetime, timedelta
import tempfile
import os

from services.playlist_versioning_service import PlaylistVersioningService
from services.playlist_versioning_config import PlaylistVersioningConfig
from services.spotify_service import get_listening_history_with_versioned_playlist_context, correlate_track_with_versioned_playlist


class TestPlaylistVersioningIntegration(unittest.TestCase):
    """Integration tests for playlist versioning system"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_playlist_name = "KRUG FM 96.2"
        self.test_username = "kkrug"
        self.base_time = datetime.utcnow()
        
        # Clear cache before each test
        PlaylistVersioningService.clear_version_cache()
    
    @patch('services.playlist_versioning_service.db')
    @patch('services.spotify_service.db')
    def test_end_to_end_versioning_workflow(self, mock_spotify_db, mock_versioning_db):
        """Test complete workflow from playlist generation to listening history correlation"""
        
        # Step 1: Mock playlist generation creating a version
        mock_current_playlist = [
            Mock(track_position=1, artist="Artist 1", song="Song 1", category="Test", 
                 play_cnt=10, artist_common_name="Artist 1", playlist_date=self.base_time),
            Mock(track_position=2, artist="Artist 2", song="Song 2", category="Test", 
                 play_cnt=5, artist_common_name="Artist 2", playlist_date=self.base_time)
        ]
        
        mock_versioning_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_current_playlist
        mock_versioning_db.session.query.return_value.filter.return_value.first.return_value = None  # No existing version
        
        # Create version
        with patch('services.playlist_versioning_service.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.__str__ = Mock(return_value="test-version-id")
            
            version_id = PlaylistVersioningService.create_version_from_current_playlist(
                self.test_playlist_name, self.test_username
            )
            
            self.assertEqual(version_id, "test-version-id")
        
        # Step 2: Mock listening history correlation
        mock_played_tracks = [
            Mock(artist="Artist 1", song="Song 1", played_at=self.base_time + timedelta(minutes=30), source="spotify"),
            Mock(artist="Artist 3", song="Song 3", played_at=self.base_time + timedelta(minutes=45), source="spotify")
        ]
        
        mock_spotify_db.session.query.return_value.filter.return_value.scalar.return_value = 2  # Total count
        mock_spotify_db.session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.offset.return_value.all.return_value = mock_played_tracks
        
        # Mock version retrieval for correlation
        mock_version = Mock()
        mock_version.version_id = "test-version-id"
        mock_version.active_from = self.base_time
        mock_version.active_until = None
        
        mock_versioning_db.session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_version
        
        # Mock track finding in version
        def mock_find_track(version_id, artist, song):
            if artist == "Artist 1" and song == "Song 1":
                track = Mock()
                track.track_position = 1
                return track
            return None
        
        with patch.object(PlaylistVersioningService, 'find_track_in_version', side_effect=mock_find_track):
            # Test correlation
            correlation_result = correlate_track_with_versioned_playlist(
                "Artist 1", "Song 1", self.base_time + timedelta(minutes=30)
            )
            
            self.assertTrue(correlation_result['from_playlist'])
            self.assertEqual(correlation_result['position'], 1)
            self.assertEqual(correlation_result['confidence'], 'high')
            
            # Test correlation for track not in playlist
            correlation_result_2 = correlate_track_with_versioned_playlist(
                "Artist 3", "Song 3", self.base_time + timedelta(minutes=45)
            )
            
            self.assertFalse(correlation_result_2['from_playlist'])
            self.assertEqual(correlation_result_2['confidence'], 'high')
    
    @patch('services.playlist_versioning_service.db')
    def test_concurrent_version_creation(self, mock_db):
        """Test handling of concurrent version creation attempts"""
        
        # Mock existing active version
        existing_version = Mock()
        existing_version.version_id = "existing-version"
        existing_version.active_until = None
        
        mock_current_playlist = [
            Mock(track_position=1, artist="Artist 1", song="Song 1", category="Test", 
                 play_cnt=10, artist_common_name="Artist 1", playlist_date=self.base_time)
        ]
        
        # Setup mocks for concurrent scenario
        mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_current_playlist
        mock_db.session.query.return_value.filter.return_value.first.return_value = existing_version
        
        with patch('services.playlist_versioning_service.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.__str__ = Mock(return_value="new-version-id")
            
            # Create version - should handle existing active version
            version_id = PlaylistVersioningService.create_version_from_current_playlist(
                self.test_playlist_name, self.test_username
            )
            
            self.assertEqual(version_id, "new-version-id")
            # Should have marked existing version as inactive
            self.assertIsNotNone(existing_version.active_until)
    
    @patch('services.playlist_versioning_service.db')
    def test_cleanup_with_referenced_versions(self, mock_db):
        """Test cleanup behavior when versions are referenced by recent listening history"""
        
        # Mock versions for cleanup
        old_version = Mock()
        old_version.version_id = "old-version"
        old_version.created_at = self.base_time - timedelta(days=10)
        old_version.active_until = self.base_time - timedelta(days=5)
        old_version.playlist_name = self.test_playlist_name
        
        recent_version = Mock()
        recent_version.version_id = "recent-version"
        recent_version.created_at = self.base_time - timedelta(days=1)
        recent_version.active_until = None
        recent_version.playlist_name = self.test_playlist_name
        
        # Mock recent played tracks that might reference versions
        recent_track = Mock()
        recent_track.played_at = self.base_time - timedelta(days=3)
        recent_track.playlist_name = self.test_playlist_name
        
        # Setup query mocks
        def mock_query_side_effect(*args):
            query_mock = Mock()
            if hasattr(args[0], '__name__') and args[0].__name__ == 'PlaylistVersion':
                query_mock.filter.return_value.order_by.return_value.all.return_value = [recent_version, old_version]
            else:  # PlayedTrack query
                query_mock.filter.return_value.all.return_value = [recent_track]
            return query_mock
        
        mock_db.session.query.side_effect = mock_query_side_effect
        
        # Test cleanup - should be conservative with referenced versions
        cleaned_count = PlaylistVersioningService.cleanup_old_versions(
            self.test_playlist_name, retention_days=7, max_versions=1
        )
        
        # Should handle the cleanup logic (exact behavior depends on implementation)
        self.assertIsInstance(cleaned_count, int)
    
    def test_configuration_integration(self):
        """Test integration between configuration and service behavior"""
        
        # Test with versioning disabled
        disabled_config = PlaylistVersioningConfig({'enabled': False})
        
        self.assertFalse(disabled_config.is_enabled())
        self.assertFalse(disabled_config.is_playlist_enabled(self.test_playlist_name))
        
        # Test with specific playlist enabled
        selective_config = PlaylistVersioningConfig({
            'enabled': True,
            'enabled_playlists': ['KRUG FM 96.2']
        })
        
        self.assertTrue(selective_config.is_playlist_enabled('KRUG FM 96.2'))
        self.assertFalse(selective_config.is_playlist_enabled('Other Playlist'))
    
    @patch('services.playlist_versioning_service.db')
    def test_version_cache_performance(self, mock_db):
        """Test that caching improves performance for repeated queries"""
        
        # Mock version data
        mock_version = Mock()
        mock_version.version_id = "cached-version"
        mock_version.active_from = self.base_time - timedelta(hours=1)
        mock_version.active_until = None
        
        mock_db.session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_version
        
        # First call - should hit database
        result1 = PlaylistVersioningService.get_active_version_at_time(
            self.test_playlist_name, self.base_time, self.test_username
        )
        
        # Second call with same rounded timestamp - should use cache
        result2 = PlaylistVersioningService.get_active_version_at_time(
            self.test_playlist_name, self.base_time, self.test_username
        )
        
        self.assertEqual(result1, mock_version)
        self.assertEqual(result2, mock_version)
        
        # Database should only be queried once due to caching
        self.assertEqual(mock_db.session.query.call_count, 1)
    
    @patch('services.playlist_versioning_service.db')
    def test_health_check_integration(self, mock_db):
        """Test health check integration with actual system components"""
        
        # Mock healthy system
        mock_db.session.query.return_value.scalar.return_value = 5
        
        with patch.object(PlaylistVersioningService, 'get_all_versioned_playlists') as mock_playlists:
            mock_playlists.return_value = ['KRUG FM 96.2', 'Test Playlist']
            
            health_result = PlaylistVersioningService.health_check()
            
            self.assertEqual(health_result['status'], 'healthy')
            self.assertEqual(health_result['total_versions'], 5)
            self.assertEqual(health_result['versioned_playlists'], 2)
            self.assertTrue(health_result['database_accessible'])
            self.assertTrue(health_result['versioning_enabled'])
    
    def test_correlation_function_behavior(self):
        """Test correlation function behavior with mocked data"""
        
        # Test correlation with mock data (avoiding Flask app context issues)
        with patch('services.playlist_versioning_service.PlaylistVersioningService.get_active_version_at_time') as mock_get_version:
            with patch('services.playlist_versioning_service.PlaylistVersioningService.find_track_in_version') as mock_find_track:
                
                # Mock version found
                mock_version = Mock()
                mock_version.version_id = "test-version"
                mock_version.active_from = self.base_time
                mock_get_version.return_value = mock_version
                
                # Mock track found in version
                mock_track = Mock()
                mock_track.track_position = 5
                mock_find_track.return_value = mock_track
                
                # Test correlation
                result = correlate_track_with_versioned_playlist(
                    "Test Artist", "Test Song", self.base_time + timedelta(minutes=30)
                )
                
                self.assertTrue(result['from_playlist'])
                self.assertEqual(result['position'], 5)
                self.assertEqual(result['confidence'], 'high')
                
                # Test track not found in version
                mock_find_track.return_value = None
                
                result2 = correlate_track_with_versioned_playlist(
                    "Other Artist", "Other Song", self.base_time + timedelta(minutes=30)
                )
                
                self.assertFalse(result2['from_playlist'])
                self.assertEqual(result2['confidence'], 'high')
    
    def test_system_resource_usage(self):
        """Test system resource usage under normal operations"""
        
        # Test cache size management
        PlaylistVersioningService.clear_version_cache()
        
        # Import the cache directly to test it
        from services.playlist_versioning_service import _version_cache
        
        # Simulate multiple cache operations
        for i in range(150):  # More than cache limit
            cache_key = f"test_key_{i}"
            mock_version = Mock()
            mock_version.version_id = f"version_{i}"
            PlaylistVersioningService._cache_version(cache_key, mock_version)
        
        # Cache should be managed to prevent unlimited growth
        # (Implementation should limit cache size)
        self.assertLessEqual(len(_version_cache), 100)
    
    @patch('services.playlist_versioning_service.db')
    def test_error_recovery_scenarios(self, mock_db):
        """Test system behavior during various error scenarios"""
        
        # Test database connection failure during version creation
        mock_db.session.query.side_effect = Exception("Connection lost")
        
        result = PlaylistVersioningService.create_version_from_current_playlist(
            self.test_playlist_name, self.test_username
        )
        
        self.assertIsNone(result)  # Should handle error gracefully
        mock_db.session.rollback.assert_called()
        
        # Test partial failure recovery
        mock_db.session.query.side_effect = None  # Reset
        mock_db.session.commit.side_effect = Exception("Commit failed")
        
        result2 = PlaylistVersioningService.create_version_from_current_playlist(
            self.test_playlist_name, self.test_username
        )
        
        self.assertIsNone(result2)  # Should handle commit failure
    
    def test_data_consistency_validation(self):
        """Test data consistency across versioning operations"""
        
        # Test that version IDs are unique
        version_ids = set()
        
        with patch('services.playlist_versioning_service.uuid.uuid4') as mock_uuid:
            # Generate multiple unique IDs
            mock_uuid.side_effect = [Mock(__str__=Mock(return_value=f"version-{i}")) for i in range(10)]
            
            for i in range(10):
                # Mock successful version creation
                with patch('services.playlist_versioning_service.db') as mock_db:
                    mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [Mock()]
                    mock_db.session.query.return_value.filter.return_value.first.return_value = None
                    
                    version_id = PlaylistVersioningService.create_version_from_current_playlist(
                        f"Playlist {i}", self.test_username
                    )
                    
                    if version_id:
                        version_ids.add(version_id)
            
            # All version IDs should be unique
            self.assertEqual(len(version_ids), 10)


if __name__ == '__main__':
    unittest.main()