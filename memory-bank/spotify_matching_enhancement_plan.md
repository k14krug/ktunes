# Spotify Matching Enhancements: Detailed Plan for Phases B & C

This document outlines the detailed plans for Phase B and Phase C of the Spotify Matching Enhancements project for kTunes. Phase A (Correct Mismatch Handling During Playlist Export) has been completed.

## Phase B: Develop Mismatch/Not-Found Resolution UI & Process (Pending)

*   **Objective:** Create a new section/screen in the kTunes app where the user can review entries from `mismatch.json` and `not_in_spotify.json` and take corrective actions.
*   **New Components:**
    1.  **Flask Routes (likely in `blueprints/spotify/routes.py` or a new dedicated blueprint e.g., `blueprints/resolve/`):**
        *   `GET /resolve/mismatches`: Displays items from `mismatch.json`.
        *   `GET /resolve/not_found`: Displays items from `not_in_spotify.json`.
        *   `POST /resolve/mismatch/link_track`: Handles "Link to this Spotify Track" action for a mismatch.
            *   Parameters: `local_track_id`, `spotify_uri_of_mismatch`, `mismatch_log_identifier`.
        *   `POST /resolve/mismatch/manual_link`: Handles "Search Spotify Again" or manual URI input for a mismatch.
            *   Parameters: `local_track_id`, `manual_spotify_uri`, `mismatch_log_identifier`.
        *   `POST /resolve/mismatch/mark_no_match`: Handles "Mark as 'No Match on Spotify'" for a mismatch.
            *   Parameters: `local_track_id`, `mismatch_log_identifier`.
        *   `POST /resolve/mismatch/ignore`: Handles "Ignore/Dismiss" for a mismatch.
            *   Parameters: `mismatch_log_identifier`.
        *   `POST /resolve/not_found/manual_link`: Handles manual URI input for a not-found track.
            *   Parameters: `local_track_id`, `manual_spotify_uri`, `not_found_log_identifier`.
        *   `POST /resolve/not_found/confirm_no_match`: Handles "Confirm 'Not on Spotify'" for a not-found track.
            *   Parameters: `local_track_id`, `not_found_log_identifier`.
        *   `POST /resolve/not_found/ignore`: Handles "Ignore/Dismiss" for a not-found track.
            *   Parameters: `not_found_log_identifier`.
        *   (Consider a route for "Edit Local Track Details" if it needs special handling from this UI, or just link to the existing edit page with `track_id`).
    2.  **HTML Templates (e.g., in `templates/spotify/resolution/` or `templates/resolve/`):**
        *   `resolve_mismatches.html`:
            *   Table display: "Local Track (Song - Artist)", "Spotify Found (Song - Artist - Link to Spotify)", "Logged Date".
            *   Action buttons/forms for each entry.
        *   `resolve_not_found.html`:
            *   Table display: "Local Track (Song - Artist - ID)", "Logged Date".
            *   Action buttons/forms for each entry.
        *   Potentially a shared modal/form for manual Spotify search and URI input if this functionality is complex.
    3.  **Service Functions (in `services/spotify_service.py` or a new `services/resolution_service.py`):**
        *   `load_mismatches(filename='mismatch.json')`: Reads, parses, and perhaps assigns unique identifiers to `mismatch.json` entries for easier processing.
        *   `load_not_found(filename='not_in_spotify.json')`: Similar to `load_mismatches` for `not_in_spotify.json`.
        *   `resolve_link_track_to_spotify_uri(local_track_id, spotify_uri, status='matched')`: Creates/updates `SpotifyURI`. Removes entry from the relevant log file.
        *   `resolve_update_track_status(local_track_id, new_status_or_flag)`: e.g., to mark as 'confirmed_not_on_spotify' (this might involve a new status in `SpotifyURI` or a boolean flag on the `Track` model). Removes entry from the relevant log file.
        *   `resolve_remove_from_log(log_identifier, filename)`: A generic function to remove an entry from a JSON log file based on a unique identifier (e.g., index or a hash of the entry).
        *   Functions to support editing local track details if specific pre/post actions are needed from this UI.
