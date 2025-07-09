# models.py
from flask_login import UserMixin
from sqlalchemy import Column, Integer, String, DateTime, func, Table, ForeignKey, JSON
from sqlalchemy.orm import synonym, relationship
from extensions import db
from datetime import datetime

class CustomDateTime(db.TypeDecorator):
    impl = db.DateTime
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            return func.strftime('%Y-%m-%d %H:%M:%S', value)
        return value

class SpotifyToken(db.Model):
    __tablename__ = 'spotify_tokens'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=False)
    expires_at = Column(Integer, nullable=False)  # Store as a Unix timestamp

track_genres = Table(
    'track_genres', db.Model.metadata,
    Column('track_id', Integer, ForeignKey('tracks.id'), primary_key=True),
    Column('genre_id', Integer, ForeignKey('genres.id'), primary_key=True)
)

class SpotifyURI(db.Model):
    __tablename__ = 'spotify_uris'
    
    id = Column(Integer, primary_key=True)
    track_id = Column(Integer, ForeignKey('tracks.id'), nullable=False)
    uri = Column(String, nullable=False)
    status = Column(String, default='matched')  # e.g., 'matched', 'unmatched', 'manual_match', 'confirmed_no_spotify'
    created_at = Column(DateTime, default=datetime.utcnow)
    
    track = relationship('Track', back_populates='spotify_uris')

class Track(db.Model):
    __tablename__ = 'tracks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    song = Column(String, nullable=True)
    artist = Column(String, nullable=True)
    album = Column(String, nullable=True)
    location = Column(String, nullable=True)
    category = Column(String, nullable=True)
    last_play_dt = Column(DateTime)
    date_added = Column(DateTime)
    play_cnt = Column(Integer, nullable=True)
    played_sw = Column(String, nullable=True)
    artist_common_name = Column(String, nullable=True)
    ktunes_last_play_dt = Column(DateTime)
    ktunes_play_cnt = Column(Integer, nullable=True)
    most_recent_playlist = Column(String, nullable=True)
    genres = relationship('Genre', secondary=track_genres, back_populates='tracks')
    spotify_uris = relationship('SpotifyURI', back_populates='track')
    # Alias for the played_sw column
    played = synonym('played_sw')
    

class Genre(db.Model):
    __tablename__ = 'genres'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    genre_type = Column(String, nullable=True)
    track_count = Column(Integer, nullable=True)
    tracks = relationship('Track', secondary=track_genres, back_populates='genres')


class Playlist(db.Model):
    __tablename__ = 'playlists'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    playlist_name = Column(String, nullable=False)
    playlist_date = Column(DateTime, nullable=False)
    track_position = Column(Integer, nullable=False)
    artist = Column(String, nullable=False)
    song = Column(String, nullable=False)
    category = Column(String, nullable=False)
    play_cnt = Column(Integer, nullable=False)
    artist_common_name = Column(String, nullable=True)
    username = Column(String, nullable=True)
    engine_id = Column(String(50), nullable=True)

class PlaylistConfiguration(db.Model):
    __tablename__ = 'playlist_configurations'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('Users.id'), nullable=False)
    name = Column(String(100), nullable=False)
    engine_id = Column(String(50), nullable=False)
    config_data = Column(JSON, nullable=False)

class User(db.Model, UserMixin):
    __tablename__ = 'Users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)


class PlayedTrack(db.Model):
    __tablename__ = 'played_tracks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, nullable=False)  # e.g. 'spotify'
    artist = Column(String, nullable=False)
    song = Column(String, nullable=False)
    spotify_id = Column(String, nullable=True)
    played_at = Column(DateTime, nullable=False)
    category = Column(String, nullable=False)
    playlist_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    __table_args__ = (
        db.UniqueConstraint('source', 'spotify_id', 'played_at', name='uq_played_track'),
    )