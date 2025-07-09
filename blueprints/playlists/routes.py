# blueprints/playlists/routes.py
from flask import render_template, redirect, url_for, abort, jsonify
from flask_login import login_required, current_user
import os
try:
    import markdown
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False
from . import bp
from services.engine_registry import get_engine, get_all_engines, get_all_engines_enhanced

@bp.route('/new')
@login_required
def new_playlist():
    engines = get_all_engines_enhanced()
    return render_template('playlists/new_playlist.html', engines=engines)

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
        
        # Convert markdown to HTML if available
        if HAS_MARKDOWN:
            html_content = markdown.markdown(content, extensions=['codehilite', 'tables'])
            return render_template('playlists/engine_docs.html', 
                                 engine_name=engine.ENGINE_NAME,
                                 documentation=html_content,
                                 is_html=True)
        else:
            return render_template('playlists/engine_docs.html', 
                                 engine_name=engine.ENGINE_NAME,
                                 documentation=content,
                                 is_html=False)
    else:
        return render_template('playlists/engine_docs.html',
                             engine_name=engine.ENGINE_NAME,
                             documentation="Documentation not available.",
                             is_html=False)

@bp.route('/api/engines/<string:engine_id>/docs')
@login_required
def api_engine_docs(engine_id):
    """API endpoint for loading engine documentation via AJAX."""
    engine = get_engine(engine_id)
    if not engine:
        return jsonify({'error': 'Engine not found'}), 404
    
    # Load documentation
    docs_path = os.path.join('docs', 'engines', f'{engine_id.replace("_", "-")}-engine.md')
    
    if os.path.exists(docs_path):
        with open(docs_path, 'r') as f:
            content = f.read()
        
        return jsonify({
            'success': True,
            'content': content,
            'has_markdown': HAS_MARKDOWN
        })
    
    return jsonify({'error': 'Documentation not found'}), 404

@bp.route('/create/<string:engine_id>', methods=['GET', 'POST'])
@login_required
def create_playlist(engine_id):
    # For kTunes Classic, redirect to the classic generator
    if engine_id == 'ktunes_classic':
        return redirect(url_for('main.classic_generator'))
    
    engine_class = get_engine(engine_id)
    if not engine_class:
        abort(404)

    form = engine_class.get_configuration_form()()

    if form.validate_on_submit():
        config = {
            'playlist_name': form.playlist_name.data,
            'playlist_length': form.playlist_length.data,
            'minimum_recent_add_playcount': form.minimum_recent_add_playcount.data,
            'categories': [
                {'name': 'A', 'percentage': 50, 'artist_repeat': 5},
                {'name': 'B', 'percentage': 25, 'artist_repeat': 5},
                {'name': 'C', 'percentage': 25, 'artist_repeat': 5},
            ]
        }
        
        engine_instance = engine_class(user=current_user, config=config)
        
        playlist, stats = engine_instance.generate()
        
        engine_instance.save_to_database(form.playlist_name.data)

        return redirect(url_for('main.index'))
    
    return render_template('playlists/create_playlist.html', form=form, engine_name=engine_class.ENGINE_NAME)

@bp.route('/manage_genres', methods=['GET', 'POST'])
@login_required
def manage_genres():
    # Your logic for managing genres goes here
    return render_template('playlists/manage_genres.html')
