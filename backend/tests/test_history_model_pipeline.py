from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backtest.io import write_json
from backtest.pipeline.config import PipelineConfig
from backtest.pipeline.cycle import run_cycle
from backtest.pipeline.modeling import (
    chronological_holdout_split,
    train_candidate_model,
)
from backtest.pipeline.qualification import qualify_registry_entry
from backtest.pipeline.registry import Registry, RegistryError, archive_artifact, sha256_file
from backtest.runner import BacktestConfig, run_backtest


BASE = datetime(2026, 7, 1, 20, 0, tzinfo=UTC)


def _source(role: str, artifact_id: str, raw_hash: str, available: datetime) -> dict:
    return {
        "source": artifact_id,
        "fetched_at": available.isoformat(),
        "published_at": available.isoformat(),
        "source_record_id": artifact_id,
        "role": role,
        "artifact_id": artifact_id,
        "source_url": f"https://example.test/{artifact_id}",
        "raw_sha256": raw_hash,
        "available_at": available.isoformat(),
        "retrieved_at": available.isoformat(),
        "timestamp_basis": "source_payload",
    }


def _player(
    player_id: int,
    position: list[str],
    team: str,
    opponent: str,
    game_id: int,
    salary: int,
    projection: float,
) -> dict:
    return {
        "mlbam_id": player_id,
        "name": f"Player {player_id}",
        "team": team,
        "opponent": opponent,
        "position": position,
        "salary": salary,
        "projected_points": projection,
        "lock": False,
        "exclude": False,
        "max_exposure": 1.0,
        "lineup_status": "expected",
        "external_id": f"dk-{player_id}",
        "name_id": f"Player {player_id} ({player_id})",
        "availability": "expected",
        "batting_order": None if position == ["P"] else ((player_id - 2) % 9) + 1,
        "projection_source": "pregame-audited-stats-v1",
        "feature_values": {"safe_signal": float(player_id % 7)},
        "game_id": game_id,
    }


def _valid_payloads(
    raw_hashes: dict[str, str],
    *,
    uniform_salary: bool = False,
    snapshot_at_lock: bool = False,
    missing_actual: bool = False,
    dnp_without_evidence: bool = False,
) -> tuple[dict, dict]:
    first = BASE + timedelta(hours=4)
    second = BASE + timedelta(hours=5)
    snapshot = first if snapshot_at_lock else first - timedelta(hours=1)
    players = [
        _player(1, ["P"], "AAA", "BBB", 1001, 9000, 18.0),
        _player(2, ["P"], "CCC", "DDD", 1002, 8800, 17.0),
        _player(3, ["C"], "BBB", "AAA", 1001, 3800, 8.0),
        _player(4, ["1B"], "AAA", "BBB", 1001, 4100, 9.0),
        _player(5, ["2B"], "DDD", "CCC", 1002, 3900, 8.5),
        _player(6, ["3B"], "CCC", "DDD", 1002, 4200, 9.5),
        _player(7, ["SS"], "BBB", "AAA", 1001, 4000, 9.0),
        _player(8, ["OF"], "AAA", "BBB", 1001, 4300, 10.0),
        _player(9, ["OF"], "DDD", "CCC", 1002, 4400, 10.5),
        _player(10, ["OF"], "CCC", "DDD", 1002, 4500, 11.0),
        _player(11, ["OF"], "BBB", "AAA", 1001, 3600, 7.5),
        _player(12, ["1B"], "DDD", "CCC", 1002, 3700, 7.8),
    ]
    if uniform_salary:
        for player in players:
            player["salary"] = 4500
    features = {
        "schema_version": "1.3",
        "data_kind": "real",
        "slate_id": "dk-real-2026-07-02-main",
        "site": "dk",
        "contest_style": "classic",
        "provider_slate_id": "draftgroup-verified-1",
        "scope": "provider_game_set",
        "provider_game_set_verified": True,
        "validation_scope": "FULL_RESEARCH",
        "warnings": [],
        "slate_start": first.isoformat(),
        "lock_time": first.isoformat(),
        "snapshot_as_of": snapshot.isoformat(),
        "game_ids": [1001, 1002],
        "games": [
            {
                "game_id": 1001,
                "away_team": "AAA",
                "home_team": "BBB",
                "scheduled_start": first.isoformat(),
                "source_record_id": "game-1001",
            },
            {
                "game_id": 1002,
                "away_team": "CCC",
                "home_team": "DDD",
                "scheduled_start": second.isoformat(),
                "source_record_id": "game-1002",
            },
        ],
        "sources": [
            _source("platform_slate_snapshot", "raw-slate", raw_hashes["slate"], snapshot),
            _source("platform_salary_snapshot", "raw-salary", raw_hashes["salary"], snapshot),
            _source("pregame_mlb_stats", "raw-stats", raw_hashes["stats"], snapshot),
        ],
        "settings": {
            "stack_team": None,
            "stack_count": 0,
            "pitcher_vs_batter_same_team": "allow",
            "min_salary_used": 0,
            "unique_lineups": True,
        },
        "players": players,
    }
    points = []
    for player in players:
        if missing_actual and player["mlbam_id"] == 12:
            continue
        is_dnp = player["mlbam_id"] == 11
        points.append(
            {
                "mlbam_id": player["mlbam_id"],
                "actual_points": 0.0 if is_dnp else float(player["mlbam_id"] + 2),
                "status": "dnp_no_game_appearance" if is_dnp else "played",
                "source_game_id": None if is_dnp and dnp_without_evidence else player["game_id"],
                "source_evidence_id": None if is_dnp and dnp_without_evidence else f"game-{player['game_id']}",
                "scoring_components": {"role": "test"},
            }
        )
    actuals = {
        "schema_version": "1.2" if missing_actual else "1.3",
        "data_kind": "real",
        "slate_id": features["slate_id"],
        "site": "dk",
        "scoring_source": "official_mlb_statsapi_feed_live_reconstruction",
        "scoring_rules_version": "dk-mlb-classic-v1",
        "acquired_at": (second + timedelta(hours=4)).isoformat(),
        "source_timestamp": (second + timedelta(hours=3)).isoformat(),
        "source_record_id": "1001;1002",
        "source_final": True,
        "validation_scope": "FULL_RESEARCH",
        "coverage_scope": "all_feature_players",
        "warnings": [],
        "raw_stats_artifact_ids": ["game-1001", "game-1002"],
        "scoring_rules_artifact_id": "dk-rules-code-v1",
        "points": points,
    }
    if not missing_actual:
        actuals["coverage_summary"] = {
            "feature_player_count": len(players),
            "records_count": len(points),
            "played_count": len(points) - 1,
            "dnp_count": 1,
            "missing_ids": [],
            "extra_ids": [],
        }
    return features, actuals


