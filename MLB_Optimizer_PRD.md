# MLB DFS Optimizer — Product Requirements Document

> Version 1.0 | Target: Production-ready MVP
> Stack: Next.js 14 + FastAPI + pydfs-lineup-optimizer + pybaseball + MLB-StatsAPI

---

## 0. AI Implementation Instructions

This PRD is written for an AI coding agent to implement a fully deployable product. Follow these rules:

- Implement every section in order. Do not skip sections.
- All environment variables go in `.env.local` (frontend) and `.env` (backend). Never hardcode secrets.
- Every API endpoint must have error handling, input validation (Pydantic), and return consistent JSON shapes.
- Frontend must be fully responsive (mobile-first). DFS users are heavily mobile.
- All data shown to users must include a `last_updated` timestamp.
- Default to TypeScript for all frontend code.
- Use `pyproject.toml` + `uv` for Python dependency management.

---

## 1. Product Overview

### 1.1 Product Name
**LineupLab** — Free MLB DFS Lineup Optimizer

### 1.2 One-Line Description
A free, browser-based MLB daily fantasy lineup optimizer that generates optimal DraftKings and FanDuel lineups using split-adjusted projections, batting order weighting, and confirmed starting lineup data.

### 1.3 Target User
- Primary: DFS players on DraftKings or FanDuel playing MLB classic contests
- Secondary: Season-long fantasy players researching daily matchups
- Behavior: Mobile-heavy, time-pressured (decisions made 30–90 min before first pitch), skeptical of paywalls

### 1.4 Core Value Proposition
The only free MLB optimizer that combines:
1. Auto-generated projections (no CSV required) using 15-day split-adjusted averages
2. Real-time confirmed lineup integration with batting order weighting
3. Professional-grade Stacking and Exposure controls, free forever for up to 20 lineups

### 1.5 Monetization (Phase 2, not MVP)
- Free tier: up to 20 lineups, basic Stacking
- Pro ($9.99/month): up to 150 lineups, Monte Carlo simulation, Ownership control, advanced Stacking rules

---

## 2. Technical Architecture

### 2.1 Repository Structure

```
lineuplab/
├── frontend/                  # Next.js 14 app
│   ├── app/
│   │   ├── page.tsx           # Home / optimizer tool
│   │   ├── layout.tsx
│   │   ├── api/               # Next.js route handlers (thin proxies only)
│   │   └── (routes)/
│   │       ├── how-it-works/
│   │       └── blog/          # pSEO content pages (Phase 2)
│   ├── components/
│   │   ├── PlayerPool.tsx
│   │   ├── LineupGrid.tsx
│   │   ├── UploadCSV.tsx
│   │   ├── SettingsPanel.tsx
│   │   └── StatusBadge.tsx
│   ├── lib/
│   │   ├── api.ts             # fetch wrappers for backend
│   │   └── types.ts           # shared TypeScript types
│   └── public/
├── backend/                   # FastAPI app
│   ├── main.py
│   ├── routers/
│   │   ├── optimize.py        # POST /optimize
│   │   ├── players.py         # GET /players/today
│   │   └── health.py          # GET /health
│   ├── services/
│   │   ├── projections.py     # 15-day split-adjusted projection engine
│   │   ├── lineup_data.py     # MLB-StatsAPI integration
│   │   ├── optimizer.py       # pydfs-lineup-optimizer wrapper
│   │   └── scheduler.py       # APScheduler lineup refresh
│   ├── models/
│   │   └── schemas.py         # Pydantic models
│   ├── cache/                 # file-based cache for player data
│   └── pyproject.toml
└── README.md
```

### 2.2 Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Frontend | Next.js 14 (App Router) | SSR for SEO, Vercel free tier |
| Styling | TailwindCSS + shadcn/ui | Rapid UI, dark mode built-in |
| Backend | FastAPI (Python 3.12) | Async, auto OpenAPI docs, ProcessPoolExecutor for LP |
| Optimizer | pydfs-lineup-optimizer 3.x | DK/FD MLB rules built-in, PuLP solver |
| Baseball data | pybaseball | Statcast, game logs, splits |
| Schedule data | MLB-StatsAPI (toddrob99) | Confirmed lineups, batting order, injury status |
| Deployment | Vercel (frontend) + Render free tier (backend) | Zero cost MVP |
| Cache | JSON files on disk + in-memory dict | No Redis needed for MVP |

