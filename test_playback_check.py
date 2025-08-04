#!/usr/bin/env python3
"""
Test script to verify the KRUG FM 96.2 playback check functionality.
Run this while playing music from the KRUG FM 96.2 playlist to test.
"""

import os
import sys
from flask import Flask

# Add the project directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.spotify_service import check_if_krug_playlist_is_playing, get_spotify_client

def create_test_app():
    """Create a minimal Flask app for testing"""
    app = Flask(__name__)
    
    # Load configuration (you may need to adjust these paths)
    app.config['SPOTIPY_CLIENT_ID'] = os.getenv('SPOTIPY_CLIENT_ID')
    app.config['SPOTIPY_CLIENT_SECRET'] = os.getenv('SPOTIPY_CLIENT_SECRET')
    app.config['SPOTIPY_REDIRECT_URI'] = os.getenv('SPOTIPY_REDIRECT_URI', 'http://localhost:5010/callback')
    
    return app

def test_playback_check():
    """Test the playback checking functionality"""
    app = create_test_app()
    
    with app.app_context():
        print("Testing KRUG FM 96.2 playback detection...")
        print("=" * 50)
        
        # Test Spotify client first
        print("1. Testing Spotify client connection...")
        sp = get_spotify_client(allow_interactive_auth=True)
        if not sp:
            print("❌ Failed to get Spotify client. Check your authentication.")
            return False
        print("✅ Spotify client connected successfully")
        
        # Test current playback check
        print("\n2. Checking current playback...")
        is_playing, current_track_info, error = check_if_krug_playlist_is_playing()
        
        if error:
            print(f"❌ Error checking playback: {error}")
            return False
        
        if is_playing and current_track_info:
            print("🎵 KRUG FM 96.2 IS CURRENTLY PLAYING!")
            print(f"   Track: {current_track_info['track_name']}")
            print(f"   Artist: {current_track_info['artist']}")
            print(f"   Playlist: {current_track_info['playlist_name']}")
            print(f"   Progress: {current_track_info['progress_ms']} / {current_track_info['duration_ms']} ms")
            
            # Calculate progress percentage
            if current_track_info['duration_ms'] > 0:
                progress_pct = (current_track_info['progress_ms'] / current_track_info['duration_ms']) * 100
                print(f"   Progress: {progress_pct:.1f}%")
            
            print("\n✅ The scheduled job would be SKIPPED to avoid interruption.")
            return True
        else:
            print("🔇 KRUG FM 96.2 is not currently playing")
            print("✅ The scheduled job would PROCEED normally.")
            return True

if __name__ == "__main__":
    print("KRUG FM 96.2 Playback Check Test")
    print("Make sure you have Spotify credentials set as environment variables:")
    print("- SPOTIPY_CLIENT_ID")
    print("- SPOTIPY_CLIENT_SECRET") 
    print("- SPOTIPY_REDIRECT_URI (optional)")
    print()
    
    success = test_playback_check()
    if success:
        print("\n🎉 Test completed successfully!")
    else:
        print("\n💥 Test failed!")
        sys.exit(1)
