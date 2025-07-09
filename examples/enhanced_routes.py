# Enhanced routes with documentation integration
# blueprints/playlists/routes.py

from flask import render_template, redirect, url_for, abort, jsonify
from flask_login import login_required, current_user
import markdown
import os
from . import bp
from services.engine_registry import get_engine, get_all_engines, get_engine_info

@bp.route('/engines')
@login_required 
def select_engine():
    """Enhanced engine selection with detailed information."""
    engines = []
    
    for engine_summary in get_all_engines():
        engine_info = get_engine_info(engine_summary['id'])
        engine_class = get_engine(engine_summary['id'])
        
        # Build enhanced engine data
        engine_data = {
            'id': engine_summary['id'],
            'name': engine_summary['name'],
            'description': _get_engine_description(engine_summary['id']),
            'features': _get_engine_features(engine_summary['id']),
            'use_cases': _get_engine_use_cases(engine_summary['id']),
            'stats': _get_engine_stats(engine_summary['id']),
            'documentation_url': f"/playlists/engines/{engine_summary['id']}/docs",
            'has_config_form': engine_info['has_config_form'] if engine_info else False
        }
        engines.append(engine_data)
    
    return render_template('playlists/select_engine.html', engines=engines)

@bp.route('/engines/<string:engine_id>/docs')
@login_required
def engine_documentation(engine_id):
    """Serve full documentation for an engine."""
    engine = get_engine(engine_id)
    if not engine:
        abort(404)
    
    # Load markdown documentation
    docs_path = os.path.join('docs', 'engines', f'{engine_id.replace("_", "-")}-engine.md')
    
    if os.path.exists(docs_path):
        with open(docs_path, 'r') as f:
            content = f.read()
        
        # Convert markdown to HTML
        html_content = markdown.markdown(content, extensions=['codehilite', 'tables'])
        
        return render_template('playlists/engine_docs.html', 
                             engine_name=engine.ENGINE_NAME,
                             documentation=html_content)
    else:
        return render_template('playlists/engine_docs.html',
                             engine_name=engine.ENGINE_NAME,
                             documentation="<p>Documentation not available.</p>")

@bp.route('/api/engines/<string:engine_id>/docs')
@login_required
def api_engine_docs(engine_id):
    """API endpoint for loading engine documentation via AJAX."""
    engine = get_engine(engine_id)
    if not engine:
        return jsonify({'error': 'Engine not found'}), 404
    
    # Load and parse documentation
    docs_path = os.path.join('docs', 'engines', f'{engine_id.replace("_", "-")}-engine.md')
    
    if os.path.exists(docs_path):
        with open(docs_path, 'r') as f:
            content = f.read()
        
        # Extract key sections for modal display
        sections = _parse_engine_docs(content)
        
        return jsonify({
            'overview': sections.get('overview', ''),
            'algorithm': sections.get('algorithm', ''),
            'configuration': sections.get('configuration', ''),
            'use_cases': sections.get('use_cases', '')
        })
    
    return jsonify({'error': 'Documentation not found'}), 404

def _get_engine_description(engine_id):
    """Extract description from engine documentation."""
    if engine_id == 'ktunes_classic':
        return """Time-weighted, category-balanced playlist generation with sophisticated 
                 artist repeat management. Perfect for large collections and discovery."""
    return "Custom playlist generation engine."

def _get_engine_features(engine_id):
    """Get key features for engine."""
    if engine_id == 'ktunes_classic':
        return [
            "6-tier category system with automatic aging",
            "Smart artist repeat prevention", 
            "Category exhaustion handling",
            "Memory-optimized for large collections",
            "Spotify integration ready"
        ]
    return []

def _get_engine_use_cases(engine_id):
    """Get use cases for engine."""
    if engine_id == 'ktunes_classic':
        return [
            "Large Collections (10K+ tracks)",
            "Long Playlists (40+ hours)", 
            "Music Discovery",
            "Personal Radio Style"
        ]
    return []

def _get_engine_stats(engine_id):
    """Get performance stats for engine."""
    if engine_id == 'ktunes_classic':
        return {
            'typical_length': '600 songs / 40 hours',
            'collection_size': '10K+ tracks',
            'generation_time': '< 30 seconds'
        }
    return None

def _parse_engine_docs(markdown_content):
    """Parse markdown documentation into sections."""
    sections = {}
    current_section = None
    current_content = []
    
    for line in markdown_content.split('\n'):
        if line.startswith('## '):
            if current_section:
                sections[current_section] = '\n'.join(current_content)
            current_section = line[3:].lower().replace(' ', '_')
            current_content = []
        else:
            current_content.append(line)
    
    if current_section:
        sections[current_section] = '\n'.join(current_content)
    
    return sections

@bp.route('/create/<string:engine_id>', methods=['GET', 'POST'])
@login_required
def create_playlist(engine_id):
    """Enhanced playlist creation with engine info."""
    engine_class = get_engine(engine_id)
    if not engine_class:
        abort(404)

    # Get engine information for display
    engine_info = get_engine_info(engine_id)
    
    form = engine_class.get_configuration_form()()

    if form.validate_on_submit():
        # ... existing playlist creation logic ...
        pass
    
    return render_template('playlists/create_playlist.html', 
                         form=form, 
                         engine_name=engine_class.ENGINE_NAME,
                         engine_info=engine_info,
                         engine_id=engine_id)