### 2.3 Environment Variables

**backend/.env**
```
MLB_CACHE_TTL_SECONDS=180
LINEUP_REFRESH_PREGAME_MINUTES=90
LOG_LEVEL=INFO
ALLOWED_ORIGINS=http://localhost:3000,https://lineuplab.io
```

**frontend/.env.local**
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 3. Data Pipeline (Critical — Build This First)

> The projection engine is the product's core IP. Build and validate the full pipeline before touching frontend.

### 3.1 DraftKings Scoring Rules (MLB Classic)

Implement as constants in `backend/services/projections.py`:

```python
DK_SCORING = {
    "single": 3,
    "double": 5,
    "triple": 8,
    "home_run": 10,
    "rbi": 2,
    "run": 2,
    "walk": 2,
    "hit_by_pitch": 2,
    "stolen_base": 5,
    # Pitcher scoring
    "pitcher_win": 4,
    "earned_run_allowed": -2,
    "strikeout_pitched": 2,
    "innings_pitched": 2.25,  # per inning
    "complete_game": 2.5,
    "no_hitter": 5,
}

FD_SCORING = {
    "single": 3,
    "double": 6,
    "triple": 9,
    "home_run": 12,
    "rbi": 3.5,
    "run": 3.2,
    "walk": 3,
    "stolen_base": 6,
    # Pitcher scoring
    "pitcher_win": 6,
    "earned_run_allowed": -3,
    "strikeout_pitched": 3,
    "innings_pitched": 3,
}
```

### 3.2 Projection Engine: `services/projections.py` (CRITICAL PERFORMANCE AMENDMENT)

DO NOT call `pybaseball.statcast_batter()` per request. It causes 429 errors, slow responses, and worker pool freezes when called repeatedly during user traffic.

Implement this caching and pre-fetching strategy instead:

#### Step 1: Daily Cron Pre-Fetch (Run at 6:00 AM)

Use `pybaseball.batting_stats(current_year)` to pull season-level stats and platoon splits for ALL players once per day.

Persist the normalized output as a static JSON file:

```text
backend/cache/season_splits.json
```

Required cache shape:

```json
{
  "last_updated": "2026-07-01T06:00:00Z",
  "season": 2026,
  "players": {
    "660271": {
      "name": "Example Player",
      "mlbam_id": 660271,
      "team": "LAD",
      "season_rates": {
        "games": 82,
        "pa": 355,
        "hits_per_game": 1.08,
        "hr_per_game": 0.22,
        "rbi_per_game": 0.71,
        "runs_per_game": 0.79,
        "walks_per_game": 0.52,
        "sb_per_game": 0.09
      },
      "splits": {
        "vs_L": { "projection_factor": 0.94, "ops": 0.781, "woba": 0.332 },
        "vs_R": { "projection_factor": 1.06, "ops": 0.862, "woba": 0.366 }
      }
    }
  }
}
```

Cron requirements:

- Create `backend/services/season_cache.py` for the pre-fetch job.
- Create `refresh_season_splits(current_year: int) -> dict` and `load_season_splits() -> dict`.
- Write atomically: save to a temp file, then rename to `backend/cache/season_splits.json`.
- Include `last_updated`, `season`, and per-player lookup by MLBAM id where possible.
- If platoon split source fields are unavailable, compute conservative `projection_factor` defaults from available handedness/split columns; otherwise use `1.00` and log the fallback.
- Never block `/players/today` or `/optimize` on a live `pybaseball` call.

#### Step 2: Per-Request Pipeline

The request-time projection path must only use fast schedule, lineup, game-log, and local cache reads:

1. Use `statsapi.schedule()` to get today's matchups and starter pitcher hand (`'L'` or `'R'`).
2. Use `statsapi.last_15_days_games(player_id)` or quick game logs to fetch the last 15 days of counting stats: Hits, HRs, RBIs, Runs, Walks, SB where available.
3. Map counting stats to DraftKings/FanDuel scoring rules via the constants in Section 3.1.
4. Apply the Batting Order Multiplier and Platoon Splits from the pre-cached `season_splits.json`.

