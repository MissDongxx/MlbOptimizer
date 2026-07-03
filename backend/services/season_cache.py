from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from services.cache_store import cache_store

logger = logging.getLogger(__name__)

SEASON_SPLITS_KEY = "season_splits"


def _empty_cache(season: int | None = None) -> dict[str, Any]:
    return {
        "last_updated": datetime.now(UTC).isoformat(),
        "season": season or datetime.now(UTC).year,
        "players": {},
    }


def load_season_splits() -> dict[str, Any]:
    data = cache_store.read_json(SEASON_SPLITS_KEY)
    if data is None:
        return _empty_cache()
    if not isinstance(data, dict):
        logger.error("season_splits.json is invalid; using empty fallback")
        return _empty_cache()
    return data


def season_cache_health() -> dict[str, Any]:
    if not cache_store.exists(SEASON_SPLITS_KEY):
        return {"exists": False, "age_hours": None, "players": 0, "last_updated": None}
    data = load_season_splits()
    last_updated = data.get("last_updated")
    age_hours = None
    if last_updated:
        try:
            parsed = datetime.fromisoformat(str(last_updated).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            age_hours = round((datetime.now(UTC) - parsed).total_seconds() / 3600, 2)
        except ValueError:
            age_hours = None
    return {
        "exists": True,
        "age_hours": age_hours,
        "players": len(data.get("players", {})),
        "last_updated": last_updated,
    }


def write_season_splits(data: dict[str, Any]) -> None:
    cache_store.write_json(SEASON_SPLITS_KEY, data)


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

    id_lookup = _build_player_id_lookup(df, pybaseball)
    players: dict[str, Any] = {}
    for _, row in df.iterrows():
        pybaseball_id = _first_present(row, ["IDfg", "key_fangraphs", "ID"])
        mlbam_id = _first_present(row, ["mlbam_id", "MLBAMID", "key_mlbam"])
        bbref_id = _first_present(row, ["key_bbref", "bbref_id", "IDbbref"])
        if mlbam_id is None and pybaseball_id is not None:
            lookup_record = id_lookup.get(str(int(float(pybaseball_id))), {})
            mlbam_id = lookup_record.get("mlbam_id")
            bbref_id = bbref_id or lookup_record.get("bbref_id")
        if mlbam_id is None:
            continue
        games = float(row.get("G", 0) or 0)
        divisor = games if games > 0 else 1
        ops = _float_stat(row, "OPS")
        woba = _float_stat(row, "wOBA")
        iso = _float_stat(row, "ISO")
        k_rate = _float_stat(row, "K%")
        bb_rate = _float_stat(row, "BB%")
        projection_factor = max(0.75, min(1.25, 1 + ((ops - 0.72) * 0.25)))
        players[str(int(mlbam_id))] = {
            "name": str(row.get("Name", "")),
            "mlbam_id": int(mlbam_id),
            "fangraphs_id": int(float(pybaseball_id)) if pybaseball_id is not None else None,
            "bbref_id": str(bbref_id) if bbref_id else None,
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
            "advanced_metrics": {
                "woba": round(woba, 3),
                "iso": round(iso, 3),
                "k_rate": round(k_rate, 3),
                "bb_rate": round(bb_rate, 3),
            },
            "splits": {
                "vs_L": {
                    "projection_factor": 1.0,
                    "ops": ops,
                    "woba": woba,
                    "iso": iso,
                    "k_rate": k_rate,
                    "bb_rate": bb_rate,
                    "sample_note": "season_overall_fallback",
                },
                "vs_R": {
                    "projection_factor": round(projection_factor, 3),
                    "ops": ops,
                    "woba": woba,
                    "iso": iso,
                    "k_rate": k_rate,
                    "bb_rate": bb_rate,
                    "sample_note": "season_overall_fallback",
                },
            },
        }

    data = {"last_updated": datetime.now(UTC).isoformat(), "season": season, "players": players}
    write_season_splits(data)
    return data


def refresh_batter_hand_splits(
    player_mlbam_ids: list[int],
    current_year: int | None = None,
    max_players: int = 80,
) -> dict[str, Any]:
    """
    Enrich the season cache with true Baseball Reference handedness splits.
    This is intentionally a cached background/data-refresh path, not request-time projection work.
    """
    data = load_season_splits()
    season = current_year or int(data.get("season") or datetime.now(UTC).year)
    try:
        import pybaseball  # type: ignore
    except ImportError:
        logger.warning("pybaseball is not installed; skipping handedness split enrichment")
        return data

    enriched = 0
    for mlbam_id in _unique_ints(player_mlbam_ids)[:max_players]:
        player = data.get("players", {}).get(str(mlbam_id))
        if not player or player.get("position") == "P":
            continue
        if not _needs_split_refresh(player):
            continue
        bbref_id = player.get("bbref_id")
        if not bbref_id:
            continue
        try:
            split_data = pybaseball.get_splits(str(bbref_id), year=season)
            hand_splits = _extract_hand_splits(split_data, player.get("splits", {}))
        except Exception:
            logger.exception("failed to refresh Baseball Reference splits for %s", mlbam_id)
            continue
        if not hand_splits:
            continue
        player.setdefault("splits", {}).update(hand_splits)
        player["split_cache_last_updated"] = datetime.now(UTC).isoformat()
        enriched += 1

    data["handedness_splits_last_updated"] = datetime.now(UTC).isoformat()
    data["handedness_splits_players"] = enriched
    write_season_splits(data)
    return data


def _first_present(row: Any, keys: list[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value == value:
            return value
    return None


def _float_stat(row: Any, key: str, default: float = 0.0) -> float:
    value = row.get(key, default)
    if value is None or value != value:
        return default
    if isinstance(value, str):
        value = value.strip().replace("%", "")
        if not value:
            return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if key.endswith("%") and parsed > 1:
        parsed /= 100
    return parsed


def _build_player_id_lookup(df: Any, pybaseball: Any) -> dict[str, dict[str, Any]]:
    fangraphs_ids: list[int] = []
    for _, row in df.iterrows():
        value = _first_present(row, ["IDfg", "key_fangraphs", "ID"])
        if value is None:
            continue
        try:
            fangraphs_ids.append(int(float(value)))
        except (TypeError, ValueError):
            continue

    if not fangraphs_ids or not hasattr(pybaseball, "playerid_reverse_lookup"):
        return {}

    try:
        lookup_df = pybaseball.playerid_reverse_lookup(
            sorted(set(fangraphs_ids)), key_type="fangraphs"
        )
    except Exception:
        logger.exception("pybaseball.playerid_reverse_lookup failed; player id map unavailable")
        return {}

    lookup: dict[str, dict[str, Any]] = {}
    for _, row in lookup_df.iterrows():
        fangraphs_id = _first_present(row, ["key_fangraphs", "IDfg", "fangraphs_id"])
        mlbam_id = _first_present(row, ["key_mlbam", "mlbam_id", "MLBAMID"])
        bbref_id = _first_present(row, ["key_bbref", "bbref_id", "IDbbref"])
        if fangraphs_id is None:
            continue
        try:
            lookup[str(int(float(fangraphs_id)))] = {
                "mlbam_id": int(float(mlbam_id)) if mlbam_id is not None else None,
                "bbref_id": str(bbref_id) if bbref_id else None,
            }
        except (TypeError, ValueError):
            continue
    return lookup


def _build_mlbam_lookup(df: Any, pybaseball: Any) -> dict[str, int]:
    player_lookup = _build_player_id_lookup(df, pybaseball)
    return {
        fangraphs_id: int(record["mlbam_id"])
        for fangraphs_id, record in player_lookup.items()
        if record.get("mlbam_id") is not None
    }


def _extract_hand_splits(split_data: Any, fallback_splits: dict[str, Any]) -> dict[str, dict[str, Any]]:
    splits: dict[str, dict[str, Any]] = {}
    overall_ops = _fallback_ops(fallback_splits)
    for key, labels in {
        "vs_L": ("vs LHP", "vs LHB"),
        "vs_R": ("vs RHP", "vs RHB"),
    }.items():
        row = _find_split_row(split_data, labels)
        if row is None:
            continue
        pa = _row_float(row, "PA")
        if pa < 10:
            continue
        ops = _row_float(row, "OPS")
        iso = _split_iso(row)
        bb_rate = _rate_from_row(row, "BB", pa)
        k_rate = _rate_from_row(row, "SO", pa)
        projection_factor = _split_projection_factor(ops, overall_ops)
        splits[key] = {
            "projection_factor": projection_factor,
            "ops": round(ops, 3),
            "iso": round(iso, 3),
            "k_rate": round(k_rate, 3),
            "bb_rate": round(bb_rate, 3),
            "pa": int(pa),
            "sample_note": "baseball_reference_handedness_split",
        }
    return splits


def _find_split_row(split_data: Any, labels: tuple[str, ...]) -> Any | None:
    for _, row in split_data.iterrows():
        index_values = row.name if isinstance(row.name, tuple) else (row.name,)
        normalized = {_normalize_split_label(value) for value in index_values}
        if any(_normalize_split_label(label) in normalized for label in labels):
            return row
    return None


def _split_projection_factor(ops: float, overall_ops: float) -> float:
    if ops <= 0:
        return 1.0
    baseline = overall_ops if overall_ops > 0 else 0.72
    return round(max(0.82, min(1.18, 1 + ((ops - baseline) * 0.35))), 3)


def _fallback_ops(fallback_splits: dict[str, Any]) -> float:
    values = []
    for split in fallback_splits.values():
        try:
            ops = float(split.get("ops", 0) or 0)
        except (AttributeError, TypeError, ValueError):
            ops = 0
        if ops > 0:
            values.append(ops)
    return sum(values) / len(values) if values else 0.72


def _split_iso(row: Any) -> float:
    iso = _row_float(row, "ISO")
    if iso > 0:
        return iso
    ab = _row_float(row, "AB")
    hits = _row_float(row, "H")
    total_bases = _row_float(row, "TB")
    if ab <= 0 or total_bases <= 0:
        return 0.0
    return max(0.0, (total_bases - hits) / ab)


def _rate_from_row(row: Any, stat: str, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return _row_float(row, stat) / denominator


def _row_float(row: Any, key: str) -> float:
    try:
        value = row.get(key, 0)
    except AttributeError:
        return 0.0
    if value is None or value != value:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_split_label(value: Any) -> str:
    return " ".join(str(value).strip().lower().split())


def _unique_ints(values: list[int]) -> list[int]:
    unique: list[int] = []
    seen: set[int] = set()
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed in seen:
            continue
        seen.add(parsed)
        unique.append(parsed)
    return unique


def _needs_split_refresh(player: dict[str, Any]) -> bool:
    last_updated = player.get("split_cache_last_updated")
    if not last_updated:
        return True
    try:
        parsed = datetime.fromisoformat(str(last_updated).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.date() != datetime.now(UTC).date()
