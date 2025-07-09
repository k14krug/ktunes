# kTunes Classic Playlist Engine

## Overview
The **kTunes Classic Engine** is the original playlist generation algorithm that creates time-weighted, category-balanced playlists with sophisticated artist repeat management. It's designed for large-scale playlist generation (typically 600 songs / 40 hours) with a focus on music discovery and aging.

**Engine ID:** `ktunes_classic`  
**Engine Name:** `kTunes Classic`

## Core Philosophy

This engine treats music as having a **lifecycle** - songs flow through categories based on how new they are, how often you've listened to them, and how much time has passed. The goal is to:

- **Prioritize new discoveries** while maintaining familiar favorites
- **Age music naturally** through different rotation levels  
- **Prevent artist fatigue** with smart repeat intervals
- **Handle massive playlists** efficiently (600+ songs)

## Music Category System

### Category Pipeline
```
NEW DISCOVERY → RecentAdd → Latest → Other → Old → Album
               (0-15 plays) (fresh,  (aging) (archive) (deep cuts)
                           <18 months)
```

### Category Definitions

| Category | Purpose | Percentage | Artist Repeat | Description |
|----------|---------|------------|---------------|-------------|
| **RecentAdd** | 20% | 30 songs | New discoveries (<15 plays) |
| **Latest** | 25% | 21 songs | Current favorites (<18 months old) |
| **In Rot** | 35% | 40 songs | Regular rotation (bulk of playlist) |
| **Other** | 10% | 200 songs | Still recent, but aging |
| **Old** | 7% | 200 songs | Archive songs you still enjoy |
| **Album** | 3% | 200 songs | Deep tracks, rare plays |

## Smart Category Migration

The engine automatically moves songs between categories:

### RecentAdd Migration
```python
# Songs with <15 plays become RecentAdd automatically
recent_tracks = Track.query.filter(
    Track.category == "Latest",
    Track.play_cnt < minimum_recent_add_playcount
)
```

### Age-Based Migration  
```python
# Songs >18 months old move from Latest → In Rot
eighteen_months_ago = datetime.now() - timedelta(days=18*30)
old_tracks = Track.query.filter(
    Track.category == "Latest",
    Track.date_added < eighteen_months_ago
)
```

## Playlist Generation Algorithm

### 1. Category Distribution
Uses fractional distribution to spread categories evenly throughout the playlist instead of playing all songs from one category before moving to the next.

**Example for 600 songs:**
- RecentAdd: 120 songs (every ~5th song)
- Latest: 150 songs (every ~4th song)  
- In Rot: 210 songs (every ~3rd song)

### 2. Track Selection Logic
For each position:
1. **Determine required category** (from distribution)
2. **Filter available tracks** (not recently played)
3. **Apply artist repeat rules** (prevent same artist too soon)
4. **Select least recently played** eligible track
5. **Mark as played** to prevent immediate reuse

### 3. Category Exhaustion Handling
When a category runs out of eligible tracks:
- **Reset "played" status** for that category
- **Smart fallback**: RecentAdd → Latest if still exhausted
- **Continue generation** seamlessly

## Artist Repeat Management

### Multi-Level Repeat Prevention
```python
# Each category has different repeat intervals
artist_repeat_intervals = {
    "RecentAdd": 30,   # ~20 appearances in 600-song playlist
    "Latest": 21,      # ~29 appearances  
    "In Rot": 40,      # ~15 appearances
    "Old": 200,        # ~3 appearances
    "Album": 200       # ~3 appearances
}
```

### Cross-Category Tracking
The engine remembers artist plays across ALL categories to prevent bunching from different sources.

## Performance Optimizations

### Memory-Based Processing
- **All tracks loaded once** at initialization
- **In-memory category filtering** for speed
- **Batch database operations** for saves

### Smart Querying
- **Single bulk query** for playlist saving
- **Efficient M3U generation** with track lookup dictionary
- **Minimal database hits** during generation

## Configuration

### Required Settings
```json
{
    "playlist_length": 40.0,          // Hours
    "minimum_recent_add_playcount": 15,
    "categories": [
        {
            "name": "RecentAdd",
            "percentage": 20.0,
            "artist_repeat": 30
        }
        // ... other categories
    ]
}
```

### Calculated Values
- **Total songs**: `playlist_length * 60 / 4` (assumes 4-min average)
- **Category counts**: `total_songs * percentage / 100`

## Output Products

1. **Database Records**: Full playlist with positions and metadata
2. **M3U File**: Standard playlist file for music players
3. **Statistics**: Category distribution and generation metrics

## Use Cases

**Ideal for:**
- Large personal music collections (10,000+ tracks)
- Long-form listening sessions (hours-long playlists)  
- Music discovery with familiar favorites mixed in
- Collections with varied acquisition dates
- Users who want "radio station" style rotation

**Not ideal for:**
- Small collections (<1,000 tracks)
- Theme-based or mood-based playlists
- Short playlists (<50 songs)
- Collections without play count data

## Technical Notes

### Database Requirements
- `Track.play_cnt` - for RecentAdd classification
- `Track.date_added` - for age-based migration  
- `Track.last_play_dt` - for staleness prioritization
- `Track.category` - for initial categorization
- `Track.artist_common_name` - for repeat management

### Memory Usage
Loads entire track collection into memory. For very large collections (100K+ tracks), consider memory constraints.

### Spotify Integration
When `target_platform = 'spotify'`, filters out tracks marked as 'not_found_in_spotify' to ensure playlist compatibility.

## Future Enhancements

Potential improvements for this engine:
- **Mood weighting** within categories
- **Time-of-day preferences** 
- **Weather-based adjustments**
- **Collaborative filtering** for similar users
- **Dynamic category percentages** based on collection size

---

**Last Updated:** July 2025  
**Engine Version:** 1.0  
**Compatible with:** kTunes v2.0+