def _registered_slate(
    root: Path,
    *,
    uniform_salary: bool = False,
    registry_provider_verified: bool = True,
    snapshot_at_lock: bool = False,
    missing_actual: bool = False,
    dnp_without_evidence: bool = False,
    identity_ambiguity: bool = False,
) -> tuple[Registry, dict]:
    artifacts_root = root / "artifacts"
    raw_files = {}
    raw_hashes = {}
    for name in ("slate", "salary", "stats"):
        path = root / f"raw-{name}.json"
        path.write_text(json.dumps({"name": name}), encoding="utf-8")
        raw_files[name] = path
        raw_hashes[name] = sha256_file(path)
    features, actuals = _valid_payloads(
        raw_hashes,
        uniform_salary=uniform_salary,
        snapshot_at_lock=snapshot_at_lock,
        missing_actual=missing_actual,
        dnp_without_evidence=dnp_without_evidence,
    )
    feature_path = root / f"{features['slate_id']}.features.json"
    actual_path = root / f"{features['slate_id']}.actuals.json"
    write_json(feature_path, features)
    write_json(actual_path, actuals)
    provider_evidence_path = root / "provider-game-set-evidence.json"
    write_json(
        provider_evidence_path,
        {
            "schema_version": "1.0",
            "provider": "draftkings",
            "provider_slate_id": features["provider_slate_id"],
            "draft_group_id": features["provider_slate_id"],
            "source_url": "https://example.test/draftgroup-verified-1",
            "captured_at": BASE.isoformat(),
        },
    )
    identity_path = root / "identity-mapping-audit.json"
    write_json(
        identity_path,
        {
            "schema_version": "1.0",
            "ambiguous_count": 1 if identity_ambiguity else 0,
            "unresolved_count": 0,
            "records": [],
        },
    )
    game_paths = []
    for game_id in (1001, 1002):
        game_path = root / f"game-{game_id}.json"
        game_path.write_text(json.dumps({"gamePk": game_id, "final": True}), encoding="utf-8")
        game_paths.append((game_id, game_path))

    captured_at = BASE
    artifacts = []
    for name, path in raw_files.items():
        artifacts.append(
            archive_artifact(
                path,
                artifact_dir=artifacts_root,
                slate_id=features["slate_id"],
                artifact_id=f"raw-{name}",
                role="raw_source_artifact",
                captured_at=captured_at,
                source_url=f"https://example.test/raw-{name}",
            )
        )
    feature_artifact = archive_artifact(
        feature_path,
        artifact_dir=artifacts_root,
        slate_id=features["slate_id"],
        artifact_id="feature-snapshot",
        role="qualified_feature_candidate",
        captured_at=captured_at,
    )
    actual_artifact = archive_artifact(
        actual_path,
        artifact_dir=artifacts_root,
        slate_id=features["slate_id"],
        artifact_id="full-pool-actuals",
        role="postgame_actuals",
        captured_at=captured_at,
    )
    provider_evidence_artifact = archive_artifact(
        provider_evidence_path,
        artifact_dir=artifacts_root,
        slate_id=features["slate_id"],
        artifact_id="provider-game-set-evidence",
        role="provider_game_set_evidence",
        captured_at=captured_at,
        source_url="https://example.test/draftgroup-verified-1",
    )
    identity_artifact = archive_artifact(
        identity_path,
        artifact_dir=artifacts_root,
        slate_id=features["slate_id"],
        artifact_id="identity-mapping-audit",
        role="identity_mapping_audit",
        captured_at=captured_at,
    )
    artifacts.extend(
        [feature_artifact, actual_artifact, provider_evidence_artifact, identity_artifact]
    )
    for game_id, game_path in game_paths:
        artifacts.append(
            archive_artifact(
                game_path,
                artifact_dir=artifacts_root,
                slate_id=features["slate_id"],
                artifact_id=f"game-{game_id}",
                role="postgame_mlb_stats",
                captured_at=captured_at,
            )
        )
    registry = Registry(root / "registry.json", clock=lambda: BASE)
    registry.upsert_captured(
        slate_id=features["slate_id"],
        data_kind="real",
        site="dk",
        captured_at=BASE,
        effective_at=datetime.fromisoformat(features["snapshot_as_of"]),
        provider="draftkings_direct_upload",
        provider_slate_id=features["provider_slate_id"],
        draft_group_id=features["provider_slate_id"],
        provider_game_set_verified=registry_provider_verified,
        artifacts=artifacts,
    )
    registry.attach_files(
        features["slate_id"],
        feature_file=feature_artifact["path"],
        actuals_file=actual_artifact["path"],
        artifacts=artifacts,
    )
    return registry, registry.get(features["slate_id"])


