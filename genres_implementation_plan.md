# kTunes Genres System Implementation Plan

## Project Overview

kTunes is a Flask-based music management application that integrates local iTunes libraries with Spotify. The app features playlist generation engines, track management, and Spotify synchronization capabilities.

## Current State Analysis

### Existing Infrastructure
- **Database Models**: Genre and Track models already exist with many-to-many relationships
- **Association Table**: `track_genres` table properly configured
- **Navigation**: "Manage Genres" navbar button exists but points to incomplete functionality
- **Templates**: Partial genre templates exist in `/templates/playlists/` but reference missing blueprint
- **AI Capability**: App already uses OpenAI APIs extensively for other features

### Database Schema (Already Implemented)
```python
# models.py - Existing relationships
track_genres = Table(
    'track_genres', db.Model.metadata,
    Column('track_id', Integer, ForeignKey('tracks.id'), primary_key=True),
    Column('genre_id', Integer, ForeignKey('genres.id'), primary_key=True)
)

class Track(db.Model):
    genres = relationship('Genre', secondary=track_genres, back_populates='tracks')

class Genre(db.Model):
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    genre_type = Column(String, nullable=True)
    track_count = Column(Integer, nullable=True)
    tracks = relationship('Track', secondary=track_genres, back_populates='genres')
```

### Current Issues
1. **No Genres Blueprint**: References exist but blueprint is missing
2. **Incomplete Routes**: Playlists blueprint has stub `manage_genres` route
3. **Broken Templates**: Templates reference `url_for('genres.*')` routes that don't exist
4. **Missing AI Integration**: No AI-powered genre tagging despite OpenAI infrastructure

## Implementation Goals

### Primary Objective
Implement **AI-powered genre tagging** system with curated genre list as the main feature.

### Key Requirements
1. **Curated Genre List**: Use predefined, well-organized list of music genres
2. **AI Tagging**: Leverage OpenAI to automatically suggest genres for tracks
3. **Blueprint Architecture**: Create dedicated `/blueprints/genres/` blueprint
4. **Dropdown Navigation**: Convert navbar button to dropdown with multiple genre functions
5. **No Engine Integration**: Keep existing playlist engines unchanged
6. **Future Engine Ready**: Design to support future genre-based playlist engine

## Detailed Implementation Plan

### Phase 1: Foundation Setup

#### 1.1 Create Genres Blueprint Structure
```
/blueprints/genres/
├── __init__.py
├── routes.py
├── forms.py
├── templates/
│   ├── manage_genres.html
│   ├── ai_assistant.html
│   └── track_genres.html
└── static/
    └── genres.js
```

#### 1.2 Blueprint Registration
- Add genres blueprint to `app.py`
- Register with URL prefix `/genres`
- Update template search paths

#### 1.3 Curated Genre List
Create comprehensive, hierarchical genre list including:
- **Rock**: Classic Rock, Progressive Rock, Alternative Rock, Indie Rock, Hard Rock
- **Pop**: Pop Rock, Synth-pop, Electropop, Indie Pop
- **Electronic**: House, Techno, Ambient, Drum & Bass, Synthwave
- **Hip-Hop**: East Coast, West Coast, Trap, Boom Bap, Alternative Hip-Hop
- **Jazz**: Bebop, Smooth Jazz, Fusion, Contemporary Jazz
- **Country**: Traditional Country, Country Rock, Alt-Country, Bluegrass
- **R&B/Soul**: Classic Soul, Neo-Soul, Contemporary R&B, Funk
- **Folk**: Folk Rock, Indie Folk, Traditional Folk, Americana
- **Metal**: Heavy Metal, Death Metal, Black Metal, Progressive Metal
- **World**: Latin, Reggae, African, Celtic, World Fusion

### Phase 2: Core Functionality

#### 2.1 Basic Genre Management Routes
```python
# /genres/ - Main genre listing and management
# /genres/manage - Track filtering with genre assignment
# /genres/create - Create new genres (admin only)
# /genres/<id>/edit - Edit genre details
# /genres/<id>/delete - Delete genre (with track reassignment)
# /genres/<id>/tracks - View all tracks in genre
```

#### 2.2 AI Integration Service
```python
class GenreAIService:
    def suggest_genres(self, track_data, max_genres=3):
        """Use OpenAI to suggest genres from curated list"""
        
    def bulk_suggest_genres(self, tracks_list):
        """Process multiple tracks efficiently"""
        
    def analyze_genre_gaps(self, user_tracks):
        """Identify missing genres in user's library"""
```

#### 2.3 Forms and Validation
- Genre creation/editing forms
- Bulk genre assignment forms
- AI suggestion preference forms
- Track filtering forms

### Phase 3: AI-Powered Features

#### 3.1 Smart Genre Tagging
- **Single Track Analysis**: Analyze track metadata (song, artist, album, year) to suggest appropriate genres
- **Batch Processing**: Process multiple untagged tracks at once
- **Confidence Scoring**: Show AI confidence levels for suggestions
- **User Review**: Allow user to approve/reject AI suggestions before applying

