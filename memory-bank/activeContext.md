# Active Context: "Resolve Unmatched Tracks" UI Implemented & Spotify Matching Enhancements

## 1. Current Work Focus

- **Completed (Current Task):** Modified the "Handle Tracks Not Found on Spotify Export" feature to be conditional. Tracks with `SpotifyURI.status = 'not_found_in_spotify'` are now *only* excluded from playlist generation if the `target_platform` is `'spotify'`. For other targets (e.g., `'local'`, the default for UI generation), these tracks are included.
- **Previously Implemented:** The initial "Handle Tracks Not Found on Spotify Export" feature.
- **Previously Implemented:** A UI and backend process for reviewing and resolving `Track` records with `category='Unmatched'`.
- **Ongoing:** Phase C (Enhance Artist/Song Name Normalization) for the Spotify Matching Enhancements project continues.

## 2. Recent Changes

- **Made "Handle Tracks Not Found on Spotify Export" Filtering Conditional (Current Task):**
    - Modified `services/playlist_generator_service.py`:
        - `PlaylistGenerator.__init__` now accepts a `target_platform` argument (defaults to `'local'`).
        - The filtering of tracks with `SpotifyURI.status == 'not_found_in_spotify'` is now conditional based on `target_platform == 'spotify'`.
        - `generate_default_playlist` function now accepts and passes `target_platform` to `PlaylistGenerator`.
    - Modified `services/task_service.py`:
        - The call to `generate_default_playlist` in `run_export_default_playlist` now passes `target_platform='spotify'`.
    - Modified `blueprints/main/routes.py`:
        - Calls to instantiate `PlaylistGenerator` in `index` and `generate_playlist` routes now pass `target_platform='local'`.

- **Previously Implemented "Handle Tracks Not Found on Spotify Export" Feature (Initial Version):**
    - Modified `services/spotify_service.py` (`create_spotify_playlist` function):
        - When a track is not found on Spotify during export, its associated `SpotifyURI` record (or a new one if not existing) has its `status` updated to `'not_found_in_spotify'`.
        - `spotify_track_id` is set to `None`, and `spotify_track_name`/`spotify_artist_name` are updated to "Not Found During Export".
    - Modified `services/playlist_generator_service.py` (`PlaylistGenerator.__init__` method - initial unconditional filter).
    - Created `GET /resolve/not_found_in_spotify_export` route and `resolve_not_found_export.html` template.
    - Added navigation link "Not Found During Export" to `templates/base.html`.

- **Implemented "Resolve Unmatched Tracks" Feature (Older Task):**
    - Added `thefuzz` and `python-Levenshtein` to `requirements.txt`.
    - Created `GET /resolve/unmatched_tracks` route and `resolve_unmatched.html` template.
    - Implemented POST routes for linking, confirming new, or ignoring unmatched tracks.
    - Added navigation link.

- **Phase C - Advanced String Cleaning (Ongoing):**
    - `normalize_text(text_input)` function in `services/spotify_service.py` is in use.
    - Applied `normalize_text` to comparisons in `create_spotify_playlist` and `fetch_and_update_recent_tracks`.

- **Completed Phase B (Previously):**
    - Developed UI and backend for users to resolve mismatches and not-found tracks from JSON logs.

## 3. Next Steps

1.  **User Review and Testing:**
    - **Test the conditional "Handle Tracks Not Found on Spotify Export" feature:**
        - Verify that playlists generated by the scheduled task (target: Spotify) *exclude* tracks with `SpotifyURI.status = 'not_found_in_spotify'`.
        - Verify that playlists generated from the UI (target: local) *include* tracks with `SpotifyURI.status = 'not_found_in_spotify'`.
        - Confirm the `services/spotify_service.py` logic for marking tracks as `'not_found_in_spotify'` during export still functions correctly.
        - Check the UI page (`/resolve/not_found_in_spotify_export`) to ensure it correctly lists these tracks (its source data is unaffected by this change).
    - Test the "Resolve Unmatched Tracks" feature for functionality and usability.
    - Continue testing the effectiveness of `normalize_text` (Phase C) in `services/spotify_service.py`.
2.  **Refinement (Optional):**
    - Consider refactoring the POST route logic for "Resolve Unmatched Tracks" from `blueprints/resolve/routes.py` into `services/resolution_service.py`.
3.  **Fuzzy Matching (Phase C Continuation):** Based on overall testing, decide if further `thefuzz` integration is needed in core Spotify matching logic.
4.  **Update `memory-bank/progress.md`:** Reflect the completion of the conditional filtering for the "Handle Tracks Not Found on Spotify Export" feature.
5.  **Update `.clinerules`:** Add notes about the new conditional logic and the `target_platform` concept.

## 4. Active Decisions and Considerations

- **`target_platform` for Playlist Generation:** Introduced `'spotify'` and `'local'` to control filtering behavior. Scheduled tasks use `'spotify'`, UI uses `'local'`.
- **`SpotifyURI.status` for Export Failures:** Still using `'not_found_in_spotify'` for marking. This remains valuable for the `/resolve/not_found_in_spotify_export` UI.
- **UI for "Not Found During Export":** Remains a read-only list. Its purpose is to show all tracks ever marked as not found during any Spotify export.
- **"Resolve Unmatched" Logic:** POST actions are directly in routes; could be moved to a service.
- **"Ignore Unmatched" Behavior:** Changes category to 'IgnoredUnmatched'.
- **Normalization Strategy (Phase C):** `normalize_text` is central.

- **Impacted Files for Conditional "Handle Tracks Not Found on Spotify Export" (Current Task):**
    - `services/playlist_generator_service.py`
    - `services/task_service.py`
    - `blueprints/main/routes.py`

- **Impacted Files for Original "Handle Tracks Not Found on Spotify Export" feature:**
    - `services/spotify_service.py`
    - `services/playlist_generator_service.py` (original unconditional filter)
    - `blueprints/resolve/routes.py`
    - `blueprints/resolve/templates/resolve_not_found_export.html`
    - `templates/base.html`

- **Impacted Files for "Resolve Unmatched Tracks" feature (Older Task):**
    - `requirements.txt`
    - `blueprints/resolve/routes.py`
    - `blueprints/resolve/templates/resolve_unmatched.html`
    - `templates/base.html`

- **Iterative Refinement:** Memory Bank and `.clinerules` are being updated.
