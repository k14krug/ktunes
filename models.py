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


class PlaylistVersion(db.Model):
    __tablename__ = 'playlist_versions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(String, nullable=False, unique=True)  # UUID for version identification
    playlist_name = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())  # When this version was created
    active_from = Column(DateTime, nullable=False)  # When this version became active
    active_until = Column(DateTime, nullable=True)  # When this version was replaced (null for current)
    track_count = Column(Integer, nullable=False)
    username = Column(String, nullable=True)
    
    # Relationship to versioned tracks
    tracks = relationship('PlaylistVersionTrack', back_populates='version', cascade='all, delete-orphan')
    
    # Indexes for efficient temporal queries
    __table_args__ = (
        db.Index('idx_playlist_versions_temporal', 'playlist_name', 'active_from', 'active_until'),
        db.Index('idx_playlist_versions_cleanup', 'created_at'),
        db.Index('idx_playlist_versions_name_active', 'playlist_name', 'active_from'),
    )


class PlaylistVersionTrack(db.Model):
    __tablename__ = 'playlist_version_tracks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(String, ForeignKey('playlist_versions.version_id'), nullable=False)
    track_position = Column(Integer, nullable=False)
    artist = Column(String, nullable=False)
    song = Column(String, nullable=False)
    category = Column(String, nullable=False)
    play_cnt = Column(Integer, nullable=False)
    artist_common_name = Column(String, nullable=True)
    
    # Relationship back to version
    version = relationship('PlaylistVersion', back_populates='tracks')
    
    # Index for efficient track lookups
    __table_args__ = (
        db.Index('idx_playlist_version_tracks_lookup', 'version_id', 'track_position'),
        db.Index('idx_playlist_version_tracks_search', 'version_id', 'artist', 'song'),
    )


class AdminAuditLog(db.Model):
    __tablename__ = 'admin_audit_logs'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    action_type = Column(String(50), nullable=False)  # 'delete_duplicate', 'bulk_delete', 'smart_delete'
    user_id = Column(Integer, ForeignKey('Users.id'), nullable=True)
    timestamp = Column(DateTime, nullable=False, default=func.now())
    details = Column(JSON, nullable=False)  # Store action details as JSON
    affected_tracks = Column(Integer, nullable=False, default=0)  # Number of tracks affected
    success = Column(db.Boolean, nullable=False, default=True)
    error_message = Column(String, nullable=True)
    ip_address = Column(String(45), nullable=True)  # Support IPv6
    user_agent = Column(String, nullable=True)
    
    # Relationship to user
    user = relationship('User', foreign_keys=[user_id])
    
    # Indexes for efficient querying
    __table_args__ = (
        db.Index('idx_audit_logs_timestamp', 'timestamp'),
        db.Index('idx_audit_logs_action_type', 'action_type'),
        db.Index('idx_audit_logs_user', 'user_id', 'timestamp'),
        db.Index('idx_audit_logs_success', 'success', 'timestamp'),
    )


