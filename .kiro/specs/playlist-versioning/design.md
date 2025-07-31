# Design Document

## Overview

The Playlist Versioning System will implement a comprehensive solution to preserve historical versions of any playlist that gets recreated, enabling accurate correlation between listening history and the specific playlist version that was active when tracks were played. While the primary use case is the KRUG FM 96.2 playlist, the system is designed to be generic and support versioning for any playlist in the system. The system will integrate seamlessly with the existing playlist generation workflow while providing temporal correlation capabilities.

The design introduces a new `PlaylistVersion` model to store playlist snapshots, a versioning service layer to manage playlist lifecycle, and enhanced correlation logic that can query historical playlist data based on timestamps. This approach preserves the existing playlist generation process while adding versioning as a transparent layer.

## Architecture

### High-Level Components

1. **PlaylistVersion Model** - New database model to store versioned playlist snapshots
2. **Playlist Versioning Service** - Service layer to manage playlist version lifecycle
3. **Integration Hooks** - Modifications to existing playlist generation to trigger versioning
4. **Correlation Service** - Enhanced logic to query appropriate playlist versions by timestamp
5. **Cleanup Service** - Automated maintenance to manage version retention policy

### Data Flow

```
Existing Flow: Scheduled Task → generate_default_playlist() → Delete Old Playlist → Create New Playlist
Enhanced Flow: Scheduled Task → generate_default_playlist() → Version Old Playlist → Create New Playlist
```

### Integration Points

1. **Playlist Generation Hook** - Intercept playlist deletion to create versions
2. **Listening History Service** - Enhance correlation to use versioned data
3. **Scheduled Cleanup** - Add maintenance tasks for version management

## Components and Interfaces

### PlaylistVersion Model

```python
class PlaylistVersion(db.Model):
    __tablename__ = 'playlist_versions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(String, nullable=False, unique=True)  # UUID for version identification
    playlist_name = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)  # When this version was created
    active_from = Column(DateTime, nullable=False)  # When this version became active
    active_until = Column(DateTime, nullable=True)  # When this version was replaced (null for current)
    track_count = Column(Integer, nullable=False)
    username = Column(String, nullable=True)
    
    # Relationship to versioned tracks
    tracks = relationship('PlaylistVersionTrack', back_populates='version')

class PlaylistVersionTrack(db.Model):
    __tablename__ = 'playlist_version_tracks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(String, ForeignKey('playlist_versions.version_id'), nullable=False)
    track_position = Column(Integer, nullable=False)
    artist = Column(String, nullable=False)
    song = Column(String, nullable=False)
    category = Column(String, nullable=False)
    play_cnt = Column(Integer, nullable=False)
    artist_common_name = Column(String, nullable=True)
    
    # Relationship back to version
    version = relationship('PlaylistVersion', back_populates='tracks')
```

### Playlist Versioning Service Interface

```python
class PlaylistVersioningService:
    
    @staticmethod
    def create_version_from_current_playlist(playlist_name: str, username: str = None) -> str:
        """
        Create a versioned snapshot of the current playlist before it gets replaced
        
        Args:
            playlist_name: Name of the playlist to version
            username: Username associated with the playlist
            
        Returns:
            version_id: Unique identifier for the created version
        """
    
    @staticmethod
    def get_active_version_at_time(playlist_name: str, timestamp: datetime, username: str = None) -> PlaylistVersion:
        """
        Get the playlist version that was active at a specific timestamp
        
        Args:
            playlist_name: Name of the playlist
            timestamp: The time to query for
            username: Username associated with the playlist
            
        Returns:
            PlaylistVersion object or None if no version found
        """
    
    @staticmethod
    def cleanup_old_versions(playlist_name: str = None, retention_days: int = 7, max_versions: int = 10) -> int:
        """
        Clean up old playlist versions based on retention policy
        
        Args:
            playlist_name: Name of specific playlist to clean up, or None to clean up all playlists
            retention_days: Keep versions newer than this many days
            max_versions: Keep at least this many recent versions
            
        Returns:
            Number of versions cleaned up across all specified playlists
        """
    
    @staticmethod
    def cleanup_all_playlists(retention_days: int = 7, max_versions: int = 10) -> dict:
        """
        Clean up old versions for all playlists using global retention policy
        
        Args:
            retention_days: Keep versions newer than this many days
            max_versions: Keep at least this many recent versions
            
        Returns:
            Dictionary mapping playlist names to number of versions cleaned up
        """
    
    @staticmethod
    def get_version_statistics(playlist_name: str = None) -> dict:
        """
        Get statistics about stored versions for monitoring
        
        Args:
            playlist_name: Specific playlist to get stats for, or None for all playlists
            
        Returns:
            Dictionary with version count, storage usage, date range per playlist
        """
    
    @staticmethod
    def get_all_versioned_playlists() -> list:
        """
        Get list of all playlists that have versions stored
        
        Returns:
            List of playlist names that have version history
        """
```

