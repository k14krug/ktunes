# kTunes: Spotify Mismatch & Not-Found Resolution Guide

This guide explains how to use the new UI screens to resolve discrepancies found during Spotify playlist exports.

## Accessing the Resolution Tools

You can find the resolution tools under the "Spotify Tools" dropdown in the main navigation bar:

1.  **Resolve Mismatches:** Select this to view tracks where the song/artist found on Spotify differed from the local track details searched for.
2.  **Resolve Not Found:** Select this to view local tracks that could not be found on Spotify during the last export attempt.

## Resolving Mismatches (`/resolve/mismatches`)

This screen lists items logged in `mismatch.json`. Each row shows:

-   **Local Track (Searched For):** The Song, Artist, and kTunes ID of the track from your local library.
-   **Spotify Track (Found):** The Song and Artist of the track that Spotify returned (which differed from the local track). Includes a link to listen on Spotify and the Spotify URI.
-   **Logged Date:** When the mismatch was logged.
-   **Actions:** Buttons to resolve the mismatch.

**Available Actions:**

1.  **Link to This:** Click this if the track Spotify found *is actually the correct match* for your local track, despite the name/artist difference.
    *   **Result:** Updates the local track's `SpotifyURI` record to link to this specific Spotify track with `status='matched'`. Removes the entry from the mismatch log.
2.  **Manual Link:** Click this if the track Spotify found is incorrect, and you know the correct Spotify track URI or URL.
    *   A modal window will appear. Paste the correct Spotify URI (e.g., `spotify:track:XXXXX`) or the full Spotify track URL into the input field.
    *   Click "Link Manually".
    *   **Result:** Updates/creates the local track's `SpotifyURI` record to link to the manually provided URI with `status='manual_match'`. Removes the entry from the mismatch log.
3.  **No Match:** Click this if the track Spotify found is incorrect, and you believe there is *no correct match* for your local track on Spotify (or you don't want to link it).
    *   **Result:** Updates the local track's Spotify linkage status to `confirmed_no_spotify`. Removes the entry from the mismatch log.
4.  **Edit Local:** Click this to go to the standard kTunes track editing page for the local track. Use this if the local track's details (song name, artist) are incorrect, causing the mismatch. After editing, you might need to re-export the playlist or use one of the other resolution options here.
5.  **Ignore:** Click this if you want to remove this mismatch entry from the log without making any changes to your local track's Spotify linkage in the database.
    *   **Result:** Removes the entry from the mismatch log only.

## Resolving Not Found Tracks (`/resolve/not_found`)

This screen lists items logged in `not_in_spotify.json`. Each row shows:

-   **Local Track:** The Song, Artist, and kTunes ID of the track from your local library that wasn't found.
-   **Logged Date:** When the track was logged as not found.
-   **Actions:** Buttons to resolve the entry.

**Available Actions:**

1.  **Enter Spotify URI:** Click this if you have found the track on Spotify and know its URI or URL.
    *   A modal window will appear. Paste the correct Spotify URI or URL.
    *   Click "Link Manually".
    *   **Result:** Creates a `SpotifyURI` record linking the local track to the provided URI with `status='manual_match'`. Removes the entry from the not-found log.
2.  **Confirm Not on Spotify:** Click this to confirm that this local track genuinely does not exist on Spotify (or you don't want it linked).
    *   **Result:** Updates the local track's Spotify linkage status to `confirmed_no_spotify`. Removes the entry from the not-found log.
3.  **Edit Local:** Click this to go to the standard kTunes track editing page. Use this if the local track's details might be incorrect, preventing Spotify from finding it. After editing, you might need to re-export the playlist or use other resolution options.
4.  **Ignore:** Click this to remove the entry from the not-found log without making any database changes.
    *   **Result:** Removes the entry from the not-found log only.

By using these tools, you can improve the accuracy of the Spotify links stored in your kTunes database and manage tracks that cause issues during playlist exports.
