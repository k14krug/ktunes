"""Add performance indexes for listening history

Revision ID: add_performance_indexes
Revises: 3cf71d7301bb
Create Date: 2025-01-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_performance_indexes'
down_revision = '3cf71d7301bb'
branch_labels = None
depends_on = None


def upgrade():
    """Add indexes to optimize listening history queries"""
    
    # Index for played_tracks chronological queries (most important)
    op.create_index(
        'idx_played_tracks_source_played_at', 
        'played_tracks', 
        ['source', 'played_at'],
        postgresql_using='btree'
    )
    
    # Index for played_tracks source filtering
    op.create_index(
        'idx_played_tracks_source', 
        'played_tracks', 
        ['source'],
        postgresql_using='btree'
    )
    
    # Index for playlist queries by name and date
    op.create_index(
        'idx_playlists_name_date', 
        'playlists', 
        ['playlist_name', 'playlist_date'],
        postgresql_using='btree'
    )
    
    # Index for playlist track position ordering
    op.create_index(
        'idx_playlists_name_date_position', 
        'playlists', 
        ['playlist_name', 'playlist_date', 'track_position'],
        postgresql_using='btree'
    )
    
    # Composite index for playlist track lookups
    op.create_index(
        'idx_playlists_artist_song', 
        'playlists', 
        ['artist', 'song'],
        postgresql_using='btree'
    )


def downgrade():
    """Remove performance indexes"""
    
    op.drop_index('idx_played_tracks_source_played_at', table_name='played_tracks')
    op.drop_index('idx_played_tracks_source', table_name='played_tracks')
    op.drop_index('idx_playlists_name_date', table_name='playlists')
    op.drop_index('idx_playlists_name_date_position', table_name='playlists')
    op.drop_index('idx_playlists_artist_song', table_name='playlists')