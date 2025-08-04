# Project Progress: kTunes

## 1. What Works (Inferred from File Structure and Recent Changes)

Based on the project's file and directory names, and recent updates, the following functionalities are implemented:

-   **User Management:**
    -   Registration (`templates/register.html`, `blueprints/auth/routes.py`)
    -   Login/Logout (`templates/login.html`, `blueprints/auth/routes.py`)
-   **Core Music Features:**
    -   Displaying tracks (`templates/tracks.html`, `models.py`)
    -   Managing playlists (`templates/playlists.html`, `templates/playlist.html`, `blueprints/main/routes.py` or a dedicated playlist blueprint)
    -   Viewing played tracks (`templates/played_tracks.html`)
    -   Editing track information (`templates/edit_track.html`)
-   **Spotify Integration:**
    -   Connecting to Spotify (`spotify_app.py`, `services/spotify_service.py`)
    -   Fetching recent Spotify tracks (via listening history: `templates/spotify_listening_history.html`)
    -   Listing Spotify playlists (`spotify_list_playlists.py`)
    -   **Exporting playlists to Spotify (Updated Logic - Phase A Complete & Phase C Normalization Applied):**
        -   Correctly handles mismatches by NOT creating/updating `SpotifyURI` with `status='matched'` for the local track if the Spotify result is a mismatch (Phase A).
        -   Still adds the Spotify-found track (even if a mismatch) to the actual Spotify playlist.
        -   Logs mismatches to `mismatch.json`, now including normalized string versions for diagnostics (Phase C).
        -   Uses `normalize_text()` for improved song/artist name comparison (Phase C).
    -   Logging tracks not found to `not_in_spotify.json` during export.
    -   **Mismatch/Not-Found Resolution UI & Process (Phase B Complete):**
        -   New blueprint `blueprints/resolve/` created.
        -   Routes for viewing mismatches (`/resolve/mismatches`) and not-found tracks (`/resolve/not_found`).
        -   Backend logic and POST routes for user actions.
        -   Service functions in `services/resolution_service.py`.
        -   HTML templates (`resolve_mismatches.html`, `resolve_not_found.html`).
        -   Navigation links added to `templates/base.html`.
    -   **"Resolve Unmatched Tracks" UI & Process (NEWLY ADDED):**
        -   New route `GET /resolve/unmatched_tracks` in `blueprints/resolve/routes.py`.
        -   Fetches `Track` records with `category='Unmatched'`.
        -   Uses `normalize_text` and `thefuzz` for similarity scoring against other library tracks.
        -   New template `blueprints/resolve/templates/resolve_unmatched.html` for display and actions.
        -   POST routes in `blueprints/resolve/routes.py` for:
            -   Linking unmatched to existing (updates `SpotifyURI`, `PlayedTrack`, deletes original 'Unmatched' `Track`).
            -   Confirming as new (updates `Track.category`, `SpotifyURI.status`).
            -   Ignoring (updates `Track.category` to 'IgnoredUnmatched').
        -   Navigation link added to `templates/base.html`.
        -   Dependencies `thefuzz` and `python-Levenshtein` added to `requirements.txt`.
    -   **Handle Tracks Not Found on Spotify Export (UPDATED - Now Conditional):**
        -   `services/spotify_service.py` (`create_spotify_playlist`): Still updates/creates `SpotifyURI` status to `'not_found_in_spotify'` if a track is not found on Spotify during export.
        -   `services/playlist_generator_service.py` (`PlaylistGenerator.__init__`):
            -   Now accepts a `target_platform` argument (defaulting to `'local'`).
            -   Filters out tracks with `SpotifyURI.status == 'not_found_in_spotify'` *only if* `target_platform` is `'spotify'`.
        -   `services/task_service.py` (`run_export_default_playlist`): Calls `generate_default_playlist` with `target_platform='spotify'`.
        -   `blueprints/main/routes.py` (`index`, `generate_playlist`): Calls/instantiates `PlaylistGenerator` with `target_platform='local'`.
        -   The route `GET /resolve/not_found_in_spotify_export` and its template remain to display all tracks ever marked as `'not_found_in_spotify'`.
        -   Navigation link "Not Found During Export" in `templates/base.html` remains.
    -   **Recent Track Fetching (Phase C Normalization Applied):**
        -   Uses `normalize_text()` for improved song/artist name comparison when matching recent Spotify plays to local library tracks in `fetch_and_update_recent_tracks` (`services/spotify_service.py`).
-   **Genre Management:**
    -   Assigning genres to tracks (`blueprints/genres/templates/assign_genres.html`)
    -   Viewing genres and tracks by genre (`blueprints/genres/templates/genres.html`, `blueprints/genres/templates/tracks_by_genre.html`)
    -   Managing genre definitions (`blueprints/genres/templates/manage_genres.html`)
