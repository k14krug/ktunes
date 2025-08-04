"""
Error Handling Configuration Service

This service manages configuration settings for error handling, timeouts,
and memory management in the duplicate analysis system.
"""

import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path


class ErrorHandlingConfig:
    """Configuration manager for error handling and performance settings."""
    
    def __init__(self, config_path: str = "config.json"):
        """
        Initialize the configuration manager.
        
        Args:
            config_path: Path to the configuration file
        """
        self.config_path = config_path
        self.logger = logging.getLogger(__name__)
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """
        Load configuration from file with fallback to defaults.
        
        Returns:
            Configuration dictionary
        """
        try:
            config_file = Path(self.config_path)
            if config_file.exists():
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    self.logger.info(f"Loaded configuration from {self.config_path}")
                    return config
            else:
                self.logger.warning(f"Configuration file {self.config_path} not found, using defaults")
                return {}
        
        except Exception as e:
            self.logger.error(f"Failed to load configuration from {self.config_path}: {str(e)}")
            return {}
    
    def get_duplicate_analysis_config(self) -> Dict[str, Any]:
        """
        Get duplicate analysis configuration with defaults.
        
        Returns:
            Dictionary with duplicate analysis settings
        """
        default_config = {
            'timeout_seconds': 300,
            'max_retry_attempts': 3,
            'retry_delay_seconds': 2,
            'checkpoint_interval': 100,
            'streaming_batch_size': 1000,
            'max_memory_usage_mb': 512,
            'memory_check_interval': 50,
            'gc_collection_interval': 200,
            'request_timeout_seconds': 30,
            'enable_timeout_handling': True,
            'enable_retry_logic': True,
            'enable_checkpoints': True,
            'enable_streaming': True,
            'enable_memory_monitoring': True
        }
        
        # Merge with config file settings
        config_settings = self._config.get('duplicate_analysis', {})
        default_config.update(config_settings)
        
        return default_config
    
    def get_timeout_seconds(self) -> int:
        """Get analysis timeout in seconds."""
        return self.get_duplicate_analysis_config().get('timeout_seconds', 300)
    
    def get_max_retry_attempts(self) -> int:
        """Get maximum retry attempts for database operations."""
        return self.get_duplicate_analysis_config().get('max_retry_attempts', 3)
    
    def get_retry_delay_seconds(self) -> int:
        """Get delay between retry attempts in seconds."""
        return self.get_duplicate_analysis_config().get('retry_delay_seconds', 2)
    
    def get_checkpoint_interval(self) -> int:
        """Get interval for saving progress checkpoints."""
        return self.get_duplicate_analysis_config().get('checkpoint_interval', 100)
    
    def get_streaming_batch_size(self) -> int:
        """Get batch size for streaming processing."""
        return self.get_duplicate_analysis_config().get('streaming_batch_size', 1000)
    
    def get_max_memory_usage_mb(self) -> int:
        """Get maximum memory usage threshold in MB."""
        return self.get_duplicate_analysis_config().get('max_memory_usage_mb', 512)
    
    def get_memory_check_interval(self) -> int:
        """Get interval for checking memory usage."""
        return self.get_duplicate_analysis_config().get('memory_check_interval', 50)
    
    def get_gc_collection_interval(self) -> int:
        """Get interval for forcing garbage collection."""
        return self.get_duplicate_analysis_config().get('gc_collection_interval', 200)
    
    def get_request_timeout_seconds(self) -> int:
        """Get timeout for individual database requests."""
        return self.get_duplicate_analysis_config().get('request_timeout_seconds', 30)
    
    def is_timeout_handling_enabled(self) -> bool:
        """Check if timeout handling is enabled."""
        return self.get_duplicate_analysis_config().get('enable_timeout_handling', True)
    
    def is_retry_logic_enabled(self) -> bool:
        """Check if retry logic is enabled."""
        return self.get_duplicate_analysis_config().get('enable_retry_logic', True)
    
    def is_checkpoints_enabled(self) -> bool:
        """Check if progress checkpoints are enabled."""
        return self.get_duplicate_analysis_config().get('enable_checkpoints', True)
    
    def is_streaming_enabled(self) -> bool:
        """Check if streaming processing is enabled."""
        return self.get_duplicate_analysis_config().get('enable_streaming', True)
    
    def is_memory_monitoring_enabled(self) -> bool:
        """Check if memory monitoring is enabled."""
        return self.get_duplicate_analysis_config().get('enable_memory_monitoring', True)
    
    def reload_config(self) -> bool:
        """
        Reload configuration from file.
        
        Returns:
            True if reload was successful, False otherwise
        """
        try:
            self._config = self._load_config()
            self.logger.info("Configuration reloaded successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to reload configuration: {str(e)}")
            return False
    
    def update_config(self, updates: Dict[str, Any]) -> bool:
        """
        Update configuration settings and save to file.
        
        Args:
            updates: Dictionary of configuration updates
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            # Update in-memory configuration
            if 'duplicate_analysis' not in self._config:
                self._config['duplicate_analysis'] = {}
            
            self._config['duplicate_analysis'].update(updates)
            
            # Save to file
            with open(self.config_path, 'w') as f:
                json.dump(self._config, f, indent=4)
            
            self.logger.info(f"Configuration updated and saved to {self.config_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to update configuration: {str(e)}")
            return False
    
    def get_performance_profile(self, dataset_size: int) -> Dict[str, Any]:
        """
        Get performance-optimized configuration based on dataset size.
        
        Args:
            dataset_size: Number of tracks to process
            
        Returns:
            Optimized configuration dictionary
        """
        base_config = self.get_duplicate_analysis_config()
        
        if dataset_size < 1000:
            # Small dataset - optimize for speed
            return {
                **base_config,
                'streaming_batch_size': min(dataset_size, 500),
                'checkpoint_interval': 50,
                'memory_check_interval': 25,
                'gc_collection_interval': 100,
                'enable_streaming': False
            }
        
        elif dataset_size < 10000:
            # Medium dataset - balanced approach
            return {
                **base_config,
                'streaming_batch_size': 1000,
                'checkpoint_interval': 100,
                'memory_check_interval': 50,
                'gc_collection_interval': 200,
                'enable_streaming': True
            }
        
        else:
            # Large dataset - optimize for memory efficiency
            return {
                **base_config,
                'streaming_batch_size': 500,
                'checkpoint_interval': 200,
                'memory_check_interval': 25,
                'gc_collection_interval': 100,
                'max_memory_usage_mb': 256,
                'enable_streaming': True,
                'enable_memory_monitoring': True
            }


# Global configuration instance
_config_instance = None


def get_error_handling_config() -> ErrorHandlingConfig:
    """
    Get the global error handling configuration instance.
    
    Returns:
        ErrorHandlingConfig instance
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = ErrorHandlingConfig()
    return _config_instance


def reload_error_handling_config() -> bool:
    """
    Reload the global error handling configuration.
    
    Returns:
        True if reload was successful, False otherwise
    """
    global _config_instance
    if _config_instance is not None:
        return _config_instance.reload_config()
    else:
        _config_instance = ErrorHandlingConfig()
        return True