def _model_rows(*, legacy_exact: bool = False, leak: bool = False) -> list[dict]:
    rows = []
    for day in range(10):
        date = f"2026-07-{day + 1:02d}"
        for role, offset in (("hitter", 2.0), ("pitcher", 8.0)):
            for index in range(12):
                signal = float(index + day)
                actual = 1.5 * signal + offset
                rows.append(
                    {
                        "slate_id": f"slate-{date}",
                        "slate_date": date,
                        "slate_start": f"{date}T20:00:00+00:00",
                        "game_start": f"{date}T20:00:00+00:00",
                        "feature_available_at": (
                            f"{date}T21:00:00+00:00" if leak else f"{date}T18:00:00+00:00"
                        ),
                        "mlbam_id": day * 1000 + index + (0 if role == "hitter" else 500),
                        "role": role,
                        "legacy_projection": actual if legacy_exact else actual + 5.0,
                        "salary": 3000.0 + signal,
                        "fv_signal": signal,
                        "target_actual_points": actual,
                    }
                )
    return rows


class RegistryQualificationTests(unittest.TestCase):
    def test_state_machine_and_idempotent_registration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry, entry = _registered_slate(root)
            second = registry.upsert_captured(
                slate_id=entry["slate_id"],
                data_kind="real",
                site="dk",
                captured_at=BASE,
                effective_at=datetime.fromisoformat(entry["effective_at"]),
                provider="draftkings_direct_upload",
                provider_slate_id="draftgroup-verified-1",
                draft_group_id="draftgroup-verified-1",
                provider_game_set_verified=True,
                artifacts=entry["artifacts"],
            )
            self.assertEqual(second["state"], "awaiting-results")
            self.assertEqual(len(second["state_history"]), 2)
            with self.assertRaises(RegistryError):
                registry.upsert_captured(
                    slate_id=entry["slate_id"],
                    data_kind="real",
                    site="dk",
                    captured_at=BASE + timedelta(minutes=1),
                    effective_at=datetime.fromisoformat(entry["effective_at"]),
                    provider="draftkings_direct_upload",
                    provider_slate_id="draftgroup-verified-1",
                    draft_group_id="draftgroup-verified-1",
                    provider_game_set_verified=True,
                    artifacts=entry["artifacts"],
                )
            result = qualify_registry_entry(registry, second)
            self.assertTrue(result.qualified, result.rejection_reasons)
            registry.transition(entry["slate_id"], "qualified", "tests", qualification=result.to_dict())
            registry.transition(entry["slate_id"], "backtested", "tests")
            registry.transition(entry["slate_id"], "backtested", "idempotent")
            self.assertEqual(registry.get(entry["slate_id"])["state"], "backtested")
            with self.assertRaises(RegistryError):
                registry.transition(entry["slate_id"], "awaiting-results", "illegal after backtest")
            registry.transition(entry["slate_id"], "rejected", "integrity quarantine")
            self.assertEqual(registry.get(entry["slate_id"])["state"], "rejected")

    def test_repeated_attach_and_same_state_transition_preserve_registry_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry, entry = _registered_slate(root)
            before_hash = sha256_file(registry.path)
            before_bytes = registry.path.read_bytes()
            registry.attach_files(
                entry["slate_id"],
                feature_file=entry["feature_file"],
                actuals_file=entry["actuals_file"],
                artifacts=entry["artifacts"],
            )
            registry.transition(entry["slate_id"], "awaiting-results", "repeat no-op")
            self.assertEqual(registry.path.read_bytes(), before_bytes)
            self.assertEqual(sha256_file(registry.path), before_hash)

    def test_provider_verification_requires_registered_evidence_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry, entry = _registered_slate(root, registry_provider_verified=False)
            self.assertFalse(entry["provider_game_set_verified"])
            with self.assertRaises(RegistryError):
                registry.mark_provider_game_set_verified(
                    entry["slate_id"],
                    provider_slate_id="draftgroup-verified-1",
                    draft_group_id="draftgroup-verified-1",
                    evidence_artifact_ids=["missing-evidence"],
                )
            registry.mark_provider_game_set_verified(
                entry["slate_id"],
                provider_slate_id="draftgroup-verified-1",
                draft_group_id="draftgroup-verified-1",
                evidence_artifact_ids=["provider-game-set-evidence"],
            )
            before = registry.path.read_bytes()
            registry.mark_provider_game_set_verified(
                entry["slate_id"],
                provider_slate_id="draftgroup-verified-1",
                draft_group_id="draftgroup-verified-1",
                evidence_artifact_ids=["provider-game-set-evidence"],
            )
            self.assertEqual(registry.path.read_bytes(), before)
            self.assertTrue(registry.get(entry["slate_id"])["provider_game_set_verified"])

    def test_corrupt_hash_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry, entry = _registered_slate(Path(directory))
            artifact = Path(entry["artifacts"][0]["path"])
            artifact.chmod(0o644)
            artifact.write_text("corrupt", encoding="utf-8")
            failures = registry.verify_all_artifacts()
            self.assertEqual(failures[0]["reason"], "hash_or_size_mismatch")

    def test_uniform_salary_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry, entry = _registered_slate(Path(directory), uniform_salary=True)
            result = qualify_registry_entry(registry, entry)
            self.assertFalse(result.qualified)
            self.assertTrue(any("non_uniform_salary" in reason for reason in result.rejection_reasons))

    def test_unverified_game_set_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry, entry = _registered_slate(Path(directory), registry_provider_verified=False)
            result = qualify_registry_entry(registry, entry)
            self.assertFalse(result.qualified)
            self.assertTrue(any("provider_game_set_verified" in reason for reason in result.rejection_reasons))

    def test_capture_at_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry, entry = _registered_slate(Path(directory), snapshot_at_lock=True)
            result = qualify_registry_entry(registry, entry)
            self.assertFalse(result.qualified)
            self.assertTrue(any("pregame_capture" in reason for reason in result.rejection_reasons))

    def test_missing_actual_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry, entry = _registered_slate(Path(directory), missing_actual=True)
            result = qualify_registry_entry(registry, entry)
            self.assertFalse(result.qualified)
            self.assertTrue(any("full_pool_coverage" in reason for reason in result.rejection_reasons))

    def test_dnp_without_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry, entry = _registered_slate(Path(directory), dnp_without_evidence=True)
            result = qualify_registry_entry(registry, entry)
            self.assertFalse(result.qualified)
            self.assertTrue(any("dnp_evidence" in reason for reason in result.rejection_reasons))

    def test_identity_ambiguity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry, entry = _registered_slate(Path(directory), identity_ambiguity=True)
            result = qualify_registry_entry(registry, entry)
            self.assertFalse(result.qualified)
            self.assertTrue(any("identity_unambiguous" in reason for reason in result.rejection_reasons))


