# Design Document

## Overview

The duplicate song management feature provides administrators with a comprehensive tool for identifying, analyzing, and managing duplicate songs in the music library. The system will integrate with the existing Flask application architecture, utilizing the current database models and iTunes XML parsing capabilities to detect songs with variations in titles or artist names (such as remaster suffixes, version numbers, or other appended text).

The feature will be accessible through a new Admin navigation section that consolidates administrative functions, moving the existing Scheduler Dashboard under this new structure for better organization.

## Architecture

### Component Structure

The duplicate management system follows the existing Flask blueprint architecture:

```
blueprints/admin/
├── __init__.py
├── routes.py
└── templates/
    ├── duplicate_management.html
    └── admin_base.html

services/
├── duplicate_detection_service.py
└── itunes_comparison_service.py (extends existing itunes_service.py)
```

### Navigation Integration

The system modifies the existing navigation structure by:
- Adding an "Admin" dropdown to the main navigation bar
- Moving the existing "Scheduler Dashboard" link under the Admin dropdown
- Adding the new "Duplicate Management" option under the Admin dropdown

### Database Integration

The system leverages the existing `Track` model without requiring schema changes, utilizing:
- `song` and `artist` fields for duplicate detection
- `play_cnt` and `last_play_dt` for decision-making metadata
- `date_added` for tracking entry creation
- Existing relationships and indexes

## Components and Interfaces

### 1. Admin Blueprint (`blueprints/admin/`)

**Purpose**: Provides the web interface and routing for administrative functions

**Key Routes**:
- `/admin/duplicates` - Main duplicate management interface
- `/admin/duplicates/analyze` - AJAX endpoint for duplicate analysis
- `/admin/duplicates/delete` - AJAX endpoint for song deletion
- `/admin/duplicates/bulk-delete` - Bulk deletion operations

**Templates**:
- `duplicate_management.html` - Main interface with search, filtering, and management tools
- `admin_base.html` - Base template extending the main base template

### 2. Duplicate Detection Service (`services/duplicate_detection_service.py`)

**Purpose**: Core logic for identifying and analyzing duplicate songs

**Key Methods**:
```python
class DuplicateDetectionService:
    def find_duplicates(self, search_term=None, sort_by='artist') -> List[DuplicateGroup]
    def analyze_duplicate_group(self, songs: List[Track]) -> DuplicateAnalysis
    def suggest_canonical_version(self, songs: List[Track]) -> Track
    def get_similarity_score(self, song1: Track, song2: Track) -> float
```

**Duplicate Detection Algorithm**:
1. **Fuzzy Matching**: Uses string similarity algorithms (Levenshtein distance) to identify potential duplicates
2. **Suffix Detection**: Identifies common patterns like "- 2020 Remaster", "- Deluxe Edition", "- Radio Edit"
3. **Artist Normalization**: Handles variations in artist names and featuring credits
4. **Grouping**: Groups similar songs together with confidence scores

### 3. iTunes Comparison Service (`services/itunes_comparison_service.py`)

**Purpose**: Cross-references duplicate songs with iTunes XML catalog

**Key Methods**:
```python
class ITunesComparisonService:
    def __init__(self, xml_path: str)
    def find_itunes_matches(self, duplicate_group: List[Track]) -> Dict[Track, ITunesMatch]
    def get_itunes_metadata(self, song_name: str, artist_name: str) -> Optional[ITunesTrack]
    def compare_metadata(self, db_track: Track, itunes_track: ITunesTrack) -> MetadataComparison
```

**Integration Points**:
- Extends existing `ITunesXMLParser` from `services/itunes_service.py`
- Reuses XML parsing logic and library initialization
- Provides read-only access to iTunes catalog for comparison

### 4. Data Models

**DuplicateGroup** (Data Transfer Object):
```python
@dataclass
class DuplicateGroup:
    canonical_song: Track
    duplicates: List[Track]
    similarity_scores: Dict[int, float]  # track_id -> similarity score
    itunes_matches: Dict[int, ITunesMatch]  # track_id -> iTunes match info
    suggested_action: str  # 'keep_most_played', 'keep_itunes_version', etc.
```

**ITunesMatch** (Data Transfer Object):
```python
@dataclass
class ITunesMatch:
    found: bool
    itunes_song: Optional[str]
    itunes_artist: Optional[str]
    metadata_differences: List[str]
    confidence_score: float
```

## Data Models

### Existing Models (No Changes Required)

The system utilizes the existing `Track` model from `models.py`:
- Primary key: `id`
- Core fields: `song`, `artist`, `album`
- Metadata: `play_cnt`, `last_play_dt`, `date_added`
- Location: `location` (file path)
- Category: `category` (genre classification)

### New Data Transfer Objects

**DuplicateAnalysis**:
```python
@dataclass
class DuplicateAnalysis:
    total_groups: int
    total_duplicates: int
    groups_with_itunes_matches: int
    suggested_deletions: int
    potential_space_savings: str  # Human-readable estimate
```

## Error Handling

### Validation and Safety Measures