*   **Functionality Details & Workflow:**
    *   **Mismatch Resolution Screen (`resolve_mismatches.html`):**
        *   For each entry from `mismatch.json`:
            *   **Display:** "Searched For (Local Track: [Song] - [Artist])" and "Found (Spotify Track: [Song] - [Artist] - [Link to actual Spotify page])".
            *   **Actions:**
                *   **"Link to this Spotify Track":**
                    1.  Calls `resolve_link_track_to_spotify_uri` with the `local_track_id` and the `spotify_uri` of the *mismatched track that was found*.
                    2.  Sets `SpotifyURI.status` to `'matched'`.
                    3.  Removes the entry from `mismatch.json`.
                *   **"Search Spotify Again / Enter URI Manually":**
                    1.  UI provides a way to input a Spotify URI or trigger a new search (latter is more complex).
                    2.  If URI provided: Calls `resolve_link_track_to_spotify_uri` with `local_track_id` and the *manually provided Spotify URI*.
                    3.  Sets `SpotifyURI.status` to `'manual_match'` or `'matched'`.
                    4.  Removes the entry from `mismatch.json`.
                *   **"Mark as 'No Match on Spotify'":**
                    1.  Calls `resolve_update_track_status` for the `local_track_id`. This might set a specific status like `'confirmed_no_spotify'` in `SpotifyURI` or a flag on the `Track` model.
                    2.  Optionally, move the entry from `mismatch.json` to `not_in_spotify.json` or a new `confirmed_not_on_spotify.json`.
                    3.  Removes the entry from `mismatch.json`.
                *   **"Edit Local Track Details":** Links to the existing edit track page for the `local_track_id`. User corrects details, then can re-attempt export or use other resolution options.
                *   **"Ignore/Dismiss":** Removes the entry from `mismatch.json`. No database changes.
    *   **Not-Found Resolution Screen (`resolve_not_found.html`):**
        *   For each entry from `not_in_spotify.json`:
            *   **Display:** "Local Track: [Song] - [Artist]".
            *   **Actions:**
                *   **"Search Spotify Manually / Enter URI":**
                    1.  UI for manual Spotify URI input.
                    2.  If URI provided: Calls `resolve_link_track_to_spotify_uri` with `local_track_id` and the *manually provided Spotify URI*.
                    3.  Sets `SpotifyURI.status` to `'manual_match'` or `'matched'`.
                    4.  Removes the entry from `not_in_spotify.json`.
                *   **"Confirm 'Not on Spotify'":**
                    1.  Calls `resolve_update_track_status` for `local_track_id`. Sets status like `'confirmed_no_spotify'`.
                    2.  Optionally, move to a `confirmed_not_on_spotify.json` or simply remove from `not_in_spotify.json` if the DB status is sufficient.
                *   **"Edit Local Track Details":** Links to existing edit track page.
                *   **"Ignore/Dismiss":** Removes entry from `not_in_spotify.json`.
*   **Considerations for Log Files:**
    *   When processing actions, ensure the log files (`mismatch.json`, `not_in_spotify.json`) are read, modified (entry removed), and then re-written atomically to avoid data loss if multiple users/processes access this (though less likely for a typical Flask app, good practice).
    *   Assigning temporary unique IDs to log entries upon loading them can simplify targeting specific entries for removal.

## Phase C: Enhance Artist/Song Name Normalization (Pending)