-   **iTunes Integration:**
    -   Code for integrating with iTunes exists (`itunes_integrator_win.py`, `services/itunes_integrator_wsl.py`, `services/itunes_service.py`)
-   **Application Structure:**
    -   Flask Blueprints for modular organization (`blueprints/`)
    -   Database models (`models.py`)
    -   Service layer for business logic (`services/`)
    -   Scheduled tasks (`tasks/scheduled_tasks.py`, `blueprints/scheduler/`)
-   **Basic UI:**
    -   Base template for consistent layout (`templates/base.html`)
    -   Dashboard (`templates/dashboard.html`)
    -   Settings page (`templates/settings.html`)

## 2. What's Left to Build / Refine

This section outlines planned work and areas for improvement.

**Current Major Project: Spotify Matching Enhancements (Three Phases)**

*   **Phase A: Correct Mismatch Handling During Playlist Export (Completed)**
*   **Phase B: Develop Mismatch/Not-Found Resolution UI & Process (Completed)**
*   **Phase C: Enhance Artist/Song Name Normalization (In Progress)**
    *   **Objective:** Improve matching accuracy through advanced string cleaning and potentially fuzzy matching in core Spotify services.
    *   **Current Progress:**
        -   Implemented `normalize_text()` function in `services/spotify_service.py`.
        -   Applied `normalize_text()` to comparisons in `create_spotify_playlist` and `fetch_and_update_recent_tracks`.
        -   Enhanced `mismatch.json` logging.
    *   **Next Steps:** User testing of normalization effectiveness in `services/spotify_service.py`. Consider if `thefuzz` or other fuzzy matching is needed *directly within* `create_spotify_playlist` and `fetch_and_update_recent_tracks` for the primary matching logic (beyond its current use in the "Resolve Unmatched" UI).
    *   **Impacted Files:** `services/spotify_service.py`.

**Newly Added Feature: "Resolve Unmatched Tracks" UI**
*   **Status: Implemented.**
*   **Next Steps:** User testing and feedback. Consider refactoring POST action logic into `services/resolution_service.py`.

**Newly Added Feature: "Handle Tracks Not Found on Spotify Export"**
*   **Status: Updated - Conditional Filtering Implemented.**
*   **Next Steps:** User testing and feedback to ensure:
    *   Playlists for Spotify (e.g., via scheduler) exclude `'not_found_in_spotify'` tracks.
    *   Playlists for local use (e.g., via UI) include `'not_found_in_spotify'` tracks.
    *   Marking of tracks in `services/spotify_service.py` remains correct.
    *   The review UI at `/resolve/not_found_in_spotify_export` correctly lists all marked tracks.

**General Areas for Future Refinement:**

-   **Comprehensive Testing:** Unit tests, integration tests for all features, including "Resolve Unmatched Tracks" and Phase C normalization.
-   **Refactor Resolution Logic:** Move POST action handlers for "Resolve Unmatched Tracks" from routes to `services/resolution_service.py`.
-   **Detailed iTunes Integration:** Ensuring full functionality and robustness of iTunes features.
-   **Advanced Playlist Features:** Smart playlist generation, collaborative playlists, etc.
-   **User Experience (UX) Enhancements:** Improving usability, design, and responsiveness.
-   **Error Handling and Logging:** Robust error management and comprehensive logging.
-   **Security Hardening:** Ensuring the application is secure against common web vulnerabilities.
-   **Deployment Strategy:** Defining and implementing a deployment process.
-   **Documentation:** In-code comments, API documentation, user guides.

## 3. Current Status

-   **"Handle Tracks Not Found on Spotify Export" Feature: Updated with conditional filtering.** Awaiting user testing.
-   **"Resolve Unmatched Tracks" UI & Process: Implemented.** Awaiting user testing.
-   **Spotify Matching Enhancements - Phase A Complete.**
-   **Spotify Matching Enhancements - Phase B Complete.**
-   **Spotify Matching Enhancements - Phase C In Progress:**
    -   Initial implementation of `normalize_text` in `services/spotify_service.py` is complete and applied.
    -   Awaiting user review and testing of its effectiveness in core matching.
-   **Memory Bank Updated:** `activeContext.md` and `progress.md` reflect recent changes.

## 4. Known Issues

-   **Suboptimal Name Normalization (Being Addressed in Phase C):** `normalize_text` implemented. Effectiveness in core services pending user testing. `thefuzz` is now used in the "Resolve Unmatched" UI for suggestions.

*(This document will be updated as each phase of the Spotify Matching Enhancements project is completed and as other work progresses.)*
