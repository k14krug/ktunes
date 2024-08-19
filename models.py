# models.py
from flask_login import UserMixin
from sqlalchemy import Column, Integer, String, DateTime, func
from sqlalchemy.orm import synonym
from extensions import db

class CustomDateTime(db.TypeDecorator):
    impl = db.DateTime
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            return func.strftime('%Y-%m-%d %H:%M:%S', value)
        return value

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
    cat_cnt = Column(Integer, nullable=True)
    artist_cat_cnt = Column(Integer, nullable=True)
    played_sw = Column(String, nullable=True)
    artist_common_name = Column(String, nullable=True)
    # Alias for the played_sw column
    played = synonym('played_sw')

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

class User(db.Model, UserMixin):
    __tablename__ = 'Users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)