class ChronologicalModelTests(unittest.TestCase):
    def test_same_day_rows_never_cross_split(self) -> None:
        rows = _model_rows()
        split = chronological_holdout_split(
            rows, test_fraction=0.2, min_train_slates=5, min_test_slates=2
        )
        self.assertTrue(set(split.train_dates).isdisjoint(split.test_dates))
        self.assertLess(max(split.train_dates), min(split.test_dates))

    def test_insufficient_training_is_rejected_not_evaluated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = train_candidate_model(
                rows=_model_rows()[:20],
                feature_schema=["salary", "fv_signal"],
                output_dir=Path(directory),
                dataset_sha256="a" * 64,
                slate_hashes={},
                code_version="test",
                seed=7,
                ridge_alpha=1.0,
                test_fraction=0.2,
                min_train_slates=8,
                min_test_slates=3,
                min_test_rows_per_role=5,
                required_mae_relative_improvement=0.0,
                max_rmse_relative_regression=0.0,
                max_correlation_drop=0.01,
            )
            self.assertEqual(result["status"], "REJECTED_NOT_EVALUATED")
            self.assertIsNone(result["model_path"])

    def test_promotion_pass_creates_candidate_only_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = train_candidate_model(
                rows=_model_rows(),
                feature_schema=["salary", "fv_signal"],
                output_dir=Path(directory),
                dataset_sha256="b" * 64,
                slate_hashes={"s": {"features_sha256": "c" * 64, "actuals_sha256": "d" * 64}},
                code_version="test-code",
                seed=7,
                ridge_alpha=0.01,
                test_fraction=0.2,
                min_train_slates=5,
                min_test_slates=2,
                min_test_rows_per_role=10,
                required_mae_relative_improvement=0.0,
                max_rmse_relative_regression=0.0,
                max_correlation_drop=0.01,
            )
            self.assertEqual(result["status"], "PROMOTION_ELIGIBLE_CANDIDATE")
            report = json.loads(Path(result["report_path"]).read_text())
            self.assertFalse(report["production_default_replaced"])
            model = json.loads(Path(result["model_path"]).read_text())
            self.assertEqual(model["status"], "CANDIDATE_ONLY_NOT_DEPLOYED")
            self.assertEqual(set(model["role_models"]), {"hitter", "pitcher"})

    def test_promotion_fail_keeps_rejected_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = train_candidate_model(
                rows=_model_rows(legacy_exact=True),
                feature_schema=["salary"],
                output_dir=Path(directory),
                dataset_sha256="e" * 64,
                slate_hashes={},
                code_version="test",
                seed=9,
                ridge_alpha=1000.0,
                test_fraction=0.2,
                min_train_slates=5,
                min_test_slates=2,
                min_test_rows_per_role=10,
                required_mae_relative_improvement=0.0,
                max_rmse_relative_regression=0.0,
                max_correlation_drop=0.0,
            )
            self.assertEqual(result["status"], "REJECTED_CANDIDATE")
            self.assertIsNotNone(result["model_path"])

    def test_event_time_leakage_forces_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = train_candidate_model(
                rows=_model_rows(leak=True),
                feature_schema=["salary", "fv_signal"],
                output_dir=Path(directory),
                dataset_sha256="f" * 64,
                slate_hashes={},
                code_version="test",
                seed=9,
                ridge_alpha=0.01,
                test_fraction=0.2,
                min_train_slates=5,
                min_test_slates=2,
                min_test_rows_per_role=10,
                required_mae_relative_improvement=0.0,
                max_rmse_relative_regression=0.0,
                max_correlation_drop=0.01,
            )
            self.assertEqual(result["status"], "REJECTED_CANDIDATE")
            report = json.loads(Path(result["report_path"]).read_text())
            self.assertEqual(report["leakage_checks"]["event_time_columns"], "FAIL")

    def test_candidate_model_is_additive_in_qualified_backtest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry, entry = _registered_slate(root)
            qualification = qualify_registry_entry(registry, entry)
            self.assertTrue(qualification.qualified, qualification.rejection_reasons)
            registry.transition(
                entry["slate_id"],
                "qualified",
                "test qualification",
                qualification=qualification.to_dict(),
            )
            model_result = train_candidate_model(
                rows=_model_rows(),
                feature_schema=["salary", "fv_signal"],
                output_dir=root / "model",
                dataset_sha256="9" * 64,
                slate_hashes={},
                code_version="test",
                seed=31,
                ridge_alpha=0.01,
                test_fraction=0.2,
                min_train_slates=5,
                min_test_slates=2,
                min_test_rows_per_role=10,
                required_mae_relative_improvement=0.0,
                max_rmse_relative_regression=0.0,
                max_correlation_drop=0.01,
            )
            self.assertIsNotNone(model_result["model_path"])
            slate_dir = root / "backtest-input"
            slate_dir.mkdir()
            shutil.copyfile(
                entry["feature_file"],
                slate_dir / f"{entry['slate_id']}.features.json",
            )
            shutil.copyfile(
                entry["actuals_file"],
                slate_dir / f"{entry['slate_id']}.actuals.json",
            )
            summary = run_backtest(
                BacktestConfig(
                    seed=31,
                    site="dk",
                    slate_dir=slate_dir,
                    lineups_per_method=1,
                    output_dir=root / "backtest-output",
                    min_real_slates=2,
                    bootstrap_samples=50,
                    qualified_registry=registry.path,
                    candidate_model=Path(model_result["model_path"]),
                )
            )
            self.assertEqual(summary["evaluation_status"], "INSUFFICIENT DATA / NOT EVALUATED")
            self.assertIsNotNone(summary["slates"][0]["candidate_model_mean_actual"])
            rows = json.loads(
                (root / "backtest-output" / f"{entry['slate_id']}.lineups.json").read_text()
            )
            self.assertEqual(
                {row["method"] for row in rows},
                {"random", "legacy", "optimized", "candidate_model"},
            )

    def test_model_serialization_and_hash_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            kwargs = dict(
                rows=_model_rows(),
                feature_schema=["salary", "fv_signal"],
                dataset_sha256="1" * 64,
                slate_hashes={},
                code_version="test",
                seed=123,
                ridge_alpha=0.1,
                test_fraction=0.2,
                min_train_slates=5,
                min_test_slates=2,
                min_test_rows_per_role=10,
                required_mae_relative_improvement=0.0,
                max_rmse_relative_regression=0.0,
                max_correlation_drop=0.01,
            )
            first = train_candidate_model(output_dir=Path(one), **kwargs)
            second = train_candidate_model(output_dir=Path(two), **kwargs)
            self.assertEqual(first["model_sha256"], second["model_sha256"])
            self.assertEqual(first["report_sha256"], second["report_sha256"])
            report = json.loads(Path(first["report_path"]).read_text())
            self.assertEqual(report["determinism"]["status"], "PASS")
            self.assertGreater(report["walk_forward_validation_on_pre_holdout_dates"]["fold_count"], 0)