class DuplicateCleanupAuditLog(db.Model):
    """Audit trail for duplicate cleanup actions with detailed tracking."""
    __tablename__ = 'duplicate_cleanup_audit_logs'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    action_id = Column(String(36), nullable=False)  # UUID for grouping related actions
    analysis_id = Column(String(36), ForeignKey('duplicate_analysis_results.analysis_id'), nullable=True)
    user_id = Column(Integer, ForeignKey('Users.id'), nullable=False)
    timestamp = Column(DateTime, nullable=False, default=func.now())
    
    # Action details
    action_type = Column(String(50), nullable=False)  # 'track_deleted', 'group_resolved', 'bulk_cleanup', 'analysis_refresh'
    operation_type = Column(String(50), nullable=False)  # 'single_delete', 'bulk_delete', 'smart_delete', 'manual_resolution'
    
    # Affected items
    affected_track_ids = Column(JSON, nullable=True)  # List of track IDs affected
    affected_group_ids = Column(JSON, nullable=True)  # List of group IDs affected
    tracks_deleted_count = Column(Integer, nullable=False, default=0)
    groups_resolved_count = Column(Integer, nullable=False, default=0)
    
    # Resolution details
    resolution_action = Column(String(50), nullable=True)  # 'duplicates_deleted', 'canonical_deleted', etc.
    cleanup_strategy = Column(String(50), nullable=True)  # 'manual_selection', 'smart_algorithm', 'bulk_operation'
    
    # Performance metrics
    processing_time_seconds = Column(db.Float, nullable=True)
    total_play_count_affected = Column(Integer, nullable=False, default=0)
    
    # Context information
    context_data = Column(JSON, nullable=True)  # Additional context (search terms, filters, etc.)
    success = Column(db.Boolean, nullable=False, default=True)
    error_message = Column(String, nullable=True)
    
    # Relationships
    analysis = relationship('DuplicateAnalysisResult', foreign_keys=[analysis_id])
    user = relationship('User', foreign_keys=[user_id])
    
    # Indexes for efficient querying
    __table_args__ = (
        db.Index('idx_cleanup_audit_timestamp', 'timestamp'),
        db.Index('idx_cleanup_audit_user', 'user_id', 'timestamp'),
        db.Index('idx_cleanup_audit_analysis', 'analysis_id', 'timestamp'),
        db.Index('idx_cleanup_audit_action', 'action_type', 'timestamp'),
        db.Index('idx_cleanup_audit_success', 'success', 'timestamp'),
    )


