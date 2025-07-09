"""Create spotify_resolution_view

Revision ID: 3cf71d7301bb
Revises: f6dc90af0767
Create Date: 2025-07-08 09:42:33.386553

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3cf71d7301bb'
down_revision = 'f6dc90af0767'
branch_labels = None
depends_on = None


def upgrade():
    # Create the spotify_resolution_view
    op.execute("""
        CREATE VIEW spotify_resolution_view AS
        SELECT 
            t.id as track_id,
            t.song as local_song,
            t.artist as local_artist,
            t.album as local_album,
            su.uri as spotify_uri,
            su.status as match_status,
            su.created_at as match_date,
            
            -- Get Spotify track name and artist from played_tracks that match this URI
            pt.song as spotify_song,
            pt.artist as spotify_artist,
            
            -- Generate the "searched_for" and "found" strings like JSON
            (t.song || ' by ' || t.artist) as searched_for,
            (COALESCE(pt.song, 'Unknown') || ' by ' || COALESCE(pt.artist, 'Unknown')) as found,
            
            -- Derive the Spotify URL from URI (extract track ID after last colon)
            ('https://open.spotify.com/track/' || SUBSTR(su.uri, LENGTH(su.uri) - 21)) as spotify_url,
            
            -- Match quality indicators
            CASE 
                WHEN su.status = 'matched' THEN 'Perfect Match'
                WHEN su.status = 'mismatch_accepted' THEN 'Accepted Mismatch' 
                WHEN su.status = 'manual_match' THEN 'Manual Override'
                WHEN su.status = 'unmatched' THEN 'Needs Resolution'
                WHEN su.status = 'not_found_in_spotify' THEN 'Not on Spotify'
                ELSE su.status 
            END as resolution_category,
            
            -- Additional useful fields
            t.category as track_category,
            t.last_play_dt as last_played,
            su.id as spotify_uri_id

        FROM tracks t
        JOIN spotify_uris su ON t.id = su.track_id
        LEFT JOIN played_tracks pt ON pt.spotify_id = SUBSTR(su.uri, LENGTH(su.uri) - 21)
            AND pt.source = 'spotify'
            AND pt.id = (
                -- Get the most recent played_tracks entry for this spotify_id
                SELECT MAX(id) FROM played_tracks pt2 
                WHERE pt2.spotify_id = SUBSTR(su.uri, LENGTH(su.uri) - 21)
                AND pt2.source = 'spotify'
            )
        WHERE su.status IN ('mismatch_accepted', 'manual_match', 'unmatched', 'not_found_in_spotify')
        ORDER BY su.created_at DESC
    """)


def downgrade():
    # Drop the view
    op.execute("DROP VIEW IF EXISTS spotify_resolution_view")
