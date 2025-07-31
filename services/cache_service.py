"""
Simple in-memory caching service for performance optimization
"""
import time
from typing import Any, Optional, Dict, Tuple
from threading import Lock
from flask import current_app

class SimpleCache:
    """
    Thread-safe in-memory cache with TTL support
    """
    
    def __init__(self):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._lock = Lock()
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache if it exists and hasn't expired
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    return value
                else:
                    # Remove expired entry
                    del self._cache[key]
            return None
    
    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """
        Set value in cache with TTL
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (default: 5 minutes)
        """
        expiry = time.time() + ttl
        with self._lock:
            self._cache[key] = (value, expiry)
    
    def delete(self, key: str) -> None:
        """
        Delete key from cache
        
        Args:
            key: Cache key to delete
        """
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self) -> None:
        """Clear all cache entries"""
        with self._lock:
            self._cache.clear()
    
    def cleanup_expired(self) -> int:
        """
        Remove expired entries from cache
        
        Returns:
            Number of entries removed
        """
        current_time = time.time()
        expired_keys = []
        
        with self._lock:
            for key, (_, expiry) in self._cache.items():
                if current_time >= expiry:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self._cache[key]
        
        return len(expired_keys)
    
    def size(self) -> int:
        """Get current cache size"""
        with self._lock:
            return len(self._cache)

# Global cache instance
_cache_instance = SimpleCache()

def get_cache() -> SimpleCache:
    """Get the global cache instance"""
    return _cache_instance

def cache_playlist_data(playlist_name: str, playlist_date, data: Any, ttl: int = 600) -> None:
    """
    Cache playlist data with a standardized key format
    
    Args:
        playlist_name: Name of the playlist
        playlist_date: Date of the playlist
        data: Data to cache
        ttl: Time to live in seconds (default: 10 minutes)
    """
    cache_key = f"playlist:{playlist_name}:{playlist_date}"
    get_cache().set(cache_key, data, ttl)

def get_cached_playlist_data(playlist_name: str, playlist_date) -> Optional[Any]:
    """
    Get cached playlist data
    
    Args:
        playlist_name: Name of the playlist
        playlist_date: Date of the playlist
        
    Returns:
        Cached data or None if not found/expired
    """
    cache_key = f"playlist:{playlist_name}:{playlist_date}"
    return get_cache().get(cache_key)

def cache_playlist_lookup(playlist_name: str, playlist_date, lookup_data: Dict, ttl: int = 600) -> None:
    """
    Cache playlist lookup dictionary
    
    Args:
        playlist_name: Name of the playlist
        playlist_date: Date of the playlist
        lookup_data: Lookup dictionary to cache
        ttl: Time to live in seconds (default: 10 minutes)
    """
    cache_key = f"playlist_lookup:{playlist_name}:{playlist_date}"
    get_cache().set(cache_key, lookup_data, ttl)

def get_cached_playlist_lookup(playlist_name: str, playlist_date) -> Optional[Dict]:
    """
    Get cached playlist lookup dictionary
    
    Args:
        playlist_name: Name of the playlist
        playlist_date: Date of the playlist
        
    Returns:
        Cached lookup dictionary or None if not found/expired
    """
    cache_key = f"playlist_lookup:{playlist_name}:{playlist_date}"
    return get_cache().get(cache_key)

def invalidate_playlist_cache(playlist_name: str = None) -> None:
    """
    Invalidate playlist-related cache entries
    
    Args:
        playlist_name: If provided, only invalidate caches for this playlist
    """
    cache = get_cache()
    
    if playlist_name:
        # Remove specific playlist caches
        keys_to_remove = []
        with cache._lock:
            for key in cache._cache.keys():
                if key.startswith(f"playlist:{playlist_name}:") or key.startswith(f"playlist_lookup:{playlist_name}:"):
                    keys_to_remove.append(key)
        
        for key in keys_to_remove:
            cache.delete(key)
    else:
        # Clear all playlist-related caches
        keys_to_remove = []
        with cache._lock:
            for key in cache._cache.keys():
                if key.startswith("playlist:") or key.startswith("playlist_lookup:"):
                    keys_to_remove.append(key)
        
        for key in keys_to_remove:
            cache.delete(key)

def log_cache_stats() -> None:
    """Log cache statistics for monitoring"""
    cache = get_cache()
    size = cache.size()
    expired_count = cache.cleanup_expired()
    
    if current_app:
        current_app.logger.info(f"Cache stats - Size: {size}, Expired cleaned: {expired_count}")
    else:
        print(f"Cache stats - Size: {size}, Expired cleaned: {expired_count}")