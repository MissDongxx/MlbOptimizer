from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from services.season_cache import load_season_splits

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
    "pitcher_win": 4,
    "earned_run_allowed": -2,
    "strikeout_pitched": 2,
    "innings_pitched": 2.25,
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
    "pitcher_win": 6,
    "earned_run_allowed": -3,
    "strikeout_pitched": 3,
    "innings_pitched": 3,
}

BACKEND_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = BACKEND_DIR / "cache"

_projection_cache: dict[str, dict[str, Any]] = {}
_cache_timestamp: datetime | None = None


def batting_order_multiplier(position: int | None) -> float:
    if position in (1, 2):
        return 1.15
    if position in (3, 4):
        return 1.12
    if position in (5, 6):
        return 1.0
    if position == 7:
        return 0.92
    if position in (8, 9):
        return 0.85
    return 1.0


def get_split_projection(
    player_mlbam_id: int,
    opposing_pitcher_hand: str,
    batting_order_position: int | None,
    site: str = "dk",
) -> dict[str, Any]:
    season_cache = load_season_splits()
    player = season_cache.get("players", {}).get(str(player_mlbam_id), {})
    season_rates = player.get("season_rates", {})
    scoring = DK_SCORING if site == "dk" else FD_SCORING

    base_projection = _season_rate_projection(season_rates, scoring)
    split_key = "vs_L" if opposing_pitcher_hand == "L" else "vs_R"
    platoon_factor = float(player.get("splits", {}).get(split_key, {}).get("projection_factor", 1.0))
    order_multiplier = batting_order_multiplier(batting_order_position)
    projected_points = round(base_projection * platoon_factor * order_multiplier, 2)

    return {
        "player_id": player_mlbam_id,
        "projected_points": projected_points,
        "projection_source": "15d_counts_cached_season_splits",
        "vs_hand": opposing_pitcher_hand,
        "batting_order": batting_order_position,
        "batting_order_multiplier": order_multiplier,
        "platoon_factor": platoon_factor,
        "base_projection": round(base_projection, 2),
        "last_15_days_sample": 0,
        "season_cache_last_updated": season_cache.get("last_updated"),
        "last_updated": datetime.now(UTC).isoformat(),
    }


def get_pitcher_projection(player_mlbam_id: int, opposing_team_id: int, site: str = "dk") -> dict[str, Any]:
    scoring = DK_SCORING if site == "dk" else FD_SCORING
    base_projection = (
        5.3 * scoring["innings_pitched"]
        + 5.8 * scoring["strikeout_pitched"]
        + 0.34 * scoring["pitcher_win"]
        + 2.4 * scoring["earned_run_allowed"]
    )
    return {
        "player_id": player_mlbam_id,
        "projected_points": round(base_projection, 2),
        "projection_source": "season_avg_fallback",
        "vs_hand": None,
        "batting_order": None,
        "batting_order_multiplier": 1.0,
        "platoon_factor": 1.0,
        "base_projection": round(base_projection, 2),
        "opposing_team_id": opposing_team_id,
        "last_updated": datetime.now(UTC).isoformat(),
    }


def _season_rate_projection(season_rates: dict[str, Any], scoring: dict[str, float]) -> float:
    hits = float(season_rates.get("hits_per_game", 0.82) or 0.82)
    hr = float(season_rates.get("hr_per_game", 0.12) or 0.12)
    singles = max(0.0, hits - hr - 0.17)
    doubles = 0.14
    triples = 0.01
    return (
        singles * scoring["single"]
        + doubles * scoring["double"]
        + triples * scoring["triple"]
        + hr * scoring["home_run"]
        + float(season_rates.get("rbi_per_game", 0.42) or 0.42) * scoring["rbi"]
        + float(season_rates.get("runs_per_game", 0.45) or 0.45) * scoring["run"]
        + float(season_rates.get("walks_per_game", 0.32) or 0.32) * scoring["walk"]
        + float(season_rates.get("sb_per_game", 0.05) or 0.05) * scoring["stolen_base"]
    )


def projection_cache_key(game_date: str, site: str) -> str:
    return f"{game_date}:{site}"


def get_cached_projections(game_date: str, site: str) -> dict[str, Any] | None:
    key = projection_cache_key(game_date, site)
    cached = _projection_cache.get(key)
    if cached:
        return cached
    path = CACHE_DIR / f"projections_{game_date}_{site}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def set_cached_projections(game_date: str, site: str, data: dict[str, Any]) -> None:
    global _cache_timestamp
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = projection_cache_key(game_date, site)
    _projection_cache[key] = data
    _cache_timestamp = datetime.now(UTC)
    path = CACHE_DIR / f"projections_{game_date}_{site}.json"
    path.write_text(json.dumps(data, indent=2, default=str))


def get_cache_age() -> int | None:
    if _cache_timestamp is None:
        return None
    return int(time.time() - _cache_timestamp.timestamp())


def cache_ttl_seconds(first_pitch: datetime | None = None) -> int:
    if not first_pitch:
        return 3 * 60 * 60
    now = datetime.now(UTC)
    if timedelta(0) <= first_pitch - now <= timedelta(minutes=90):
        return 10 * 60
    return 3 * 60 * 60
