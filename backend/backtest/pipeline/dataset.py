from __future__ import annotations

import csv
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from backtest.contracts import SlateActualPoints, SlateFeatureSnapshot, _is_prohibited_feature_key
from backtest.io import load_json, write_json
from backtest.pipeline.registry import sha256_file


BASE_FEATURES = (
    "salary",
    "batting_order",
    "is_confirmed",
    "is_expected",
    "is_unconfirmed",
    "position_p",
    "position_c",
    "position_1b",
    "position_2b",
    "position_3b",
    "position_ss",
    "position_of",
)
_IDENTIFIER_COLUMNS = {
    "slate_id",
    "slate_sha256",
    "site",
    "slate_start",
    "slate_date",
    "game_start",
    "feature_available_at",
    "mlbam_id",
    "role",
    "legacy_projection",
    "target_actual_points",
}


class DatasetError(ValueError):
    pass


def build_training_dataset(
    entries: Iterable[dict[str, Any]],
    *,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_rows: list[dict[str, Any]] = []
    slate_hashes: dict[str, dict[str, str]] = {}
    custom_features: set[str] = set()

    for entry in sorted(entries, key=lambda item: str(item["slate_id"])):
        if entry.get("state") not in {"qualified", "backtested"}:
            continue
        feature_path = Path(str(entry["feature_file"]))
        actuals_path = Path(str(entry["actuals_file"]))
        features = SlateFeatureSnapshot.model_validate(load_json(feature_path))
        actuals = SlateActualPoints.model_validate(load_json(actuals_path))
        if features.data_kind != "real" or actuals.data_kind != "real":
            raise DatasetError(f"non-real slate entered qualified dataset: {features.slate_id}")
        actual_by_id = {item.mlbam_id: item.actual_points for item in actuals.points}
        game_by_id = {game.game_id: game for game in features.games}
        available_at = max(
            (source.available_at or source.published_at or source.fetched_at)
            for source in features.sources
        )
        for player in sorted(features.players, key=lambda item: item.mlbam_id):
            game = game_by_id.get(player.game_id)
            if game is None:
                raise DatasetError(f"player {player.mlbam_id} has no game mapping")
            if available_at >= game.scheduled_start:
                raise DatasetError(
                    f"event-time leakage for {features.slate_id}/{player.mlbam_id}: "
                    f"available_at={available_at.isoformat()} first_pitch={game.scheduled_start.isoformat()}"
                )
            if player.mlbam_id not in actual_by_id:
                raise DatasetError(f"missing target for {features.slate_id}/{player.mlbam_id}")
            row = _feature_row(features, player, game.scheduled_start, available_at, sha256_file(feature_path))
            for key, value in player.feature_values.items():
                safe = _safe_custom_feature_name(key)
                if safe is None:
                    continue
                if isinstance(value, bool):
                    row[safe] = float(value)
                    custom_features.add(safe)
                elif isinstance(value, (int, float)):
                    row[safe] = float(value)
                    custom_features.add(safe)
            row["target_actual_points"] = float(actual_by_id[player.mlbam_id])
            raw_rows.append(row)
        slate_hashes[features.slate_id] = {
            "features_sha256": sha256_file(feature_path),
            "actuals_sha256": sha256_file(actuals_path),
        }

    if not raw_rows:
        raise DatasetError("no qualified real rows are available")
    feature_schema = list(BASE_FEATURES) + sorted(custom_features)
    rows = []
    for row in raw_rows:
        normalized = dict(row)
        for feature in feature_schema:
            normalized[feature] = float(normalized.get(feature, 0.0) or 0.0)
        rows.append(normalized)
    rows.sort(key=lambda item: (item["slate_start"], item["slate_id"], item["role"], item["mlbam_id"]))

    csv_path = output_dir / "qualified-training-dataset.csv"
    fields = [
        "slate_id",
        "slate_sha256",
        "site",
        "slate_start",
        "slate_date",
        "game_start",
        "feature_available_at",
        "mlbam_id",
        "role",
        "legacy_projection",
        *feature_schema,
        "target_actual_points",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})
    dataset_hash = sha256_file(csv_path)
    dates = sorted({str(row["slate_date"]) for row in rows})
    manifest = {
        "schema_version": "1.0",
        "status": "BUILT_FROM_QUALIFIED_REAL_SLATES",
        "dataset_file": csv_path.name,
        "dataset_sha256": dataset_hash,
        "row_count": len(rows),
        "slate_count": len(slate_hashes),
        "date_count": len(dates),
        "date_min": dates[0],
        "date_max": dates[-1],
        "feature_schema": feature_schema,
        "target": "target_actual_points",
        "legacy_projection": "legacy_projection",
        "event_time_rule": "feature_available_at < player game first pitch",
        "same_day_rule": "all model splits use whole UTC slate dates; no same-day row crosses a split",
        "prohibited_fields": [
            "AvgPointsPerGame",
            "actual/final/boxscore/outcome fields as features",
            "postgame statistics",
        ],
        "slate_hashes": slate_hashes,
    }
    manifest_path = output_dir / "qualified-training-dataset.manifest.json"
    write_json(manifest_path, manifest)
    return {
        **manifest,
        "dataset_path": str(csv_path.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "rows": rows,
    }


def load_dataset_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, Any]] = []
        for raw in reader:
            row: dict[str, Any] = dict(raw)
            row["mlbam_id"] = int(raw["mlbam_id"])
            for key, value in raw.items():
                if key in _IDENTIFIER_COLUMNS or key in {"role", "site"}:
                    continue
                row[key] = float(value)
            row["legacy_projection"] = float(raw["legacy_projection"])
            row["target_actual_points"] = float(raw["target_actual_points"])
            rows.append(row)
    return rows


