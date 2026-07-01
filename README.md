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
- Greedy fallback optimizer for DK/FD roster shapes
- Next.js optimizer page
- Settings panel, CSV projection upload, player table filters
- Lock/exclude controls
- Central projection overrides for multi-position players
- Lineup display and CSV export

Still to harden before production:

- Enable and validate real `statsapi` lineup extraction
- Map pybaseball IDs to MLBAM IDs robustly in season cache
- Replace fallback optimizer with full `pydfs-lineup-optimizer` adapter
- Add tests around infeasible locks, salary constraints, and multi-position overrides
- Add production salary feed ingestion
