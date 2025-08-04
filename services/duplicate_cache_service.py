"""
Duplicate Cache Service for caching duplicate detection results.
"""

import hashlib
import json
import time
from typing import Optional, Dict, Any, List
from services.duplicate_detection_service import DuplicateGroup, DuplicateAnalysis


class DuplicateCacheService:
    """Service for caching duplicate detection results."""
    
    def __init__(self, cache_duration_minutes: int = 30):
        self.cache_duration_minutes = cache_duration_minutes
        self.cache = {}  # In-memory cache
        self.cache_timestamps = {}
        
    def _generate_cache_key(self, search_term: Optional[str] = None, 
                           sort_by: str = 'artist', min_confidence: float = 0.0) -> str:
        """Generate a cache key based on search parameters."""
        cache_data = {
            'search_term': search_term or '',
            'sort_by': sort_by,
            'min_confidence': min_confidence
        }
        
        cache_string = json.dumps(cache_data, sort_keys=True)
        return hashlib.md5(cache_string.encode()).hexdigest()
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid."""
        if cache_key not in self.cache_timestamps:
            return False
        
        cache_time = self.cache_timestamps[cache_key]
        current_time = time.time()
        cache_age_minutes = (current_time - cache_time) / 60
        
        return cache_age_minutes < self.cache_duration_minutes
    
    def get_cached_duplicates(self, search_term: Optional[str] = None, 
                             sort_by: str = 'artist', min_confidence: float = 0.0) -> Optional[List[DuplicateGroup]]:
        """Get cached duplicate groups if available."""
        cache_key = self._generate_cache_key(search_term, sort_by, min_confidence)
        
        if cache_key in self.cache and self._is_cache_valid(cache_key):
            return self.cache[cache_key]
        
        # Clean up expired cache entry
        if cache_key in self.cache:
            del self.cache[cache_key]
            del self.cache_timestamps[cache_key]
        
        return None
    
    def cache_duplicates(self, duplicate_groups: List[DuplicateGroup], 
                        search_term: Optional[str] = None, sort_by: str = 'artist', 
                        min_confidence: float = 0.0) -> None:
        """Cache duplicate groups."""
        cache_key = self._generate_cache_key(search_term, sort_by, min_confidence)
        
        self.cache[cache_key] = duplicate_groups
        self.cache_timestamps[cache_key] = time.time()
        
        self._cleanup_expired_cache()
    
    def _cleanup_expired_cache(self) -> None:
        """Clean up expired cache entries."""
        current_time = time.time()
        expired_keys = []
        
        for cache_key, timestamp in self.cache_timestamps.items():
            cache_age_minutes = (current_time - timestamp) / 60
            if cache_age_minutes >= self.cache_duration_minutes:
                expired_keys.append(cache_key)
        
        for key in expired_keys:
            if key in self.cache:
                del self.cache[key]
            if key in self.cache_timestamps:
                del self.cache_timestamps[key]
    
    def invalidate_cache(self) -> None:
        """Invalidate all cached data."""
        self.cache.clear()
        self.cache_timestamps.clear()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for monitoring."""
        current_time = time.time()
        
        # Count valid and expired entries
        valid_entries = 0
        expired_entries = 0
        total_size = 0
        
        for cache_key, timestamp in self.cache_timestamps.items():
            cache_age_minutes = (current_time - timestamp) / 60
            if cache_age_minutes < self.cache_duration_minutes:
                valid_entries += 1
            else:
                expired_entries += 1
            
            # Estimate cache entry size
            if cache_key in self.cache:
                cache_data = self.cache[cache_key]
                # Rough estimate of memory usage
                total_size += len(str(cache_data))
        
        return {
            'total_entries': len(self.cache),
            'valid_entries': valid_entries,
            'expired_entries': expired_entries,
            'cache_duration_minutes': self.cache_duration_minutes,
            'estimated_size_bytes': total_size,
            'estimated_size_mb': round(total_size / (1024 * 1024), 2),
            'cache_hit_ratio': self._calculate_hit_ratio(),
            'oldest_entry_age_minutes': self._get_oldest_entry_age_minutes()
        }
    
    def _calculate_hit_ratio(self) -> float:
        """Calculate cache hit ratio (placeholder - would need request tracking)."""
        # This is a placeholder - in a real implementation, you'd track hits/misses
        return 0.0
    
    def _get_oldest_entry_age_minutes(self) -> float:
        """Get the age of the oldest cache entry in minutes."""
        if not self.cache_timestamps:
            return 0.0
        
        current_time = time.time()
        oldest_timestamp = min(self.cache_timestamps.values())
        return (current_time - oldest_timestamp) / 60


# Global cache instance
_duplicate_cache = None

def get_duplicate_cache() -> DuplicateCacheService:
    """Get the global duplicate cache instance."""
    global _duplicate_cache
    if _duplicate_cache is None:
        _duplicate_cache = DuplicateCacheService()
    return _duplicate_cache