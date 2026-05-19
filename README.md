# NoHitterTracker

NoHitterTracker monitors live MLB games for no-hitters and perfect games, automatically sending notifications and providing real-time data via a web UI and HTTP API.

## Features

- **Live Monitoring**: Scans MLB Stats API for active no-hitters and perfect games
- **Event Tracking**: Detects no-hitter starts, downgrades, pitching changes, broken games, and final outcomes
- **Twitter Integration**: Sends automated tweet notifications for game events (production mode)
- **Web Interface**: Real-time game tracking website with datepicker (1901–present) for historical lookups
- **HTTP API**: RESTful endpoints for querying no-hitter data programmatically
- **State Persistence**: Tracks tweeted events to prevent duplicates

## Quick Start

### Web Interface

Open `web/index.html` in a browser to view the no-hitter tracker website. The page auto-refreshes every 60 seconds and displays active no-hitters with live inning-by-inning updates.

### Run the Services

Bot runner:

```bash
python bot.py
```

API server:

```bash
python api.py --host 127.0.0.1 --port 8001
```

## API Endpoints

- `GET /health` — Health check
- `GET /api/no-hitters` — Active no-hitters and perfect games
- `GET /api/games` — All games with no-hitter/perfect-game activity

### Query Parameters

Both `/api/no-hitters` and `/api/games` accept:

- `date=MM/DD/YYYY` — Specific date filter
- `include_events=true|false` — Include event timeline
- `include_games=true|false` — Include full game details
- `include_all_plays=true|false` — Include all plays (verbose)
- `include_event_snapshot=true|false` — Include game snapshots at each event
- `include_legacy=true|false` — Include legacy/historical data

### Response Format

Both endpoints return a normalized response structure:

```json
{
  "response_version": "2.1",
  "meta": { ... },
  "entities": {
    "games_by_id": { ... },
    "game_ids_in_order": [ ... ],
    "active_no_hitters_by_key": { ... }
  },
  "activity": {
    "events": [ ... ]
  }
}
```

## Project Structure

```
nohittertracker/
├── bot.py                  # Entry point for Twitter bot runner
├── api.py                  # Entry point for HTTP API server
├── web/                    # Website interface
│   ├── index.html          # Web UI
│   └── nohittertracker.js  # Frontend logic
├── nohittertracker/        # Internal package (library code)
│   ├── service.py          # NoHitterTracker core scanning logic
│   ├── api_server.py       # HTTP request routing and responses
│   ├── formatter.py        # Tweet message formatting
│   ├── state.py            # Game state persistence
│   ├── game_details.py     # Live game data parsing
│   ├── play_details.py     # Play-by-play parsing
│   ├── util.py             # Utilities (logging, config, HTTP)
│   ├── constants.py        # Configuration templates
│   ├── models/             # Response dataclasses
│   └── __init__.py         # Package exports
├── requirements.txt        # Python dependencies
├── config.json             # Application config
└── README.md              # This file
```

**Root Entrypoints**:
- `bot.py` — Execute to run the Twitter bot
- `api.py` — Execute to run the HTTP API server

**Internal Package** (`nohittertracker/`):
- Contains all library modules
- Imported by root entrypoints and each other
- Not meant to be executed directly

## Dependencies

Install from `requirements.txt`:

```bash
pip install -r requirements.txt
```

## Environment Variables

Configure via `.env` file (see `.env.example` as template):

**Required**:
- `ENVIRONMENT` — `test` (no Twitter posting) or `prod` (live posting); default: `test`
- `GITHUB_TOKEN` — Required for `arodsgntfy` notification dependency
- `TWITTER_CONSUMER_KEY`, `TWITTER_CONSUMER_SECRET` — Twitter API v2 credentials
- `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_TOKEN_SECRET` — Twitter API v2 credentials

**Optional**:
- `INTERVAL_MINUTES` — Bot polling interval; default: `2` minutes
- `NOHITTERTRACKER_SCHEDULE_CACHE_TTL_SECONDS` — MLB schedule cache time-to-live; default: `60.0` seconds
- `NOHITTERTRACKER_GAME_FEED_SCHEDULED_CACHE_TTL_SECONDS` — TTL for scheduled games that are not close to first pitch; default: `3600.0` seconds
- `NOHITTERTRACKER_GAME_FEED_NEAR_START_WINDOW_SECONDS` — How soon before first pitch a scheduled game is treated as near start; default: `1800.0` seconds
- `NOHITTERTRACKER_GAME_FEED_NEAR_START_CACHE_TTL_SECONDS` — TTL for near-start and pregame (`P`) game feeds; default: `60.0` seconds
- `NOHITTERTRACKER_GAME_FEED_FINAL_CACHE_TTL_SECONDS` — TTL for finished game feeds; default: `21600.0` seconds

## Configuration

`config.json` should define:

- `num_innings_to_alert` — Minimum innings before alerting (e.g., 5)
- `ntfy_settings` — Notification service config (e.g., Pushover credentials)
- `team_hashtags` — Map of team abbreviations to hashtags for tweets

Example:

```json
{
  "num_innings_to_alert": 6.0,
  "ntfy_settings": {
    "enabled": true,
    "topic": "ntfy-topic-name",
    "title": "NtfyTitle"
  },
  "team_hashtags": {
    "ATL": "BravesCountry",
    "AZ": "DBacks",
    ...
  }
}
```

## State Files

The bot persists tweeted event IDs to prevent duplicate tweets across restarts:

- `data/tweeted_event_ids.pkl` — Event IDs tweeted today; reset automatically each new day
