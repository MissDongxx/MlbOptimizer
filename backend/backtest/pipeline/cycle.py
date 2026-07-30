from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backtest.contracts import SlateActualPoints, SlateFeatureSnapshot
from backtest.historical.capture import SlateCaptureError, capture_current_dk_slate
from backtest.historical.http_cache import ImmutableHttpCache
from backtest.historical.mlb_statsapi import StatsApiActualsError, StatsApiFullPoolActualsBuilder
from backtest.io import load_json, write_json
from backtest.pipeline.config import PipelineConfig
from backtest.pipeline.dataset import BASE_FEATURES, DatasetError, build_training_dataset
from backtest.pipeline.modeling import train_candidate_model
from backtest.pipeline.qualification import qualify_registry_entry
from backtest.pipeline.registry import Registry, RegistryError, archive_artifact, sha256_file
from backtest.runner import BacktestConfig, BacktestDataError, run_backtest


class PipelineCycleError(ValueError):
    pass


def run_cycle(config: PipelineConfig) -> dict[str, Any]:
    """Run one non-interactive, offline-capable history/model cycle.

    The function archives inputs and writes only under the configured pipeline root. It never
    edits production settings or deploys a candidate model. Concurrent cycles sharing one root
    fail closed instead of racing registry and model artifacts.
    """
    config.validate()
    config.ensure_directories()
    with _cycle_lock(config.root_dir / ".run-cycle.lock"):
        return _run_cycle_unlocked(config)


def _run_cycle_unlocked(config: PipelineConfig) -> dict[str, Any]:
    registry = Registry(config.registry_path)
    if not config.registry_path.exists():
        registry.save(registry.load())
    events: list[dict[str, Any]] = []
    events.extend(_discover_salary_captures(config, registry))
    events.extend(_discover_feature_uploads(config, registry))

    artifact_failures = registry.verify_all_artifacts()
    if artifact_failures:
        for failure in artifact_failures:
            entry = registry.get(failure["slate_id"])
            if entry and entry.get("state") in {
                "captured",
                "awaiting-results",
                "qualified",
                "backtested",
            }:
                registry.transition(
                    failure["slate_id"],
                    "rejected",
                    "registered immutable artifact failed hash verification",
                    rejection_reasons=[json.dumps(failure, sort_keys=True)],
                )
        events.append({"stage": "integrity", "status": "FAIL", "failures": artifact_failures})
    else:
        events.append({"stage": "integrity", "status": "PASS"})

    events.extend(_complete_actuals(config, registry))
    events.extend(_qualify_pending(registry))

    baseline_backtest = _run_registry_backtest(config, registry, candidate_model=None, label="baseline")
    events.append({"stage": "backtest", **baseline_backtest})
    if baseline_backtest.get("status") == "COMPLETE":
        for entry in registry.qualified_entries():
            if entry.get("state") == "qualified":
                registry.transition(
                    entry["slate_id"],
                    "backtested",
                    "qualified slate included in deterministic baseline backtest",
                    backtest={
                        "summary_path": baseline_backtest.get("summary_path"),
                        "summary_sha256": baseline_backtest.get("summary_sha256"),
                        "seed": config.seed,
                        "lineups_per_method": config.lineups_per_method,
                    },
                )

    qualified = registry.qualified_entries()
    dataset_result: dict[str, Any] | None = None
    try:
        dataset_result = build_training_dataset(qualified, output_dir=config.dataset_dir)
        events.append(
            {
                "stage": "dataset",
                "status": "COMPLETE",
                "row_count": dataset_result["row_count"],
                "slate_count": dataset_result["slate_count"],
                "dataset_sha256": dataset_result["dataset_sha256"],
            }
        )
        model_result = train_candidate_model(
            rows=dataset_result["rows"],
            feature_schema=dataset_result["feature_schema"],
            output_dir=config.model_dir,
            dataset_sha256=dataset_result["dataset_sha256"],
            slate_hashes=dataset_result["slate_hashes"],
            code_version=config.code_version,
            seed=config.seed,
            ridge_alpha=config.ridge_alpha,
            test_fraction=config.test_fraction,
            min_train_slates=config.min_train_slates,
            min_test_slates=config.min_test_slates,
            min_test_rows_per_role=config.min_test_rows_per_role,
            required_mae_relative_improvement=config.required_mae_relative_improvement,
            max_rmse_relative_regression=config.max_rmse_relative_regression,
            max_correlation_drop=config.max_correlation_drop,
        )
    except DatasetError as exc:
        events.append({"stage": "dataset", "status": "NOT_EVALUATED", "reason": str(exc)})
        model_result = train_candidate_model(
            rows=[],
            feature_schema=list(BASE_FEATURES),
            output_dir=config.model_dir,
            dataset_sha256="NO_QUALIFIED_DATASET",
            slate_hashes={},
            code_version=config.code_version,
            seed=config.seed,
            ridge_alpha=config.ridge_alpha,
            test_fraction=config.test_fraction,
            min_train_slates=config.min_train_slates,
            min_test_slates=config.min_test_slates,
            min_test_rows_per_role=config.min_test_rows_per_role,
            required_mae_relative_improvement=config.required_mae_relative_improvement,
            max_rmse_relative_regression=config.max_rmse_relative_regression,
            max_correlation_drop=config.max_correlation_drop,
        )
    events.append({"stage": "model", **model_result})

    candidate_backtest: dict[str, Any] | None = None
    if model_result.get("model_path"):
        candidate_backtest = _run_registry_backtest(
            config,
            registry,
            candidate_model=Path(str(model_result["model_path"])),
            label="candidate",
        )
        events.append({"stage": "candidate_backtest", **candidate_backtest})

    registry_payload = registry.load()
    states: dict[str, int] = {}
    for entry in registry_payload["slates"].values():
        state = str(entry["state"])
        states[state] = states.get(state, 0) + 1
    report = {
        "schema_version": "1.0",
        "status": "COMPLETE",
        "production_changes": False,
        "deployment_performed": False,
        "seed": config.seed,
        "offline": config.offline,
        "registry_path": str(config.registry_path.resolve()),
        "registry_sha256": sha256_file(config.registry_path),
        "slate_states": states,
        "events": events,
        "baseline_backtest": baseline_backtest,
        "dataset": _without_rows(dataset_result),
        "model": model_result,
        "candidate_backtest": candidate_backtest,
        "known_blocker": (
            "No qualified real slate exists until a genuine pre-lock non-uniform DK Classic snapshot, "
            "verified provider/DraftGroup evidence, exact identity mapping, and final full-pool actuals are archived."
        ),
    }
    report_path = config.report_dir / "latest-cycle-report.json"
    write_json(report_path, report)
    report["cycle_report_path"] = str(report_path.resolve())
    report["cycle_report_sha256"] = sha256_file(report_path)
    return report



