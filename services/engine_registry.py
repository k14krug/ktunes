# services/engine_registry.py
"""
Playlist Engine Registry

Manages registration and discovery of all available playlist generation engines.
Each engine must extend BasePlaylistEngine and define ENGINE_ID and ENGINE_NAME.

See docs/engines/ for detailed documentation on each engine.
"""

import os
from typing import Dict, List, Optional

# We will populate this dynamically to avoid circular imports.
AVAILABLE_ENGINES = {}

# Engine metadata for UI display
ENGINE_UI_METADATA = {
    'ktunes_classic': {
        'description': 'Time-weighted, category-balanced playlist generation with sophisticated artist repeat management. Perfect for large collections and music discovery.',
        'features': [
            '6-tier category system with automatic aging',
            'Smart artist repeat prevention', 
            'Category exhaustion handling',
            'Memory-optimized for large collections',
            'Spotify integration ready'
        ],
        'use_cases': [
            'Large Collections (10K+ tracks)',
            'Long Playlists (40+ hours)', 
            'Music Discovery',
            'Personal Radio Style'
        ],
        'stats': {
            'typical_length': '600 songs / 40 hours',
            'collection_size': '10K+ tracks',
            'generation_time': '< 30 seconds'
        },
        'best_for': 'Large personal music collections with varied acquisition dates',
        'not_ideal_for': 'Small collections, theme-based playlists, or short playlists'
    }
}

def register_engines():
    """
    This function is called to populate the engine registry.
    It's called after all modules are loaded to avoid circular dependencies.
    
    When adding new engines:
    1. Import the engine class here
    2. Register it in AVAILABLE_ENGINES dictionary  
    3. Create documentation in docs/engines/
    4. Update docs/engines/README.md
    """
    from .playlist_generator_service import PlaylistGenerator
    # Import future engines here
    # from .artist_shuffle_engine import ArtistShuffleEngine 
    # from .mood_based_engine import MoodBasedEngine

    # Register engines with their unique IDs
    AVAILABLE_ENGINES[PlaylistGenerator.ENGINE_ID] = PlaylistGenerator
    # AVAILABLE_ENGINES[ArtistShuffleEngine.ENGINE_ID] = ArtistShuffleEngine
    # AVAILABLE_ENGINES[MoodBasedEngine.ENGINE_ID] = MoodBasedEngine

def get_engine(engine_id):
    """Get a specific engine by its ID."""
    if not AVAILABLE_ENGINES:
        register_engines()
    return AVAILABLE_ENGINES.get(engine_id)

def get_all_engines():
    """Get list of all available engines with their basic info."""
    if not AVAILABLE_ENGINES:
        register_engines()
    return [
        {"id": engine.ENGINE_ID, "name": engine.ENGINE_NAME}
        for engine in AVAILABLE_ENGINES.values()
    ]

def get_all_engines_enhanced():
    """Get all engines with enhanced metadata for UI display."""
    if not AVAILABLE_ENGINES:
        register_engines()
    
    engines = []
    for engine in AVAILABLE_ENGINES.values():
        engine_id = engine.ENGINE_ID
        metadata = ENGINE_UI_METADATA.get(engine_id, {})
        
        enhanced_engine = {
            'id': engine_id,
            'name': engine.ENGINE_NAME,
            'description': metadata.get('description', 'Custom playlist generation engine.'),
            'features': metadata.get('features', []),
            'use_cases': metadata.get('use_cases', []),
            'stats': metadata.get('stats', {}),
            'best_for': metadata.get('best_for', ''),
            'not_ideal_for': metadata.get('not_ideal_for', ''),
            'documentation_url': f"/playlists/engines/{engine_id}/docs"
        }
        engines.append(enhanced_engine)
    
    return engines

def get_engine_info(engine_id):
    """Get detailed information about a specific engine."""
    engine = get_engine(engine_id)
    if not engine:
        return None
    
    return {
        "id": engine.ENGINE_ID,
        "name": engine.ENGINE_NAME,
        "class": engine.__name__,
        "module": engine.__module__,
        "has_config_form": hasattr(engine, 'get_configuration_form'),
        "documentation": f"docs/engines/{engine_id.replace('_', '-')}-engine.md"
    }