### Enhanced Correlation Service Interface

```python
def get_listening_history_with_versioned_playlist_context(limit=50, offset=0):
    """
    Enhanced version of existing function that uses playlist versioning
    
    Args:
        limit (int): Maximum number of records to return
        offset (int): Number of records to skip for pagination
    
    Returns:
        tuple: (listening_data, total_count, error_message)
        - listening_data: List of enriched PlayedTrack records with versioned playlist context
        - total_count: Total number of available PlayedTrack records
        - error_message: Any errors or warnings about correlation accuracy
    """

def correlate_track_with_versioned_playlist(artist: str, song: str, played_at: datetime) -> dict:
    """
    Correlate a played track with the appropriate playlist version
    
    Args:
        artist: Track artist
        song: Track title
        played_at: When the track was played
        
    Returns:
        dict: Correlation result with version info, position, confidence level
    """
```

## Data Models

### Playlist Version Storage Strategy

The system will use a separate table structure to store playlist versions rather than modifying the existing `playlists` table. This approach:

1. **Preserves existing functionality** - No changes to current playlist queries
2. **Enables efficient versioning** - Dedicated schema optimized for version queries
3. **Supports cleanup operations** - Easy to identify and remove old versions
4. **Provides audit trail** - Complete history of playlist changes

### Version Identification Strategy

Each playlist version will have:
- **version_id**: UUID for unique identification
- **active_from**: Timestamp when version became active
- **active_until**: Timestamp when version was replaced (null for current)
- **created_at**: When the version record was created

### Temporal Correlation Logic

```sql
-- Find active version at specific timestamp for any playlist
SELECT * FROM playlist_versions 
WHERE playlist_name = ? 
  AND active_from <= ?
  AND (active_until IS NULL OR active_until > ?)
ORDER BY active_from DESC 
LIMIT 1

-- Get all playlists with versions for cleanup operations
SELECT DISTINCT playlist_name FROM playlist_versions
```

## Error Handling

### Version Creation Failures
- **Database unavailable**: Queue versioning operation for retry
- **Insufficient storage**: Trigger emergency cleanup before versioning
- **Concurrent modifications**: Use database locks to prevent race conditions
- **Partial version creation**: Rollback incomplete versions and log errors

### Correlation Failures
- **No version found**: Fall back to current playlist correlation method
- **Multiple versions match**: Use closest preceding timestamp with confidence indicator
- **Version data corrupted**: Mark version as invalid and exclude from queries
- **Performance degradation**: Implement query timeouts and fallback strategies

### Cleanup Operation Failures
- **Cannot delete versions**: Log errors but continue with other cleanup operations
- **Storage constraints**: Prioritize keeping most recent and most accessed versions
- **Retention policy conflicts**: Resolve using configurable priority rules

## Testing Strategy

### Unit Tests

1. **PlaylistVersioningService Tests**
   - Test version creation with various playlist sizes and configurations
   - Test temporal correlation with edge cases (exact timestamps, gaps, overlaps)
   - Test cleanup operations with different retention policies
   - Test error handling for database failures and invalid data

2. **Model Tests**
   - Test PlaylistVersion and PlaylistVersionTrack model relationships
   - Test database constraints and indexing performance
   - Test data integrity during concurrent operations

3. **Integration Hook Tests**
   - Test versioning integration with existing playlist generation
   - Test backward compatibility with existing correlation methods
   - Test performance impact on playlist generation workflow

### Integration Tests