class CycleTests(unittest.TestCase):
    def test_direct_upload_enriches_earlier_capture_and_qualifies_with_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox" / "slate"
            raw_dir = inbox / "raw"
            postgame_dir = raw_dir / "postgame"
            postgame_dir.mkdir(parents=True)
            raw_hashes: dict[str, str] = {}
            for name in ("slate", "salary", "stats"):
                source = raw_dir / f"{name}.json"
                source.write_text(json.dumps({"name": name}), encoding="utf-8")
                raw_hashes[name] = sha256_file(source)
            features, actuals = _valid_payloads(raw_hashes)
            feature_path = inbox / f"{features['slate_id']}.features.json"
            actuals_path = inbox / f"{features['slate_id']}.actuals.json"
            write_json(feature_path, features)
            write_json(actuals_path, actuals)
            write_json(
                inbox / "provider-game-set-evidence.json",
                {
                    "schema_version": "1.0",
                    "provider": "draftkings",
                    "provider_slate_id": features["provider_slate_id"],
                    "draft_group_id": features["provider_slate_id"],
                    "source_url": "https://example.test/provider-game-set",
                    "captured_at": BASE.isoformat(),
                },
            )
            write_json(
                inbox / "identity-mapping-audit.json",
                {
                    "schema_version": "1.0",
                    "ambiguous_count": 0,
                    "unresolved_count": 0,
                    "records": [],
                },
            )
            manifest_records = []
            for game_id in (1001, 1002):
                game_path = postgame_dir / f"game-{game_id}.json"
                game_path.write_text(
                    json.dumps({"gamePk": game_id, "final": True}),
                    encoding="utf-8",
                )
                manifest_records.append(
                    {
                        "artifact_id": f"game-{game_id}",
                        "role": "postgame_mlb_stats",
                        "path": f"raw/postgame/game-{game_id}.json",
                        "source_url": f"https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live",
                        "captured_at": (BASE + timedelta(hours=9)).isoformat(),
                        "effective_at": (BASE + timedelta(hours=8)).isoformat(),
                    }
                )
            write_json(
                inbox / "artifact-manifest.json",
                {"schema_version": "1.0", "artifacts": manifest_records},
            )

            salary_capture = root / "captured-salary.csv"
            salary_capture.write_text("Name,Salary\nExample,5000\n", encoding="utf-8")
            salary_artifact = archive_artifact(
                salary_capture,
                artifact_dir=root / "artifacts",
                slate_id=features["slate_id"],
                artifact_id="draftkings-salary-export",
                role="platform_salary_snapshot",
                captured_at=BASE,
                effective_at=datetime.fromisoformat(features["lock_time"]),
                source_url="https://example.test/dk-salary-download",
            )
            registry = Registry(root / "catalog" / "registry.json", clock=lambda: BASE)
            registry.upsert_captured(
                slate_id=features["slate_id"],
                data_kind="real",
                site="dk",
                captured_at=BASE,
                effective_at=datetime.fromisoformat(features["lock_time"]),
                provider="draftkings_direct_upload",
                provider_slate_id=None,
                draft_group_id=None,
                provider_game_set_verified=False,
                artifacts=[salary_artifact],
                blockers=["provider_game_set_unverified"],
            )
            config = PipelineConfig(
                root_dir=root,
                inbox_dir=root / "inbox",
                artifact_dir=root / "artifacts",
                registry_path=registry.path,
                statsapi_cache_dir=root / "cache",
                backtest_dir=root / "backtests",
                dataset_dir=root / "datasets",
                model_dir=root / "models",
                report_dir=root / "reports",
                offline=True,
                lineups_per_method=1,
                min_backtest_real_slates=2,
                bootstrap_samples=50,
                min_train_slates=5,
                min_test_slates=2,
                min_test_rows_per_role=10,
            )
            result = run_cycle(config)
            updated = Registry(registry.path).get(features["slate_id"])
            self.assertEqual(updated["state"], "backtested")
            self.assertTrue(updated["provider_game_set_verified"])
            self.assertEqual(updated["provider_slate_id"], features["provider_slate_id"])
            self.assertEqual(result["baseline_backtest"]["status"], "COMPLETE")
            self.assertEqual(result["model"]["status"], "REJECTED_NOT_EVALUATED")
            self.assertEqual(Registry(registry.path).verify_all_artifacts(), [])
            registry_bytes = registry.path.read_bytes()
            second = run_cycle(config)
            self.assertEqual(second["status"], "COMPLETE")
            self.assertEqual(registry.path.read_bytes(), registry_bytes)

    def test_empty_offline_cycle_is_explicitly_not_evaluated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = PipelineConfig(
                root_dir=root,
                inbox_dir=root / "inbox",
                artifact_dir=root / "artifacts",
                registry_path=root / "catalog" / "registry.json",
                statsapi_cache_dir=root / "cache",
                backtest_dir=root / "backtests",
                dataset_dir=root / "datasets",
                model_dir=root / "models",
                report_dir=root / "reports",
                offline=True,
                min_train_slates=5,
                min_test_slates=2,
                min_test_rows_per_role=10,
            )
            result = run_cycle(config)
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["baseline_backtest"]["status"], "NOT_EVALUATED")
            self.assertEqual(result["model"]["status"], "REJECTED_NOT_EVALUATED")
            self.assertFalse(result["production_changes"])
            self.assertTrue(Path(result["cycle_report_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
