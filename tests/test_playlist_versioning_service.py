# tests/test_playlist_versioning_service.py
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import uuid

from services.playlist_versioning_service import PlaylistVersioningService
from models import PlaylistVersion, PlaylistVersionTrack, Playlist


class TestPlaylistVersioningService(unittest.TestCase):
    """Test cases for PlaylistVersioningService"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_playlist_name = "Test Playlist"
        self.test_username = "testuser"
        self.test_version_id = str(uuid.uuid4())
        self.base_time = datetime.utcnow()
        
        # Clear cache before each test
        PlaylistVersioningService.clear_version_cache()
    
    @patch('services.playlist_versioning_service.db')
    @patch('services.playlist_versioning_service.uuid.uuid4')
    def test_create_version_from_current_playlist_success(self, mock_uuid, mock_db):
        """Test successful version creation from current playlist"""
        # Setup mocks
        mock_uuid.return_value = Mock()
        mock_uuid.return_value.__str__ = Mock(return_value=self.test_version_id)
        
        # Mock current playlist data
        mock_tracks = []
        for i in range(3):
            track = Mock()
            track.track_position = i + 1
            track.artist = f"Artist {i + 1}"
            track.song = f"Song {i + 1}"
            track.category = "Test"
            track.play_cnt = 10
            track.artist_common_name = f"Artist {i + 1}"
            track.playlist_date = self.base_time
            mock_tracks.append(track)
        
        mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_tracks
        mock_db.session.query.return_value.filter.return_value.first.return_value = None  # No existing active version
        
        # Execute
        result = PlaylistVersioningService.create_version_from_current_playlist(
            self.test_playlist_name, self.test_username
        )
        
        # Verify
        self.assertEqual(result, self.test_version_id)
        mock_db.session.add.assert_called()
        mock_db.session.add_all.assert_called()
        mock_db.session.commit.assert_called()
    
    @patch('services.playlist_versioning_service.db')
    def test_create_version_no_current_playlist(self, mock_db):
        """Test version creation when no current playlist exists"""
        # Setup mocks
        mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        
        # Execute
        result = PlaylistVersioningService.create_version_from_current_playlist(
            self.test_playlist_name, self.test_username
        )
        
        # Verify
        self.assertIsNone(result)
        mock_db.session.add.assert_not_called()
        mock_db.session.commit.assert_not_called()
    
    @patch('services.playlist_versioning_service.db')
    def test_create_version_database_error(self, mock_db):
        """Test version creation with database error"""
        # Setup mocks
        mock_db.session.query.side_effect = Exception("Database error")
        
        # Execute
        result = PlaylistVersioningService.create_version_from_current_playlist(
            self.test_playlist_name, self.test_username
        )
        
        # Verify
        self.assertIsNone(result)
        mock_db.session.rollback.assert_called()
    
    @patch('services.playlist_versioning_service.db')
    def test_get_active_version_at_time_success(self, mock_db):
        """Test successful retrieval of active version at specific time"""
        # Setup mocks
        mock_version = Mock()
        mock_version.version_id = self.test_version_id
        mock_version.active_from = self.base_time - timedelta(hours=1)
        mock_version.active_until = None
        
        mock_db.session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_version
        
        # Execute
        result = PlaylistVersioningService.get_active_version_at_time(
            self.test_playlist_name, self.base_time, self.test_username
        )
        
        # Verify
        self.assertEqual(result, mock_version)
    
    @patch('services.playlist_versioning_service.db')
    def test_get_active_version_at_time_not_found(self, mock_db):
        """Test retrieval when no active version exists at timestamp"""
        # Setup mocks
        mock_db.session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        
        # Execute
        result = PlaylistVersioningService.get_active_version_at_time(
            self.test_playlist_name, self.base_time, self.test_username
        )
        
        # Verify
        self.assertIsNone(result)
    
    @patch('services.playlist_versioning_service.db')
    def test_get_active_version_at_time_with_caching(self, mock_db):
        """Test that caching works for version retrieval"""
        # Setup mocks
        mock_version = Mock()
        mock_version.version_id = self.test_version_id
        mock_version.active_from = self.base_time - timedelta(hours=1)
        mock_version.active_until = None
        
        mock_db.session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_version
        
        # Execute first call
        result1 = PlaylistVersioningService.get_active_version_at_time(
            self.test_playlist_name, self.base_time, self.test_username
        )
        
        # Execute second call (should use cache)
        result2 = PlaylistVersioningService.get_active_version_at_time(
            self.test_playlist_name, self.base_time, self.test_username
        )
        
        # Verify
        self.assertEqual(result1, mock_version)
        self.assertEqual(result2, mock_version)
        # Database should only be queried once due to caching
        self.assertEqual(mock_db.session.query.call_count, 1)
    
    @patch('services.playlist_versioning_service.db')
    def test_get_version_tracks_success(self, mock_db):
        """Test successful retrieval of version tracks"""
        # Setup mocks
        mock_tracks = []
        for i in range(3):
            track = Mock()
            track.track_position = i + 1
            track.artist = f"Artist {i + 1}"
            track.song = f"Song {i + 1}"
            mock_tracks.append(track)
        
        mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_tracks
        
        # Execute
        result = PlaylistVersioningService.get_version_tracks(self.test_version_id)
        
        # Verify
        self.assertEqual(len(result), 3)
        self.assertEqual(result, mock_tracks)
    
    @patch('services.playlist_versioning_service.db')
    def test_find_track_in_version_success(self, mock_db):
        """Test successful track finding in version"""
        # Setup mocks
        mock_track = Mock()
        mock_track.track_position = 5
        mock_track.artist = "Test Artist"
        mock_track.song = "Test Song"
        
        mock_db.session.query.return_value.filter.return_value.first.return_value = mock_track
        
        # Execute
        result = PlaylistVersioningService.find_track_in_version(
            self.test_version_id, "Test Artist", "Test Song"
        )
        
        # Verify
        self.assertEqual(result, mock_track)
    
    @patch('services.playlist_versioning_service.db')
    def test_find_track_in_version_not_found(self, mock_db):
        """Test track finding when track doesn't exist in version"""
        # Setup mocks
        mock_db.session.query.return_value.filter.return_value.first.return_value = None
        
        # Execute
        result = PlaylistVersioningService.find_track_in_version(
            self.test_version_id, "Test Artist", "Test Song"
        )
        
        # Verify
        self.assertIsNone(result)
    
    @patch('services.playlist_versioning_service.db')
    def test_cleanup_old_versions_success(self, mock_db):
        """Test successful cleanup of old versions"""
        # Setup mocks - simulate versions to clean up
        old_version = Mock()
        old_version.version_id = "old-version-id"
        old_version.created_at = self.base_time - timedelta(days=10)
        old_version.active_until = self.base_time - timedelta(days=5)
        
        recent_version = Mock()
        recent_version.version_id = "recent-version-id"
        recent_version.created_at = self.base_time - timedelta(days=1)
        recent_version.active_until = None
        
        mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            recent_version, old_version  # Ordered by newest first
        ]
        
        # Mock PlayedTrack query for reference checking
        mock_db.session.query.return_value.filter.return_value.all.return_value = []
        
        # Execute
        result = PlaylistVersioningService.cleanup_old_versions(
            self.test_playlist_name, retention_days=7, max_versions=1
        )
        
        # Verify
        self.assertEqual(result, 1)  # Should clean up 1 version
        mock_db.session.delete.assert_called_once()
        mock_db.session.commit.assert_called()
    
    @patch('services.playlist_versioning_service.db')
    def test_cleanup_all_playlists(self, mock_db):
        """Test cleanup across all playlists"""
        # Setup mocks
        with patch.object(PlaylistVersioningService, 'get_all_versioned_playlists') as mock_get_playlists:
            mock_get_playlists.return_value = ["Playlist 1", "Playlist 2"]
            
            with patch.object(PlaylistVersioningService, '_cleanup_playlist_versions') as mock_cleanup:
                mock_cleanup.side_effect = [2, 1]  # Return cleanup counts
                
                # Execute
                result = PlaylistVersioningService.cleanup_all_playlists(
                    retention_days=7, max_versions=10
                )
                
                # Verify
                self.assertEqual(result, {"Playlist 1": 2, "Playlist 2": 1})
                self.assertEqual(mock_cleanup.call_count, 2)
    
    @patch('services.playlist_versioning_service.db')
    def test_get_all_versioned_playlists(self, mock_db):
        """Test retrieval of all versioned playlist names"""
        # Setup mocks
        mock_db.session.query.return_value.distinct.return_value.all.return_value = [
            ("Playlist 1",), ("Playlist 2",), ("Playlist 3",)
        ]
        
        # Execute
        result = PlaylistVersioningService.get_all_versioned_playlists()
        
        # Verify
        self.assertEqual(result, ["Playlist 1", "Playlist 2", "Playlist 3"])
    
    @patch('services.playlist_versioning_service.db')
    def test_get_version_statistics_specific_playlist(self, mock_db):
        """Test statistics generation for specific playlist"""
        # Setup mocks
        mock_versions = [
            Mock(created_at=self.base_time - timedelta(days=5), active_until=self.base_time - timedelta(days=1)),
            Mock(created_at=self.base_time - timedelta(days=1), active_until=None)
        ]
        mock_db.session.query.return_value.filter.return_value.all.return_value = mock_versions
        mock_db.session.query.return_value.join.return_value.filter.return_value.scalar.return_value = 50
        
        # Execute
        result = PlaylistVersioningService.get_version_statistics(self.test_playlist_name)
        
        # Verify
        self.assertIn(self.test_playlist_name, result)
        stats = result[self.test_playlist_name]
        self.assertEqual(stats['version_count'], 2)
        self.assertEqual(stats['total_tracks'], 50)
        self.assertIsNotNone(stats['active_version'])
    
    def test_cache_management(self):
        """Test cache management functionality"""
        # Test cache clearing
        PlaylistVersioningService.clear_version_cache()
        
        # Test cache operations
        test_version = Mock()
        test_version.version_id = self.test_version_id
        
        cache_key = "test_key"
        PlaylistVersioningService._cache_version(cache_key, test_version)
        
        # Verify cache hit
        cached_result = PlaylistVersioningService._get_cached_version(cache_key)
        self.assertEqual(cached_result, test_version)
        
        # Test cache miss
        miss_result = PlaylistVersioningService._get_cached_version("nonexistent_key")
        self.assertIsNone(miss_result)
    
    @patch('services.playlist_versioning_service.db')
    def test_health_check_healthy(self, mock_db):
        """Test health check when system is healthy"""
        # Setup mocks
        mock_db.session.query.return_value.scalar.return_value = 10
        
        with patch.object(PlaylistVersioningService, 'get_all_versioned_playlists') as mock_get_playlists:
            mock_get_playlists.return_value = ["Playlist 1", "Playlist 2"]
            
            # Execute
            result = PlaylistVersioningService.health_check()
            
            # Verify
            self.assertEqual(result['status'], 'healthy')
            self.assertEqual(result['total_versions'], 10)
            self.assertEqual(result['versioned_playlists'], 2)
            self.assertTrue(result['database_accessible'])
            self.assertEqual(len(result['errors']), 0)
    
    @patch('services.playlist_versioning_service.db')
    def test_health_check_database_error(self, mock_db):
        """Test health check when database is unavailable"""
        # Setup mocks
        mock_db.session.query.side_effect = Exception("Database connection failed")
        
        # Execute
        result = PlaylistVersioningService.health_check()
        
        # Verify
        self.assertEqual(result['status'], 'degraded')
        self.assertFalse(result['database_accessible'])
        self.assertGreater(len(result['errors']), 0)
        self.assertIn("Database error", result['errors'][0])


if __name__ == '__main__':
    unittest.main()