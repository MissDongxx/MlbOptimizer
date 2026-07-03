# LineupLab MLB DFS Optimizer

Free MLB DFS lineup optimizer for DraftKings and FanDuel. This repo follows the PRD architecture:

- `backend/`: FastAPI, projection cache, MLB lineup data, optimizer API
- `frontend/`: Next.js 16, Tailwind, single-page optimizer UI

## Key MVP Decisions

- Request-time projection code does **not** call `pybaseball.statcast_batter()`.
- Season and platoon data is designed to be pre-fetched into `backend/cache/season_splits.json`.
- The backend ships with mock data enabled by default so the UI and optimizer flow can run before external API keys/data are configured.
- User projection edits are stored in the parent page as `overriddenPlayers: Record<string, number>` and keyed by stable MLBAM id, so multi-position players keep the same edited projection across filters.

## Backend

```bash
cd backend
cp .env.example .env
uv sync
uvicorn main:app --reload
```

Useful endpoints:

- `GET http://localhost:8000/health`
- `GET http://localhost:8000/players/today`
- `POST http://localhost:8000/optimize/`

To switch from mock data to live schedule attempts:

```bash
USE_MOCK_DATA=false
```

The season cache job is implemented in `backend/services/season_cache.py`. It writes atomically to:

```text
backend/cache/season_splits.json
```

All JSON cache reads/writes go through `backend/services/cache_store.py`. The default backend is local
disk, which is appropriate for a VPS deployment. Set `CACHE_DIR` to move cache files onto a persistent
data volume:

```bash
CACHE_DIR=/var/lib/lineuplab/cache
```

The same adapter boundary can later be replaced with R2/S3/MinIO storage if long-term Statcast or
machine-learning datasets outgrow local JSON caches.

## Frontend

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Open:

```text
http://localhost:3000
```

## Current MVP Scope

Implemented:

- FastAPI app with CORS and lifespan scheduler
- `/health`, `/players/today`, `/optimize/`
- Projection constants and cache helpers
- Daily season-splits refresh function
- Mock player pool for local development
- `pydfs-lineup-optimizer` adapter for DK/FD MLB roster solving, with greedy fallback only for
  local dependency/adapter failures
- Live `statsapi` schedule and batting-order extraction when `USE_MOCK_DATA=false`
- FanGraphs/pybaseball id to MLBAM id mapping in the season cache via
  `pybaseball.playerid_reverse_lookup()`
- Next.js optimizer page
- Settings panel, CSV projection/salary/position upload, player table filters
- Lock/exclude controls
- Central projection overrides for multi-position players
- Lineup display and CSV export

Still to harden before production:

- Validate live `statsapi` lineup extraction against current-day pre-lock slates and late lineup
  release edge cases
- Add broader tests around multi-position overrides and same-game pitcher/batter restrictions
- Add production salary feed ingestion beyond user-uploaded DK/FD CSV files
- Confirm Render cold-start timing after deployment
