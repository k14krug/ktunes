# Implementation Plan

- [x] 1. Add service functions to existing spotify_service.py





  - Create `get_listening_history_with_playlist_context()` function to query PlayedTrack data and correlate with Playlist data
  - Create `determine_track_position_from_context()` function to implement smart position detection for repeated tracks
  - Add helper functions for playlist correlation and data enrichment
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 3.1, 3.2, 3.4, 3.5_

- [x] 2. Create route handler for listening history page





  - Add `/listening_history` route to `blueprints/spotify/routes.py`
  - Implement pagination with default limit of 50 records
  - Add authentication requirement using `@login_required` decorator
  - Handle query parameters for pagination (page, limit)
  - _Requirements: 4.1, 4.2, 6.1, 6.2_


- [x] 3. Create listening history template




  - Create `templates/spotify_listening_history.html` template
  - Implement responsive table layout using existing Spotify theme
  - Add visual indicators for tracks from KRUG FM 96.2 playlist
  - Display track position information with confidence indicators
  - Add pagination controls for navigation
  - _Requirements: 1.2, 2.2, 2.3, 3.2, 3.4, 5.3, 6.2_

- [x] 4. Update navigation to include listening history link





  - Modify `templates/base.html` to add new menu item under "Spotify Tools" dropdown
  - Add link to listening history page with appropriate icon
  - Ensure proper navigation highlighting for active page
  - _Requirements: 4.1, 4.3_

- [x] 5. Implement position detection algorithm for repeated tracks





  - Create context analysis logic to examine surrounding PlayedTrack records
  - Implement sequence matching to find patterns that match playlist sequences
  - Add temporal proximity analysis using played_at timestamps
  - Create confidence scoring system for position determinations
  - _Requirements: 3.3, 3.4, 3.5_

- [x] 6. Add error handling and edge cases





  - Handle cases where no KRUG FM 96.2 playlist data exists
  - Implement graceful degradation when playlist correlation fails
  - Add error handling for database connection issues
  - Create user-friendly error messages using flash notifications
  - _Requirements: 1.3, 2.3_

- [x] 7. Implement data formatting and display enhancements





  - Add relative time formatting for played_at timestamps (e.g., "2 hours ago")
  - Display play count information for tracks
  - Show total number of tracks in current time period
  - Format track position display (e.g., "Track #15" or "Position unknown")
  - _Requirements: 5.1, 5.2, 5.3, 3.2, 3.5_

- [x] 8. Add performance optimizations





  - Implement database query optimization with proper indexing considerations
  - Add query result caching for playlist data
  - Optimize pagination queries to prevent performance issues
  - Ensure queries complete within 2-3 second requirements
  - _Requirements: 4.2, 6.1, 6.3_

- [x] 9. Create unit tests for service functions





  - Write tests for `get_listening_history_with_playlist_context()` with various data scenarios
  - Test `determine_track_position_from_context()` with repeated tracks and edge cases
  - Test playlist correlation logic with missing or incomplete data
  - Test pagination functionality and parameter validation
  - _Requirements: 1.1, 2.1, 3.1, 6.1_

- [ ] 10. Create integration tests for the complete feature
  - Test route handler with authentication and pagination
  - Test template rendering with various data scenarios including empty states
  - Test navigation integration and page highlighting
  - Test error handling scenarios and user feedback
  - _Requirements: 4.1, 4.2, 4.3, 1.3, 2.3_