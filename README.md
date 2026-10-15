# Mister_Scraper

Mister_Scraper is a Python-based content harvesting system built for X/Twitter media extraction, Telegram delivery, and lightweight automation workflows. The project combines a FastAPI API, a Telegram bot, queue processing, media handling, and SQLite-backed persistence to ingest X posts and deliver media to Telegram channels or direct chats.

This repository is structured as an end-to-end scraper and delivery pipeline for harvesting X content at scale while normalizing metadata, cleaning captions, and managing background jobs.

## Overview

Mister_Scraper is designed to:

- Fetch metadata and media from X/Twitter post URLs
- Extract and normalize media items (images and videos)
- Clean captions before publishing
- Deliver content to Telegram users or channel destinations
- Persist processed items and queue state in SQLite
- Run as a headless API service, a Telegram bot, or both together

The application boots through `main.py`, initializes the database, starts the FastAPI server, and optionally starts the Telegram bot if a token is configured.

## Features

- X post scraping via normalized adapter layer
- Profile harvesting for recent X content
- Caption sanitization and signature injection
- Media URL resolution and filename handling
- Background queue processing and scheduled delivery jobs
- Telegram upload/retry logic with resilient delivery
- FastAPI health and scrape endpoints
- SQLite-backed tracking for seen items and queued jobs

## Project Structure

```text
Mister_Scraper/
├── api/
│   ├── __init__.py
│   └── routers/
│       └── scraper.py
├── bot/
│   ├── handlers/
│   ├── helpers/
│   ├── keyboards.py
│   ├── states.py
│   └── utils/
├── core/
│   ├── __init__.py
│   ├── media_resolver.py
│   ├── text_cleaner.py
│   └── time_utils.py
├── data/
│   ├── __init__.py
│   ├── database.py
│   ├── models.py
│   └── repository.py
├── features/
│   └── x/
│       ├── __init__.py
│       ├── adapter.py
│       ├── fast_meta.py
│       └── scraper.py
├── services/
│   ├── __init__.py
│   ├── downloader.py
│   ├── queue_worker.py
│   ├── quick_grab_service.py
│   ├── scheduler.py
│   └── telegram_sender.py
├── .env.example
├── .gitignore
├── BACKLOG.md
├── LESSONS.md
├── config.py
├── main.py
├── requirements.txt
└── README.md
```

## Core Components

### API

The API is created in `api/__init__.py` and exposes the scraper router under `/api/v1`.

Available endpoints:

- `GET /api/v1/health`
- `POST /api/v1/scrape`

The scrape endpoint validates the API key and returns normalized metadata, cleaned caption text, and media URLs for a given X post.

### Telegram Bot

The bot layer in `bot/handlers` registers menu, settings, sync, deep harvest, source management, and quick-grab flows. It is intended to support interactive operations such as delivering posts to a user or channel and handling periodic content sync jobs.

### Data Layer

The project uses SQLite with SQLAlchemy models and repository helpers in the `data/` package. The database stores state for processed posts, pending jobs, and tracking information to avoid duplicate processing.

### X Feature Module

The `features/x` package provides the main extraction logic for X content:

- `adapter.py`: standardized `ScrapedItem` data model
- `fast_meta.py`: metadata retrieval and X/Twitter compatibility handling
- `scraper.py`: profile and media harvesting logic

### Services

The service layer includes:

- `downloader.py`: media download logic
- `queue_worker.py`: queue processing and delivery pipeline
- `scheduler.py`: scheduled recurring jobs
- `quick_grab_service.py`: direct, rapid delivery workflow
- `telegram_sender.py`: Telegram uploads and fallback handling

## Installation

1. Clone the repository.
2. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate  # Windows
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Create your environment file:

```bash
cp .env.example .env
```

5. Fill in the required values in `.env`.

## Environment Variables

The project reads configuration from `config.py`, which loads values from `.env`.

Example values from `.env.example`:

```env
BOT_TOKEN=
ADMIN_IDS=
API_HOST=0.0.0.0
API_PORT=8120
API_KEY=mister_scraper_secret_key
```

Additional optional variables may be used by X-related flows:

- `X_AUTH_TOKEN`
- `X_CT0`

These are configured in `config.py` and may be needed depending on the environment or the behavior of X/Twitter endpoints.

## Running the Project

Start the full application:

```bash
python main.py
```

This will:

- initialize the database
- start the FastAPI web server
- start the Telegram bot if `BOT_TOKEN` is present
- launch the conveyor worker and scheduler if bot functionality is enabled

## API Usage

### Health Check

```bash
curl http://localhost:8120/api/v1/health
```

### Scrape Endpoint

```bash
curl -X POST http://localhost:8120/api/v1/scrape \
  -H "Content-Type: application/json" \
  -H "X-API-Key: mister_scraper_secret_key" \
  -d '{
    "url": "https://x.com/username/status/1234567890",
    "signature": "Your signature text",
    "filter_mode": 1
  }'
```

Example response:

```json
{
  "platform": "x",
  "content_id": "1234567890",
  "author": "username",
  "original_caption": "Example post text",
  "cleaned_caption": "Example post text",
  "media_count": 1,
  "media_urls": [
    "https://example.com/media.jpg"
  ]
}
```

## Notes

- The project is currently oriented around X/Twitter scraping workflows.
- Some features are designed for Telegram-based delivery and processing pipelines.
- The repository includes additional planning and lessons documents (`BACKLOG.md` and `LESSONS.md`) that document the MVP scope and bug-fix notes.

## License

No explicit license file is included in the repository, so licensing should be confirmed before public reuse or redistribution.

## Related Files

- `BACKLOG.md` — roadmap and MVP scope
- `LESSONS.md` — implementation notes and fixes
- `.env.example` — sample environment configuration

## Summary

Mister_Scraper is a modular Python automation project focused on harvesting X media content, cleaning text, and delivering it through Telegram with robust scheduling and persistence. It is built as a practical MVP architecture with components for scraping, processing, queueing, storage, and HTTP/API access.
