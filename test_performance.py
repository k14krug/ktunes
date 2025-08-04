#!/usr/bin/env python3
"""
Quick test script to benchmark fetch_and_update_recent_tracks performance
"""
import sys
import os
import time

# Add the project root to the Python path
sys.path.insert(0, '/home/kkrug/projects/ktunes')

def test_fetch_performance():
    """Test the performance of the optimized fetch function"""
    print("Starting performance test...")
    
    # Import here to ensure Flask app context is available
    from app import create_app
    from services.spotify_service import fetch_and_update_recent_tracks
    
    app = create_app()
    
    with app.app_context():
        start_time = time.time()
        
        try:
            result, error = fetch_and_update_recent_tracks(limit=50)
            end_time = time.time()
            
            print(f"\nPerformance Test Results:")
            print(f"Total execution time: {end_time - start_time:.2f} seconds")
            print(f"Result: {'Success' if error is None else 'Error'}")
            
            if error:
                print(f"Error details: {error}")
            else:
                print(f"Tracks processed: {len(result) if result else 0}")
                
        except Exception as e:
            end_time = time.time()
            print(f"\nPerformance Test Failed:")
            print(f"Total execution time: {end_time - start_time:.2f} seconds")
            print(f"Exception: {str(e)}")

if __name__ == "__main__":
    test_fetch_performance()