@contextmanager
def _cycle_lock(path: Path):
    """Serialize cycles for one pipeline root without creating external state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PipelineCycleError(f"another run-cycle holds {path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        handle.close()


def _discover_salary_captures(config: PipelineConfig, registry: Registry) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for csv_path in sorted(config.inbox_dir.glob("*.csv")):
        sidecar = csv_path.with_suffix(csv_path.suffix + ".capture.json")
        if not sidecar.exists():
            events.append(
                {
                    "stage": "capture",
                    "file": csv_path.name,
                    "status": "BLOCKED",
                    "reason": f"missing sidecar {sidecar.name}",
                }
            )
            continue
        metadata = load_json(sidecar)
        if not isinstance(metadata, dict) or not metadata.get("source_url"):
            events.append({"stage": "capture", "file": csv_path.name, "status": "REJECTED", "reason": "sidecar requires source_url"})
            continue
        raw_hash = sha256_file(csv_path)
        capture_id = str(metadata.get("slate_id") or f"dk-capture-{raw_hash[:16]}")
        output_dir = config.artifact_dir / capture_id / "capture"
        provider_metadata = metadata.get("provider_metadata")
        provider_path = None
        if provider_metadata:
            provider_path = Path(str(provider_metadata))
            if not provider_path.is_absolute():
                provider_path = sidecar.parent / provider_path
        try:
            result = capture_current_dk_slate(
                salary_csv=csv_path,
                output_dir=output_dir,
                source_url=str(metadata["source_url"]),
                draft_group_id=metadata.get("draft_group_id"),
                provider_metadata=provider_path,
                provider_metadata_url=metadata.get("provider_metadata_url"),
            )
            manifest = load_json(output_dir / "capture-manifest.json")
            artifacts = []
            for item in manifest["artifacts"]:
                path = output_dir / item["local_path"]
                artifacts.append(
                    {
                        "artifact_id": item["artifact_id"],
                        "role": item["role"],
                        "path": str(path.resolve()),
                        "source_url": item.get("source_url"),
                        "captured_at": item["captured_at"],
                        "effective_at": manifest["first_lock"],
                        "byte_count": item["byte_count"],
                        "sha256": item["sha256"],
                        "immutable": True,
                    }
                )
            captured_at = datetime.fromisoformat(manifest["captured_at"])
            effective_at = datetime.fromisoformat(manifest["first_lock"])
            registry.upsert_captured(
                slate_id=capture_id,
                data_kind="real",
                site="dk",
                captured_at=captured_at,
                effective_at=effective_at,
                provider="draftkings_direct_upload",
                provider_slate_id=metadata.get("provider_slate_id"),
                draft_group_id=metadata.get("draft_group_id"),
                provider_game_set_verified=False,
                artifacts=artifacts,
                blockers=[
                    "provider_game_set_unverified",
                    "feature_snapshot_not_supplied",
                    "identity_mapping_not_supplied",
                ],
            )
            events.append({"stage": "capture", "file": csv_path.name, **result, "slate_id": capture_id})
        except (SlateCaptureError, RegistryError, ValueError) as exc:
            events.append({"stage": "capture", "file": csv_path.name, "status": "REJECTED", "reason": str(exc)})
    return events


def _discover_feature_uploads(config: PipelineConfig, registry: Registry) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for feature_path in sorted(config.inbox_dir.rglob("*.features.json")):
        try:
            features = SlateFeatureSnapshot.model_validate(load_json(feature_path))
            captured_at = max(source.retrieved_at or source.fetched_at for source in features.sources)
            source_url = features.sources[0].source_url
            feature_artifact = archive_artifact(
                feature_path,
                artifact_dir=config.artifact_dir,
                slate_id=features.slate_id,
                artifact_id="feature-snapshot",
                role="qualified_feature_candidate",
                captured_at=captured_at,
                effective_at=features.snapshot_as_of,
                source_url=source_url,
            )
            evidence_source = feature_path.parent / "provider-game-set-evidence.json"
            provider_evidence = None
            if evidence_source.exists():
                evidence_payload = load_json(evidence_source)
                if not isinstance(evidence_payload, dict):
                    raise PipelineCycleError("provider-game-set-evidence.json must be an object")
                evidence_captured_at = datetime.fromisoformat(
                    str(evidence_payload.get("captured_at", "")).replace("Z", "+00:00")
                )
                provider_evidence = archive_artifact(
                    evidence_source,
                    artifact_dir=config.artifact_dir,
                    slate_id=features.slate_id,
                    artifact_id="provider-game-set-evidence",
                    role="provider_game_set_evidence",
                    captured_at=evidence_captured_at,
                    effective_at=features.snapshot_as_of,
                    source_url=str(evidence_payload.get("source_url", "")),
                )
            initial_artifacts = [feature_artifact] + ([provider_evidence] if provider_evidence else [])
            declared_artifacts, declared_paths = _archive_declared_upload_artifacts(
                feature_path.parent,
                artifact_dir=config.artifact_dir,
                slate_id=features.slate_id,
            )
            initial_artifacts.extend(declared_artifacts)
            existing_entry = registry.get(features.slate_id)
            if existing_entry is None:
                registration_captured_at = captured_at
                registration_effective_at = features.snapshot_as_of
                registration_provider = "direct_upload"
                registration_provider_slate_id = features.provider_slate_id
                registration_draft_group_id = features.provider_slate_id
            else:
                registration_captured_at = datetime.fromisoformat(
                    str(existing_entry["captured_at"]).replace("Z", "+00:00")
                )
                effective_value = existing_entry.get("effective_at")
                registration_effective_at = (
                    datetime.fromisoformat(str(effective_value).replace("Z", "+00:00"))
                    if effective_value
                    else None
                )
                registration_provider = str(existing_entry["provider"])
                registration_provider_slate_id = existing_entry.get("provider_slate_id")
                registration_draft_group_id = existing_entry.get("draft_group_id")
            registry.upsert_captured(
                slate_id=features.slate_id,
                data_kind=features.data_kind,
                site=features.site,
                captured_at=registration_captured_at,
                effective_at=registration_effective_at,
                provider=registration_provider,
                provider_slate_id=registration_provider_slate_id,
                draft_group_id=registration_draft_group_id,
                provider_game_set_verified=features.provider_game_set_verified,
                artifacts=initial_artifacts,
                blockers=(
                    []
                    if features.provider_game_set_verified and provider_evidence
                    else ["provider_game_set_unverified"]
                ),
            )
            actuals_source = feature_path.with_name(feature_path.name.replace(".features.json", ".actuals.json"))
            artifacts = list(initial_artifacts)
            raw_dir = feature_path.parent / "raw"
            if raw_dir.is_dir():
                for raw_source in sorted(path for path in raw_dir.rglob("*") if path.is_file()):
                    if raw_source.resolve() in declared_paths:
                        continue
                    raw_hash = sha256_file(raw_source)
                    artifacts.append(
                        archive_artifact(
                            raw_source,
                            artifact_dir=config.artifact_dir,
                            slate_id=features.slate_id,
                            artifact_id=f"raw-{raw_source.stem}-{raw_hash[:8]}",
                            role="raw_source_artifact",
                            captured_at=captured_at,
                            effective_at=features.snapshot_as_of,
                            source_url=next(
                                (
                                    source.source_url
                                    for source in features.sources
                                    if source.raw_sha256 == raw_hash
                                ),
                                None,
                            ),
                        )
                    )
            actuals_target: str | None = None
            direct_actuals: SlateActualPoints | None = None
            if actuals_source.exists():
                direct_actuals = SlateActualPoints.model_validate(load_json(actuals_source))
                actuals_artifact = archive_artifact(
                    actuals_source,
                    artifact_dir=config.artifact_dir,
                    slate_id=features.slate_id,
                    artifact_id="full-pool-actuals",
                    role="postgame_actuals",
                    captured_at=direct_actuals.acquired_at,
                    effective_at=direct_actuals.source_timestamp,
                    source_url=None,
                )
                artifacts.append(actuals_artifact)
                actuals_target = actuals_artifact["path"]
                identity_source = feature_path.parent / "identity-mapping-audit.json"
                if identity_source.exists():
                    artifacts.append(
                        archive_artifact(
                            identity_source,
                            artifact_dir=config.artifact_dir,
                            slate_id=features.slate_id,
                            artifact_id="identity-mapping-audit",
                            role="identity_mapping_audit",
                            captured_at=direct_actuals.acquired_at,
                            effective_at=direct_actuals.source_timestamp,
                        )
                    )
            manifest_source = feature_path.parent / "provenance-manifest.json"
            manifest_target: str | None = None
            if manifest_source.exists():
                manifest_artifact = archive_artifact(
                    manifest_source,
                    artifact_dir=config.artifact_dir,
                    slate_id=features.slate_id,
                    artifact_id="provenance-manifest",
                    role="provenance_manifest",
                    captured_at=captured_at,
                    effective_at=features.snapshot_as_of,
                )
                artifacts.append(manifest_artifact)
                manifest_target = manifest_artifact["path"]
            registry.attach_files(
                features.slate_id,
                feature_file=feature_artifact["path"],
                actuals_file=actuals_target,
                provenance_manifest=manifest_target,
                artifacts=artifacts,
            )
            if features.provider_game_set_verified and provider_evidence:
                registry.mark_provider_game_set_verified(
                    features.slate_id,
                    provider_slate_id=features.provider_slate_id,
                    draft_group_id=features.provider_slate_id,
                    evidence_artifact_ids=[provider_evidence["artifact_id"]],
                )
            events.append(
                {
                    "stage": "direct_upload",
                    "status": "REGISTERED",
                    "slate_id": features.slate_id,
                    "feature_sha256": feature_artifact["sha256"],
                    "actuals_supplied": actuals_target is not None,
                    "provider_evidence_supplied": provider_evidence is not None,
                }
            )
        except Exception as exc:
            events.append({"stage": "direct_upload", "status": "REJECTED", "file": str(feature_path), "reason": f"{type(exc).__name__}: {exc}"})
    return events


def _archive_declared_upload_artifacts(
    upload_dir: Path,
    *,
    artifact_dir: Path,
    slate_id: str,
) -> tuple[list[dict[str, Any]], set[Path]]:
    manifest_path = upload_dir / "artifact-manifest.json"
    if not manifest_path.exists():
        return [], set()
    payload = load_json(manifest_path)
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise PipelineCycleError("artifact-manifest.json must be a schema_version 1.0 object")
    records = payload.get("artifacts")
    if not isinstance(records, list) or not records:
        raise PipelineCycleError("artifact-manifest.json artifacts must be a non-empty array")
    upload_root = upload_dir.resolve()
    artifacts: list[dict[str, Any]] = []
    declared_paths: set[Path] = set()
    seen_ids: set[str] = set()
    captured_times: list[datetime] = []
    reserved_ids = {
        "feature-snapshot",
        "provider-game-set-evidence",
        "full-pool-actuals",
        "identity-mapping-audit",
        "provenance-manifest",
        "artifact-manifest",
    }
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise PipelineCycleError(f"artifact manifest record {index} must be an object")
        artifact_id = str(record.get("artifact_id", "")).strip()
        role = str(record.get("role", "")).strip()
        relative_path = str(record.get("path", "")).strip()
        source_url = str(record.get("source_url", "")).strip()
        if not artifact_id or artifact_id in seen_ids:
            raise PipelineCycleError(f"artifact manifest record {index} has missing/duplicate artifact_id")
        if artifact_id in reserved_ids:
            raise PipelineCycleError(
                f"artifact manifest record {index} uses reserved artifact_id {artifact_id}"
            )
        if not role or not relative_path:
            raise PipelineCycleError(f"artifact manifest record {index} requires role and path")
        if not source_url.startswith(("https://", "http://")):
            raise PipelineCycleError(f"artifact manifest record {index} requires http(s) source_url")
        source = (upload_root / relative_path).resolve()
        try:
            source.relative_to(upload_root)
        except ValueError as exc:
            raise PipelineCycleError(
                f"artifact manifest record {index} escapes upload directory"
            ) from exc
        try:
            captured_at = datetime.fromisoformat(
                str(record.get("captured_at", "")).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise PipelineCycleError(
                f"artifact manifest record {index} has invalid captured_at"
            ) from exc
        effective_value = record.get("effective_at")
        try:
            effective_at = (
                datetime.fromisoformat(str(effective_value).replace("Z", "+00:00"))
                if effective_value
                else None
            )
        except ValueError as exc:
            raise PipelineCycleError(
                f"artifact manifest record {index} has invalid effective_at"
            ) from exc
        captured_times.append(captured_at)
        artifacts.append(
            archive_artifact(
                source,
                artifact_dir=artifact_dir,
                slate_id=slate_id,
                artifact_id=artifact_id,
                role=role,
                captured_at=captured_at,
                effective_at=effective_at,
                source_url=source_url,
            )
        )
        declared_paths.add(source)
        seen_ids.add(artifact_id)
    manifest_artifact = archive_artifact(
        manifest_path,
        artifact_dir=artifact_dir,
        slate_id=slate_id,
        artifact_id="artifact-manifest",
        role="artifact_manifest",
        captured_at=max(captured_times),
    )
    artifacts.append(manifest_artifact)
    return artifacts, declared_paths


def _complete_actuals(config: PipelineConfig, registry: Registry) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for slate_id, entry in sorted(registry.load()["slates"].items()):
        if entry.get("state") != "awaiting-results" or entry.get("actuals_file"):
            continue
        feature_path = Path(str(entry["feature_file"]))
        output_dir = config.artifact_dir / slate_id / "statsapi-results"
        try:
            result = StatsApiFullPoolActualsBuilder(
                feature_path=feature_path,
                output_dir=output_dir,
                cache=ImmutableHttpCache(config.statsapi_cache_dir),
                offline=config.offline,
                retries=config.retries,
                timeout=config.timeout_seconds,
            ).build()
            actual_path = output_dir / result["actuals_file"]
            artifact = archive_artifact(
                actual_path,
                artifact_dir=config.artifact_dir,
                slate_id=slate_id,
                artifact_id="full-pool-actuals",
                role="postgame_actuals",
                captured_at=datetime.now(UTC),
            )
            result_artifacts = [artifact]
            identity_path = output_dir / result["identity_audit_file"]
            result_artifacts.append(
                archive_artifact(
                    identity_path,
                    artifact_dir=config.artifact_dir,
                    slate_id=slate_id,
                    artifact_id="identity-mapping-audit",
                    role="identity_mapping_audit",
                    captured_at=datetime.now(UTC),
                )
            )
            for feed in result.get("raw_game_feeds", []):
                raw_path = output_dir / str(feed["raw_file"])
                result_artifacts.append(
                    archive_artifact(
                        raw_path,
                        artifact_dir=config.artifact_dir,
                        slate_id=slate_id,
                        artifact_id=str(feed["artifact_id"]),
                        role="postgame_mlb_stats",
                        captured_at=datetime.now(UTC),
                        effective_at=datetime.fromisoformat(str(feed["fetched_at"])),
                        source_url=feed.get("url"),
                    )
                )
            registry.attach_files(
                slate_id,
                actuals_file=artifact["path"],
                artifacts=result_artifacts,
            )
            events.append({"stage": "actuals", "status": "COMPLETE", **result})
        except (StatsApiActualsError, RegistryError, OSError, ValueError) as exc:
            events.append(
                {
                    "stage": "actuals",
                    "status": "RETRY_LATER" if not config.offline else "OFFLINE_BLOCKED",
                    "slate_id": slate_id,
                    "reason": str(exc),
                }
            )
    return events


def _qualify_pending(registry: Registry) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for slate_id, entry in sorted(registry.load()["slates"].items()):
        if entry.get("state") not in {"awaiting-results", "qualified"} or not entry.get("actuals_file"):
            continue
        result = qualify_registry_entry(registry, entry)
        if result.qualified:
            registry.transition(
                slate_id,
                "qualified",
                "all strict historical qualification gates passed",
                qualification=result.to_dict(),
                rejection_reasons=[],
                blockers=[],
            )
        else:
            registry.transition(
                slate_id,
                "rejected",
                "one or more strict historical qualification gates failed",
                qualification=result.to_dict(),
                rejection_reasons=result.rejection_reasons,
            )
        events.append({"stage": "qualification", **result.to_dict()})
    return events


def _run_registry_backtest(
    config: PipelineConfig,
    registry: Registry,
    *,
    candidate_model: Path | None,
    label: str,
) -> dict[str, Any]:
    entries = registry.qualified_entries()
    if not entries:
        return {"status": "NOT_EVALUATED", "reason": "no qualified real slates"}
    input_dir = config.backtest_dir / f"{label}-inputs"
    output_dir = config.backtest_dir / f"{label}-output"
    if input_dir.exists():
        shutil.rmtree(input_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    input_dir.mkdir(parents=True)
    for entry in entries:
        feature = Path(str(entry["feature_file"]))
        actuals = Path(str(entry["actuals_file"]))
        shutil.copyfile(feature, input_dir / f"{entry['slate_id']}.features.json")
        shutil.copyfile(actuals, input_dir / f"{entry['slate_id']}.actuals.json")
    try:
        summary = run_backtest(
            BacktestConfig(
                seed=config.seed,
                site="dk",
                slate_dir=input_dir,
                lineups_per_method=config.lineups_per_method,
                output_dir=output_dir,
                min_real_slates=config.min_backtest_real_slates,
                bootstrap_samples=config.bootstrap_samples,
                qualified_registry=config.registry_path,
                candidate_model=candidate_model,
            )
        )
    except BacktestDataError as exc:
        return {"status": "FAILED", "reason": str(exc)}
    summary_path = output_dir / "summary.json"
    return {
        "status": "COMPLETE",
        "evaluation_status": summary["evaluation_status"],
        "valid_real_slates": summary["valid_real_slates"],
        "summary_path": str(summary_path.resolve()),
        "summary_sha256": sha256_file(summary_path),
        "candidate_model": str(candidate_model.resolve()) if candidate_model else None,
    }


def _without_rows(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    result = dict(value)
    result.pop("rows", None)
    return result