1. **Deletion Protection**:
   - Confirmation dialogs for all deletion operations
   - Batch size limits for bulk operations
   - Transaction rollback on errors
   - Audit logging of deletion actions

2. **iTunes Integration Errors**:
   - Graceful handling of missing or corrupted XML files
   - Fallback behavior when iTunes library is unavailable
   - Clear error messages for XML parsing failures

3. **Performance Safeguards**:
   - Pagination for large result sets
   - Background processing for intensive operations
   - Progress indicators for long-running tasks
   - Request timeouts and cancellation

### Error Response Patterns

```python
# API Error Response Format
{
    "success": false,
    "error": {
        "code": "DUPLICATE_ANALYSIS_FAILED",
        "message": "Unable to analyze duplicates",
        "details": "iTunes XML file not accessible"
    }
}
```

## Testing Strategy

### Unit Tests

1. **Duplicate Detection Logic**:
   - Test similarity algorithms with known duplicate pairs
   - Verify suffix detection patterns
   - Test edge cases (empty strings, special characters)

2. **iTunes Integration**:
   - Mock iTunes XML parsing
   - Test metadata comparison logic
   - Verify error handling for missing files

3. **Data Safety**:
   - Test deletion validation
   - Verify transaction rollback scenarios
   - Test bulk operation limits

### Integration Tests

1. **End-to-End Workflows**:
   - Complete duplicate detection and deletion flow
   - iTunes cross-reference integration
   - Navigation and UI integration

2. **Database Operations**:
   - Test with realistic dataset sizes
   - Verify performance with large numbers of duplicates
   - Test concurrent access scenarios

### Test Data Setup

```python
# Example test data creation
def create_test_duplicates():
    tracks = [
        Track(song="I Got", artist="Artist Name", play_cnt=10),
        Track(song="I Got - 2020 Remaster", artist="Artist Name", play_cnt=5),
        Track(song="I Got (Radio Edit)", artist="Artist Name", play_cnt=3)
    ]
    return tracks
```

### Performance Testing

1. **Load Testing**:
   - Test with libraries containing 10,000+ tracks
   - Measure response times for duplicate analysis
   - Test memory usage during large operations

2. **Scalability Testing**:
   - Test pagination performance
   - Measure iTunes XML parsing time
   - Test concurrent user scenarios

## Security Considerations

### Access Control

1. **Authentication Requirements**:
   - All admin routes require user authentication
   - Leverage existing Flask-Login integration
   - Session-based access control

2. **Authorization**:
   - Admin functions restricted to authenticated users
   - CSRF protection on all state-changing operations
   - Input validation and sanitization

### Data Protection

1. **Deletion Safety**:
   - Soft delete options where appropriate
   - Audit trail for administrative actions
   - Backup recommendations before bulk operations

2. **Input Validation**:
   - Sanitize search terms and filter parameters
   - Validate track IDs before deletion
   - Prevent SQL injection through parameterized queries

## Performance Optimizations

### Database Optimization

1. **Query Efficiency**:
   - Use database indexes for song/artist lookups
   - Batch database operations where possible
   - Implement query result caching for repeated analyses

2. **Memory Management**:
   - Stream large result sets instead of loading all into memory
   - Implement pagination for UI display
   - Use generators for iTunes XML processing

### Caching Strategy

1. **Duplicate Analysis Caching**:
   - Cache duplicate detection results for repeated queries
   - Invalidate cache when tracks are added/modified
   - Use Redis or in-memory caching for session-based results

2. **iTunes Data Caching**:
   - Cache iTunes XML parsing results
   - Implement file modification time checking
   - Provide manual cache refresh options

## Integration Points

### Navigation Integration

The system integrates with the existing navigation by modifying `templates/base.html`:

```html
<!-- New Admin Dropdown -->
<li class="nav-item dropdown">
    <a class="nav-link dropdown-toggle" href="#" id="adminDropdown" role="button" 
       data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
        <i class="fas fa-cog"></i> Admin
    </a>
    <div class="dropdown-menu" aria-labelledby="adminDropdown">
        <a class="dropdown-item" href="{{ url_for('admin.duplicate_management') }}">
            <i class="fas fa-copy"></i> Duplicate Management
        </a>
        <a class="dropdown-item" href="{{ url_for('apscheduler.dashboard') }}">
            <i class="fas fa-clock"></i> Scheduler Dashboard
        </a>
    </div>
</li>
```

### Service Integration

1. **iTunes Service Extension**:
   - Extends existing `ITunesXMLParser` class
   - Reuses XML file path configuration
   - Maintains compatibility with existing update logic

2. **Database Service Integration**:
   - Uses existing SQLAlchemy session management
   - Leverages current transaction handling patterns
   - Maintains consistency with existing data access patterns

### Configuration Integration

The system uses the existing configuration system from `config_loader.py`:

```python
# Configuration options
{
    "duplicate_management": {
        "similarity_threshold": 0.8,
        "batch_size_limit": 100,
        "enable_itunes_comparison": true,
        "cache_duration_minutes": 30
    }
}
```