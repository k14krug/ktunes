# Kiro IDE Command Authorization for kTunes

## Overview
This document provides specific guidance for configuring Kiro IDE's trusted commands for the kTunes project. Use the Kiro IDE Settings > Kiro Agent Trusted Commands interface to configure these.

## Standard Trusted Commands

### Development & Testing
```
python run.py
python app.py
python -m pytest *
flask db *
pip install *
npm install *
npm test *
npm run *
```

### Database Operations
```
sqlite3 instance/kTunes.sqlite *
flask db init
flask db migrate *
flask db upgrade
```

### Version Control
```
git *
```

### File Operations (Safe)
```
ls *
cat *
grep *
find *
wc *
```

## Semicolon Command Exceptions

### Why Semicolons Are Blocked
Kiro normally blocks commands with ";" to prevent command chaining that could be dangerous. However, some legitimate development workflows require chaining commands.

### Important: Explicit Specification Required
**Yes, you must specify each semicolon command explicitly.** Wildcards like `git *` will NOT match `git add .; git commit -m "message"` because of the semicolon security restriction.

### Approved Semicolon Commands for kTunes

#### Database Workflow
```
cd migrations; flask db upgrade
flask db migrate -m "message"; flask db upgrade
```

#### Development Workflow  
```
source venv/bin/activate; python run.py
pip install -r requirements.txt; python run.py
```

#### Git Workflow
```
git add .; git commit -m "message"
git add .; git commit -m "message"; git push
```

#### Testing Workflow
```
python -m pytest; echo "Tests completed"
pip install -r requirements.txt; python -m pytest
```

## Managing Semicolon Commands

### Strategies to Minimize Explicit Entries

1. **Use Shell Scripts**: Instead of chaining commands with semicolons, create shell scripts:
   ```bash
   # Create scripts/deploy.sh
   #!/bin/bash
   pip install -r requirements.txt
   python run.py
   ```
   Then trust: `bash scripts/*.sh`

2. **Use Make/NPM Scripts**: Define common workflows in package.json or Makefile:
   ```json
   "scripts": {
     "dev": "pip install -r requirements.txt && python run.py"
   }
   ```
   Then trust: `npm run *`

3. **Prioritize Most Common**: Only add semicolon commands you actually use frequently

### Configuration Instructions

1. Open Kiro IDE Settings
2. Navigate to "Kiro Agent Trusted Commands"
3. Add the standard commands using wildcards (*)
4. For semicolon commands, add each specific command exactly as written
5. Consider creating shell scripts for complex command chains
6. Test with a simple command first to ensure configuration works

## Security Guidelines

- **Never allow**: `rm -rf *; *` or similar destructive patterns
- **Be specific**: Don't use broad wildcards with semicolons like `*; *`
- **Review regularly**: Remove unused command permissions
- **Test safely**: Try new commands in a safe environment first

## kTunes-Specific Commands

### iTunes Integration
```
python -c "from services.itunes_service import *; update_database_from_xml_logic()"
```

### Spotify Operations
```
python -c "from services.spotify_service import *; get_spotify_client()"
```

### Playlist Generation
```
python -c "from services.playlist_generator_service import *; PlaylistGenerator"
```

## Common Semicolon Patterns for kTunes

### Most Frequently Used (Add These First)
```
git add .; git commit -m "Auto-commit"
pip install -r requirements.txt; python run.py
source venv/bin/activate; python run.py
flask db migrate -m "Auto migration"; flask db upgrade
```

### Testing Workflows
```
python -m pytest; echo "Tests completed"
python -m pytest tests/; coverage report
pip install -r requirements.txt; python -m pytest
```

### Database Management
```
cd migrations; flask db upgrade
sqlite3 instance/kTunes.sqlite ".tables"; echo "Database ready"
```

### Development Shortcuts
```
git status; git add .; git commit -m "WIP"
python -c "print('Starting kTunes...'); exec(open('run.py').read())"
```

## Alternative Approaches

### Create Utility Scripts
Instead of adding many semicolon commands, create utility scripts in a `scripts/` directory:

```bash
# scripts/quick-test.sh
#!/bin/bash
pip install -r requirements.txt
python -m pytest

# scripts/db-reset.sh  
#!/bin/bash
cd migrations
flask db upgrade
echo "Database updated"
```

Then trust: `bash scripts/*.sh`

## Troubleshooting

If a command is blocked:
1. **Contains semicolons?** → Add the exact command to trusted list
2. **Complex chain?** → Consider creating a shell script instead
3. **Typos?** → Verify exact spacing and syntax in trusted commands
4. **Test incrementally** → Try individual parts of the command first
5. **Check logs** → Kiro may show why a command was blocked