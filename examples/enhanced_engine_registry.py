# Enhanced engine registry with UI support
# services/engine_registry.py

import os
import yaml
from typing import Dict, List, Optional

# Engine metadata loaded from documentation
ENGINE_METADATA = {}

def load_engine_metadata():
    """Load engine metadata from documentation files."""
    global ENGINE_METADATA
    
    docs_dir = 'docs/engines'
    if not os.path.exists(docs_dir):
        return
    
    for filename in os.listdir(docs_dir):
        if filename.endswith('-engine.md'):
            engine_id = filename.replace('-engine.md', '').replace('-', '_')
            metadata = _parse_engine_docs(os.path.join(docs_dir, filename))
            ENGINE_METADATA[engine_id] = metadata

def _parse_engine_docs(filepath: str) -> Dict:
    """Parse engine documentation to extract metadata."""
    metadata = {
        'description': '',
        'features': [],
        'use_cases': [],
        'collection_category': 'any',
        'length_category': 'any',
        'focus_tags': [],
        'tips': [],
        'stats': {}
    }
    
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        
        # Extract description from overview section
        if '## Overview' in content:
            overview_start = content.find('## Overview') + len('## Overview')
            overview_end = content.find('##', overview_start)
            if overview_end == -1:
                overview_end = len(content)
            
            overview = content[overview_start:overview_end].strip()
            # Get first paragraph as description
            first_para = overview.split('\n\n')[0].replace('\n', ' ').strip()
            metadata['description'] = first_para
        
        # Extract use cases
        if '**Ideal for:**' in content:
            ideal_start = content.find('**Ideal for:**')
            ideal_end = content.find('**Not ideal for:**', ideal_start)
            if ideal_end == -1:
                ideal_end = content.find('\n\n', ideal_start)
            
            ideal_section = content[ideal_start:ideal_end]
            use_cases = []
            for line in ideal_section.split('\n'):
                if line.strip().startswith('- '):
                    use_cases.append(line.strip()[2:])
            metadata['use_cases'] = use_cases
        
        # Categorize based on content keywords
        content_lower = content.lower()
        
        # Collection size category
        if 'large' in content_lower and 'collection' in content_lower:
            metadata['collection_category'] = 'large'
        elif 'small' in content_lower and 'collection' in content_lower:
            metadata['collection_category'] = 'small'
        else:
            metadata['collection_category'] = 'medium'
        
        # Length category
        if '40 hour' in content_lower or '600 song' in content_lower:
            metadata['length_category'] = 'long'
        elif 'short' in content_lower:
            metadata['length_category'] = 'short'
        else:
            metadata['length_category'] = 'medium'
        
        # Focus tags
        focus_tags = []
        if 'discovery' in content_lower:
            focus_tags.append('discovery')
        if 'favorite' in content_lower:
            focus_tags.append('favorites')
        if 'variety' in content_lower:
            focus_tags.append('variety')
        if 'mood' in content_lower:
            focus_tags.append('mood')
        metadata['focus_tags'] = focus_tags
        
        # Engine-specific logic for known engines
        if 'ktunes_classic' in filepath:
            metadata.update({
                'features': [
                    "6-tier category system with automatic aging",
                    "Smart artist repeat prevention", 
                    "Category exhaustion handling",
                    "Memory-optimized for large collections",
                    "Spotify integration ready"
                ],
                'stats': {
                    'typical_length': '600 songs / 40 hours',
                    'collection_size': '10K+ tracks',
                    'generation_time': '< 30 seconds'
                },
                'tips': [
                    "Works best with collections over 10,000 tracks",
                    "40+ hour playlists give the best category balance",
                    "Set recent add count to match your discovery rate",
                    "Let the system run category resets for optimal variety"
                ]
            })
    
    except Exception as e:
        print(f"Error parsing engine docs {filepath}: {e}")
    
    return metadata

# Enhanced registry functions
def get_all_engines_enhanced():
    """Get all engines with enhanced metadata for UI."""
    if not ENGINE_METADATA:
        load_engine_metadata()
    
    engines = []
    for engine_summary in get_all_engines():
        engine_id = engine_summary['id']
        metadata = ENGINE_METADATA.get(engine_id, {})
        
        enhanced_engine = {
            **engine_summary,
            **metadata,
            'documentation_url': f"/playlists/engines/{engine_id}/docs"
        }
        engines.append(enhanced_engine)
    
    return engines

def get_engine_guidance(engine_id: str) -> Dict:
    """Get UI guidance for a specific engine."""
    metadata = ENGINE_METADATA.get(engine_id, {})
    
    guidance = {
        'description': metadata.get('description', ''),
        'length_guidance': '',
        'tips': metadata.get('tips', []),
        'use_cases': metadata.get('use_cases', [])
    }
    
    # Engine-specific guidance
    if engine_id == 'ktunes_classic':
        guidance['length_guidance'] = "Recommended: 40+ hours (2400+ minutes) for optimal category balance"
    
    return guidance

def filter_engines(collection_size: str = None, 
                  playlist_length: str = None, 
                  focus: str = None) -> List[Dict]:
    """Filter engines based on user criteria."""
    engines = get_all_engines_enhanced()
    filtered = []
    
    for engine in engines:
        include = True
        
        if collection_size and engine.get('collection_category') != 'any':
            if engine.get('collection_category') != collection_size:
                include = False
        
        if playlist_length and engine.get('length_category') != 'any':
            if engine.get('length_category') != playlist_length:
                include = False
        
        if focus and engine.get('focus_tags'):
            if focus not in engine.get('focus_tags', []):
                include = False
        
        if include:
            filtered.append(engine)
    
    return filtered

# Initialize metadata on import
load_engine_metadata()
