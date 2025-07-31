# Design Document

## Overview

The Spotify Listening History feature will provide users with a comprehensive view of their recent Spotify listening activity, enhanced with contextual information about which tracks originated from their KRUG FM 96.2 playlists. The feature leverages the existing `PlayedTrack` model that is already populated by the `fetch_and_update_recent_tracks()` function in `services/spotify_service.py`, which runs on a schedule to capture Spotify listening data.

The design reuses the existing data collection infrastructure and focuses on creating a new presentation layer that correlates `PlayedTrack` data with `Playlist` data to provide playlist context and track positioning. This approach avoids duplicating the existing Spotify data retrieval logic and instead builds upon the established data pipeline.

## Architecture

### High-Level Components

1. **Route Handler** (`blueprints/spotify/routes.py`)
   - New route: `/listening_history`
   - Handles GET requests for the listening history page
   - Implements pagination for performance
   - Queries `PlayedTrack` model directly (no new data collection needed)

2. **Service Functions** (added to existing `services/spotify_service.py`)
   - `get_listening_history_with_playlist_context()` - Queries PlayedTrack and correlates with Playlist data
   - `determine_track_position_from_context()` - Implements smart position detection for repeated tracks
   - Reuses existing database connection and models

3. **Template** (`templates/spotify_listening_history.html`)
   - Responsive table displaying listening history from PlayedTrack data
   - Visual indicators for playlist tracks
   - Pagination controls
   - Sorting capabilities

4. **Navigation Integration** (`templates/base.html`)
   - Add new menu item under "Spotify Tools" dropdown

### Data Flow Integration

```
Existing: Scheduled Task → fetch_and_update_recent_tracks() → PlayedTrack Model
New: User Request → Route Handler → Service Functions → Query PlayedTrack + Playlist → Template
```

The new feature reads from the existing `PlayedTrack` table that is already being populated by the scheduled `fetch_and_update_recent_tracks()` process, eliminating the need for additional Spotify API calls or data collection logic.

### Data Flow

```
User Request → Route Handler → Service Layer → Database Queries → Data Processing → Template Rendering
```

## Components and Interfaces

### Route Handler Interface

```python
@spotify_bp.route('/listening_history')
@login_required
def listening_history():
    """
    Display recent Spotify listening history with playlist context
    
    Query Parameters:
    - page: int (default: 1) - Page number for pagination
    - limit: int (default: 50) - Number of records per page
    
    Returns:
    - Rendered template with listening history data
    """
```

### Service Functions Interface (added to services/spotify_service.py)

```python
def get_listening_history_with_playlist_context(limit=50, offset=0):
    """
    Retrieve recent listening history from PlayedTrack with playlist correlation
    
    Args:
        limit (int): Maximum number of records to return
        offset (int): Number of records to skip for pagination
    
    Returns:
        tuple: (listening_data, total_count)
        - listening_data: List of enriched PlayedTrack records with playlist context
        - total_count: Total number of available PlayedTrack records
    """

def determine_track_position_from_context(artist, song, played_at, surrounding_tracks, playlist_data):
    """
    Determine track position for repeated songs using context analysis
    
    Args:
        artist (str): Track artist from PlayedTrack
        song (str): Track title from PlayedTrack  
        played_at (datetime): When the track was played from PlayedTrack
        surrounding_tracks: List of PlayedTrack objects played around the same time
        playlist_data: Playlist data for the most recent KRUG FM 96.2 playlist
    
    Returns:
        dict: Position information with confidence level
        - position: int or None
        - confidence: 'high', 'medium', 'low', or 'unknown'
        - method: description of how position was determined
    """
```

## Data Models

### Existing Models Used

1. **PlayedTrack** - Primary source of listening history
   - `source` - Filter for 'spotify' records
   - `artist`, `song` - Track identification
   - `played_at` - Timestamp for chronological ordering
   - `playlist_name` - May contain playlist context

2. **Playlist** - Source of KRUG FM 96.2 playlist data
   - `playlist_name` - Filter for 'KRUG FM 96.2' playlists
   - `playlist_date` - Determine most recent playlist
   - `track_position` - Position within playlist
   - `artist`, `song` - Match with played tracks

### Data Processing Logic

#### Recent Playlist Identification
```sql
SELECT MAX(playlist_date) as latest_date
FROM playlists 
WHERE playlist_name = 'KRUG FM 96.2'
```

#### Listening History Query (uses existing PlayedTrack data)
```sql
SELECT * FROM played_tracks 
WHERE source = 'spotify' 
ORDER BY played_at DESC 
LIMIT ? OFFSET ?
```

