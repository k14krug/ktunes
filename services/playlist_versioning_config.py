# services/playlist_versioning_config.py
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Default configuration for playlist versioning
DEFAULT_VERSIONING_CONFIG = {
    'enabled': True,  # Global enable/disable
    'retention_days': 7,  # Default retention period
    'max_versions': 10,  # Default maximum versions to keep
    'enabled_playlists': ['*'],  # List of playlist names to version, '*' for all
    'cleanup_schedule': 'daily',  # How often to run cleanup
    'performance_mode': 'balanced'  # 'fast', 'balanced', or 'thorough'
}


class PlaylistVersioningConfig:
    """
    Configuration manager for playlist versioning system.
    Handles loading, validation, and access to versioning settings.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize configuration with provided settings or defaults.
        
        Args:
            config: Configuration dictionary, uses defaults if None
        """
        self.config = config or DEFAULT_VERSIONING_CONFIG.copy()
        self._validate_config()
    
    def _validate_config(self):
        """Validate configuration values and set defaults for missing keys."""
        # Ensure all required keys exist
        for key, default_value in DEFAULT_VERSIONING_CONFIG.items():
            if key not in self.config:
                self.config[key] = default_value
                logger.warning(f"Missing config key '{key}', using default: {default_value}")
        
        # Validate specific values
        if self.config['retention_days'] < 1:
            logger.warning("retention_days must be >= 1, setting to 1")
            self.config['retention_days'] = 1
        
        if self.config['max_versions'] < 1:
            logger.warning("max_versions must be >= 1, setting to 1")
            self.config['max_versions'] = 1
        
        if self.config['performance_mode'] not in ['fast', 'balanced', 'thorough']:
            logger.warning(f"Invalid performance_mode '{self.config['performance_mode']}', using 'balanced'")
            self.config['performance_mode'] = 'balanced'
    
    def is_enabled(self) -> bool:
        """Check if versioning is globally enabled."""
        return self.config.get('enabled', True)
    
    def is_playlist_enabled(self, playlist_name: str) -> bool:
        """
        Check if versioning is enabled for a specific playlist.
        
        Args:
            playlist_name: Name of the playlist to check
            
        Returns:
            True if versioning is enabled for this playlist
        """
        if not self.is_enabled():
            return False
        
        enabled_playlists = self.config.get('enabled_playlists', ['*'])
        
        # Check for wildcard (all playlists enabled)
        if '*' in enabled_playlists:
            return True
        
        # Check for exact match
        if playlist_name in enabled_playlists:
            return True
        
        # Check for pattern matches (simple wildcard support)
        for pattern in enabled_playlists:
            if pattern.endswith('*') and playlist_name.startswith(pattern[:-1]):
                return True
            if pattern.startswith('*') and playlist_name.endswith(pattern[1:]):
                return True
        
        return False
    
    def get_retention_days(self) -> int:
        """Get the retention period in days."""
        return self.config.get('retention_days', 7)
    
    def get_max_versions(self) -> int:
        """Get the maximum number of versions to keep."""
        return self.config.get('max_versions', 10)
    
    def get_cleanup_schedule(self) -> str:
        """Get the cleanup schedule setting."""
        return self.config.get('cleanup_schedule', 'daily')
    
    def get_performance_mode(self) -> str:
        """Get the performance mode setting."""
        return self.config.get('performance_mode', 'balanced')
    
    def update_config(self, updates: Dict[str, Any]):
        """
        Update configuration with new values.
        
        Args:
            updates: Dictionary of configuration updates
        """
        self.config.update(updates)
        self._validate_config()
        logger.info(f"Updated versioning configuration: {updates}")
    
    def get_config(self) -> Dict[str, Any]:
        """Get the current configuration dictionary."""
        return self.config.copy()


# Global configuration instance
_global_config = PlaylistVersioningConfig()


def get_versioning_config() -> PlaylistVersioningConfig:
    """Get the global versioning configuration instance."""
    return _global_config


def update_versioning_config(updates: Dict[str, Any]):
    """Update the global versioning configuration."""
    _global_config.update_config(updates)


def is_versioning_enabled_for_playlist(playlist_name: str) -> bool:
    """
    Convenience function to check if versioning is enabled for a playlist.
    
    Args:
        playlist_name: Name of the playlist to check
        
    Returns:
        True if versioning is enabled for this playlist
    """
    return _global_config.is_playlist_enabled(playlist_name)