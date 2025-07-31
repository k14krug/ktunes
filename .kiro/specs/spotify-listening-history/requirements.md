# Requirements Document

## Introduction

This feature will provide users with a dedicated screen to view their recent Spotify listening history, with enhanced context showing which songs came from their KRUG FM 96.2 playlist and the track position within that playlist. The feature leverages existing scheduled tasks that already track Spotify listening data and updates play counts in the tracks table.

## Requirements

### Requirement 1

**User Story:** As a user, I want to view my recent Spotify listening history, so that I can see what songs I've been listening to lately.

#### Acceptance Criteria

1. WHEN the user navigates to the listening history screen THEN the system SHALL display a chronological list of recently played tracks from Spotify
2. WHEN displaying recent tracks THEN the system SHALL show track name, artist, album, and timestamp of when it was played
3. WHEN no recent listening data is available THEN the system SHALL display an appropriate message indicating no recent activity

### Requirement 2

**User Story:** As a user, I want to see which of my recently played songs came from my KRUG FM 96.2 playlist, so that I can understand my listening patterns and playlist effectiveness.

#### Acceptance Criteria

1. WHEN displaying a recently played track THEN the system SHALL indicate if the track was from the most recent KRUG FM 96.2 playlist
2. WHEN a track is from the KRUG FM 96.2 playlist THEN the system SHALL display a visual indicator or badge showing "From KRUG FM 96.2"
3. WHEN a track is not from the KRUG FM 96.2 playlist THEN the system SHALL clearly indicate it was played from another source

### Requirement 3

**User Story:** As a user, I want to see the track position of songs that came from my KRUG FM 96.2 playlist, so that I can understand which parts of my playlist I'm engaging with most.

#### Acceptance Criteria

1. WHEN a recently played track is from the KRUG FM 96.2 playlist THEN the system SHALL display the track's position number within that playlist
2. WHEN displaying track position THEN the system SHALL show it in a clear format like "Track #15" or "Position 15"
3. WHEN a track appears multiple times in the playlist THEN the system SHALL attempt to determine the correct position based on surrounding tracks played
4. WHEN the system can determine the position of a repeated track THEN the system SHALL display the determined position number
5. WHEN the system cannot determine the position of a repeated track THEN the system SHALL display "Position unknown" or similar indicator

### Requirement 4

**User Story:** As a user, I want the listening history to be easily accessible from the main navigation, so that I can quickly check my recent activity.

#### Acceptance Criteria

1. WHEN the user is on any page of the application THEN the system SHALL provide a navigation link to the listening history screen under the "Spotify Tools" dropdown menu
2. WHEN the user clicks the listening history navigation link THEN the system SHALL load the listening history page within 3 seconds
3. WHEN on the listening history page THEN the system SHALL highlight the current page in the navigation

### Requirement 5

**User Story:** As a user, I want to see additional context about my listening history, so that I can better understand my music consumption patterns.

#### Acceptance Criteria

1. WHEN displaying the listening history THEN the system SHALL show the total number of tracks played in the current time period
2. WHEN a track has been played multiple times THEN the system SHALL indicate the play count for that track
3. WHEN displaying timestamps THEN the system SHALL use a user-friendly format showing relative time (e.g., "2 hours ago", "Yesterday")

### Requirement 6

**User Story:** As a user, I want the listening history to load efficiently, so that I can quickly access my recent activity without delays.

#### Acceptance Criteria

1. WHEN the listening history page loads THEN the system SHALL display the most recent 50 tracks by default
2. WHEN there are more than 50 recent tracks THEN the system SHALL provide pagination or load-more functionality
3. WHEN loading listening history data THEN the system SHALL complete the operation within 2 seconds under normal conditions