#### 3.2 AI Prompt Engineering
```python
GENRE_SUGGESTION_PROMPT = """
Analyze this music track and suggest 1-3 most appropriate genres from the following curated list:

Track Information:
- Song: {song}
- Artist: {artist}
- Album: {album}
- Year: {year}

Available Genres: {genre_list}

Rules:
1. Choose only from the provided genre list
2. Select 1-3 most specific and accurate genres
3. Prioritize sub-genres over broad categories when appropriate
4. Consider artist's typical style and historical context
5. Return ONLY the genre names, comma-separated

Response format: Genre1, Genre2, Genre3
"""
```

#### 3.3 Bulk Operations Interface
- Filter tracks by: untagged, specific genres, artists, categories
- Preview AI suggestions before applying
- Batch approve/reject functionality
- Progress tracking for large operations

### Phase 4: User Interface

#### 4.1 Navigation Update
Convert navbar "Manage Genres" to dropdown:
```html
<li class="nav-item dropdown">
    <a class="nav-link dropdown-toggle" href="#" role="button">
        <i class="fas fa-tags"></i> Genres
    </a>
    <div class="dropdown-menu">
        <a class="dropdown-item" href="{{ url_for('genres.manage') }}">
            <i class="fas fa-cogs"></i> Manage Genres
        </a>
        <a class="dropdown-item" href="{{ url_for('genres.ai_assistant') }}">
            <i class="fas fa-robot"></i> AI Genre Assistant
        </a>
        <a class="dropdown-item" href="{{ url_for('genres.bulk_operations') }}">
            <i class="fas fa-tasks"></i> Bulk Operations
        </a>
    </div>
</li>
```

#### 4.2 Main Genre Management Interface
- **Track Table**: Sortable/filterable list of all tracks
- **Genre Display**: Show current genres for each track as badges
- **Quick Actions**: Add/remove genres inline
- **AI Suggestions**: "Get AI Suggestions" button for untagged tracks

#### 4.3 AI Assistant Interface
- **Track Selection**: Filter tracks needing genre assignment
- **AI Analysis**: Batch analyze selected tracks
- **Review Interface**: Approve/reject AI suggestions
- **Progress Tracking**: Real-time progress for batch operations

### Phase 5: Advanced Features

#### 5.1 Genre Analytics
- Genre distribution charts
- Most/least tagged genres
- Genre popularity trends
- Untagged track statistics

#### 5.2 Search and Discovery
- Advanced filtering by genre combinations
- "Similar tracks" based on genre overlap
- Genre-based track recommendations

#### 5.3 Integration Points (Future)
Design hooks for future genre-based playlist engine:
- Genre combination queries
- Mood-based genre mapping
- Era-specific genre filtering
- Discovery algorithms

## Technical Considerations

### API Rate Limiting
- Implement rate limiting for OpenAI calls
- Batch multiple tracks in single API requests
- Cache results to avoid re-processing same tracks

### Performance Optimization
- Lazy loading for large track lists
- AJAX for real-time updates
- Database indexing on genre relationships
- Pagination for bulk operations

### Error Handling
- Graceful degradation when AI service unavailable
- Validation for manual genre assignments
- Conflict resolution for genre merging/deletion

### Security
- User authentication for all genre operations
- Admin-only access for genre creation/deletion
- Input sanitization for AI prompts
- Rate limiting to prevent API abuse

## Success Metrics

1. **AI Accuracy**: >80% user acceptance rate for AI suggestions
2. **Coverage**: >70% of tracks have at least one genre assigned
3. **Performance**: Bulk operations complete within reasonable timeframes
4. **Usability**: Intuitive interface requiring minimal training
5. **Reliability**: <1% error rate in genre assignments

## Future Enhancements

1. **Genre-Based Playlist Engine**: New engine that creates playlists using genre criteria
2. **Mood Mapping**: Connect genres to moods for emotional playlist generation
3. **User Genre Preferences**: Learn user's genre preferences over time
4. **Collaborative Filtering**: Suggest genres based on similar users' libraries
5. **Genre Evolution**: Track how genres change over time in user's library

## Migration Strategy

1. **Backward Compatibility**: Existing functionality remains unchanged
2. **Gradual Rollout**: Release basic features first, add AI incrementally
3. **Data Preservation**: Ensure no existing data is lost during implementation
4. **User Training**: Provide clear documentation and tutorials

## Files to Create/Modify

### New Files
- `/blueprints/genres/__init__.py`
- `/blueprints/genres/routes.py`
- `/blueprints/genres/forms.py`
- `/blueprints/genres/templates/manage_genres.html`
- `/blueprints/genres/templates/ai_assistant.html`
- `/blueprints/genres/static/genres.js`
- `/services/genre_ai_service.py`

### Files to Modify
- `app.py` (register blueprint)
- `templates/base.html` (update navbar)
- Remove incomplete templates from `/templates/playlists/`

## Development Notes

- Leverage existing OpenAI service patterns from other app features
- Follow established Flask blueprint patterns used in auth, main, resolve blueprints
- Maintain consistency with existing UI/UX design (Spotify-themed styling)
- Ensure proper error handling and user feedback throughout
- Design with scalability in mind for large music libraries
- Consider internationalization for genre names if needed

---

*This plan assumes familiarity with Flask, SQLAlchemy, OpenAI APIs, and the existing kTunes codebase structure.*
