from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_paginate import Pagination, get_page_parameter
from .forms import GenreForm, AssignGenreForm
from models import db, Genre, Track
from . import genres_bp
import openai
from services.openai_service import OpenAIService
from sqlalchemy import func, distinct, desc
import os



openai_service = OpenAIService()

# Initialize OpenAI API
openai.api_key = os.getenv("OPENAI_API_KEY")

@genres_bp.route('/genres', methods=['GET', 'POST'])
def manage_genres():
    """
    A clone of the tracks route with additional filtering by genres and bulk actions
    for managing genres.
    """
    page = request.args.get(get_page_parameter(), type=int, default=1)
    per_page = 50  # Number of tracks per page

    # Get filter and sort parameters
    song_filter = request.args.get('song', '')
    artist_filter = request.args.get('artist', '')
    category_filter = request.args.get('category', '')
    genre_filter = request.args.get('genre', '')  # New filter for genres
    sort_column = request.args.get('sort', 'artist')
    sort_direction = request.args.get('direction', 'asc')

    # Build the query
    query = Track.query

    # Apply filters
    if song_filter:
        query = query.filter(Track.song.ilike(f'%{song_filter}%'))
    if artist_filter:
        query = query.filter(Track.artist.ilike(f'%{artist_filter}%'))
    if category_filter:
        query = query.filter(Track.category.ilike(f'%{category_filter}%'))
    if genre_filter:
        query = query.join(Track.genres).filter(Genre.name.ilike(f'%{genre_filter}%'))

    # Apply sorting
    if sort_direction == 'desc':
        query = query.order_by(desc(getattr(Track, sort_column)))
    else:
        query = query.order_by(getattr(Track, sort_column))

    # Get total number of tracks (for pagination)
    total = query.count()

    # Apply pagination
    tracks = query.paginate(page=page, per_page=per_page, error_out=False)

    # Create pagination object
    pagination = Pagination(page=page, total=total, per_page=per_page, css_framework='bootstrap4')

    return render_template(
        'manage_genres.html',
        tracks=tracks.items,
        pagination=pagination,
        sort_column=sort_column,
        sort_direction=sort_direction,
    )

@genres_bp.route('/genres/delete/<int:genre_id>', methods=['POST'])
def delete_genre(genre_id):
    """Delete a genre."""
    genre = Genre.query.get_or_404(genre_id)
    db.session.delete(genre)
    db.session.commit()
    flash(f"Genre '{genre.name}' deleted successfully!", 'success')
    return redirect(url_for('genres.manage_genres'))

@genres_bp.route('/assign', methods=['POST'])
def assign_genres_bulk():
    """Assign specified genres to filtered tracks."""
    data = request.get_json()
    filters = data.get('filters', {})
    genres = data.get('genres', [])

    if not genres:
        return jsonify({"error": "No genres provided to assign"}), 400

    # Build the query based on filters
    query = Track.query
    if filters.get('song'):
        query = query.filter(Track.song.ilike(f"%{filters['song']}%"))
    if filters.get('artist'):
        query = query.filter(Track.artist.ilike(f"%{filters['artist']}%"))
    if filters.get('category'):
        query = query.filter(Track.category.ilike(f"%{filters['category']}%"))
    if filters.get('genre'):
        query = query.join(Track.genres).filter(Genre.name.ilike(f"%{filters['genre']}%"))

    # Get the filtered tracks
    tracks = query.all()

    # Get or create the genres
    genre_objects = []
    for genre_name in genres:
        genre = Genre.query.filter_by(name=genre_name).first()
        if not genre:
            genre = Genre(name=genre_name)
            db.session.add(genre)
        genre_objects.append(genre)

    # Assign genres to tracks
    for track in tracks:
        track.genres.extend(genre_objects)
    db.session.commit()

    return jsonify({"message": "Genres assigned successfully"})

@genres_bp.route('/remove', methods=['POST'])
def remove_genres_bulk():
    """Remove specified genres from filtered tracks."""
    data = request.get_json()
    filters = data.get('filters', {})
    genres = data.get('genres', [])

    if not genres:
        return jsonify({"error": "No genres provided to remove"}), 400

    # Build the query based on filters
    query = Track.query
    if filters.get('song'):
        query = query.filter(Track.song.ilike(f"%{filters['song']}%"))
    if filters.get('artist'):
        query = query.filter(Track.artist.ilike(f"%{filters['artist']}%"))
    if filters.get('category'):
        query = query.filter(Track.category.ilike(f"%{filters['category']}%"))
    if filters.get('genre'):
        query = query.join(Track.genres).filter(Genre.name.ilike(f"%{filters['genre']}%"))

    # Get the filtered tracks
    tracks = query.all()

    # Get the genres to remove
    genres_to_remove = Genre.query.filter(Genre.name.in_(genres)).all()

    # Remove genres from tracks
    for track in tracks:
        for genre in genres_to_remove:
            if genre in track.genres:
                track.genres.remove(genre)
    db.session.commit()

    return jsonify({"message": "Genres removed successfully"})


@genres_bp.route('/<int:genre_id>/tracks')
def tracks_by_genre(genre_id):
    print("genres_bp.route('/<int:genre_id>/tracks')")
    """View all tracks associated with a specific genre."""
    genre = Genre.query.get_or_404(genre_id)
    tracks = genre.tracks  # Access the related tracks
    return render_template('tracks_by_genre.html', genre=genre, tracks=tracks)

@genres_bp.route('/suggest', methods=['POST'])
def suggest_genres():
    """Fetch genre recommendations for filtered tracks using OpenAI."""
    data = request.get_json()
    filters = data.get('filters', {})

    # Build the query based on filters
    query = Track.query
    if filters.get('song'):
        query = query.filter(Track.song.ilike(f"%{filters['song']}%"))
    if filters.get('artist'):
        query = query.filter(Track.artist.ilike(f"%{filters['artist']}%"))
    if filters.get('category'):
        query = query.filter(Track.category.ilike(f"%{filters['category']}%"))
    if filters.get('genre'):
        query = query.join(Track.genres).filter(Genre.name.ilike(f"%{filters['genre']}%"))

    # Get the filtered tracks
    tracks = query.all()

    # Prepare the track data for OpenAI
    track_info = [
        {"song": track.song, "artist": track.artist, "album": track.album or "Unknown"}
        for track in tracks
    ]

    try:
        # Use OpenAIService to get recommendations
        suggestions = openai_service.suggest_genres(track_info)
        return jsonify({"suggestions": suggestions})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

