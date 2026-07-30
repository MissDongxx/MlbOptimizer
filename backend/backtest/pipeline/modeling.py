from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from backtest.contracts import SlateFeatureSnapshot
from backtest.io import load_json, write_json
from backtest.pipeline.dataset import feature_vector_for_player
from backtest.pipeline.registry import sha256_file


ROLES = ("hitter", "pitcher")


class ModelError(ValueError):
    pass


@dataclass(frozen=True)
class SplitResult:
    train_dates: list[str]
    test_dates: list[str]
    train_rows: list[dict[str, Any]]
    test_rows: list[dict[str, Any]]


def chronological_holdout_split(
    rows: list[dict[str, Any]],
    *,
    test_fraction: float,
    min_train_slates: int,
    min_test_slates: int,
) -> SplitResult:
    dates = sorted({str(row["slate_date"]) for row in rows})
    if len(dates) < min_train_slates + min_test_slates:
        raise ModelError(
            f"insufficient chronological slates: {len(dates)} < "
            f"{min_train_slates + min_test_slates}"
        )
    desired_test = max(min_test_slates, int(math.ceil(len(dates) * test_fraction)))
    desired_test = min(desired_test, len(dates) - min_train_slates)
    if desired_test < min_test_slates:
        raise ModelError("chronological split cannot satisfy minimum test slates")
    test_dates = dates[-desired_test:]
    train_dates = dates[:-desired_test]
    boundary = test_dates[0]
    train_rows = [row for row in rows if str(row["slate_date"]) < boundary]
    test_rows = [row for row in rows if str(row["slate_date"]) >= boundary]
    if {str(row["slate_date"]) for row in train_rows}.intersection(
        str(row["slate_date"]) for row in test_rows
    ):
        raise ModelError("same-day rows crossed the chronological split")
    return SplitResult(train_dates, test_dates, train_rows, test_rows)


