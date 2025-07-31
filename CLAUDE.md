# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

1. 務必測試
2. 搭配 git 做版本控制

## Essential Commands

### Development
```bash
# Install dependencies
pip install -r requirements.txt

# Start Flask web application (port 5000)
python app.py

# Start scheduler (in separate terminal)
python scheduler.py

# Manual report generation
python generate_report.py --lang zh-tw --detail all

# Initialize database
python init_db.py

# Test connections
python -c "from app import app; print('Flask OK')"
python -c "from scheduler import fetch_and_generate_report; print('Scheduler OK')"
```

### Data Collection Scripts
```bash
# Fetch BGG hot games list
python fetch_hotgames.py

# Fetch game details
python fetch_details.py

# Fetch forum threads and comments
python fetch_bgg_forum_threads.py

# Generate comment summaries using LLM
python comment_summarize_llm.py

# Clean duplicate comments
python clean_duplicate_comments.py

# Sync user collections
python collection_sync.py
```

## Architecture Overview

This is a BGG (BoardGameGeek) hot games report system that:

1. **Data Collection Pipeline**: Scrapes BGG for hot games, game details, and forum discussions
2. **LLM Processing**: Uses OpenAI API to summarize forum comments and generate insights
3. **Report Generation**: Creates daily Markdown reports in Traditional Chinese
4. **Web Interface**: Flask app with login system to view reports
5. **Scheduling**: Automated daily report generation at 9:00 AM

### Core Components

- **app.py**: Flask web server with login, report viewing, and manual regeneration
- **scheduler.py**: APScheduler-based daily automation (runs at 9:00 AM)
- **generate_report.py**: Main report generation logic with i18n support
- **fetch_*.py**: Data collection scripts for different BGG APIs
- **comment_summarize_llm.py**: OpenAI integration for content analysis

### Data Flow

1. **Collection**: `fetch_hotgames.py` → `fetch_details.py` → `fetch_bgg_forum_threads.py`
2. **Processing**: `comment_summarize_llm.py` analyzes forum discussions
3. **Generation**: `generate_report.py` creates localized reports
4. **Storage**: SQLite database (`data/bgg_rag.db`) + Markdown files (`frontend/public/outputs/`)

### Database Schema

Uses SQLite with tables for:
- Hot games rankings (with date tracking)
- Game details and metadata
- Forum threads and comments
- Comment summaries and insights

### Environment Variables Required

- `SECRET_KEY`: Flask session security
- `ADMIN_USERNAME`/`ADMIN_PASSWORD`: Web interface login
- `OPENAI_API_KEY`: LLM processing

### Output Structure

Reports generated as: `frontend/public/outputs/report-YYYY-MM-DD-zh-tw.md`

### Deployment

Configured for cloud deployment with:
- `Procfile`: Heroku/Render (web + worker processes)
- `render.yaml`: Render Blueprint configuration
- `zeabur.yml`: Zeabur deployment settings