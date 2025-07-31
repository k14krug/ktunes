# Spotify Listening History Performance Optimizations

This document describes the performance optimizations implemented for the Spotify Listening History feature to ensure queries complete within 2-3 seconds as required.

## Database Indexes

The following indexes have been added to optimize query performance:

### PlayedTrack Table Indexes
- `idx_played_tracks_source_played_at`: Composite index on (source, played_at) - optimizes the main chronological query
- `idx_played_tracks_source`: Index on source column for filtering

### Playlist Table Indexes  
- `idx_playlists_name_date`: Composite index on (playlist_name, playlist_date) - optimizes playlist date queries
- `idx_playlists_name_date_position`: Composite index on (playlist_name, playlist_date, track_position) - optimizes ordered playlist queries
- `idx_playlists_artist_song`: Composite index on (artist, song) - optimizes track lookups

## Caching System

A simple in-memory caching system has been implemented to reduce database load:

### Cache Features
- **TTL Support**: Cached data expires after configurable time periods (default: 10 minutes for playlist data)
- **Thread Safety**: Uses locks to ensure thread-safe operations
- **Automatic Cleanup**: Expired entries are automatically removed
- **Cache Invalidation**: Playlist caches can be invalidated when data changes

### Cached Data
- **Playlist Data**: Raw playlist records for KRUG FM 96.2
- **Playlist Lookup**: Normalized lookup dictionaries for track correlation
- **Cache Duration**: 10 minutes (600 seconds) for playlist-related data

## Query Optimizations

### Optimized Queries
1. **Count Query**: Uses `func.count(PlayedTrack.id)` instead of `.count()` for better performance
2. **Main Query**: Leverages composite index on (source, played_at) for efficient chronological ordering
3. **Playlist Date Query**: Uses index on (playlist_name, playlist_date) for fast max date lookup
4. **Playlist Data Query**: Uses composite index for efficient playlist track retrieval

### Performance Monitoring
- **Query Timing**: All database queries are timed and logged
- **Slow Query Detection**: Queries taking >2 seconds trigger warnings
- **Cache Hit Rates**: Cache statistics are logged for monitoring

## Performance Targets

- **Total Page Load**: <3 seconds
- **Database Queries**: <2 seconds each
- **Cache Hit Rate**: >50% for repeated requests
- **Memory Usage**: Minimal impact with automatic cache cleanup

## Monitoring and Maintenance

### Performance Stats Endpoint
Access `/spotify/performance_stats` (requires authentication) to view:
- Cache statistics (size, hit rates)
- Database query performance metrics
- Performance recommendations

### Cache Management
- **Manual Cleanup**: `cleanup_listening_history_cache()` function
- **Automatic Cleanup**: Expired entries removed during normal operations
- **Cache Invalidation**: Triggered when playlist data is updated

### Database Maintenance
- **Index Usage**: Monitor query execution plans to ensure indexes are being used
- **Data Archiving**: Consider archiving old played_tracks data if dataset grows large (>10,000 records)
- **Regular Analysis**: Use `optimize_database_queries()` function to check performance

## Implementation Details

### Files Modified
- `services/spotify_service.py`: Added caching and optimized queries
- `services/cache_service.py`: New caching utility (created)
- `blueprints/spotify/routes.py`: Added performance monitoring and optimized pagination
- `migrations/versions/add_performance_indexes.py`: Database indexes (created)

### Configuration
- **Cache TTL**: 600 seconds (10 minutes) for playlist data
- **Max Page Size**: Reduced from 200 to 100 records for better performance
- **Default Page Size**: 50 records
- **Performance Thresholds**: 2 seconds for individual queries, 3 seconds for total page load

## Troubleshooting

### Slow Queries
1. Check if indexes exist: `EXPLAIN QUERY PLAN` on slow queries
2. Verify cache is working: Check cache statistics
3. Monitor database size: Large datasets may need archiving
4. Check for database locks: Concurrent operations may cause delays

### Cache Issues
1. **Cache Misses**: Normal on first request or after expiration
2. **Memory Usage**: Monitor cache size, implement cleanup if needed
3. **Stale Data**: Cache invalidation ensures data freshness

### Performance Degradation
1. **Database Growth**: Archive old played_tracks data
2. **Index Fragmentation**: Consider rebuilding indexes periodically
3. **Cache Overhead**: Monitor cache hit rates and adjust TTL if needed

## Future Improvements

1. **Redis Integration**: Replace in-memory cache with Redis for multi-instance deployments
2. **Query Result Pagination**: Implement cursor-based pagination for very large datasets
3. **Background Processing**: Move heavy correlation logic to background tasks
4. **Database Partitioning**: Partition played_tracks by date for better performance
5. **CDN Integration**: Cache static assets and API responses at CDN level