*   **Objective:** Improve the accuracy of song/artist matching when searching Spotify by making the comparison more flexible to common variations.
*   **Impacted Area:** Primarily the search logic within `create_spotify_playlist` in `services/spotify_service.py`. Also consider applying to the secondary song/artist match in `fetch_and_update_recent_tracks`.
*   **Potential Approaches (to be implemented sequentially or chosen based on effectiveness):**
    1.  **Advanced String Cleaning Function:**
        *   Create a reusable helper function `normalize_text(text_input)` in `services/spotify_service.py` or a utility module.
        *   **Operations within `normalize_text`:**
            *   Convert to lowercase: `text_input.lower()`.
            *   Remove leading/trailing whitespace: `text_input.strip()`.
            *   Remove articles (e.g., "the", "a", "an") as whole words at the beginning of strings: `re.sub(r'^\b(the|a|an)\b\s+', '', text, flags=re.IGNORECASE)`.
            *   Normalize "feat.", "ft.", "featuring" to a standard form (e.g., "feat"): `re.sub(r'\b(featuring|ft)\b', 'feat', text, flags=re.IGNORECASE)`.
            *   Remove all characters that are not alphanumeric or whitespace: `re.sub(r'[^\w\s]', '', text)`. This is aggressive; might need refinement to keep essential characters like '&'.
            *   Alternatively, specifically remove common punctuation: `text.translate(str.maketrans('', '', string.punctuation))`.
            *   Normalize ampersands: `text.replace('&', 'and')`.
            *   Collapse multiple spaces to one: `re.sub(r'\s+', ' ', text).strip()`.
        *   Apply this `normalize_text` function to both local track names/artists and Spotify track names/artists before comparison in `create_spotify_playlist`.
            ```python
            # Example in create_spotify_playlist
            local_song_norm = normalize_text(track.song)
            local_artist_norm = normalize_text(track.artist)
            spotify_song_norm = normalize_text(spotify_track['name'])
            spotify_artist_norm = normalize_text(', '.join(a['name'] for a in spotify_track['artists']))

            is_mismatch = local_song_norm != spotify_song_norm or local_artist_norm != spotify_artist_norm
            ```
    2.  **Fuzzy Matching (if advanced cleaning is insufficient):**
        *   **Library:** Integrate `thefuzz` (e.g., `pip install thefuzz python-Levenshtein`).
        *   **Comparison:** Replace direct string equality with a similarity score.
            ```python
            from kardeş import fuzz

            # Inside create_spotify_playlist, after normalization
            song_similarity = fuzz.ratio(local_song_norm, spotify_song_norm)
            artist_similarity = fuzz.ratio(local_artist_norm, spotify_artist_norm)
            # Or token_set_ratio for more flexibility with word order/subset
            # song_similarity = fuzz.token_set_ratio(local_song_norm, spotify_song_norm)

            MIN_CONFIDENCE_THRESHOLD = 88 # Example, needs tuning
            POSSIBLE_MATCH_THRESHOLD = 75 # Example, for logging different kinds of mismatches

            if song_similarity >= MIN_CONFIDENCE_THRESHOLD and artist_similarity >= MIN_CONFIDENCE_THRESHOLD:
                is_mismatch = False
            elif song_similarity >= POSSIBLE_MATCH_THRESHOLD and artist_similarity >= POSSIBLE_MATCH_THRESHOLD:
                # Log as a "possible mismatch" - still a mismatch for DB purposes, but good for review
                is_mismatch = True
                # Add similarity scores to mismatch_details for better review
            else:
                # Treat as a more significant mismatch or even "not found" if scores are very low
                is_mismatch = True
            ```
        *   **Threshold Tuning:** The `MIN_CONFIDENCE_THRESHOLD` and `POSSIBLE_MATCH_THRESHOLD` will require experimentation to find optimal values that balance reducing false positives (incorrect matches) and false negatives (missing actual matches).
        *   **Mismatch Definition:** If using fuzzy matching, the definition of what gets logged to `mismatch.json` might change. Tracks below `MIN_CONFIDENCE_THRESHOLD` but above `POSSIBLE_MATCH_THRESHOLD` could be logged as "low confidence mismatches". Tracks below `POSSIBLE_MATCH_THRESHOLD` might be treated as "not found" by the fuzzy logic.
*   **Testing:** Thoroughly test with various real-world examples of song/artist name variations after implementing either approach.
