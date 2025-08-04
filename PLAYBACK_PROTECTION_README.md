# KRUG FM 96.2 Playback Protection Implementation

## Summary
Added functionality to prevent the scheduled job from updating the KRUG FM 96.2 playlist while it's currently being played, avoiding song interruptions.

## Changes Made

### 1. New Function: `check_if_krug_playlist_is_playing()` in `services/spotify_service.py`
- Uses Spotify's `current_playback()` API to check if music is currently playing
- Verifies if the current playback context is the "KRUG FM 96.2" playlist
- Returns detailed information about the currently playing track if applicable
- Handles errors gracefully and logs appropriate messages

### 2. Updated `run_export_default_playlist()` in `services/task_service.py`
- Added a new optional `force_update` parameter
- Checks if KRUG FM 96.2 is currently playing before proceeding with playlist update
- Skips the update if the playlist is actively being played (unless `force_update=True`)
- Provides detailed logging about the decision process

### 3. Updated Spotify OAuth Scopes
- Added `user-read-playback-state` scope to both OAuth configurations
- This permission is required to check current playback status

### 4. New Test Endpoint: `/spotify/check_current_playback`
- Provides a way to test the playback detection via web interface
- Returns JSON with current playback status and track information

### 5. Test Script: `test_playback_check.py`
- Standalone script to test the functionality
- Can be run while music is playing to verify detection works

## How It Works

1. **Scheduled Job Flow**:
   - Scheduled job triggers → Check if KRUG FM 96.2 is playing
   - If playing: Skip update, log the reason, return success message
   - If not playing: Continue with normal playlist generation and export

2. **Detection Logic**:
   - Gets current Spotify playback state
   - Checks if music is actively playing (`is_playing: true`)
   - Verifies the context is a playlist (not album, artist, etc.)
   - Fetches playlist details and compares name to "KRUG FM 96.2"

3. **Error Handling**:
   - If playback check fails, logs warning but continues with update
   - If authentication fails, logs error and skips update
   - All errors are logged with appropriate detail levels

## Testing the Implementation

### Method 1: Using the Test Script
```bash
cd /home/kkrug/projects/ktunes
python test_playback_check.py
```

### Method 2: Using the Web Endpoint
Visit: `http://your-app-url/spotify/check_current_playback`

### Method 3: Testing the Scheduled Job
1. Start playing music from KRUG FM 96.2 playlist
2. Manually trigger the scheduled job
3. Check logs to verify it was skipped

## Expected Behavior

### When KRUG FM 96.2 is Playing:
- Log message: "KRUG FM 96.2 is currently playing 'Song Name' by 'Artist'. Skipping playlist update..."
- Job returns: `(True, "Playlist update skipped. KRUG FM 96.2 is currently playing: Song Name by Artist")`
- No playlist changes occur

### When KRUG FM 96.2 is NOT Playing:
- Log message: "KRUG FM 96.2 is not currently playing. Proceeding with playlist update."
- Job continues normally with playlist generation and export

### Force Update Option:
- Can be used via: `run_export_default_playlist(force_update=True)`
- Bypasses the playback check and updates playlist regardless

## Important Notes

1. **Scope Requirements**: Users may need to re-authenticate with Spotify to grant the new `user-read-playback-state` permission.

2. **Authentication Improvements**: The system now distinguishes between interactive (web) and background (scheduled task) authentication:
   - Background tasks use stored tokens and automatic refresh without browser interaction
   - Web requests can trigger interactive authentication if needed
   - This prevents the browser popup issues seen in scheduled tasks

3. **Timing Considerations**: The check happens at the very beginning of the job, so if someone starts playing after the check but before the update completes, there could still be a brief interruption.

4. **Performance**: The additional API call adds ~100-200ms to the job execution time.

5. **Fallback Behavior**: If the playback check fails due to API issues, the job continues normally rather than blocking updates.

## Troubleshooting

### "Spotify client not authenticated for background task" Error
- This means the stored Spotify token has expired and couldn't be refreshed
- Solution: Re-authenticate via the web interface to refresh your tokens
- The system will automatically use these refreshed tokens for future background tasks

### Browser Opens During Scheduled Tasks (Fixed)
- Previous versions would try to open a browser during background tasks
- This has been fixed by implementing separate authentication modes
- Background tasks now only use stored/refreshed tokens

### No Playback Detected When Music Is Playing
- Ensure you're playing from the exact playlist named "KRUG FM 96.2"
- Check that Spotify is reporting the correct context (playlist vs album)
- Verify the `user-read-playback-state` permission has been granted
