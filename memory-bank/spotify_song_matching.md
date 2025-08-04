# Spotify Song Matching Logic in kTunes

This document outlines the processes kTunes uses to match local library tracks with Spotify tracks, primarily when exporting playlists to Spotify and when processing recently played tracks from Spotify.

## Key Data Structures

-   **`Track` (models.py):** Represents a song in the local kTunes library.
-   **`SpotifyURI` (models.py):** Links a local `Track` to a Spotify track URI.
    -   `uri`: Stores the Spotify track URI (e.g., `spotify:track:TRACK_ID_HERE`).
    -   `status`: Indicates the nature of the link.
        -   `'matched'`: A confirmed link, either manually set or found via search.
        -   `'unmatched'`: Typically set when a new local `Track` is created based on a Spotify play for which no prior local match existed.
-   **`mismatch.json`:** A file where discrepancies are logged if Spotify returns a track with a different name/artist than what was searched for during playlist export.
-   **`not_in_spotify.json`:** A file where local tracks are logged if they cannot be found on Spotify during playlist export.

## Core Files Involved

-   `services/spotify_service.py`: Contains the primary logic for interacting with the Spotify API, including searching, matching, and updating.
-   `services/playlist_generator_service.py`: Generates the tracklist for local kTunes playlists (e.g., "krug radio").
-   `models.py`: Defines the database schema, including `Track` and `SpotifyURI`.
-   `blueprints/spotify/routes.py`: Provides web endpoints that trigger these services.

## Process 1: Exporting a Local Playlist to Spotify

This process typically occurs when a user wants to take a kTunes-generated playlist (e.g., "krug radio") and create/update it on Spotify. It's primarily handled by the `export_playlist_to_spotify` function within `services/spotify_service.py`, often triggered via a route like `/export_to_spotify/<playlist_name>` or `/export_default_playlist_to_spotify`.

**Steps for each track in the local playlist:**

1.  **Check for Existing Matched Spotify ID:**
    *   The system queries the `SpotifyURI` table for an entry linked to the local `Track` where `status='matched'`.
    *   If found, this existing Spotify URI (which contains the `spotify_id`) is used for adding the track to the Spotify playlist.

2.  **Search Spotify by Song/Artist (if no matched URI):**
    *   If no 'matched' `SpotifyURI` exists for the local track, the system constructs a search query using the local track's song title and artist name (e.g., `"Song Title artist:Artist Name"`).
    *   This query is sent to the Spotify search API.

3.  **Handle Spotify Search Results:**
    *   **If Spotify Returns a Track:**
        *   The Spotify URI of the *first track returned by the search* is taken.
        *   A new `SpotifyURI` record is created (or an existing one updated) for the local `Track`, linking it to this found Spotify URI with `status='matched'`.
        *   **Mismatch Detection & Logging:** The system compares the name and artist of the track returned by Spotify with the original local track's name and artist (case-insensitive).
            *   If they do not match, this is considered a mismatch. The details (searched for, found, Spotify URL, local track ID) are logged to `mismatch.json` via the `document_mismatches` function.
            *   *Note: Even in a mismatch, the track found by Spotify is what gets added to the Spotify playlist, and its URI is what's stored in the 'matched' `SpotifyURI` record.*
        *   The found Spotify track URI is added to the list of tracks to be included in the Spotify playlist.
    *   **If Spotify Returns No Track (Not Found):**
        *   The local track (song, artist, and local track ID) is logged to `not_in_spotify.json` via the `add_to_not_in_spotify` function. This track is not added to the Spotify playlist.

4.  **Add Tracks to Spotify Playlist:**
    *   After processing all local tracks, the collected Spotify URIs are used to add items to the target Spotify playlist. If the playlist doesn't exist, it's created. If it exists, its contents are typically replaced.

## Process 2: Processing Recently Played Tracks from Spotify

This process updates the local kTunes library based on listening history from Spotify. It's handled by the `fetch_and_update_recent_tracks` function in `services/spotify_service.py`, usually triggered via scheduled tasks or the listening history route (which renders `spotify_listening_history.html`).

**Steps for each recently played track from Spotify:**

1.  **Fetch Recent Plays:** The system retrieves a list of recently played tracks from the Spotify API. Each item includes the Spotify track name, artist, `played_at` timestamp, and the Spotify `track_id`.

2.  **Match to Local kTunes Track:** For each track from Spotify:
    *   **Primary Match Attempt (by Spotify ID):** The system queries the `SpotifyURI` table for an entry where the `uri` contains the `track_id` from the Spotify play and `status='matched'`. If found, the associated local `Track` is considered the match.
    *   **Secondary Match Attempt (by Song/Artist):** If no 'matched' `SpotifyURI` is found, the system queries the `Track` table for a record where the song and artist names match those from the Spotify play (case-insensitive).

3.  **Handle Match Result:**
    *   **If a Local `Track` is Matched (by either method):**
        *   The `last_play_dt` of the local `Track` is updated to the `played_at` timestamp from Spotify if the Spotify play is more recent.
        *   The `play_cnt` (play count) of the local `Track` is incremented.
    *   **If No Local `Track` is Matched:**
        *   A new `Track` record is created in the local kTunes database using the song name and artist from the Spotify play. This new track is typically assigned a category like 'Unmatched'.
        *   A new `SpotifyURI` record is created, linking this new local `Track` to the Spotify `track_id` (as a URI) with `status='unmatched'`. This establishes an initial link for future reference.

4.  **Log Played Track:**
    *   Regardless of whether a local match was found or a new track was created, the played event (source 'spotify', artist, song, `spotify_id`, `played_at`, category, playlist name if available) is recorded in the `PlayedTrack` table.

## Summary of Matching Priorities

*   **Exporting to Spotify:** Prefers existing 'matched' `SpotifyURI`s. Falls back to song/artist search, creating new 'matched' `SpotifyURI`s (even for mismatches, which are logged externally).
*   **Processing Recent Plays:** Prefers matching via 'matched' `SpotifyURI`s using the incoming `spotify_id`. Falls back to song/artist search. Creates new local tracks and 'unmatched' `SpotifyURI`s if no local counterpart is found.

This detailed understanding of the matching logic is crucial for any future modifications aimed at improving mismatch handling or the "not-found" process.
