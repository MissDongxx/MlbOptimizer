from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backtest.contracts import SlateActualPoints, SlateFeatureSnapshot
from backtest.io import load_json
from backtest.pipeline.registry import Registry, sha256_file
from models.schemas import OptimizeRequest
from services.lineup_rules import LineupValidationError, validate_lineup_set
from services.optimizer import OptimizerError, generate_lineups


@dataclass(frozen=True)
class QualificationResult:
    slate_id: str
    status: str
    checks: list[dict[str, Any]]
    rejection_reasons: list[str]
    feature_sha256: str | None
    actuals_sha256: str | None

    @property
    def qualified(self) -> bool:
        return self.status == "QUALIFIED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "slate_id": self.slate_id,
            "status": self.status,
            "checks": self.checks,
            "rejection_reasons": self.rejection_reasons,
            "feature_sha256": self.feature_sha256,
            "actuals_sha256": self.actuals_sha256,
        }


def qualify_registry_entry(registry: Registry, entry: dict[str, Any]) -> QualificationResult:
    slate_id = str(entry["slate_id"])
    checks: list[dict[str, Any]] = []
    reasons: list[str] = []

    def check(name: str, passed: bool, detail: Any) -> None:
        checks.append({"name": name, "status": "PASS" if passed else "FAIL", "detail": detail})
        if not passed:
            reasons.append(f"{name}: {detail}")

    corrupt = [item for item in registry.verify_all_artifacts() if item["slate_id"] == slate_id]
    check("immutable_artifact_hashes", not corrupt, corrupt or "all registered bytes and hashes match")

    feature_value = entry.get("feature_file")
    actuals_value = entry.get("actuals_file")
    feature_path = Path(str(feature_value)) if feature_value else None
    actuals_path = Path(str(actuals_value)) if actuals_value else None
    check("feature_snapshot_present", bool(feature_path and feature_path.is_file()), str(feature_path))
    check("final_actuals_present", bool(actuals_path and actuals_path.is_file()), str(actuals_path))
    if feature_path is None or actuals_path is None or not feature_path.is_file() or not actuals_path.is_file():
        return QualificationResult(slate_id, "REJECTED", checks, sorted(set(reasons)), None, None)

    feature_hash = sha256_file(feature_path)
    actuals_hash = sha256_file(actuals_path)
    registered_artifacts = list(entry.get("artifacts", []))
    registered_hashes = {str(item.get("sha256")) for item in registered_artifacts}
    registered_ids = {str(item.get("artifact_id")) for item in registered_artifacts}
    try:
        features = SlateFeatureSnapshot.model_validate(load_json(feature_path))
        check("feature_contract", True, "strict schema and no-leakage validators passed")
    except (ValidationError, ValueError) as exc:
        check("feature_contract", False, str(exc))
        return QualificationResult(slate_id, "REJECTED", checks, sorted(set(reasons)), feature_hash, actuals_hash)

    try:
        actuals = SlateActualPoints.model_validate(load_json(actuals_path))
        check("actuals_contract", True, "strict final/full-pool schema passed")
    except (ValidationError, ValueError) as exc:
        check("actuals_contract", False, str(exc))
        return QualificationResult(slate_id, "REJECTED", checks, sorted(set(reasons)), feature_hash, actuals_hash)

    check("real_data_only", features.data_kind == "real" and actuals.data_kind == "real", {
        "features": features.data_kind,
        "actuals": actuals.data_kind,
    })
    check("dk_classic_roster", features.site == "dk" and features.contest_style == "classic", {
        "site": features.site,
        "contest_style": features.contest_style,
    })
    check("matching_slate_identity", actuals.slate_id == features.slate_id == slate_id and actuals.site == features.site, {
        "feature_slate_id": features.slate_id,
        "actuals_slate_id": actuals.slate_id,
        "registry_slate_id": slate_id,
    })
    salaries = [player.salary for player in features.players]
    check("non_uniform_salary", len(set(salaries)) > 1, {
        "unique_salary_count": len(set(salaries)),
        "minimum": min(salaries),
        "maximum": max(salaries),
    })
    provider_verification = entry.get("provider_verification") or {}
    evidence_ids = sorted(provider_verification.get("evidence_artifact_ids", []))
    evidence_roles = {
        str(item.get("artifact_id")): item.get("role")
        for item in registered_artifacts
        if str(item.get("artifact_id")) in evidence_ids
    }
    provider_verified = bool(
        features.provider_game_set_verified
        and entry.get("provider_game_set_verified")
        and evidence_ids
        and len(evidence_roles) == len(evidence_ids)
        and all(role == "provider_game_set_evidence" for role in evidence_roles.values())
    )
    check("provider_game_set_verified", provider_verified, {
        "feature": features.provider_game_set_verified,
        "registry": entry.get("provider_game_set_verified"),
        "evidence_artifact_ids": evidence_ids,
    })
    registry_provider_id = entry.get("provider_slate_id") or entry.get("draft_group_id")
    identity_matches = bool(
        registry_provider_id
        and features.provider_slate_id
        and registry_provider_id == features.provider_slate_id
    )
    evidence_before_lock = True
    evidence_times: dict[str, str | None] = {}
    for artifact_id in evidence_ids:
        artifact = next(
            (item for item in registered_artifacts if str(item.get("artifact_id")) == artifact_id),
            None,
        )
        captured_value = artifact.get("captured_at") if artifact else None
        evidence_times[artifact_id] = captured_value
        try:
            captured_at = datetime.fromisoformat(str(captured_value).replace("Z", "+00:00"))
        except ValueError:
            evidence_before_lock = False
            continue
        if captured_at >= features.lock_time:
            evidence_before_lock = False
    check(
        "provider_or_draftgroup_evidence",
        identity_matches and bool(evidence_ids) and evidence_before_lock,
        {
            "feature_provider_slate_id": features.provider_slate_id,
            "registry_provider_or_draft_group_id": registry_provider_id,
            "evidence_artifact_ids": evidence_ids,
            "evidence_captured_at": evidence_times,
            "must_precede_lock": features.lock_time.isoformat(),
        },
    )
    check("pregame_capture", features.snapshot_as_of < features.lock_time, {
        "snapshot_as_of": features.snapshot_as_of.isoformat(),
        "lock_time": features.lock_time.isoformat(),
    })
    missing_source_hashes = sorted(
        {
            str(source.raw_sha256)
            for source in features.sources
            if source.raw_sha256 and source.raw_sha256 not in registered_hashes
        }
    )
    check(
        "pregame_raw_artifacts_archived",
        not missing_source_hashes,
        missing_source_hashes or "every feature source raw SHA-256 is archived immutably",
    )
    check("at_least_two_games", len(features.games) >= 2, len(features.games))
    game_by_id = {game.game_id: game for game in features.games}
    invalid_game_players = [p.mlbam_id for p in features.players if p.game_id not in game_by_id]
    check("complete_game_mapping", not invalid_game_players, invalid_game_players[:20] or "all mapped")

    late_sources: list[dict[str, Any]] = []
    for source in features.sources:
        available = source.available_at or source.published_at or source.fetched_at
        for game in features.games:
            if available >= game.scheduled_start:
                late_sources.append({
                    "source": source.source,
                    "available_at": available.isoformat(),
                    "game_id": game.game_id,
                    "first_pitch": game.scheduled_start.isoformat(),
                })
    check("event_time_no_leakage", not late_sources, late_sources[:20] or "every source available before every game")

    feature_ids = {player.mlbam_id for player in features.players}
    actual_ids = {record.mlbam_id for record in actuals.points}
    missing = sorted(feature_ids - actual_ids)
    extra = sorted(actual_ids - feature_ids)
    full_pool = actuals.coverage_scope == "all_feature_players" and not missing and not extra
    check("full_pool_coverage", full_pool, {
        "coverage_scope": actuals.coverage_scope,
        "feature_count": len(feature_ids),
        "actual_count": len(actual_ids),
        "missing": missing[:20],
        "extra": extra[:20],
    })
    check("final_boxscores", actuals.source_final, {
        "source_final": actuals.source_final,
        "source_timestamp": actuals.source_timestamp.isoformat(),
    })
    missing_postgame_artifacts = sorted(set(actuals.raw_stats_artifact_ids) - registered_ids)
    check(
        "postgame_raw_artifacts_archived",
        not missing_postgame_artifacts,
        missing_postgame_artifacts or "every final raw stats artifact is registered",
    )
    dnp_without_evidence = [
        record.mlbam_id
        for record in actuals.points
        if record.status and record.status.startswith("dnp_")
        and (record.actual_points != 0 or not record.source_evidence_id or not record.source_game_id)
    ]
    check("dnp_evidence", not dnp_without_evidence, dnp_without_evidence[:20] or "DNP records have zero points and source evidence")

    identity_artifact = next(
        (item for item in registered_artifacts if item.get("role") == "identity_mapping_audit"),
        None,
    )
    identity_ok = identity_artifact is not None
    ambiguity: Any = "identity mapping audit is required"
    if identity_artifact is not None:
        identity_audit = Path(str(identity_artifact["path"]))
        audit = load_json(identity_audit)
        ambiguous_count = int(audit.get("ambiguous_count", 0))
        unresolved_count = int(audit.get("unresolved_count", 0))
        identity_ok = ambiguous_count == 0 and unresolved_count == 0
        ambiguity = {"ambiguous_count": ambiguous_count, "unresolved_count": unresolved_count}
    check("identity_unambiguous", identity_ok, ambiguity)

    roster_request = OptimizeRequest(
        site="dk",
        num_lineups=1,
        players=features.players,
        settings=features.settings.model_copy(
            update={
                "stack_team": None,
                "stack_count": 0,
                "pitcher_vs_batter_same_team": "allow",
                "min_salary_used": 0,
                "unique_lineups": True,
            }
        ),
        seed=0,
    )
    try:
        response = generate_lineups(roster_request, method="optimized", seed=0, prefer_pydfs=False)
        validate_lineup_set(roster_request, response.lineups)
        check("classic_roster_feasible", True, "one legal 2P+C+1B+2B+3B+SS+3OF lineup exists")
    except (OptimizerError, LineupValidationError, ValueError) as exc:
        check("classic_roster_feasible", False, str(exc))

    status = "QUALIFIED" if not reasons else "REJECTED"
    return QualificationResult(
        slate_id=slate_id,
        status=status,
        checks=checks,
        rejection_reasons=sorted(set(reasons)),
        feature_sha256=feature_hash,
        actuals_sha256=actuals_hash,
    )
