# kTunes Project Structure

## Architecture Overview

kTunes follows a Flask blueprint architecture with clear separation of concerns. The application uses a service layer pattern for business logic and maintains a clean MVC structure.

## Directory Structure

### Core Application Files
- `app.py` - Application factory and configuration
- `run.py` - Application entry point
- `models.py` - SQLAlchemy database models
- `extensions.py` - Flask extension initialization
- `config_loader.py` - Configuration management
- `app_context_holder.py` - Global app context for APScheduler

### Blueprints (`blueprints/`)
Each blueprint follows the pattern: `__init__.py` + `routes.py`
- `auth/` - User authentication (login, register, logout)
- `main/` - Core application routes (dashboard, tracks, playlists)
- `spotify/` - Spotify integration features
- `playlists/` - Playlist management and generation
- `resolve/` - Mismatch resolution UI
- `scheduler/` - Task scheduling dashboard

### Services (`services/`)
Business logic layer following single responsibility principle:
- `base_playlist_engine.py` - Abstract base class for playlist engines
- `engine_registry.py` - Engine discovery and registration
- `playlist_generator_service.py` - Main playlist generation engine
- `spotify_service.py` - Spotify API integration
- `itunes_service.py` - iTunes XML parsing
- `cache_service.py` - Caching layer
- `resolution_service.py` - Track matching and resolution
- `playlist_versioning_service.py` - Playlist history management
- `task_service.py` - Background task management

### Templates (`templates/`)
Jinja2 templates with consistent structure:
- `base.html` - Base template with Spotify-themed styling
- Individual page templates organized by feature
- Subdirectories mirror blueprint structure

### Database & Migrations
- `instance/` - SQLite database and Flask sessions
- `migrations/` - Alembic database migrations

### Testing (`tests/`)
- Comprehensive unit tests for services
- Mock-based testing for external API integrations
- Test coverage for critical business logic

## Coding Conventions

### File Naming
- Snake_case for Python files and directories
- Blueprint modules: `__init__.py` + `routes.py`
- Service files: `{feature}_service.py`
- Test files: `test_{module_name}.py`

### Import Organization
```python
# Standard library imports
import os
from datetime import datetime

# Third-party imports
from flask import Flask, request
from sqlalchemy import Column, Integer

# Local imports
from extensions import db
from models import Track
from services.spotify_service import get_track
```

### Database Models
- Use SQLAlchemy declarative base
- Include `__tablename__` explicitly
- Add relationships with proper back_populates
- Include indexes for performance-critical queries

### Service Layer Pattern
- Services handle business logic
- Controllers (routes) handle HTTP concerns
- Models handle data persistence
- Clear separation of concerns

### Error Handling
- Use try/catch blocks for external API calls
- Log errors with appropriate context
- Return meaningful error messages to users
- Graceful degradation for non-critical features

### Configuration Management
- Environment variables for secrets (.env)
- JSON config for application settings (config.json)
- Separate development/production configurations