Projection function contract:

```python
def get_split_projection(
    player_mlbam_id: int,
    opposing_pitcher_hand: str,  # 'L' or 'R'
    batting_order_position: int | None,
    site: str = 'dk'
) -> dict:
    """
    Returns projection dict:
    {
        "player_id": int,
        "projected_points": float,
        "projection_source": "15d_counts_cached_season_splits",
        "vs_hand": str,
        "batting_order": int | None,
        "batting_order_multiplier": float,
        "platoon_factor": float,
        "base_projection": float,
        "last_15_days_sample": int,
        "season_cache_last_updated": str,
        "last_updated": str
    }

    Algorithm:
    1. Load player season/platoon data from backend/cache/season_splits.json.
    2. Fetch lightweight last-15-day counting stats through statsapi/game logs.
    3. Convert counting stats to DK/FD points using Section 3.1 constants.
    4. If the 15-day sample is too small or unavailable, fall back to cached season rates.
    5. Apply platoon factor for opposing pitcher hand from season_splits.json.
    6. Apply batting order multiplier:
       - Position 1-2: 1.15
       - Position 3-4: 1.12
       - Position 5-6: 1.00
       - Position 7: 0.92
       - Position 8-9: 0.85
       - Unknown/unconfirmed: 1.00
    7. Apply injury/DNP check: return projected_points = 0 if player is not in the active/expected lineup.
    """
```

#### Step 3: Pitcher Projection

```python
def get_pitcher_projection(
    player_mlbam_id: int,
    opposing_team_id: int,
    site: str = 'dk'
) -> dict:
    """
    Pitcher projection uses fast game-log and cached opponent context only:
    1. Last 4 starts: average innings pitched, K rate, ERA
    2. Opposing team's K% vs pitcher hand from cached/pre-fetched team data where available
    3. DK scoring: IP * 2.25 + K * 2 + W * 4 - ER * 2

    Do not call pybaseball.statcast_pitcher() or batter-level Statcast endpoints per request.
    Returns same dict structure as get_split_projection().
    """
```

#### Step 4: Cache Layer

```python
# Cache all request-time projections in memory dict keyed by game date and site.
# TTL: 3 hours during day, 10 minutes within 90 min of first pitch.
# Store as JSON file in backend/cache/projections_{YYYY-MM-DD}_{site}.json.
# Load from file on startup if file is fresh.
# Depend on backend/cache/season_splits.json for season/platoon factors.

_projection_cache: dict = {}
_cache_timestamp: datetime | None = None

def get_cached_projections(game_date: str, site: str) -> dict | None:
    """Return cached projections if fresh, else None."""

def set_cached_projections(game_date: str, site: str, data: dict) -> None:
    """Write to memory and disk cache."""
```

### 3.3 Lineup Data: `services/lineup_data.py`

```python
import statsapi  # toddrob99/MLB-StatsAPI

def get_todays_games() -> list[dict]:
    """
    Returns list of today's games:
    [{
        "game_id": int,
        "game_time": str (ISO),
        "away_team": str,
        "home_team": str,
        "away_starter": {"name": str, "mlbam_id": int, "hand": str},
        "home_starter": {"name": str, "mlbam_id": int, "hand": str},
        "away_lineup_confirmed": bool,
        "home_lineup_confirmed": bool,
        "away_lineup": [{"name": str, "mlbam_id": int, "batting_order": int, "position": str}],
        "home_lineup": [{"name": str, "mlbam_id": int, "batting_order": int, "position": str}],
        "venue": str,
    }]
    
    Use statsapi.schedule() for game list.
    Use statsapi.get('game', {'gamePk': game_id}) for lineup details.
    Lineup is 'confirmed' when linescore shows lineup is posted.
    """

def get_player_status(mlbam_id: int) -> str:
    """Returns 'active', 'injured', 'day-to-day', 'DNP'"""
```

### 3.4 Scheduler: `services/scheduler.py`