class DuplicateAnalysisResult(db.Model):
    __tablename__ = 'duplicate_analysis_results'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(String(36), unique=True, nullable=False)  # UUID
    user_id = Column(Integer, ForeignKey('Users.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default='running')  # running, completed, failed, cancelled
    
    # Analysis parameters
    search_term = Column(String, nullable=True)
    sort_by = Column(String(50), nullable=False, default='artist')
    min_confidence = Column(db.Float, nullable=False, default=0.0)
    
    # Analysis results summary
    total_tracks_analyzed = Column(Integer, nullable=True)
    total_groups_found = Column(Integer, nullable=True)
    total_duplicates_found = Column(Integer, nullable=True)
    average_similarity_score = Column(db.Float, nullable=True)
    processing_time_seconds = Column(db.Float, nullable=True)
    
    # Library state tracking
    library_track_count = Column(Integer, nullable=True)  # Total tracks when analysis was run
    library_last_modified = Column(DateTime, nullable=True)  # Estimated last library modification
    
    # Error information
    error_message = Column(String, nullable=True)
    error_details = Column(JSON, nullable=True)
    
    # Relationships
    groups = relationship('DuplicateAnalysisGroup', back_populates='analysis', cascade='all, delete-orphan')
    user = relationship('User', foreign_keys=[user_id])
    
    # Indexes for efficient querying
    __table_args__ = (
        db.Index('idx_duplicate_analysis_user_created', 'user_id', 'created_at'),
        db.Index('idx_duplicate_analysis_status', 'status'),
        db.Index('idx_duplicate_analysis_cleanup', 'created_at'),
        db.Index('idx_duplicate_analysis_search', 'user_id', 'search_term'),
    )


class DuplicateAnalysisGroup(db.Model):
    __tablename__ = 'duplicate_analysis_groups'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(String(36), ForeignKey('duplicate_analysis_results.analysis_id'), nullable=False)
    group_index = Column(Integer, nullable=False)  # Order within the analysis
    
    # Group metadata
    canonical_track_id = Column(Integer, nullable=False)  # ID of suggested canonical track
    duplicate_count = Column(Integer, nullable=False)
    average_similarity_score = Column(db.Float, nullable=False)
    suggested_action = Column(String(50), nullable=False)
    
    # iTunes integration
    has_itunes_matches = Column(db.Boolean, nullable=False, default=False)
    itunes_match_data = Column(JSON, nullable=True)
    
    # Status tracking
    resolved = Column(db.Boolean, nullable=False, default=False)
    resolved_at = Column(DateTime, nullable=True)
    resolution_action = Column(String(50), nullable=True)  # deleted, kept_canonical, manual_review
    
    # Relationships
    analysis = relationship('DuplicateAnalysisResult', back_populates='groups')
    tracks = relationship('DuplicateAnalysisTrack', back_populates='group', cascade='all, delete-orphan')
    
    # Indexes for efficient querying
    __table_args__ = (
        db.Index('idx_duplicate_groups_analysis', 'analysis_id', 'group_index'),
        db.Index('idx_duplicate_groups_resolved', 'resolved'),
        db.Index('idx_duplicate_groups_canonical', 'canonical_track_id'),
    )


class DuplicateAnalysisTrack(db.Model):
    __tablename__ = 'duplicate_analysis_tracks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey('duplicate_analysis_groups.id'), nullable=False)
    track_id = Column(Integer, nullable=False)  # Reference to tracks table
    
    # Track snapshot (in case original track is deleted)
    song_name = Column(String, nullable=True)
    artist_name = Column(String, nullable=True)
    album_name = Column(String, nullable=True)
    play_count = Column(Integer, nullable=True)
    last_played = Column(DateTime, nullable=True)
    date_added = Column(DateTime, nullable=True)
    
    # Analysis metadata
    similarity_score = Column(db.Float, nullable=False)
    is_canonical = Column(db.Boolean, nullable=False, default=False)
    
    # iTunes integration
    itunes_match_found = Column(db.Boolean, nullable=False, default=False)
    itunes_match_confidence = Column(db.Float, nullable=True)
    itunes_match_type = Column(String(20), nullable=True)  # exact, fuzzy, none
    
    # Status tracking
    still_exists = Column(db.Boolean, nullable=False, default=True)  # Track still exists in database
    deleted_at = Column(DateTime, nullable=True)
    
    # Relationships
    group = relationship('DuplicateAnalysisGroup', back_populates='tracks')
    
    # Indexes for efficient querying
    __table_args__ = (
        db.Index('idx_duplicate_tracks_group', 'group_id'),
        db.Index('idx_duplicate_tracks_track_id', 'track_id'),
        db.Index('idx_duplicate_tracks_canonical', 'is_canonical'),
        db.Index('idx_duplicate_tracks_exists', 'still_exists'),
    )


class UserPreferences(db.Model):
    __tablename__ = 'user_preferences'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('Users.id'), nullable=False, unique=True)
    
    # Staleness notification preferences
    staleness_threshold_hours = Column(Integer, nullable=False, default=24)
    change_threshold_percentage = Column(db.Float, nullable=False, default=10.0)
    change_threshold_count = Column(Integer, nullable=False, default=50)
    show_age_warnings = Column(db.Boolean, nullable=False, default=True)
    show_change_warnings = Column(db.Boolean, nullable=False, default=True)
    auto_suggest_refresh = Column(db.Boolean, nullable=False, default=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship('User', foreign_keys=[user_id])
    
    # Indexes for efficient querying
    __table_args__ = (
        db.Index('idx_user_preferences_user', 'user_id'),
    )


class DuplicateAnalysisExport(db.Model):
    __tablename__ = 'duplicate_analysis_exports'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    export_id = Column(String(36), unique=True, nullable=False)  # UUID
    analysis_id = Column(String(36), ForeignKey('duplicate_analysis_results.analysis_id'), nullable=False)
    user_id = Column(Integer, ForeignKey('Users.id'), nullable=False)
    
    # Export metadata
    format = Column(String(10), nullable=False)  # json, csv
    filename = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)  # Size in bytes
    created_at = Column(DateTime, nullable=False, default=func.now())
    
    # Export status
    status = Column(String(20), nullable=False, default='completed')  # completed, failed, expired
    download_count = Column(Integer, nullable=False, default=0)
    last_downloaded_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)  # For automatic cleanup
    
    # File path (for cleanup)
    file_path = Column(String(500), nullable=True)
    
    # Relationships
    analysis = relationship('DuplicateAnalysisResult', foreign_keys=[analysis_id])
    user = relationship('User', foreign_keys=[user_id])
    
    # Indexes for efficient querying
    __table_args__ = (
        db.Index('idx_duplicate_exports_user_created', 'user_id', 'created_at'),
        db.Index('idx_duplicate_exports_analysis', 'analysis_id'),
        db.Index('idx_duplicate_exports_cleanup', 'expires_at', 'status'),
    )