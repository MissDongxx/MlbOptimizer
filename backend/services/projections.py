from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from services.cache_store import cache_store
from services.park_factors import get_park_factor, hitter_park_multiplier
from services.season_cache import load_season_splits
from services.vegas import get_team_vegas_context, vegas_team_multiplier
from services.weather import get_weather_context, weather_multiplier

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

_projection_cache: dict[str, dict[str, Any]] = {}
_cache_timestamp: datetime | None = None
_player_log_cache: dict[str, dict[str, Any]] = {}


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
    venue: str | None = None,
    team: str | None = None,
) -> dict[str, Any]:
    season_cache = load_season_splits()
    player = season_cache.get("players", {}).get(str(player_mlbam_id), {})
    season_rates = player.get("season_rates", {})
    advanced_metrics = player.get("advanced_metrics", {})
    scoring = DK_SCORING if site == "dk" else FD_SCORING

    season_projection = _season_rate_projection(season_rates, scoring)
    last_15_counts = get_last_15_day_counts(player_mlbam_id)
    last_15_projection = 0.0
    if last_15_counts.get("games", 0) >= 3:
        last_15_projection = _counts_projection(last_15_counts, scoring) / max(float(last_15_counts["games"]), 1.0)
        recent_form_factor = _recent_form_factor(season_projection, last_15_projection, int(last_15_counts["games"]))
        projection_source = "season_with_15d_form_blend"
    else:
        recent_form_factor = 1.0
        projection_source = "season_avg_fallback"

    split_key = "vs_L" if opposing_pitcher_hand == "L" else "vs_R" if opposing_pitcher_hand == "R" else None
    platoon_factor = (
        float(player.get("splits", {}).get(split_key, {}).get("projection_factor", 1.0))
        if split_key
        else 1.0
    )
    skill_factor = _advanced_skill_factor(advanced_metrics)
    order_multiplier = batting_order_multiplier(batting_order_position)
    park_multiplier = hitter_park_multiplier(venue)
    vegas_multiplier = vegas_team_multiplier(team)
    weather_factor = weather_multiplier(venue)
    raw_adjustment = (
        platoon_factor
        * skill_factor
        * recent_form_factor
        * order_multiplier
        * park_multiplier
        * vegas_multiplier
        * weather_factor
    )
    final_adjustment = _clamp(raw_adjustment, 0.75, 1.3)
    projected_points = round(season_projection * final_adjustment, 2)
    park_factor = get_park_factor(venue)
    vegas_context = get_team_vegas_context(team)
    weather_context = get_weather_context(venue)

    return {
        "player_id": player_mlbam_id,
        "projected_points": projected_points,
        "projection_source": projection_source,
        "vs_hand": opposing_pitcher_hand,
        "batting_order": batting_order_position,
        "batting_order_multiplier": order_multiplier,
        "platoon_factor": platoon_factor,
        "skill_factor": skill_factor,
        "recent_form_factor": recent_form_factor,
        "park_multiplier": park_multiplier,
        "vegas_multiplier": vegas_multiplier,
        "weather_multiplier": weather_factor,
        "raw_adjustment": round(raw_adjustment, 3),
        "final_adjustment": round(final_adjustment, 3),
        "base_projection": round(season_projection, 2),
        "season_projection": round(season_projection, 2),
        "last_15_projection": round(last_15_projection, 2),
        "last_15_days_sample": int(last_15_counts.get("games", 0)),
        "advanced_metrics": advanced_metrics,
        "park_factor": park_factor,
        "vegas_context": vegas_context,
        "weather_context": weather_context,
        "season_cache_last_updated": season_cache.get("last_updated"),
        "last_updated": datetime.now(UTC).isoformat(),
    }


def get_last_15_day_counts(player_mlbam_id: int) -> dict[str, Any]:
    today = date.today().isoformat()
    cache_key = f"{today}:{player_mlbam_id}"
    if cache_key in _player_log_cache:
        return _player_log_cache[cache_key]

    file_cache = _load_player_log_file(today)
    if cache_key in file_cache:
        _player_log_cache[cache_key] = file_cache[cache_key]
        return file_cache[cache_key]

    counts = _empty_count_stats(player_mlbam_id)
    try:
        import statsapi  # type: ignore

        end_date = date.today()
        start_date = end_date - timedelta(days=15)
        data = statsapi.player_stat_data(
            player_mlbam_id,
            group="hitting",
            type="gameLog",
            sportId=1,
            startDate=start_date.strftime("%m/%d/%Y"),
            endDate=end_date.strftime("%m/%d/%Y"),
        )
        for split in data.get("stats", [{}])[0].get("splits", []):
            stat = split.get("stat", {})
            counts["games"] += 1
            counts["hits"] += _int_stat(stat, "hits")
            counts["doubles"] += _int_stat(stat, "doubles")
            counts["triples"] += _int_stat(stat, "triples")
            counts["home_runs"] += _int_stat(stat, "homeRuns")
            counts["rbi"] += _int_stat(stat, "rbi")
            counts["runs"] += _int_stat(stat, "runs")
            counts["walks"] += _int_stat(stat, "baseOnBalls")
            counts["hit_by_pitch"] += _int_stat(stat, "hitByPitch")
            counts["stolen_bases"] += _int_stat(stat, "stolenBases")
    except Exception:
        counts = _empty_count_stats(player_mlbam_id)

    file_cache[cache_key] = counts
    _player_log_cache[cache_key] = counts
    _write_player_log_file(today, file_cache)
    return counts


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