```python
from apscheduler.schedulers.background import BackgroundScheduler

def get_refresh_interval_seconds() -> int:
    """
    Dynamic refresh based on time to first pitch:
    - > 3 hours: 7200 seconds (2 hours)
    - 90 min - 3 hours: 600 seconds (10 min)  
    - < 90 min: 120 seconds (2 min)
    - Game in progress: 300 seconds (5 min, for DNP updates)
    """

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        refresh_all_data,
        'interval',
        seconds=get_refresh_interval_seconds(),
        id='lineup_refresh'
    )
    scheduler.start()
    return scheduler

async def refresh_all_data():
    """Fetch lineup data + recalculate projections + update cache."""
```

---

## 4. Backend API

### 4.1 FastAPI App: `main.py`

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from services.scheduler import start_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = start_scheduler()
    yield
    scheduler.shutdown()

app = FastAPI(title="LineupLab API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(players_router, prefix="/players")
app.include_router(optimize_router, prefix="/optimize")
app.include_router(health_router)
```

### 4.2 Endpoint: GET /players/today

**Purpose:** Return today's full player pool with projections and lineup status.

**Response schema:**
```typescript
interface PlayerPoolResponse {
  game_date: string;           // "2025-06-15"
  last_updated: string;        // ISO timestamp
  games: GameSummary[];
  players: Player[];
}

interface Player {
  mlbam_id: number;
  name: string;
  team: string;
  opponent: string;
  position: string[];          // ["OF"] or ["1B", "3B"] for multi-position
  salary_dk: number;
  salary_fd: number;
  batting_order: number | null;  // null if unconfirmed
  opposing_pitcher: string;
  opposing_pitcher_hand: "L" | "R" | null;
  lineup_status: "confirmed" | "expected" | "unconfirmed" | "dnp";
  projected_dk: number;        // projected DK fantasy points
  projected_fd: number;
  projection_source: "15d_split" | "season_split" | "user_override";
  last_15_avg_dk: number;      // raw 15-day average, shown in UI
  vs_lhp_avg: number;
  vs_rhp_avg: number;
}
```

**Implementation notes:**
- Run pybaseball projection calculation in a `ProcessPoolExecutor` (not async, it's CPU-bound)
- Cache result in memory; return cached if age < TTL
- Include `last_updated` in every response
- If pybaseball is down, fall back to cached file from previous run

### 4.3 Endpoint: POST /optimize

**Purpose:** Run the LP optimizer and return N optimal lineups.

**Request schema:**
```typescript
interface OptimizeRequest {
  site: "dk" | "fd";
  num_lineups: number;           // 1–20 (free tier cap)
  players: PlayerInput[];        // full player pool with projections
  settings: OptimizerSettings;
}

interface PlayerInput {
  mlbam_id: number;
  name: string;
  team: string;
  position: string[];
  salary: number;
  projected_points: number;      // may be user-overridden
  lock: boolean;                 // force include
  exclude: boolean;              // force exclude
  max_exposure: number;          // 0.0–1.0, default 1.0
}

interface OptimizerSettings {
  stack_team: string | null;         // force N players from this team
  stack_count: number;               // default 4 for MLB
  pitcher_vs_batter_same_team: "allow" | "avoid";  // default "avoid"
  min_salary_used: number;           // default 49500 for DK
  unique_lineups: boolean;           // enforce lineup uniqueness
}
```

**Response schema:**
```typescript
interface OptimizeResponse {
  lineups: Lineup[];
  solve_time_ms: number;
  warnings: string[];            // e.g. "3 players have unconfirmed lineup status"
}

interface Lineup {
  lineup_number: number;
  players: LineupPlayer[];
  total_salary: number;
  projected_points: number;
}

interface LineupPlayer {
  mlbam_id: number;
  name: string;
  position_slot: string;         // the slot this player fills: "P", "C", "1B"...
  salary: number;
  projected_points: number;
}
```

**Implementation: `routers/optimize.py`**
```python
from concurrent.futures import ProcessPoolExecutor
import asyncio

executor = ProcessPoolExecutor(max_workers=2)

@router.post("/", response_model=OptimizeResponse)
async def run_optimizer(request: OptimizeRequest):
    # Validate: max 20 lineups (free tier)
    if request.num_lineups > 20:
        raise HTTPException(status_code=400, detail="Free tier limit: 20 lineups")
    
    # Run LP solver in process pool (blocks the thread pool otherwise)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        executor,
        _run_optimizer_sync,
        request
    )
    return result

