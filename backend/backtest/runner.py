from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Literal

from pydantic import ValidationError

from backtest.contracts import SlateActualPoints, SlateFeatureSnapshot
from backtest.io import load_json, write_csv, write_json
from backtest.provenance import ProvenanceError, ProvenanceIndex
from backtest.statistics import (
    paired_bootstrap_ci,
    relative_mean_difference,
    standard_error,
)
from models.schemas import Lineup, OptimizeRequest, OptimizeResponse
from services.lineup_rules import LineupValidationError, validate_lineup, validate_lineup_set
from services.optimizer import OptimizerError, generate_lineups
from services.optimizer_legacy import (
    OptimizerError as LegacyOptimizerError,
    run_optimizer_sync as run_legacy_optimizer_sync,
)


METHODS = ("random", "legacy", "optimized")


@dataclass(frozen=True)
class BacktestConfig:
    seed: int
    site: Literal["dk", "fd"]
    slate_dir: Path
    lineups_per_method: int
    output_dir: Path
    noninferiority_margin: float = 0.02
    min_real_slates: int = 30
    bootstrap_samples: int = 2000
    provenance_manifest: Path | None = None


class BacktestDataError(ValueError):
    pass


def run_backtest(config: BacktestConfig) -> dict[str, Any]:
    _validate_config(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    feature_paths = sorted(config.slate_dir.glob("*.features.json"))
    if not feature_paths:
        raise BacktestDataError(f"No *.features.json files found in {config.slate_dir}")

    has_real_inputs = any(load_json(path).get("data_kind") == "real" for path in feature_paths)
    provenance: ProvenanceIndex | None = None
    provenance_load_error: ProvenanceError | None = None
    if has_real_inputs:
        try:
            provenance = ProvenanceIndex.load(config.slate_dir, config.provenance_manifest)
        except ProvenanceError as exc:
            provenance_load_error = exc

    slate_summaries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for feature_path in feature_paths:
        actual_path = feature_path.with_name(
            feature_path.name.replace(".features.json", ".actuals.json")
        )
        try:
            result = _run_slate(
                config, feature_path, actual_path, provenance, provenance_load_error
            )
        except (
            BacktestDataError,
            ValidationError,
            OptimizerError,
            LegacyOptimizerError,
            LineupValidationError,
            ProvenanceError,
        ) as exc:
            failures.append(
                {
                    "feature_file": feature_path.name,
                    "actuals_file": actual_path.name,
                    "reason_type": type(exc).__name__,
                    "reason": str(exc),
                    "error": exc.to_dict() if isinstance(exc, OptimizerError) else None,
                }
            )
            continue
        slate_summaries.append(result)

    summary = _summarize(config, slate_summaries, failures)
    write_json(config.output_dir / "summary.json", summary)
    write_csv(
        config.output_dir / "summary.csv",
        [_flatten_summary(summary)],
        list(_flatten_summary(summary).keys()),
    )
    write_json(config.output_dir / "failures.json", failures)
    write_csv(
        config.output_dir / "failures.csv",
        failures,
        ["feature_file", "actuals_file", "reason_type", "reason", "error"],
    )
    return summary


def _validate_config(config: BacktestConfig) -> None:
    if config.min_real_slates < 1:
        raise BacktestDataError("min_real_slates must be at least 1")
    if not 1 <= config.lineups_per_method <= 20:
        raise BacktestDataError("lineups_per_method must be between 1 and 20")
    if not 0 <= config.noninferiority_margin < 1:
        raise BacktestDataError("noninferiority_margin must be in [0, 1)")
    if config.bootstrap_samples < 1:
        raise BacktestDataError("bootstrap_samples must be at least 1")


def _run_slate(
    config: BacktestConfig,
    feature_path: Path,
    actual_path: Path,
    provenance: ProvenanceIndex | None = None,
    provenance_load_error: ProvenanceError | None = None,
) -> dict[str, Any]:
    if not actual_path.exists():
        raise BacktestDataError(f"Missing scoring file: {actual_path.name}")
    features = SlateFeatureSnapshot.model_validate(load_json(feature_path))
    actuals = SlateActualPoints.model_validate(load_json(actual_path))
    if features.site != config.site:
        raise BacktestDataError(
            f"Feature site {features.site} does not match requested site {config.site}"
        )
    if actuals.site != features.site or actuals.slate_id != features.slate_id:
        raise BacktestDataError("Feature and actual-points files refer to different slates/sites")
    if actuals.data_kind != features.data_kind:
        raise BacktestDataError("Feature and actual-points files have different data_kind values")
    if actuals.source_timestamp < features.slate_start:
        raise BacktestDataError("Actual-points source_timestamp must be at or after slate_start")
    if actuals.acquired_at < features.slate_start:
        raise BacktestDataError("Actual-points acquired_at must be at or after slate_start")

    manifest_entry = None
    if features.data_kind == "real":
        if provenance_load_error is not None:
            raise provenance_load_error
        if provenance is None:
            raise ProvenanceError("A qualified provenance manifest is required for real data")
        assert features.contest_style is not None
        assert features.provider_slate_id is not None
        manifest_entry = provenance.validate_real_slate(
            slate_id=features.slate_id,
            site=features.site,
            contest_style=features.contest_style,
            provider_slate_id=features.provider_slate_id,
            game_ids=features.game_ids,
            lock_time=features.lock_time,
            snapshot_as_of=features.snapshot_as_of,
            scope=features.scope,
            provider_game_set_verified=features.provider_game_set_verified,
            validation_scope=features.validation_scope,
            warnings=features.warnings,
            feature_path=feature_path,
            actuals_path=actual_path,
            scoring_rules_version=actuals.scoring_rules_version,
            feature_sources=features.sources,
            raw_stats_artifact_ids=actuals.raw_stats_artifact_ids,
            scoring_rules_artifact_id=actuals.scoring_rules_artifact_id,
            actuals_source_record_id=actuals.source_record_id,
            actuals_source_timestamp=actuals.source_timestamp,
            actuals_acquired_at=actuals.acquired_at,
            actuals_source_final=actuals.source_final,
        )

    actual_by_id = {record.mlbam_id: record.actual_points for record in actuals.points}
    if actuals.validation_scope != features.validation_scope:
        raise BacktestDataError("Feature and actuals validation_scope values differ")
    if actuals.coverage_scope == "all_feature_players":
        missing_actuals = sorted(
            player.mlbam_id for player in features.players if player.mlbam_id not in actual_by_id
        )
        if missing_actuals:
            raise BacktestDataError(
                f"Actual points are missing for feature players: {missing_actuals[:20]}"
            )
    elif not (
        features.scope == "historical_daily_pool"
        and features.validation_scope == "LIMITED_SINGLE_SLATE_VALIDATION"
    ):
        raise BacktestDataError("selected-lineup actual coverage is only allowed for a limited historical daily pool")

    request = OptimizeRequest(
        site=features.site,
        num_lineups=config.lineups_per_method,
        players=features.players,
        settings=features.settings,
        seed=config.seed,
    )

    method_responses: dict[str, OptimizeResponse] = {}
    method_responses["random"] = generate_lineups(
        request, method="random", seed=config.seed, prefer_pydfs=False
    )
    legacy_response = run_legacy_optimizer_sync(request, prefer_pydfs=False)
    legacy_response.method = "legacy"
    legacy_response.seed = config.seed
    method_responses["legacy"] = legacy_response
    method_responses["optimized"] = generate_lineups(
        request, method="optimized", seed=config.seed, prefer_pydfs=False
    )

    for method, response in method_responses.items():
        if len(response.lineups) != config.lineups_per_method:
            raise BacktestDataError(
                f"{method} generated {len(response.lineups)} lineups; "
                f"expected {config.lineups_per_method}"
            )
        validate_lineup_set(request, response.lineups)

    if actuals.coverage_scope == "selected_lineup_players":
        selected_ids = {
            player.mlbam_id
            for response in method_responses.values()
            for lineup in response.lineups
            for player in lineup.players
        }
        missing_selected = sorted(selected_ids - set(actual_by_id))
        extra_actuals = sorted(set(actual_by_id) - selected_ids)
        if missing_selected:
            raise BacktestDataError(
                f"Actual points are missing for selected lineup players: {missing_selected}"
            )
        if extra_actuals:
            raise BacktestDataError(
                f"selected_lineup_players actuals contain unselected IDs: {extra_actuals}"
            )

    rows: list[dict[str, Any]] = []
    method_scores: dict[str, list[float]] = {}
    for method in METHODS:
        method_scores[method] = []
        for lineup in method_responses[method].lineups:
            validation = validate_lineup(request, lineup)
            actual_score = sum(actual_by_id[player.mlbam_id] for player in lineup.players)
            method_scores[method].append(actual_score)
            rows.append(
                _lineup_row(
                    features.slate_id,
                    features.site,
                    features.data_kind,
                    method,
                    lineup,
                    actual_score,
                    validation={
                        "valid": validation.valid,
                        "issues": [issue.to_dict() for issue in validation.issues],
                        "set_validated": True,
                    },
                )
            )

    rows.sort(key=lambda row: (row["method"], row["lineup_number"]))
    base_name = _safe_name(features.slate_id)
    write_json(config.output_dir / f"{base_name}.lineups.json", rows)
    write_csv(
        config.output_dir / f"{base_name}.lineups.csv",
        rows,
        [
            "slate_id",
            "data_kind",
            "site",
            "method",
            "lineup_number",
            "player_ids",
            "players",
            "total_salary",
            "projected_points",
            "actual_points",
            "legal",
            "legality",
        ],
    )

    means = {method: fmean(scores) for method, scores in method_scores.items()}
    slate_summary = {
        "slate_id": features.slate_id,
        "site": features.site,
        "data_kind": features.data_kind,
        "scope": features.scope,
        "provider_game_set_verified": features.provider_game_set_verified,
        "validation_scope": features.validation_scope,
        "warnings": sorted(set(features.warnings + actuals.warnings)),
        "actuals_coverage_scope": actuals.coverage_scope,
        "lineups_per_method": config.lineups_per_method,
        "random_mean_actual": means["random"],
        "legacy_mean_actual": means["legacy"],
        "optimized_mean_actual": means["optimized"],
        "optimized_vs_random_relative": _relative(means["optimized"], means["random"]),
        "optimized_vs_legacy_relative": _relative(means["optimized"], means["legacy"]),
        "optimized_beats_random": means["optimized"] > means["random"],
        "sample_size_per_method": config.lineups_per_method,
        "snapshot_as_of": features.snapshot_as_of.isoformat(),
        "lock_time": features.lock_time.isoformat(),
        "feature_sources": [source.model_dump(mode="json") for source in features.sources],
        "scoring_source": actuals.scoring_source,
        "scoring_rules_version": actuals.scoring_rules_version,
        "actuals_source_timestamp": actuals.source_timestamp.isoformat(),
        "actuals_acquired_at": actuals.acquired_at.isoformat(),
        "feature_sha256": _sha256(feature_path),
        "actuals_sha256": _sha256(actual_path),
        "provenance_manifest_sha256": provenance.manifest_sha256 if manifest_entry else None,
        "provenance_transform_version": (
            manifest_entry.transform_version if manifest_entry else None
        ),
        "provenance_qualification_status": (
            manifest_entry.qualification_status if manifest_entry else None
        ),
    }
    write_json(config.output_dir / f"{base_name}.summary.json", slate_summary)
    return slate_summary


def _lineup_row(
    slate_id: str,
    site: str,
    data_kind: str,
    method: str,
    lineup: Lineup,
    actual_score: float,
    *,
    validation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "slate_id": slate_id,
        "data_kind": data_kind,
        "site": site,
        "method": method,
        "lineup_number": lineup.lineup_number,
        "player_ids": [player.mlbam_id for player in lineup.players],
        "players": [
            {
                "mlbam_id": player.mlbam_id,
                "name": player.name,
                "slot": player.position_slot,
                "team": player.team,
                "salary": player.salary,
                "projected_points": player.projected_points,
            }
            for player in lineup.players
        ],
        "total_salary": lineup.total_salary,
        "projected_points": lineup.projected_points,
        "actual_points": round(actual_score, 6),
        "legal": bool(validation["valid"]),
        "legality": validation,
    }


def _summarize(
    config: BacktestConfig,
    slates: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    real_slates = [slate for slate in slates if slate["data_kind"] == "real"]
    evaluation_slates = real_slates
    random_pairs = [
        (slate["optimized_mean_actual"], slate["random_mean_actual"])
        for slate in evaluation_slates
    ]
    legacy_pairs = [
        (slate["optimized_mean_actual"], slate["legacy_mean_actual"])
        for slate in evaluation_slates
    ]

    if evaluation_slates:
        optimized_mean = fmean(item["optimized_mean_actual"] for item in evaluation_slates)
        random_mean = fmean(item["random_mean_actual"] for item in evaluation_slates)
        legacy_mean = fmean(item["legacy_mean_actual"] for item in evaluation_slates)
        relative_random = _relative(optimized_mean, random_mean)
        relative_legacy = _relative(optimized_mean, legacy_mean)
        win_rate = fmean(
            1.0 if item["optimized_beats_random"] else 0.0
            for item in evaluation_slates
        )
        random_differences = [left - right for left, right in random_pairs]
        legacy_differences = [left - right for left, right in legacy_pairs]
        random_ci = paired_bootstrap_ci(
            random_pairs,
            statistic=relative_mean_difference,
            seed=config.seed + 101,
            samples=config.bootstrap_samples,
        )
        legacy_ci = paired_bootstrap_ci(
            legacy_pairs,
            statistic=relative_mean_difference,
            seed=config.seed + 202,
            samples=config.bootstrap_samples,
        )
    else:
        optimized_mean = random_mean = legacy_mean = None
        relative_random = relative_legacy = win_rate = None
        random_differences = legacy_differences = []
        random_ci = legacy_ci = (None, None)

    enough_data = len(evaluation_slates) >= config.min_real_slates
    limited_validation = bool(evaluation_slates) and any(
        slate.get("validation_scope") == "LIMITED_SINGLE_SLATE_VALIDATION"
        for slate in evaluation_slates
    )
    evaluate_performance = enough_data and not limited_validation
    gates = {
        "minimum_real_slates": {
            "threshold": config.min_real_slates,
            "actual": len(evaluation_slates),
            "status": "PASS" if enough_data else "FAIL",
        },
        "optimized_vs_random_mean": {
            "threshold": 0.10,
            "actual": relative_random,
            "status": (
                "PASS" if evaluate_performance and relative_random is not None and relative_random >= 0.10
                else "FAIL" if evaluate_performance
                else "NOT EVALUATED"
            ),
        },
        "optimized_vs_random_slate_win_rate": {
            "threshold": 0.60,
            "actual": win_rate,
            "status": (
                "PASS" if evaluate_performance and win_rate is not None and win_rate >= 0.60
                else "FAIL" if evaluate_performance
                else "NOT EVALUATED"
            ),
        },
        "optimized_vs_legacy_noninferiority": {
            "threshold": -config.noninferiority_margin,
            "actual": relative_legacy,
            "status": (
                "PASS"
                if evaluate_performance
                and relative_legacy is not None
                and relative_legacy >= -config.noninferiority_margin
                else "FAIL" if evaluate_performance
                else "NOT EVALUATED"
            ),
            "definition": (
                "optimized mean actual points must be at least "
                f"{(1 - config.noninferiority_margin) * 100:.2f}% of legacy mean actual points"
            ),
        },
    }

    return {
        "schema_version": "1.1",
        "evaluation_status": (
            "LIMITED VALIDATION"
            if limited_validation and enough_data
            else "EVALUATED" if enough_data
            else "INSUFFICIENT DATA / NOT EVALUATED"
        ),
        "performance_metrics_interpretation": (
            "INFORMATIONAL_ONLY" if limited_validation else "FORMAL_GATE_EVALUATION"
        ),
        "seed": config.seed,
        "site": config.site,
        "lineups_per_method": config.lineups_per_method,
        "minimum_real_slates": config.min_real_slates,
        "noninferiority_margin": config.noninferiority_margin,
        "valid_slates_total": len(slates),
        "valid_real_slates": len(real_slates),
        "valid_fixture_or_synthetic_slates": len(slates) - len(real_slates),
        "failed_or_skipped_slates": len(failures),
        "means_real_slates_only": {
            "random_actual": random_mean,
            "legacy_actual": legacy_mean,
            "optimized_actual": optimized_mean,
        },
        "paired_metrics_real_slates_only": {
            "optimized_vs_random_relative": relative_random,
            "optimized_vs_random_relative_bootstrap_95_ci": list(random_ci),
            "optimized_vs_random_difference_standard_error": standard_error(random_differences),
            "optimized_vs_random_slate_win_rate": win_rate,
            "optimized_vs_legacy_relative": relative_legacy,
            "optimized_vs_legacy_relative_bootstrap_95_ci": list(legacy_ci),
            "optimized_vs_legacy_difference_standard_error": standard_error(legacy_differences),
        },
        "gates": gates,
        "slates": sorted(slates, key=lambda item: item["slate_id"]),
        "failures": failures,
        "note": (
            "Single-slate LIMITED VALIDATION proves the real-data pipeline only; performance "
            "metrics are informational and formal +10%, win-rate, and noninferiority gates remain "
            "NOT EVALUATED. In full research mode, bootstrap intervals are reported separately "
            "from the predeclared point-estimate gates."
        ),
    }


def _flatten_summary(summary: dict[str, Any]) -> dict[str, Any]:
    metrics = summary["paired_metrics_real_slates_only"]
    means = summary["means_real_slates_only"]
    gates = summary["gates"]
    return {
        "evaluation_status": summary["evaluation_status"],
        "seed": summary["seed"],
        "site": summary["site"],
        "lineups_per_method": summary["lineups_per_method"],
        "valid_slates_total": summary["valid_slates_total"],
        "valid_real_slates": summary["valid_real_slates"],
        "failed_or_skipped_slates": summary["failed_or_skipped_slates"],
        "random_mean_actual": means["random_actual"],
        "legacy_mean_actual": means["legacy_actual"],
        "optimized_mean_actual": means["optimized_actual"],
        "optimized_vs_random_relative": metrics["optimized_vs_random_relative"],
        "optimized_vs_random_win_rate": metrics["optimized_vs_random_slate_win_rate"],
        "optimized_vs_legacy_relative": metrics["optimized_vs_legacy_relative"],
        "minimum_real_slates_status": gates["minimum_real_slates"]["status"],
        "random_improvement_status": gates["optimized_vs_random_mean"]["status"],
        "slate_win_rate_status": gates["optimized_vs_random_slate_win_rate"]["status"],
        "legacy_noninferiority_status": gates["optimized_vs_legacy_noninferiority"]["status"],
    }


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def _relative(left: float, right: float) -> float:
    if right == 0:
        return float("inf") if left > 0 else 0.0
    return (left - right) / abs(right)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
