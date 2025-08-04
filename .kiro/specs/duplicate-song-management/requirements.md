# Requirements Document

## Introduction

This feature provides an admin screen for detecting, analyzing, and managing duplicate songs in the music library. The system will identify songs that appear multiple times with variations in their titles or artist names (such as remaster suffixes, version numbers, or other appended text), cross-reference them with the iTunes XML catalog to understand their origin, and provide tools for administrators to review and remove unwanted duplicates.

## Requirements

### Requirement 1

**User Story:** As an administrator, I want to access duplicate management through a dedicated Admin section in the navigation, so that administrative functions are properly organized and accessible.

#### Acceptance Criteria

1. WHEN the application loads THEN the system SHALL display an "Admin" dropdown in the main navigation bar
2. WHEN I click the Admin dropdown THEN the system SHALL show "Duplicate Management" and "Scheduler Dashboard" options
3. WHEN I select "Duplicate Management" THEN the system SHALL navigate to the duplicate detection screen
4. WHEN I select "Scheduler Dashboard" THEN the system SHALL navigate to the existing scheduler dashboard (moved from main navbar)

### Requirement 2

**User Story:** As an administrator, I want to view all duplicate songs in my library, so that I can identify and manage redundant entries that clutter my music collection.

#### Acceptance Criteria

1. WHEN the admin accesses the duplicate detection screen THEN the system SHALL display all songs that have potential duplicates based on similar titles and artists
2. WHEN displaying duplicates THEN the system SHALL group similar songs together showing variations like "I Got" and "I Got - 2020 Remaster"
3. WHEN showing duplicate groups THEN the system SHALL display song metadata including title, artist, album, play count, and last played date for each variant
4. IF a song has multiple variations THEN the system SHALL highlight the differences between versions (suffixes, remasters, etc.)

### Requirement 3

**User Story:** As an administrator, I want to see which duplicate songs match entries in my iTunes XML file, so that I can understand the source of duplicates and make informed decisions about which versions to keep.

#### Acceptance Criteria

1. WHEN analyzing duplicates THEN the system SHALL cross-reference each duplicate song against the iTunes XML catalog
2. IF a duplicate song matches an iTunes entry THEN the system SHALL display an indicator showing "Found in iTunes"
3. WHEN a song matches iTunes THEN the system SHALL show the iTunes metadata alongside the database entry
4. WHEN displaying iTunes matches THEN the system SHALL highlight any differences between the iTunes version and database version

### Requirement 4

**User Story:** As an administrator, I want to delete unwanted duplicate songs, so that I can clean up my library and prevent confusion during playlist creation.

#### Acceptance Criteria

1. WHEN viewing a duplicate group THEN the system SHALL provide checkboxes or selection controls for each song variant
2. WHEN I select songs to delete THEN the system SHALL show a confirmation dialog listing exactly which songs will be removed
3. WHEN I confirm deletion THEN the system SHALL remove the selected songs from the tracks table
4. WHEN songs are deleted THEN the system SHALL display a success message and refresh the duplicate list
5. IF a song cannot be deleted due to constraints THEN the system SHALL display an appropriate error message

### Requirement 5

**User Story:** As an administrator, I want to see detailed information about potential duplicates, so that I can make informed decisions about which versions to keep or remove.

#### Acceptance Criteria

1. WHEN viewing duplicates THEN the system SHALL display play statistics for each variant (play count, last played date)
2. WHEN comparing duplicates THEN the system SHALL show creation/modification dates for each entry
3. WHEN analyzing duplicates THEN the system SHALL indicate which version appears to be the "canonical" or most complete entry
4. IF available THEN the system SHALL display audio quality information or file format details

### Requirement 6

**User Story:** As an administrator, I want to filter and search through duplicate songs, so that I can efficiently manage large numbers of duplicates.

#### Acceptance Criteria

1. WHEN the duplicate screen loads THEN the system SHALL provide search functionality to filter duplicates by artist or song name
2. WHEN searching THEN the system SHALL update the display in real-time to show only matching duplicate groups
3. WHEN viewing duplicates THEN the system SHALL provide sorting options (by artist, song name, number of duplicates, etc.)
4. WHEN managing many duplicates THEN the system SHALL provide pagination or virtual scrolling for performance

### Requirement 7

**User Story:** As an administrator, I want to perform bulk operations on duplicate songs, so that I can efficiently clean up large numbers of duplicates at once.

#### Acceptance Criteria

1. WHEN viewing multiple duplicate groups THEN the system SHALL provide "Select All" functionality for each group
2. WHEN I want to clean up systematically THEN the system SHALL provide options like "Keep iTunes version" or "Keep most played version"
3. WHEN performing bulk operations THEN the system SHALL show a progress indicator for long-running deletions
4. WHEN bulk operations complete THEN the system SHALL provide a summary of actions taken