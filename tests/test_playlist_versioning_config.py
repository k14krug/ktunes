# tests/test_playlist_versioning_config.py
import unittest
from unittest.mock import patch

from services.playlist_versioning_config import (
    PlaylistVersioningConfig, 
    get_versioning_config,
    update_versioning_config,
    is_versioning_enabled_for_playlist,
    DEFAULT_VERSIONING_CONFIG
)


class TestPlaylistVersioningConfig(unittest.TestCase):
    """Test cases for PlaylistVersioningConfig"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.default_config = DEFAULT_VERSIONING_CONFIG.copy()
    
    def test_init_with_default_config(self):
        """Test initialization with default configuration"""
        config = PlaylistVersioningConfig()
        
        self.assertTrue(config.is_enabled())
        self.assertEqual(config.get_retention_days(), 7)
        self.assertEqual(config.get_max_versions(), 10)
        self.assertEqual(config.get_cleanup_schedule(), 'daily')
        self.assertEqual(config.get_performance_mode(), 'balanced')
    
    def test_init_with_custom_config(self):
        """Test initialization with custom configuration"""
        custom_config = {
            'enabled': False,
            'retention_days': 14,
            'max_versions': 20,
            'enabled_playlists': ['KRUG FM 96.2'],
            'cleanup_schedule': 'weekly',
            'performance_mode': 'fast'
        }
        
        config = PlaylistVersioningConfig(custom_config)
        
        self.assertFalse(config.is_enabled())
        self.assertEqual(config.get_retention_days(), 14)
        self.assertEqual(config.get_max_versions(), 20)
        self.assertEqual(config.get_cleanup_schedule(), 'weekly')
        self.assertEqual(config.get_performance_mode(), 'fast')
    
    def test_config_validation_invalid_retention_days(self):
        """Test configuration validation for invalid retention days"""
        invalid_config = {'retention_days': 0}
        
        config = PlaylistVersioningConfig(invalid_config)
        
        # Should be corrected to minimum value
        self.assertEqual(config.get_retention_days(), 1)
    
    def test_config_validation_invalid_max_versions(self):
        """Test configuration validation for invalid max versions"""
        invalid_config = {'max_versions': -5}
        
        config = PlaylistVersioningConfig(invalid_config)
        
        # Should be corrected to minimum value
        self.assertEqual(config.get_max_versions(), 1)
    
    def test_config_validation_invalid_performance_mode(self):
        """Test configuration validation for invalid performance mode"""
        invalid_config = {'performance_mode': 'invalid_mode'}
        
        config = PlaylistVersioningConfig(invalid_config)
        
        # Should be corrected to default
        self.assertEqual(config.get_performance_mode(), 'balanced')
    
    def test_is_playlist_enabled_wildcard(self):
        """Test playlist enabling with wildcard"""
        config = PlaylistVersioningConfig({'enabled_playlists': ['*']})
        
        self.assertTrue(config.is_playlist_enabled('Any Playlist'))
        self.assertTrue(config.is_playlist_enabled('KRUG FM 96.2'))
        self.assertTrue(config.is_playlist_enabled('Another Playlist'))
    
    def test_is_playlist_enabled_exact_match(self):
        """Test playlist enabling with exact match"""
        config = PlaylistVersioningConfig({
            'enabled_playlists': ['KRUG FM 96.2', 'My Playlist']
        })
        
        self.assertTrue(config.is_playlist_enabled('KRUG FM 96.2'))
        self.assertTrue(config.is_playlist_enabled('My Playlist'))
        self.assertFalse(config.is_playlist_enabled('Other Playlist'))
    
    def test_is_playlist_enabled_pattern_match(self):
        """Test playlist enabling with pattern matching"""
        config = PlaylistVersioningConfig({
            'enabled_playlists': ['KRUG*', '*Radio']
        })
        
        self.assertTrue(config.is_playlist_enabled('KRUG FM 96.2'))
        self.assertTrue(config.is_playlist_enabled('KRUG Test'))
        self.assertTrue(config.is_playlist_enabled('My Radio'))
        self.assertTrue(config.is_playlist_enabled('Test Radio'))
        self.assertFalse(config.is_playlist_enabled('Other Playlist'))
    
    def test_is_playlist_enabled_globally_disabled(self):
        """Test playlist enabling when globally disabled"""
        config = PlaylistVersioningConfig({
            'enabled': False,
            'enabled_playlists': ['*']
        })
        
        self.assertFalse(config.is_playlist_enabled('Any Playlist'))
    
    def test_update_config(self):
        """Test configuration updates"""
        config = PlaylistVersioningConfig()
        
        updates = {
            'retention_days': 14,
            'max_versions': 20,
            'performance_mode': 'fast'
        }
        
        config.update_config(updates)
        
        self.assertEqual(config.get_retention_days(), 14)
        self.assertEqual(config.get_max_versions(), 20)
        self.assertEqual(config.get_performance_mode(), 'fast')
    
    def test_get_config(self):
        """Test getting configuration dictionary"""
        custom_config = {
            'enabled': True,
            'retention_days': 10,
            'max_versions': 15
        }
        
        config = PlaylistVersioningConfig(custom_config)
        result = config.get_config()
        
        # Should include all default keys plus custom ones
        self.assertIn('enabled', result)
        self.assertIn('retention_days', result)
        self.assertIn('max_versions', result)
        self.assertIn('enabled_playlists', result)
        self.assertIn('cleanup_schedule', result)
        self.assertIn('performance_mode', result)
        
        self.assertEqual(result['retention_days'], 10)
        self.assertEqual(result['max_versions'], 15)
    
    def test_global_config_functions(self):
        """Test global configuration functions"""
        # Test getting global config
        global_config = get_versioning_config()
        self.assertIsInstance(global_config, PlaylistVersioningConfig)
        
        # Test updating global config
        update_versioning_config({'retention_days': 21})
        updated_config = get_versioning_config()
        self.assertEqual(updated_config.get_retention_days(), 21)
        
        # Test convenience function
        result = is_versioning_enabled_for_playlist('Test Playlist')
        self.assertIsInstance(result, bool)
    
    def test_missing_config_keys(self):
        """Test handling of missing configuration keys"""
        incomplete_config = {
            'enabled': True,
            'retention_days': 5
            # Missing other keys
        }
        
        config = PlaylistVersioningConfig(incomplete_config)
        
        # Should use defaults for missing keys
        self.assertEqual(config.get_max_versions(), 10)  # Default
        self.assertEqual(config.get_cleanup_schedule(), 'daily')  # Default
        self.assertEqual(config.get_performance_mode(), 'balanced')  # Default
        self.assertEqual(config.get_retention_days(), 5)  # Custom value
    
    def test_config_validation_edge_cases(self):
        """Test configuration validation edge cases"""
        edge_case_config = {
            'retention_days': -10,
            'max_versions': 0,
            'performance_mode': None,
            'enabled_playlists': []
        }
        
        config = PlaylistVersioningConfig(edge_case_config)
        
        # Should handle edge cases gracefully
        self.assertEqual(config.get_retention_days(), 1)  # Corrected minimum
        self.assertEqual(config.get_max_versions(), 1)  # Corrected minimum
        self.assertEqual(config.get_performance_mode(), 'balanced')  # Default
        self.assertEqual(config.config['enabled_playlists'], [])  # Preserved empty list


if __name__ == '__main__':
    unittest.main()