def train_candidate_model(
    *,
    rows: list[dict[str, Any]],
    feature_schema: list[str],
    output_dir: Path,
    dataset_sha256: str,
    slate_hashes: dict[str, dict[str, str]],
    code_version: str,
    seed: int,
    ridge_alpha: float,
    test_fraction: float,
    min_train_slates: int,
    min_test_slates: int,
    min_test_rows_per_role: int,
    required_mae_relative_improvement: float,
    max_rmse_relative_regression: float,
    max_correlation_drop: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "promotion-report.json"
    card_path = output_dir / "MODEL_CARD.md"
    try:
        split = chronological_holdout_split(
            rows,
            test_fraction=test_fraction,
            min_train_slates=min_train_slates,
            min_test_slates=min_test_slates,
        )
    except ModelError as exc:
        report = _rejected_not_evaluated_report(
            reason=str(exc),
            row_count=len(rows),
            date_count=len({str(row["slate_date"]) for row in rows}),
            min_train_slates=min_train_slates,
            min_test_slates=min_test_slates,
            dataset_sha256=dataset_sha256,
        )
        write_json(report_path, report)
        card_path.write_text(_model_card(report, None), encoding="utf-8")
        return _result_paths(report, report_path, card_path, None)

    role_models: dict[str, Any] = {}
    fixed_holdout_predictions: list[dict[str, Any]] = []
    role_metrics: dict[str, Any] = {}
    role_gates: dict[str, Any] = {}
    training_shortfalls: list[str] = []
    for role in ROLES:
        train_role = [row for row in split.train_rows if row["role"] == role]
        test_role = [row for row in split.test_rows if row["role"] == role]
        if not train_role:
            training_shortfalls.append(f"{role}: no training rows")
            continue
        if len(test_role) < min_test_rows_per_role:
            training_shortfalls.append(
                f"{role}: test rows {len(test_role)} < {min_test_rows_per_role}"
            )
        model = fit_ridge(train_role, feature_schema, alpha=ridge_alpha)
        role_models[role] = model
        predictions = predict_rows(model, test_role)
        fixed_holdout_predictions.extend(predictions)
        metrics = compare_predictions(predictions)
        role_metrics[role] = metrics
        role_gates[role] = _metric_gates(
            metrics,
            min_rows=min_test_rows_per_role,
            required_mae_relative_improvement=required_mae_relative_improvement,
            max_rmse_relative_regression=max_rmse_relative_regression,
            max_correlation_drop=max_correlation_drop,
        )

    walk_forward = expanding_walk_forward_validation(
        split.train_rows,
        feature_schema=feature_schema,
        alpha=ridge_alpha,
        min_train_dates=max(2, min(5, len(split.train_dates) - 1)),
    )
    overall_metrics = compare_predictions(fixed_holdout_predictions) if fixed_holdout_predictions else None
    determinism = _determinism_check(split.train_rows, feature_schema, ridge_alpha, role_models)
    leakage_checks = {
        "chronological_split": "PASS",
        "same_day_future_game_exclusion": "PASS",
        "train_max_date_before_test_min_date": (
            "PASS" if max(split.train_dates) < min(split.test_dates) else "FAIL"
        ),
        "event_time_columns": _check_event_time(rows),
    }
    all_role_gates_pass = bool(role_gates) and all(
        all(item["status"] == "PASS" for item in gates.values())
        for gates in role_gates.values()
    )
    promotion_pass = (
        not training_shortfalls
        and all_role_gates_pass
        and determinism["status"] == "PASS"
        and all(value == "PASS" for value in leakage_checks.values())
    )

    model_payload = {
        "schema_version": "1.0",
        "artifact_type": "candidate_projection_model",
        "status": "CANDIDATE_ONLY_NOT_DEPLOYED",
        "algorithm": "deterministic_standardized_ridge",
        "separate_roles": True,
        "feature_schema": feature_schema,
        "ridge_alpha": ridge_alpha,
        "seed": seed,
        "code_version": code_version,
        "dataset_sha256": dataset_sha256,
        "data_slate_hashes": slate_hashes,
        "training_cutoff_date": max(split.train_dates),
        "holdout_start_date": min(split.test_dates),
        "holdout_end_date": max(split.test_dates),
        "role_models": role_models,
    }
    model_path = output_dir / "candidate-model.json"
    write_json(model_path, model_payload)
    model_hash = sha256_file(model_path)
    report = {
        "schema_version": "1.0",
        "status": "PROMOTION_ELIGIBLE_CANDIDATE" if promotion_pass else "REJECTED_CANDIDATE",
        "production_action": "NONE",
        "production_default_replaced": False,
        "reason": (
            "all predeclared offline candidate gates passed; manual independent review still required"
            if promotion_pass
            else "one or more predeclared gates failed; candidate must not replace production projections"
        ),
        "dataset_sha256": dataset_sha256,
        "model_file": model_path.name,
        "model_sha256": model_hash,
        "seed": seed,
        "code_version": code_version,
        "split": {
            "method": "whole-date chronological holdout; no random split",
            "train_dates": split.train_dates,
            "test_dates": split.test_dates,
            "train_rows": len(split.train_rows),
            "test_rows": len(split.test_rows),
        },
        "minimums": {
            "min_train_slates": min_train_slates,
            "min_test_slates": min_test_slates,
            "min_test_rows_per_role": min_test_rows_per_role,
        },
        "training_shortfalls": training_shortfalls,
        "leakage_checks": leakage_checks,
        "determinism": determinism,
        "fixed_completely_held_out_test_metrics": {
            "overall": overall_metrics,
            "by_role": role_metrics,
        },
        "role_gates": role_gates,
        "walk_forward_validation_on_pre_holdout_dates": walk_forward,
        "thresholds": {
            "required_mae_relative_improvement": required_mae_relative_improvement,
            "max_rmse_relative_regression": max_rmse_relative_regression,
            "max_correlation_drop": max_correlation_drop,
        },
        "limitations": [
            "No online deployment or production configuration change was performed.",
            "Passing this offline gate only creates an auditable candidate for independent review.",
            "Lineup-level value must also be evaluated through the candidate_model backtest method.",
        ],
    }
    write_json(report_path, report)
    card_path.write_text(_model_card(report, model_payload), encoding="utf-8")
    predictions_path = output_dir / "heldout-predictions.json"
    write_json(predictions_path, {"schema_version": "1.0", "records": fixed_holdout_predictions})
    return _result_paths(report, report_path, card_path, model_path, predictions_path)


def fit_ridge(rows: list[dict[str, Any]], feature_schema: list[str], *, alpha: float) -> dict[str, Any]:
    if not rows:
        raise ModelError("cannot train ridge on zero rows")
    x = np.asarray([[float(row.get(name, 0.0)) for name in feature_schema] for row in rows], dtype=float)
    y = np.asarray([float(row["target_actual_points"]) for row in rows], dtype=float)
    means = x.mean(axis=0)
    scales = x.std(axis=0)
    scales = np.where(scales <= 1e-12, 1.0, scales)
    standardized = (x - means) / scales
    design = np.column_stack([np.ones(len(rows)), standardized])
    penalty = np.eye(design.shape[1]) * float(alpha)
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return {
        "feature_schema": list(feature_schema),
        "intercept": float(coefficients[0]),
        "coefficients": [float(value) for value in coefficients[1:]],
        "means": [float(value) for value in means],
        "scales": [float(value) for value in scales],
        "training_rows": len(rows),
        "training_slate_dates": sorted({str(row["slate_date"]) for row in rows}),
    }


def predict_rows(model: dict[str, Any], rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    schema = list(model["feature_schema"])
    coefficients = np.asarray(model["coefficients"], dtype=float)
    means = np.asarray(model["means"], dtype=float)
    scales = np.asarray(model["scales"], dtype=float)
    result: list[dict[str, Any]] = []
    for row in rows:
        values = np.asarray([float(row.get(name, 0.0)) for name in schema], dtype=float)
        prediction = float(model["intercept"] + ((values - means) / scales) @ coefficients)
        result.append(
            {
                "slate_id": row["slate_id"],
                "slate_date": row["slate_date"],
                "mlbam_id": int(row["mlbam_id"]),
                "role": row["role"],
                "actual": float(row["target_actual_points"]),
                "legacy": float(row["legacy_projection"]),
                "candidate": max(0.0, prediction),
            }
        )
    return result


def compare_predictions(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"rows": 0, "candidate": None, "legacy": None, "relative": None}
    actual = np.asarray([item["actual"] for item in records], dtype=float)
    candidate = np.asarray([item["candidate"] for item in records], dtype=float)
    legacy = np.asarray([item["legacy"] for item in records], dtype=float)
    candidate_metrics = _metrics(actual, candidate)
    legacy_metrics = _metrics(actual, legacy)
    return {
        "rows": len(records),
        "slates": len({item["slate_id"] for item in records}),
        "candidate": candidate_metrics,
        "legacy": legacy_metrics,
        "relative": {
            "mae_improvement": _improvement(candidate_metrics["mae"], legacy_metrics["mae"]),
            "rmse_improvement": _improvement(candidate_metrics["rmse"], legacy_metrics["rmse"]),
            "correlation_delta": _finite_delta(candidate_metrics["correlation"], legacy_metrics["correlation"]),
        },
    }


def expanding_walk_forward_validation(
    rows: list[dict[str, Any]],
    *,
    feature_schema: list[str],
    alpha: float,
    min_train_dates: int,
) -> dict[str, Any]:
    dates = sorted({str(row["slate_date"]) for row in rows})
    predictions: list[dict[str, Any]] = []
    folds: list[dict[str, Any]] = []
    for index in range(min_train_dates, len(dates)):
        validation_date = dates[index]
        train_dates = dates[:index]
        train_rows = [row for row in rows if str(row["slate_date"]) in train_dates]
        validation_rows = [row for row in rows if str(row["slate_date"]) == validation_date]
        fold_predictions: list[dict[str, Any]] = []
        for role in ROLES:
            role_train = [row for row in train_rows if row["role"] == role]
            role_valid = [row for row in validation_rows if row["role"] == role]
            if not role_train or not role_valid:
                continue
            fold_predictions.extend(predict_rows(fit_ridge(role_train, feature_schema, alpha=alpha), role_valid))
        predictions.extend(fold_predictions)
        folds.append(
            {
                "validation_date": validation_date,
                "training_date_min": train_dates[0],
                "training_date_max": train_dates[-1],
                "training_dates": len(train_dates),
                "validation_rows": len(fold_predictions),
            }
        )
    return {
        "method": "expanding walk-forward by whole slate date",
        "fold_count": len(folds),
        "folds": folds,
        "metrics": compare_predictions(predictions),
    }


def predict_feature_snapshot(features: SlateFeatureSnapshot, model_path: Path) -> dict[int, float]:
    payload = load_json(model_path)
    if payload.get("artifact_type") != "candidate_projection_model":
        raise ModelError("not a candidate projection model artifact")
    game_by_id = {game.game_id: game for game in features.games}
    latest_available = max(
        (source.available_at or source.published_at or source.fetched_at)
        for source in features.sources
    )
    predictions: dict[int, float] = {}
    for player in features.players:
        game = game_by_id.get(player.game_id)
        if game is None or latest_available >= game.scheduled_start:
            raise ModelError(f"event-time check failed for player {player.mlbam_id}")
        role = "pitcher" if {item.upper() for item in player.position} == {"P"} else "hitter"
        model = payload.get("role_models", {}).get(role)
        if not isinstance(model, dict):
            raise ModelError(f"candidate artifact lacks {role} model")
        values = feature_vector_for_player(features, player, list(model["feature_schema"]))
        row = {
            **values,
            "slate_id": features.slate_id,
            "slate_date": features.slate_start.date().isoformat(),
            "mlbam_id": player.mlbam_id,
            "role": role,
            "target_actual_points": 0.0,
            "legacy_projection": player.projected_points,
        }
        predictions[player.mlbam_id] = predict_rows(model, [row])[0]["candidate"]
    return predictions


def _metrics(actual: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    error = prediction - actual
    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(error ** 2)))
    correlation: float | None
    if len(actual) < 2 or float(np.std(actual)) <= 1e-12 or float(np.std(prediction)) <= 1e-12:
        correlation = None
    else:
        correlation = float(np.corrcoef(actual, prediction)[0, 1])
    if float(np.var(prediction)) <= 1e-12:
        calibration_slope = None
        calibration_intercept = float(np.mean(actual))
    else:
        calibration_slope = float(np.cov(prediction, actual, ddof=0)[0, 1] / np.var(prediction))
        calibration_intercept = float(np.mean(actual) - calibration_slope * np.mean(prediction))
    return {
        "mae": mae,
        "rmse": rmse,
        "correlation": correlation,
        "calibration_slope": calibration_slope,
        "calibration_intercept": calibration_intercept,
        "mean_prediction": float(np.mean(prediction)),
        "mean_actual": float(np.mean(actual)),
    }


def _metric_gates(
    metrics: dict[str, Any],
    *,
    min_rows: int,
    required_mae_relative_improvement: float,
    max_rmse_relative_regression: float,
    max_correlation_drop: float,
) -> dict[str, Any]:
    relative = metrics["relative"]
    candidate = metrics["candidate"]
    legacy = metrics["legacy"]
    correlation_delta = relative["correlation_delta"]
    return {
        "minimum_rows": {
            "status": "PASS" if metrics["rows"] >= min_rows else "FAIL",
            "threshold": min_rows,
            "actual": metrics["rows"],
        },
        "mae_improvement": {
            "status": "PASS" if relative["mae_improvement"] >= required_mae_relative_improvement else "FAIL",
            "threshold": required_mae_relative_improvement,
            "actual": relative["mae_improvement"],
        },
        "rmse_noninferiority": {
            "status": "PASS" if relative["rmse_improvement"] >= -max_rmse_relative_regression else "FAIL",
            "threshold": -max_rmse_relative_regression,
            "actual": relative["rmse_improvement"],
        },
        "correlation_noninferiority": {
            "status": (
                "PASS"
                if correlation_delta is None or correlation_delta >= -max_correlation_drop
                else "FAIL"
            ),
            "threshold": -max_correlation_drop,
            "actual": correlation_delta,
            "candidate": candidate["correlation"],
            "legacy": legacy["correlation"],
        },
    }


def _determinism_check(
    rows: list[dict[str, Any]], feature_schema: list[str], alpha: float, expected: dict[str, Any]
) -> dict[str, Any]:
    repeated = {
        role: fit_ridge([row for row in rows if row["role"] == role], feature_schema, alpha=alpha)
        for role in ROLES
        if any(row["role"] == role for row in rows)
    }
    left = hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    right = hashlib.sha256(json.dumps(repeated, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"status": "PASS" if left == right else "FAIL", "first_sha256": left, "repeat_sha256": right}


def _check_event_time(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        available = datetime.fromisoformat(str(row["feature_available_at"]).replace("Z", "+00:00"))
        start = datetime.fromisoformat(str(row["game_start"]).replace("Z", "+00:00"))
        if available >= start:
            return "FAIL"
    return "PASS"


def _improvement(candidate_error: float, legacy_error: float) -> float:
    if legacy_error == 0:
        return 0.0 if candidate_error == 0 else -math.inf
    return (legacy_error - candidate_error) / abs(legacy_error)


def _finite_delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _rejected_not_evaluated_report(
    *,
    reason: str,
    row_count: int,
    date_count: int,
    min_train_slates: int,
    min_test_slates: int,
    dataset_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "REJECTED_NOT_EVALUATED",
        "production_action": "NONE",
        "production_default_replaced": False,
        "reason": reason,
        "dataset_sha256": dataset_sha256,
        "row_count": row_count,
        "date_count": date_count,
        "minimums": {
            "min_train_slates": min_train_slates,
            "min_test_slates": min_test_slates,
        },
        "fixed_completely_held_out_test_metrics": None,
        "limitations": [
            "Insufficient qualified chronological real data; no performance claim is permitted.",
            "No model was deployed or enabled in production.",
        ],
    }


def _model_card(report: dict[str, Any], model: dict[str, Any] | None) -> str:
    lines = [
        "# Candidate MLB DFS Projection Model Card",
        "",
        f"- Status: **{report['status']}**",
        "- Production action: **NONE**",
        "- Production default replaced: **false**",
        f"- Dataset SHA-256: `{report.get('dataset_sha256')}`",
        "",
        "## Intended use",
        "",
        "Offline, auditable candidate projection generation and lineup backtest comparison only.",
        "It is not an instruction to deploy, promote, or replace the current production projection.",
        "",
        "## Data and leakage controls",
        "",
        "Only registry-qualified real slates may enter the dataset. Splits use whole chronological slate dates,",
        "and every feature availability timestamp must be strictly earlier than the corresponding first pitch.",
        "AvgPointsPerGame and postgame/final/boxscore/outcome fields are prohibited as model features.",
        "",
        "## Decision",
        "",
        str(report.get("reason", "")),
    ]
    if model is not None:
        lines.extend(
            [
                "",
                "## Model",
                "",
                f"- Algorithm: `{model['algorithm']}`",
                f"- Training cutoff: `{model['training_cutoff_date']}`",
                f"- Holdout: `{model['holdout_start_date']}` through `{model['holdout_end_date']}`",
                f"- Ridge alpha: `{model['ridge_alpha']}`",
                f"- Seed: `{model['seed']}`",
                f"- Code version: `{model['code_version']}`",
                f"- Features: `{', '.join(model['feature_schema'])}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Known limitations",
            "",
            "A candidate that passes the offline gates still requires independent review. Projection metrics do not",
            "guarantee lineup-level improvement, and lineup backtests must retain random, legacy, and current optimized baselines.",
            "",
        ]
    )
    return "\n".join(lines)


def _result_paths(
    report: dict[str, Any],
    report_path: Path,
    card_path: Path,
    model_path: Path | None,
    predictions_path: Path | None = None,
) -> dict[str, Any]:
    result = {
        "status": report["status"],
        "report_path": str(report_path.resolve()),
        "report_sha256": sha256_file(report_path),
        "model_card_path": str(card_path.resolve()),
        "model_card_sha256": sha256_file(card_path),
        "model_path": str(model_path.resolve()) if model_path else None,
        "model_sha256": sha256_file(model_path) if model_path else None,
    }
    if predictions_path is not None:
        result["predictions_path"] = str(predictions_path.resolve())
        result["predictions_sha256"] = sha256_file(predictions_path)
    return result