def feature_vector_for_player(features: SlateFeatureSnapshot, player: Any, schema: list[str]) -> dict[str, float]:
    row = _base_numeric_features(player)
    for key, value in player.feature_values.items():
        safe = _safe_custom_feature_name(key)
        if safe and isinstance(value, (bool, int, float)):
            row[safe] = float(value)
    return {feature: float(row.get(feature, 0.0) or 0.0) for feature in schema}


def _feature_row(
    features: SlateFeatureSnapshot,
    player: Any,
    game_start: datetime,
    available_at: datetime,
    feature_hash: str,
) -> dict[str, Any]:
    return {
        "slate_id": features.slate_id,
        "slate_sha256": feature_hash,
        "site": features.site,
        "slate_start": features.slate_start.isoformat(),
        "slate_date": features.slate_start.astimezone(UTC).date().isoformat(),
        "game_start": game_start.isoformat(),
        "feature_available_at": available_at.isoformat(),
        "mlbam_id": player.mlbam_id,
        "role": "pitcher" if {p.upper() for p in player.position} == {"P"} else "hitter",
        "legacy_projection": float(player.projected_points),
        **_base_numeric_features(player),
    }


def _base_numeric_features(player: Any) -> dict[str, float]:
    positions = {str(item).upper() for item in player.position}
    return {
        "salary": float(player.salary),
        "batting_order": float(player.batting_order or 0),
        "is_confirmed": float(player.lineup_status == "confirmed"),
        "is_expected": float(player.lineup_status == "expected"),
        "is_unconfirmed": float(player.lineup_status == "unconfirmed"),
        "position_p": float(positions == {"P"}),
        "position_c": float("C" in positions),
        "position_1b": float("1B" in positions or "C/1B" in positions),
        "position_2b": float("2B" in positions),
        "position_3b": float("3B" in positions),
        "position_ss": float("SS" in positions),
        "position_of": float("OF" in positions),
    }


def _safe_custom_feature_name(key: object) -> str | None:
    text = str(key).strip()
    if not text or _is_prohibited_feature_key(text):
        return None
    compact = re.sub(r"[^a-z0-9]", "", text.lower())
    if "avgpointspergame" in compact or text.lower().endswith("available_at"):
        return None
    normalized = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return f"fv_{normalized}" if normalized else None