Note: This data is already being populated by the existing `fetch_and_update_recent_tracks()` function that runs on a schedule.

#### Playlist Correlation Query
```sql
SELECT track_position, artist, song 
FROM playlists 
WHERE playlist_name = 'KRUG FM 96.2' 
AND playlist_date = ?
```

## Error Handling

### Database Connection Issues
- Graceful degradation with error messages
- Fallback to basic listening history without playlist context
- User-friendly error notifications via flash messages

### Missing Playlist Data
- Handle cases where no KRUG FM 96.2 playlist exists
- Display tracks without playlist context when correlation fails
- Clear messaging about missing playlist information

### Position Detection Failures
- Display "Position unknown" for tracks that cannot be correlated
- Log failed correlation attempts for debugging
- Maintain functionality even when position detection fails

### Performance Considerations
- Implement query timeouts
- Use database indexes on frequently queried columns
- Limit result sets to prevent memory issues

## Testing Strategy

### Unit Tests
1. **Service Layer Tests**
   - Test `get_recent_listening_history()` with various parameters
   - Test `correlate_with_playlist()` with different playlist scenarios
   - Test `determine_track_position()` with repeated tracks and edge cases

2. **Route Handler Tests**
   - Test pagination functionality
   - Test error handling for invalid parameters
   - Test authentication requirements

3. **Position Detection Algorithm Tests**
   - Test with tracks that appear multiple times in playlist
   - Test with tracks played in sequence vs. random order
   - Test edge cases where surrounding context is insufficient

### Integration Tests
1. **Database Integration**
   - Test with real PlayedTrack and Playlist data
   - Test query performance with large datasets
   - Test transaction handling and rollback scenarios

2. **Template Rendering**
   - Test template rendering with various data scenarios
   - Test responsive design elements
   - Test pagination controls functionality

### Performance Tests
1. **Load Testing**
   - Test with large numbers of played tracks (1000+)
   - Test concurrent user access
   - Test database query performance

2. **Memory Usage**
   - Monitor memory consumption with large result sets
   - Test pagination effectiveness in reducing memory usage

### User Acceptance Testing
1. **UI/UX Testing**
   - Verify visual indicators for playlist tracks are clear
   - Test sorting and filtering functionality
   - Verify responsive design on different screen sizes

2. **Data Accuracy Testing**
   - Verify playlist correlation accuracy
   - Test position detection with known repeated tracks
   - Validate timestamp formatting and relative time display

## Implementation Considerations

### Integration with Existing System

The new feature integrates with the existing Spotify data pipeline:

1. **No Additional API Calls**: Uses existing `PlayedTrack` data populated by `fetch_and_update_recent_tracks()`
2. **Consistent Data Model**: Leverages the same `PlayedTrack` and `Playlist` models already in use
3. **Shared Service Layer**: Adds functions to existing `services/spotify_service.py` rather than creating new service files
4. **Existing Authentication**: Uses the same Spotify authentication system already established

### Position Detection Algorithm

For tracks that appear multiple times in a playlist, the system will:

1. **Context Analysis**: Examine `PlayedTrack` records played before and after the target track
2. **Sequence Matching**: Look for patterns in the surrounding tracks that match playlist sequences
3. **Temporal Proximity**: Consider the time gaps between `played_at` timestamps
4. **Confidence Scoring**: Assign confidence levels to position determinations based on context strength

### Performance Optimization

1. **Database Indexing**
   - Index on `played_tracks.played_at` for chronological queries
   - Index on `played_tracks.source` for filtering
   - Composite index on `playlists(playlist_name, playlist_date)`

2. **Query Optimization**
   - Use JOIN operations instead of separate queries where possible
   - Implement query result caching for playlist data
   - Use LIMIT and OFFSET for efficient pagination

3. **Frontend Optimization**
   - Implement client-side sorting where appropriate
   - Use progressive loading for large datasets
   - Optimize table rendering for mobile devices

### Security Considerations

1. **Authentication**: Ensure all routes require login
2. **Data Privacy**: Only show user's own listening history
3. **Input Validation**: Validate pagination parameters
4. **SQL Injection Prevention**: Use parameterized queries

### Scalability Considerations

1. **Pagination**: Default to 50 records per page, configurable
2. **Caching**: Cache playlist data to reduce database load
3. **Async Processing**: Consider background processing for complex correlations
4. **Database Partitioning**: Plan for partitioning played_tracks by date if needed