1. **End-to-End Workflow Tests**
   - Test complete playlist generation → versioning → correlation cycle
   - Test listening history correlation accuracy with versioned data
   - Test system behavior during high-frequency playlist generation

2. **Performance Tests**
   - Test correlation query performance with large numbers of versions
   - Test version creation performance impact on playlist generation
   - Test cleanup operation performance during peak usage

3. **Data Consistency Tests**
   - Test version data accuracy compared to original playlists
   - Test temporal correlation accuracy across different time ranges
   - Test system recovery after partial failures

### User Acceptance Tests

1. **Listening History Accuracy**
   - Verify improved correlation accuracy compared to current system
   - Test edge cases where current system fails but versioning succeeds
   - Validate confidence indicators and fallback behavior

2. **System Transparency**
   - Verify no user-visible changes to playlist generation process
   - Test that listening history performance remains acceptable
   - Validate error messages and degraded functionality scenarios

## Implementation Considerations

### Database Schema Changes

The implementation will add new tables without modifying existing schema:
- `playlist_versions` - Store version metadata
- `playlist_version_tracks` - Store versioned track data

### Indexing Strategy

Critical indexes for performance:
- `playlist_versions(playlist_name, active_from, active_until)` - Temporal queries
- `playlist_version_tracks(version_id, track_position)` - Track lookups
- `playlist_versions(created_at)` - Cleanup operations

### Integration with Existing Code

1. **Generic Integration**: Hook into playlist deletion operations across all playlist generation functions
2. **Backward Compatibility**: Existing correlation code continues to work for all playlists
3. **Configurable Versioning**: Allow enabling/disabling versioning per playlist name or globally
4. **Fallback Strategy**: System degrades gracefully if versioning fails for any playlist

### Performance Optimization

1. **Lazy Loading**: Only load version data when correlation is needed
2. **Caching Strategy**: Cache frequently accessed versions in memory
3. **Query Optimization**: Use efficient indexes and query patterns
4. **Background Processing**: Perform cleanup operations during low-usage periods

### Monitoring and Observability

1. **Version Metrics**: Track version creation rate, storage usage, cleanup frequency
2. **Correlation Metrics**: Monitor correlation accuracy, query performance, fallback usage
3. **Error Tracking**: Log and alert on versioning failures and data inconsistencies
4. **Performance Monitoring**: Track impact on playlist generation and listening history performance

### Security Considerations

1. **Data Privacy**: Ensure versioned data follows same privacy rules as current playlists
2. **Access Control**: Restrict version management operations to appropriate users
3. **Data Retention**: Comply with data retention policies for historical playlist data
4. **Audit Trail**: Maintain logs of version operations for compliance and debugging

### Configuration Management

The system will support configuration for versioning behavior:

```python
# Configuration options
PLAYLIST_VERSIONING_CONFIG = {
    'enabled': True,  # Global enable/disable
    'retention_days': 7,  # Default retention period
    'max_versions': 10,  # Default maximum versions to keep
    'enabled_playlists': ['*'],  # List of playlist names to version, '*' for all
    'cleanup_schedule': 'daily',  # How often to run cleanup
    'performance_mode': 'balanced'  # 'fast', 'balanced', or 'thorough'
}
```

### Scalability Considerations

1. **Storage Growth**: Plan for linear growth in storage requirements across all versioned playlists
2. **Query Performance**: Design indexes and queries to scale with version count across multiple playlists
3. **Cleanup Efficiency**: Ensure cleanup operations scale with data volume and number of different playlists
4. **Concurrent Access**: Handle multiple users and scheduled tasks safely across all playlist types

### Generic Cleanup Strategy

The cleanup process will operate across all versioned playlists:

1. **Daily Cleanup Job**: Scheduled task that processes all playlists with versions
2. **Per-Playlist Rules**: Apply same retention policy (10 versions or 7 days) to each playlist
3. **Global Monitoring**: Track storage usage and performance across all versioned playlists
4. **Configurable Policies**: Allow different retention rules for different playlist patterns if needed

The design prioritizes reliability and backward compatibility while providing a generic foundation for versioning any playlist in the system. The modular approach allows for incremental implementation and testing while maintaining system stability across all playlist types.