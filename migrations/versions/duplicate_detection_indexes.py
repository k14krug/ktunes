"""Add duplicate detection performance indexes

Revision ID: duplicate_detection_indexes
Revises: add_performance_indexes
Create Date: 2025-01-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'duplicate_detection_indexes'
down_revision = 'add_performance_indexes'
branch_labels = None
depends_on = None


def upgrade():
    """Add indexes to optimize duplicate detection queries"""
    
    # Index for tracks by song name (for duplicate detection)
    op.create_index(
        'idx_tracks_song_lower', 
        'tracks', 
        [sa.text('LOWER(song)')],
        postgresql_using='btree'
    )
    
    # Index for tracks by artist name (for duplicate detection)
    op.create_index(
        'idx_tracks_artist_lower', 
        'tracks', 
        [sa.text('LOWER(artist)')],
        postgresql_using='btree'
    )
    
    # Composite index for song and artist together (most important for duplicates)
    op.create_index(
        'idx_tracks_song_artist_lower', 
        'tracks', 
        [sa.text('LOWER(song)'), sa.text('LOWER(artist)')],
        postgresql_using='btree'
    )
    
    # Index for play count (for sorting and canonical version selection)
    op.create_index(
        'idx_tracks_play_cnt', 
        'tracks', 
        ['play_cnt'],
        postgresql_using='btree'
    )
    
    # Index for last played date (for sorting)
    op.create_index(
        'idx_tracks_last_play_dt', 
        'tracks', 
        ['last_play_dt'],
        postgresql_using='btree'
    )
    
    # Index for date added (for sorting)
    op.create_index(
        'idx_tracks_date_added', 
        'tracks', 
        ['date_added'],
        postgresql_using='btree'
    )


def downgrade():
    """Remove duplicate detection performance indexes"""
    
    op.drop_index('idx_tracks_song_lower', table_name='tracks')
    op.drop_index('idx_tracks_artist_lower', table_name='tracks')
    op.drop_index('idx_tracks_song_artist_lower', table_name='tracks')
    op.drop_index('idx_tracks_play_cnt', table_name='tracks')
    op.drop_index('idx_tracks_last_play_dt', table_name='tracks')
    op.drop_index('idx_tracks_date_added', table_name='tracks')