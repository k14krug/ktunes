  # Spotify Playlist Review Flow

  ## Default playlist creation
  - `services/playlist_generator_service.py` builds playlists from the `tracks` table using the kTunes Classic engine. `generate_default_playlist` snapshots the previous playlist, rebuilds it from Track
  records, and stores the ordered result in the `playlist` table so the app knows the intended song/artist sequence.

  ## Exporting the playlist to Spotify
  - `export_playlist_to_spotify` hands the stored playlist rows to `create_spotify_playlist`. For each item, the app first reuses any saved `spotify_uri` tagged `matched` so only vetted links are replayed.
  Missing URIs trigger a Spotify search that normalizes titles/artists (`normalize_text_for_matching`) before comparing them.
  - Matching search results are saved as `SpotifyURI(status='matched')`. If the normalized names differ, the URI is recorded with status `mismatch_accepted`; the track still goes on the Spotify playlist but
  is earmarked for review. If no result is found, the track is tagged `not_found_in_spotify` with a placeholder URI and the failure is surfaced in the export response.

  ## Capturing what Spotify actually played
  - `fetch_and_update_recent_tracks` is invoked by the scheduler, the "refresh" button on `/spotify/listening_history`, and the combined export task. It keeps a two-minute "no new tracks" cache and checks the
  latest `PlayedTrack.played_at` timestamp before it does a full fetch, so routine polling does not burn through Spotify's rate limits when nothing changed.
  - When a newer play is detected, the service pulls a batch (default 50) from `fetch_recent_tracks`, parses the timestamps in Pacific time, and de-duplicates by `spotify_id` + `played_at`. Any row that is not
  already present in `played_tracks` is inserted with the source, track metadata, Spotify track ID, and a snapshot of the category/playlist name we already know.
  - After each insert, the job tries to reconcile the play with the library. It first looks for an existing `SpotifyURI` marked `matched`, `manual_match`, or `mismatch_accepted` whose URI suffix matches the
  Spotify ID. If that fails it falls back to normalized artist/title comparisons (using `normalize_text`) to find the closest `Track` record.
  - On a match we update `Track.last_play_dt` / `Track.play_cnt` and overwrite the `PlayedTrack.category` so reporting stays in sync. On a miss we create a new `Track` with category `Unmatched` plus a
  `SpotifyURI(status='unmatched')`, ensuring every ambiguous play shows up in the mismatch workflow.
  - Errors from Spotify or the database short-circuit the run and are bubbled back to the caller (route, task runner, or CLI) so the job scheduler can alert you. Successful runs also reset the "no new tracks"
  cache to capture the next listen immediately.

  ## Comparing playback to the intended playlist
  - `get_listening_history_with_playlist_context` (and its version-aware wrapper) paginates the most recent Spotify `PlayedTrack` rows, using cached playlist snapshots when possible. It pre-computes the
  current KRUG FM 96.2 playlist (or the historical version that was active at play time) and builds a normalized artist/title lookup so comparisons are deterministic.
  - Each play is evaluated against that lookup. A single normalized match marks the row as `from_krug_playlist` with high confidence. If multiple playlist slots share the same song, we call
  `determine_track_position_from_context`, which scores each candidate by walking neighbouring plays, timing gaps, and sequence continuity via `_get_surrounding_tracks`, `_analyze_position_context`, and
  `_check_sequence_patterns`.
  - The service records the chosen slot, confidence level, and the method used so the UI can explain why a correlation was made. Plays with no match (or context failures) are explicitly flagged "not in KRUG
  playlist"; correlation issues are counted so we can surface warnings in the interface.
  - When playlist versioning is turned on, `correlate_track_with_versioned_playlist` consults `PlaylistVersioningService` to pick the playlist that was active when the song played, preventing false negatives
  after a mid-day playlist refresh.

  ## Surfacing mismatches for manual cleanup
  - Because mismatched searches and not-found tracks are stored in `spotify_uris`, the `/resolve/mismatches` route pulls every `mismatch_accepted` entry from the `spotify_resolution_view` view. The
  review screen shows the local metadata versus the Spotify track, allows retagging, pasting a corrected URI, or marking a track as "no Spotify version". A similar `/resolve/not_found` view handles
  `not_found_in_spotify` cases.
  - Accepting a corrected URI updates the associated `SpotifyURI` (usually to `matched` or `manual_match`), which means the next export will use the fixed track and future playback correlation will succeed.

  ## Further reading
  - For an operator-focused walkthrough with UI screenshots and route shortcuts, see the in-app “Spotify Playlist Review Guide” available under **Spotify Tools → Playlist Review Guide** once you log into kTunes.