def _run_optimizer_sync(request: OptimizeRequest) -> dict:
    """
    Run pydfs-lineup-optimizer synchronously.
    This runs in a separate process via ProcessPoolExecutor.
    
    Steps:
    1. Create optimizer: get_optimizer(Site.DRAFTKINGS, Sport.BASEBALL)
    2. Build player list from request.players
    3. Apply locks and excludes
    4. Apply stacking rules via GenericStacksRule
    5. Apply pitcher-vs-team restriction if settings.pitcher_vs_batter_same_team == 'avoid'
    6. Apply max_exposure per player
    7. Run optimizer.optimize(n=request.num_lineups)
    8. Serialize lineups to dict
    9. Return with warnings list
    """
```

### 4.4 Endpoint: GET /health

```python
@router.get("/health")
async def health():
    return {
        "status": "ok",
        "cache_age_seconds": get_cache_age(),
        "last_lineup_refresh": get_last_refresh_timestamp(),
        "players_loaded": get_player_count(),
    }
```

---

## 5. Frontend

### 5.1 Page Structure: Single-page optimizer tool

The entire product lives on a single page (`app/page.tsx`). Layout:

```
┌─────────────────────────────────────────────────┐
│  HEADER: Logo | DK / FD toggle | "How it works" │
├──────────────────┬──────────────────────────────┤
│                  │                              │
│  LEFT PANEL      │   RIGHT PANEL                │
│  (40% width)     │   (60% width)                │
│                  │                              │
│  Site toggle     │   Lineup grid                │
│  Settings        │   (output)                   │
│  ──────────      │                              │
│  Player Pool     │                              │
│  (filterable     │                              │
│   table)         │                              │
│                  │                              │
│  [OPTIMIZE]      │                              │
│  button          │                              │
└──────────────────┴──────────────────────────────┘
```

On mobile: Settings panel collapses to drawer. Player pool is full-width. Lineup grid appears below after optimization.

### 5.2 Component: Settings Panel

```typescript
// components/SettingsPanel.tsx

interface SettingsPanelProps {
  site: 'dk' | 'fd';
  onSiteChange: (site: 'dk' | 'fd') => void;
}

// UI elements:
// 1. Site toggle: [DraftKings] [FanDuel] pill toggle
// 2. Number of lineups: number input (1–20), default 5
// 3. Stack team: dropdown of today's teams (optional)
// 4. Stack count: 2–6 slider, default 4
// 5. Pitcher vs same team: checkbox "Avoid pitcher facing team batters" (checked by default)
// 6. Min salary used: number input, default 49500
// 7. Upload custom projections CSV: file input
//    - Accept CSV with columns: Name, Team, Projection
//    - Merge with auto-projections, user value overrides
//    - Show "Using your projections" badge on affected players
```

### 5.3 Component: Player Pool Table (UI Override Rule)

```typescript
// components/PlayerPool.tsx

// Columns:
// Name | Pos | Team | Opp | Salary | Proj | Status | L/E
// 
// Status badge colors:
// "confirmed" -> green dot
// "expected" -> yellow dot
// "unconfirmed" -> gray dot
// "dnp" -> red strikethrough, row grayed out
//
// L/E column: Lock / Exclude toggle buttons per row
// Clicking Lock forces player into all lineups
// Clicking Exclude removes player from all lineups
//
// Filters row (above table):
// - Search by name
// - Filter by position (All | P | C | 1B | 2B | SS | 3B | OF)
// - Filter by team
// - Filter by status (Confirmed only toggle)
// - Sort by: Salary | Projection | Value (Proj/Salary*1000)
//
// Projection override behavior:
// - When a user clicks and edits the "Proj" cell, the value must be committed
//   to local component state immediately.
// - Commit on each valid numeric change and also on blur/enter.
// - Mark the player as "user_override" and show a pencil icon on modified rows.
// - If a player has multi-position eligibility, e.g. "1B/OF", modifying their
//   projection under the "1B" filter MUST automatically update the same player's
//   projection when the user switches the filter to "OF".
// - Maintain a central overriddenPlayers: Record<string, number> state in the
//   parent page component to sync values across position views.
// - Key overriddenPlayers by stable player id, not by rendered row index,
//   displayed position, or filter state.
//
// Parent page state contract:
// const [overriddenPlayers, setOverriddenPlayers] = useState<Record<string, number>>({});
//
// <PlayerPool
//   players={players}
//   overriddenPlayers={overriddenPlayers}
//   onProjectionOverride={(playerId, projection) => {
//     setOverriddenPlayers((prev) => ({ ...prev, [playerId]: projection }));
//   }}
// />
//
// The optimizer request payload must merge overriddenPlayers into the player pool
// before submission so generated lineups use user-edited projections.
//
// Show pitcher section separately at top (pitchers have different scoring)
//
// Bottom of table:
// "Last updated: 2 min ago · [Refresh]"
// "X of Y players have confirmed lineups"
```

### 5.4 Component: Lineup Grid

```typescript
// components/LineupGrid.tsx

