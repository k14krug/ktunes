# kTunes Playlist Engines

This directory contains documentation for all available playlist generation engines in kTunes.

## Available Engines

### [kTunes Classic Engine](./ktunes-classic-engine.md)
**Engine ID:** `ktunes_classic`

The original time-weighted playlist generator with sophisticated category aging and artist repeat management. Ideal for large personal collections and long-form listening sessions.

**Best for:** Music discovery, large collections (10K+ tracks), 40+ hour playlists  
**Features:** 6-tier category system, automatic music aging, smart artist spacing

---

## Engine Development

When creating new engines:

1. **Extend `BasePlaylistEngine`** in `/services/base_playlist_engine.py`
2. **Register in `engine_registry.py`** 
3. **Create documentation** in this directory following the template above
4. **Add configuration form** if needed
5. **Update this index** with your new engine

### Documentation Template
Each engine should have:
- **Overview & Philosophy** - What makes this engine unique?
- **Algorithm Details** - How does it work?
- **Configuration Options** - What can users customize?
- **Use Cases** - When should users choose this engine?
- **Technical Requirements** - What data does it need?

---

**Last Updated:** July 2025
