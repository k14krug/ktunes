# Active Context: "Resolve Unmatched Tracks" UI Implemented & Spotify Matching Enhancements

## 1. Current Work Focus

- **Newly Implemented:** A UI and backend process for reviewing and resolving `Track` records with `category='Unmatched'`. This feature is now available under "Spotify Tools".
- **Ongoing:** Phase C (Enhance Artist/Song Name Normalization) for the Spotify Matching Enhancements project continues, with `normalize_text` in `services/spotify_service.py` being a key component. The new "Resolve Unmatched Tracks" UI leverages `normalize_text` and `thefuzz` for similarity scoring.

## 2. Recent Changes

- **Implemented "Resolve Unmatched Tracks" Feature:**
    - Added `thefuzz` and `python-Levenshtein` to `requirements.txt` and installed them.
    - Created a new route `GET /resolve/unmatched_tracks` in `blueprints/resolve/routes.py`.
        - This route fetches `Track` records with `category='Unmatched'`.
        - It uses `normalize_text` (from `services.spotify_service`) and `thefuzz.token_set_ratio` to calculate similarity scores against other library tracks.
    - Created a new HTML template `blueprints/resolve/templates/resolve_unmatched.html` to display unmatched tracks, potential matches, and action forms.
    - Implemented POST routes in `blueprints/resolve/routes.py` for handling user actions:
        - `POST /resolve/unmatched/link_existing`: Links an unmatched track to an existing library track, updates `SpotifyURI`, `PlayedTrack` records, and deletes the original 'Unmatched' `Track`.
        - `POST /resolve/unmatched/confirm_new`: Confirms an unmatched track as new, updates its `Track.category`, and updates the associated `SpotifyURI.status`.
        - `POST /resolve/unmatched/ignore`: Changes the category of an 'Unmatched' track to 'IgnoredUnmatched'.
    - Added a navigation link to "Resolve Unmatched Tracks" in `templates/base.html` under the "Spotify Tools" dropdown.
- **Phase C - Advanced String Cleaning (Ongoing):**
    - `normalize_text(text_input)` function in `services/spotify_service.py` is in use.
    - Applied `normalize_text` to comparisons in `create_spotify_playlist` and `fetch_and_update_recent_tracks`.
- **Completed Phase B (Previously):**
    - Developed UI and backend for users to resolve mismatches and not-found tracks.

## 3. Next Steps

1.  **User Review and Testing:**
    - Test the new "Resolve Unmatched Tracks" feature for functionality and usability.
    - Continue testing the effectiveness of `normalize_text` (Phase C) in `services/spotify_service.py` for reducing mismatches during playlist export and recent track processing.
2.  **Refinement (Optional):**
    - Consider refactoring the POST route logic for "Resolve Unmatched Tracks" from `blueprints/resolve/routes.py` into new functions within `services/resolution_service.py` for better separation of concerns.
3.  **Fuzzy Matching (Phase C Continuation):** Based on overall testing, decide if further `thefuzz` integration or other fuzzy matching strategies are needed in `services/spotify_service.py` for core matching logic (beyond the "Resolve Unmatched" UI).
4.  **Update `memory-bank/progress.md`:** Reflect the completion of the "Resolve Unmatched Tracks" feature and current progress of Phase C.
5.  **Update `.clinerules`:** Add notes about the new resolution UI, use of `thefuzz`, and any patterns observed.

## 4. Active Decisions and Considerations

- **"Resolve Unmatched" Logic:** The current implementation for POST actions is directly in the routes. This is functional but could be moved to a service layer.
- **"Ignore" Behavior:** Ignoring an unmatched track currently changes its category to 'IgnoredUnmatched'. This prevents it from appearing in the "Resolve Unmatched" list but keeps the record.
- **Normalization Strategy (Phase C):** The `normalize_text` function is central. Its effectiveness will guide further decisions on fuzzy matching for primary Spotify matching.
- **Impacted Files for "Resolve Unmatched" feature:**
    - `requirements.txt`
    - `blueprints/resolve/routes.py`
    - `blueprints/resolve/templates/resolve_unmatched.html`
    - `templates/base.html`
- **Iterative Refinement:** Memory Bank and `.clinerules` are being updated.
