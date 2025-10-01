-- Playlist version overview for KRUG FM 96.2
SELECT
    version_id,
    active_from,
    active_until,
    track_count,
    strftime('%Y-%m-%d %H:%M:%S', created_at, 'localtime') AS created_local
FROM playlist_versions
WHERE playlist_name = 'KRUG FM 96.2'
ORDER BY active_from DESC;

-- Detailed track listing for a specific version.
-- Replace :target_version with the version_id you want to inspect before running.
SELECT
    pvt.version_id,
    pv.active_from,
    pv.active_until,
    pvt.track_position,
    pvt.artist,
    pvt.song,
    pvt.category,
    pvt.play_cnt
FROM playlist_version_tracks AS pvt
JOIN playlist_versions AS pv ON pv.version_id = pvt.version_id
WHERE pv.playlist_name = 'KRUG FM 96.2'
  AND pvt.version_id = :target_version
ORDER BY pvt.track_position;

-- If you want to preview the most recent version automatically, uncomment the query below.
-- It joins the latest active_from version without editing the SQL each time.
--
--WITH latest AS (
--    SELECT version_id
--    FROM playlist_versions
--    WHERE playlist_name = 'KRUG FM 96.2'
--    ORDER BY active_from DESC
--    LIMIT 1
--)
--SELECT
--    pvt.version_id,
--    pv.active_from,
--    pvt.track_position,
--    pvt.artist,
--    pvt.song,
--    pvt.category,
--    pvt.play_cnt
--FROM playlist_version_tracks AS pvt
--JOIN playlist_versions AS pv ON pv.version_id = pvt.version_id
--WHERE pvt.version_id = (SELECT version_id FROM latest)
--ORDER BY pvt.track_position;