// Display after optimization runs:
// 
// Tab row: [Lineup 1] [Lineup 2] ... [Lineup N]  
// 
// Per lineup card:
// ┌────────────────────────────────────┐
// │ Lineup #1              Proj: 48.3 │
// │ Salary: $49,800 / $50,000         │
// ├──────┬──────────────────┬──────────┤
// │ SLOT │ PLAYER           │ PROJ   $ │
// ├──────┼──────────────────┼──────────┤
// │  P   │ Gerrit Cole      │ 28.4 9k  │
// │  P   │ ...              │          │
// │  C   │ ...              │          │
// │  1B  │ ...              │          │
// │  2B  │ ...              │          │
// │  3B  │ ...              │          │
// │  SS  │ ...              │          │
// │  OF  │ ...              │          │
// │  OF  │ ...              │          │
// │  OF  │ ...              │          │
// │ UTIL │ ...              │          │
// └──────┴──────────────────┴──────────┘
//
// Bottom actions:
// [Copy to Clipboard]  [Download CSV]  [Upload to DK ↗]
//
// "Download All Lineups CSV" button (for multi-lineup MME entry)
// Format matches DraftKings bulk upload CSV exactly
//
// Stack indicator: highlight players from same team in matching color
// (e.g. all Yankees players have blue left border)
```

### 5.5 Data Fetching: `lib/api.ts`

```typescript
const API_URL = process.env.NEXT_PUBLIC_API_URL;

export async function fetchTodaysPlayers(): Promise<PlayerPoolResponse> {
  const res = await fetch(`${API_URL}/players/today`, {
    next: { revalidate: 120 }  // ISR: revalidate every 2 min
  });
  if (!res.ok) throw new Error('Failed to fetch players');
  return res.json();
}

