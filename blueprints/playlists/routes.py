# blueprints/playlists/routes.py
from flask import render_template, redirect, url_for, abort, jsonify, request
from flask_login import login_required, current_user
from extensions import db
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
    """Manage track genres with filtering and pagination"""
    from models import Track
    from sqlalchemy import func, or_
    
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    # Get filter parameters
    category_filter = request.args.get('category', '')
    search_query = request.args.get('search', '')
    
    # Get sorting parameters
    sort_column = request.args.get('sort', 'artist')
    sort_direction = request.args.get('direction', 'asc')
    
    # Build query
    query = Track.query
    
    # Apply filters
    if category_filter:
        query = query.filter(Track.category == category_filter)
    
    if search_query:
        query = query.filter(
            or_(
                Track.song.ilike(f'%{search_query}%'),
                Track.artist.ilike(f'%{search_query}%')
            )
        )
    
    # Apply sorting
    if sort_column == 'song':
        order_by = Track.song.desc() if sort_direction == 'desc' else Track.song.asc()
    elif sort_column == 'artist':
        order_by = Track.artist.desc() if sort_direction == 'desc' else Track.artist.asc()
    elif sort_column == 'album':
        order_by = Track.album.desc() if sort_direction == 'desc' else Track.album.asc()
    elif sort_column == 'category':
        order_by = Track.category.desc() if sort_direction == 'desc' else Track.category.asc()
    elif sort_column == 'play_cnt':
        order_by = Track.play_cnt.desc() if sort_direction == 'desc' else Track.play_cnt.asc()
    elif sort_column == 'date_added':
        order_by = Track.date_added.desc() if sort_direction == 'desc' else Track.date_added.asc()
    elif sort_column == 'last_play_dt':
        order_by = Track.last_play_dt.desc() if sort_direction == 'desc' else Track.last_play_dt.asc()
    else:
        # Default sort by artist and song
        order_by = [Track.artist.asc(), Track.song.asc()]
    
    if isinstance(order_by, list):
        query = query.order_by(*order_by)
    else:
        query = query.order_by(order_by)
    
    # Paginate results
    pagination = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    tracks = pagination.items
    
    # Get available categories for filter dropdown
    categories = db.session.query(Track.category).distinct().filter(Track.category.isnot(None)).all()
    categories = [cat[0] for cat in categories if cat[0]]
    
    return render_template(
        'playlists/manage_genres.html',
        tracks=tracks,
        pagination=pagination,
        categories=categories,
        current_category=category_filter,
        current_search=search_query,
        sort_column=sort_column,
        sort_direction=sort_direction
    )
