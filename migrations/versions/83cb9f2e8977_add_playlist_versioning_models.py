"""Add playlist versioning models

Revision ID: 83cb9f2e8977
Revises: add_performance_indexes
Create Date: 2025-07-30 20:09:13.620296

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '83cb9f2e8977'
down_revision = 'add_performance_indexes'
branch_labels = None
depends_on = None


def upgrade():
    # Create playlist_versions table
    op.create_table('playlist_versions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('version_id', sa.String(), nullable=False),
        sa.Column('playlist_name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('active_from', sa.DateTime(), nullable=False),
        sa.Column('active_until', sa.DateTime(), nullable=True),
        sa.Column('track_count', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version_id')
    )
    
    # Create playlist_version_tracks table
    op.create_table('playlist_version_tracks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('version_id', sa.String(), nullable=False),
        sa.Column('track_position', sa.Integer(), nullable=False),
        sa.Column('artist', sa.String(), nullable=False),
        sa.Column('song', sa.String(), nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('play_cnt', sa.Integer(), nullable=False),
        sa.Column('artist_common_name', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['version_id'], ['playlist_versions.version_id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for efficient queries
    op.create_index('idx_playlist_versions_temporal', 'playlist_versions', ['playlist_name', 'active_from', 'active_until'])
    op.create_index('idx_playlist_versions_cleanup', 'playlist_versions', ['created_at'])
    op.create_index('idx_playlist_versions_name_active', 'playlist_versions', ['playlist_name', 'active_from'])
    op.create_index('idx_playlist_version_tracks_lookup', 'playlist_version_tracks', ['version_id', 'track_position'])
    op.create_index('idx_playlist_version_tracks_search', 'playlist_version_tracks', ['version_id', 'artist', 'song'])


def downgrade():
    # Drop indexes
    op.drop_index('idx_playlist_version_tracks_search', table_name='playlist_version_tracks')
    op.drop_index('idx_playlist_version_tracks_lookup', table_name='playlist_version_tracks')
    op.drop_index('idx_playlist_versions_name_active', table_name='playlist_versions')
    op.drop_index('idx_playlist_versions_cleanup', table_name='playlist_versions')
    op.drop_index('idx_playlist_versions_temporal', table_name='playlist_versions')
    
    # Drop tables
    op.drop_table('playlist_version_tracks')
    op.drop_table('playlist_versions')
