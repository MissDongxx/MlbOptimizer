from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = BACKEND_DIR / "cache"
SEASON_SPLITS_PATH = CACHE_DIR / "season_splits.json"


def _empty_cache(season: int | None = None) -> dict[str, Any]:
    return {
        "last_updated": datetime.now(UTC).isoformat(),
        "season": season or datetime.now(UTC).year,
        "players": {},
    }


def load_season_splits() -> dict[str, Any]:
    if not SEASON_SPLITS_PATH.exists():
        return _empty_cache()
    try:
        return json.loads(SEASON_SPLITS_PATH.read_text())
    except json.JSONDecodeError:
        logger.exception("season_splits.json is invalid; using empty fallback")
        return _empty_cache()


def write_season_splits(data: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = SEASON_SPLITS_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True))
    os.replace(tmp_path, SEASON_SPLITS_PATH)


def refresh_season_splits(current_year: int | None = None) -> dict[str, Any]:
    """
    Daily pre-fetch job. It intentionally uses pybaseball.batting_stats() only here,
    never from request-time projection paths.
    """
    season = current_year or datetime.now(UTC).year
    try:
        import pybaseball  # type: ignore
    except ImportError:
        logger.warning("pybaseball is not installed; writing empty season cache")
        data = _empty_cache(season)
        write_season_splits(data)
        return data

    try:
        df = pybaseball.batting_stats(season)
    except Exception:
        logger.exception("pybaseball.batting_stats failed; preserving previous cache if present")
        return load_season_splits()

    players: dict[str, Any] = {}
    for _, row in df.iterrows():
        mlbam_id = _first_present(row, ["IDfg", "mlbam_id", "MLBAMID", "ID"])
        if mlbam_id is None:
            continue
        games = float(row.get("G", 0) or 0)
        divisor = games if games > 0 else 1
        ops = float(row.get("OPS", 0) or 0)
        projection_factor = max(0.75, min(1.25, 1 + ((ops - 0.72) * 0.25)))
        players[str(int(mlbam_id))] = {
            "name": str(row.get("Name", "")),
            "mlbam_id": int(mlbam_id),
            "team": str(row.get("Team", "")),
            "season_rates": {
                "games": int(games),
                "pa": int(row.get("PA", 0) or 0),
                "hits_per_game": round(float(row.get("H", 0) or 0) / divisor, 3),
                "hr_per_game": round(float(row.get("HR", 0) or 0) / divisor, 3),
                "rbi_per_game": round(float(row.get("RBI", 0) or 0) / divisor, 3),
                "runs_per_game": round(float(row.get("R", 0) or 0) / divisor, 3),
                "walks_per_game": round(float(row.get("BB", 0) or 0) / divisor, 3),
                "sb_per_game": round(float(row.get("SB", 0) or 0) / divisor, 3),
            },
            "splits": {
                "vs_L": {"projection_factor": 1.0, "ops": ops, "woba": float(row.get("wOBA", 0) or 0)},
                "vs_R": {
                    "projection_factor": round(projection_factor, 3),
                    "ops": ops,
                    "woba": float(row.get("wOBA", 0) or 0),
                },
            },
        }

    data = {"last_updated": datetime.now(UTC).isoformat(), "season": season, "players": players}
    write_season_splits(data)
    return data


def _first_present(row: Any, keys: list[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value == value:
            return value
    return None
