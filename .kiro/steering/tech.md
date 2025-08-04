# kTunes Technical Stack

## Core Technologies

### Backend
- **Python 3.x** - Primary language
- **Flask** - Web framework with blueprint architecture
- **SQLAlchemy** - ORM with Flask-SQLAlchemy integration
- **SQLite** - Database (located at `instance/kTunes.sqlite`)
- **Flask-Migrate** - Database migrations via Alembic
- **APScheduler** - Background task scheduling

### Frontend
- **Jinja2** - Template engine
- **Bootstrap 4.5.2** - CSS framework
- **jQuery** - JavaScript library
- **Font Awesome** - Icons
- **Custom Spotify-themed CSS** - Dark theme with Spotify color palette

### External APIs & Services
- **Spotify Web API** - via `spotipy` library
- **OpenAI API** - For potential AI enhancements
- **iTunes XML** - Library parsing via `libpytunes`

### Key Dependencies
- `spotipy==2.24.0` - Spotify API client
- `Flask-Login==0.6.3` - User authentication
- `Flask-Session==0.8.0` - Session management
- `python-Levenshtein==0.25.1` - Fuzzy string matching
- `thefuzz==0.22.1` - String similarity matching
- `redis==5.0.8` - Caching (optional)

## Development Commands

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env  # Edit with your API keys
```

### Database Operations
```bash
# Initialize database
flask db init

# Create migration
flask db migrate -m "Description"

# Apply migrations
flask db upgrade
```

### Running the Application
```bash
# Development server
python run.py
# or
python app.py

# Production considerations
# App runs on port 5003 by default
# Uses host="0.0.0.0" for network access
```

### Testing
```bash
# Run test suite
python -m pytest tests/

# Run specific test file
python -m pytest tests/test_spotify_service.py

# Run with coverage
python -m pytest --cov=services tests/
```

## Configuration

### Environment Variables (.env)
- `SPOTIPY_CLIENT_ID` - Spotify app client ID
- `SPOTIPY_CLIENT_SECRET` - Spotify app client secret  
- `OPENAI_API_KEY` - OpenAI API key

### Application Config (config.json)
- `itunes_dir` - Path to iTunes music folder
- `itunes_lib` - iTunes library XML filename
- `playlist_defaults` - Default playlist generation settings
- `scheduled_tasks` - Task scheduling configuration

### Kiro IDE Command Authorization
Configure trusted commands in the Kiro IDE Settings > Kiro Agent Trusted Commands:

**Standard Trusted Commands for kTunes:**
- `flask db *` - Database operations
- `python -m pytest *` - Testing commands  
- `python run.py` - Application startup
- `npm install *` - Package management
- `git *` - Version control operations
- `sqlite3 instance/kTunes.sqlite *` - Database queries

**Semicolon Command Handling:**
By default, Kiro blocks commands containing ";" even if they match trusted patterns. For kTunes development, the following semicolon commands should be explicitly allowed:

**Recommended Semicolon Exceptions:**
- `cd migrations; flask db upgrade` - Database migration workflow
- `source venv/bin/activate; python run.py` - Environment activation + run
- `git add .; git commit -m "message"` - Common git workflow
- `pip install -r requirements.txt; python run.py` - Install dependencies + run

**Security Note:** Only add semicolon commands that you fully understand and trust, as they can chain multiple operations together.