export async function runOptimizer(request: OptimizeRequest): Promise<OptimizeResponse> {
  const res = await fetch(`${API_URL}/optimize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Optimization failed');
  }
  return res.json();
}
```

### 5.6 Loading States

```typescript
// While fetching player pool on page load:
// - Skeleton rows in player table (10 rows)
// - "Loading today's lineups..." status text

// While optimizer is running:
// - Button shows animated "Optimizing..." state
// - Rotating messages every 1.2s:
//   "Calculating split matchups..."
//   "Applying stacking rules..."
//   "Solving lineup constraints..."
//   "Almost there..."
// - Estimated time shown: "~2 seconds"

// On error:
// - Toast notification: red, specific error message
// - Retry button
```

### 5.7 CSV Upload (Custom Projections)

```typescript
// Accept CSV with header row: Name,Team,Projection
// Or accept DraftKings export CSV (auto-detect by column count)
// 
// On upload:
// 1. Parse CSV client-side (use papaparse)
// 2. Match by player Name (fuzzy match: normalize case, remove accents)
// 3. Override projected_points for matched players
// 4. Show match summary: "Matched 43/45 players. 2 not found: [names]"
// 5. Mark overridden players with "📊 Custom" badge
// 
// DraftKings export CSV columns (auto-detect):
// Position,Name+ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame
// When DK CSV detected: use AvgPointsPerGame as base projection seed
```

---

## 6. DraftKings Lineup Rules (Hard Constraints)

Implement these constraints exactly in the optimizer wrapper. pydfs handles most via `Site.DRAFTKINGS, Sport.BASEBALL`, but verify:

```
DK MLB Classic Roster:
- 2 P (starting pitchers)
- 1 C/1B
- 1 1B
- 1 2B
- 1 3B
- 1 SS
- 3 OF
- 1 UTIL (any non-pitcher)

Salary cap: $50,000
Min players per team: no restriction
Max players per team: no restriction (but optimizer settings may add one)
Stacking: no official rule, but conventional wisdom is 4-5 batters from same team

FD MLB Classic Roster:
- 1 P
- 1 C
- 1 1B
- 1 2B
- 1 3B
- 1 SS
- 3 OF
- 1 UTIL
Salary cap: $35,000
```

---

## 7. Error Handling & Edge Cases

### 7.1 Data gaps

```python
# If pybaseball returns empty dataframe for a player:
# → Fall back to player's season batting average × avg_game_duration_factor
# → Mark projection_source as "season_avg_fallback"
# → Show warning badge on player in UI

# If MLB-StatsAPI returns no lineup (game not yet posted):
# → Set batting_order = None, lineup_status = "unconfirmed"
# → Apply no batting order multiplier (use 1.0)
# → Show clock icon in Status column

# If optimizer has no feasible solution:
# → Check if too many locks make salary constraint impossible
# → Return 400 with message: "Salary constraint infeasible with current locks. Try removing some locked players."
```

### 7.2 No-games day

```python
# If no MLB games today (off-day, All-Star break):
# → GET /players/today returns { "players": [], "message": "No games scheduled today" }
# → Frontend shows "No games today" empty state with tomorrow's schedule
```

### 7.3 Rate limiting

```python
# pybaseball respects Baseball Savant rate limits automatically
# Add 0.5s delay between player batch requests to avoid 429s
# MLB-StatsAPI has no rate limit (official endpoint)
# Cache aggressively: all projection data cached for game day
```

---

## 8. SEO Configuration

### 8.1 Page metadata (`app/layout.tsx`)

```typescript
export const metadata: Metadata = {
  title: 'MLB Optimizer — Free DFS Lineup Builder | LineupLab',
  description: 'Free MLB DFS lineup optimizer for DraftKings and FanDuel. Auto-generates split-adjusted projections with confirmed starting lineups. Build 20 lineups free.',
  keywords: 'mlb optimizer, mlb dfs optimizer, draftkings mlb optimizer, fanduel mlb optimizer, free mlb lineup optimizer',
  openGraph: {
    title: 'MLB DFS Lineup Optimizer — Free | LineupLab',
    description: 'Optimize your MLB DFS lineups with split-adjusted projections and live lineup data. Free for 20 lineups.',
    url: 'https://lineuplab.io',
    type: 'website',
  },
  alternates: {
    canonical: 'https://lineuplab.io',
  }
};
```

### 8.2 Structured data (JSON-LD in `app/page.tsx`)

```typescript
const structuredData = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  "name": "LineupLab MLB Optimizer",
  "applicationCategory": "SportsApplication",
  "offers": {
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "USD"
  },
  "description": "Free MLB DFS lineup optimizer for DraftKings and FanDuel"
};
```

### 8.3 H1 tag

```html
<h1>Free MLB DFS Lineup Optimizer</h1>
<!-- Subheading below: "Build DraftKings & FanDuel lineups with split-adjusted projections and live starting lineups" -->
```

---

## 9. Deployment

### 9.1 Backend (Render)

```yaml
# render.yaml
services:
  - type: web
    name: lineuplab-api
    runtime: python
    buildCommand: pip install uv && uv sync
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT --workers 2
    envVars:
      - key: ALLOWED_ORIGINS
        value: https://lineuplab.io
    disk:
      name: cache
      mountPath: /app/cache
      sizeGB: 1
```

**Important:** Render free tier spins down after 15 min inactivity. Add a keep-alive ping from frontend every 10 min OR upgrade to $7/month instance. For MVP, add a note to frontend: "First load may take 15s if server is waking up."

### 9.2 Frontend (Vercel)

```json
// vercel.json
{
  "framework": "nextjs",
  "buildCommand": "next build",
  "outputDirectory": ".next",
  "env": {
    "NEXT_PUBLIC_API_URL": "https://lineuplab-api.onrender.com"
  }
}
```

---

## 10. Build Order (Strict Sequence for AI Agent)

Implement in this exact order. Do not proceed to next step until current step passes its validation test.

### Step 1: Projection engine validation
- [ ] Install pybaseball, statsapi, pandas
- [ ] Write `projections.py` with DK scoring constants
- [ ] Script: fetch Shohei Ohtani (MLBAM ID: 660271) game logs, past 15 days
- [ ] Calculate DK points per game row
- [ ] Calculate vs LHP and vs RHP split averages
- [ ] Print result: `{"player": "Ohtani", "projected_dk": X, "vs_lhp": Y, "vs_rhp": Z}`
- **Pass criteria:** Script runs without error, returns non-zero projection values

### Step 2: Lineup data validation
- [ ] Write `lineup_data.py` using statsapi
- [ ] Fetch today's games
- [ ] For one confirmed game, extract batting order for both teams
- [ ] Print first game's lineups with batting order and starter hand
- **Pass criteria:** Returns at least one game with ≥ 1 confirmed lineup

### Step 3: Optimizer validation
- [ ] Install pydfs-lineup-optimizer
- [ ] Write `optimizer.py` wrapper
- [ ] Load mock CSV of 20 players (hand-written: 2 SP, 2 C, 2 1B, 2 2B, 2 3B, 2 SS, 6 OF with salaries and projections)
- [ ] Generate 5 lineups with 4-man same-team stack
- [ ] Print all 5 lineups with total salary and projection
- **Pass criteria:** 5 unique lineups, all under $50,000, each has 4 players from one team

### Step 4: Full pipeline integration
- [ ] Wire Steps 1+2+3: given today's date, fetch players, calculate projections, run optimizer
- [ ] Test end-to-end with real today's data
- [ ] Identify any players missing data (handle gracefully)
- **Pass criteria:** Generates 5 valid DK lineups using today's real player pool

### Step 5: FastAPI backend
- [ ] Implement all three endpoints per Section 4
- [ ] Start server: `uvicorn main:app --reload`
- [ ] Test `/health` returns 200
- [ ] Test `/players/today` returns player list with projections
- [ ] Test `/optimize` with valid request body returns 5 lineups
- **Pass criteria:** All three endpoints return valid responses

### Step 6: Frontend
- [ ] `npx create-next-app@latest frontend --typescript --tailwind --app`
- [ ] Install shadcn/ui: `npx shadcn@latest init`
- [ ] Implement `SettingsPanel.tsx`
- [ ] Implement `PlayerPool.tsx` with filtering and lock/exclude
- [ ] Implement `LineupGrid.tsx` with CSV export
- [ ] Wire to backend API via `lib/api.ts`
- [ ] Test full flow: page loads → player pool shows → optimize → lineups appear → CSV downloads
- **Pass criteria:** Full end-to-end flow works in browser

### Step 7: Deploy
- [ ] Push to GitHub
- [ ] Deploy backend to Render, confirm `/health` responds
- [ ] Deploy frontend to Vercel, set `NEXT_PUBLIC_API_URL`
- [ ] Test production URL end-to-end
- **Pass criteria:** Live URL works from mobile browser

---

## 11. Out of Scope (Phase 2)

Do not implement these in the MVP:

- User accounts / authentication
- Monte Carlo GPP simulation
- Vegas implied totals integration
- Ownership % input and control
- NFL / NBA optimizer
- Blog / pSEO content pages
- Payment / Pro tier
- Email capture

---

## 12. Acceptance Criteria (MVP Done When)

1. User can visit the site and see today's MLB players with projections within 3 seconds
2. User can generate 5 DK lineups in under 5 seconds without uploading any CSV
3. User can upload a custom projections CSV and see their values reflected
4. User can lock/exclude players and re-run optimizer
5. User can download all lineups as a DraftKings-compatible bulk upload CSV
6. Confirmed lineups show green status; DNP players are greyed out and excluded automatically
7. Page H1 contains "MLB" and "Optimizer" for SEO
8. Site loads on mobile without horizontal scroll
9. Backend `/health` endpoint responds with cache age and player count
10. Render cold-start completes within 30 seconds
