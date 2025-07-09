# Gemini Project Brief: kTunes

This document provides context for the Gemini agent working on the kTunes project.

## Core Purpose

kTunes is a Flask-based web application for managing a personal music library and generating intelligent playlists. It integrates with local music files (via iTunes XML) and the Spotify API.

## Key Technologies

*   **Backend:** Python, Flask
*   **Database:** SQLAlchemy with a SQLite database (`kTunes.sqlite`).
*   **Frontend:** Jinja2 templates, Bootstrap CSS.
*   **Dependencies:** Flask-Login, Flask-Migrate, Flask-Session, Spotipy.

## Project Structure

The application is organized using Flask Blueprints:

*   `main`: Core application routes (homepage, track lists, playlist viewing).
*   `auth`: User authentication (login, logout, registration).
*   `spotify`: Handles Spotify API integration and callbacks.
*   `playlists`: Manages the creation and configuration of playlists using different engines.
*   `resolve`: UI for resolving mismatches and other data issues.
*   `services`: Contains the core business logic, including playlist generation engines and API service clients.
*   `models.py`: Defines the SQLAlchemy database models.
*   `templates/`: Contains the Jinja2 HTML templates.

## Playlist Generation Architecture

A key feature of this application is its flexible, multi-engine playlist generation system.

*   **`BasePlaylistEngine` (`services/base_playlist_engine.py`):** An abstract base class that defines the common interface for all playlist generation engines.
*   **`engine_registry.py` (`services/engine_registry.py`):** A registry that dynamically discovers and provides access to all available playlist engines. This is designed to prevent circular import issues.
*   **Engines:** Concrete implementations of the `BasePlaylistEngine`.
    *   **`PlaylistGenerator` (`services/playlist_generator_service.py`):** The original, sophisticated engine (ID: `ktunes_classic`) that uses categories, play counts, and artist separation rules.
*   **Workflow:**
    1.  The user navigates to `/playlists/new`.
    2.  The UI displays a list of all engines retrieved from the `engine_registry`.
    3.  The user selects an engine, which directs them to `/playlists/create/<engine_id>`.
    4.  This route loads the appropriate configuration form (`get_configuration_form()`) for the selected engine.
    5.  Upon submission, the engine is instantiated with the user's configuration, and the `generate()` method is called.

## Development Branch

Major new features should be developed on a separate feature branch to protect the stability of the `main` branch. The current refactoring for the multi-engine architecture is being done on the `feature/multi-engine-playlist` branch.

## Current Development Plan: Multi-Engine Architecture

The work on the `feature/multi-engine-playlist` branch is focused on refactoring the core playlist generation logic to be more modular and extensible.

**Key Goals & Features:**

1.  **Abstract the Engine:** Decouple the playlist generation logic from the main application by creating a `BasePlaylistEngine` abstract class. This will define a standard interface for all future engines.
2.  **Engine Registry:** Implement a dynamic `engine_registry` to allow the application to discover and use any number of playlist engines without requiring changes to the core application logic.
3.  **Database Support:**
    *   Add an `engine_id` to the `Playlist` model to track which engine created a given playlist.
    *   Create a `PlaylistConfiguration` model to allow users to save and load named configurations for different engines.
4.  **Flexible UI:**
    *   Create a new `/playlists/new` route where users can select which engine they want to use.
    *   Dynamically render the correct configuration form based on the selected engine.
5.  **Refactor Existing Logic:** Convert the original `PlaylistGenerator` into the first official engine (`ktunes_classic`) that conforms to the new `BasePlaylistEngine` interface.

**End Goal:** The successful completion of this plan will result in a system where new playlist generation algorithms (e.g., "Simple Artist Shuffle", "Genre-Based Radio") can be added to the application simply by creating a new engine class, without needing to modify the surrounding application structure.