def _counts_projection(counts: dict[str, Any], scoring: dict[str, float]) -> float:
    hits = float(counts.get("hits", 0) or 0)
    doubles = float(counts.get("doubles", 0) or 0)
    triples = float(counts.get("triples", 0) or 0)
    home_runs = float(counts.get("home_runs", 0) or 0)
    singles = max(0.0, hits - doubles - triples - home_runs)
    return (
        singles * scoring["single"]
        + doubles * scoring["double"]
        + triples * scoring["triple"]
        + home_runs * scoring["home_run"]
        + float(counts.get("rbi", 0) or 0) * scoring["rbi"]
        + float(counts.get("runs", 0) or 0) * scoring["run"]
        + float(counts.get("walks", 0) or 0) * scoring["walk"]
        + float(counts.get("hit_by_pitch", 0) or 0) * scoring.get("hit_by_pitch", 0)
        + float(counts.get("stolen_bases", 0) or 0) * scoring["stolen_base"]
    )


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


def _recent_form_factor(season_projection: float, last_15_projection: float, games: int) -> float:
    if season_projection <= 0 or last_15_projection <= 0 or games < 3:
        return 1.0
    sample_weight = _clamp(games / 15, 0.1, 0.35)
    recent_ratio = _clamp(last_15_projection / season_projection, 0.65, 1.5)
    return round(1 + ((recent_ratio - 1) * sample_weight), 3)


def _advanced_skill_factor(metrics: dict[str, Any]) -> float:
    woba = _float_metric(metrics, "woba", 0.32)
    iso = _float_metric(metrics, "iso", 0.17)
    k_rate = _float_metric(metrics, "k_rate", 0.22)
    bb_rate = _float_metric(metrics, "bb_rate", 0.085)
    factor = (
        1
        + ((woba - 0.32) * 0.45)
        + ((iso - 0.17) * 0.35)
        + ((bb_rate - 0.085) * 0.8)
        - ((k_rate - 0.22) * 0.35)
    )
    return round(_clamp(factor, 0.92, 1.1), 3)


def _float_metric(metrics: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(metrics.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def projection_cache_key(game_date: str, site: str) -> str:
    return f"{game_date}:{site}"


def get_cached_projections(game_date: str, site: str) -> dict[str, Any] | None:
    key = projection_cache_key(game_date, site)
    cached = _projection_cache.get(key)
    if cached:
        return cached
    data = cache_store.read_json(f"projections_{game_date}_{site}")
    return data if isinstance(data, dict) else None


def set_cached_projections(game_date: str, site: str, data: dict[str, Any]) -> None:
    global _cache_timestamp
    key = projection_cache_key(game_date, site)
    _projection_cache[key] = data
    _cache_timestamp = datetime.now(UTC)
    cache_store.write_json(f"projections_{game_date}_{site}", data)


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


def _empty_count_stats(player_mlbam_id: int) -> dict[str, Any]:
    return {
        "player_id": player_mlbam_id,
        "games": 0,
        "hits": 0,
        "doubles": 0,
        "triples": 0,
        "home_runs": 0,
        "rbi": 0,
        "runs": 0,
        "walks": 0,
        "hit_by_pitch": 0,
        "stolen_bases": 0,
        "last_updated": datetime.now(UTC).isoformat(),
    }


def _int_stat(stat: dict[str, Any], key: str) -> int:
    try:
        return int(stat.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _load_player_log_file(game_date: str) -> dict[str, dict[str, Any]]:
    data = cache_store.read_json(f"player_logs_{game_date}", default={})
    return data if isinstance(data, dict) else {}


def _write_player_log_file(game_date: str, data: dict[str, dict[str, Any]]) -> None:
    cache_store.write_json(f"player_logs_{game_date}", data)
