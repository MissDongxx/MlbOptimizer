from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from backtest.contracts import SlateFeatureSnapshot
from backtest.historical.builder import HistoricalBuilderError, HistoricalSlateBuilder
from backtest.historical.identity import (
    IdentityMappingError,
    MlbIdentity,
    PlatformPlayerIdentity,
    map_identities,
    normalize_name,
)
from backtest.historical.projection import HistoricalFantasyGame, project_player
from backtest.historical.scoring import (
    HitterGameStats,
    PitcherGameStats,
    score_hitter_game,
    score_pitcher_game,
)
from backtest.provenance import RawArtifact
from backtest.runner import BacktestConfig, run_backtest


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "backtest" / "fixtures" / "smoke"


class HistoricalDataTests(unittest.TestCase):
    def test_dk_hitter_scoring(self) -> None:
        stats = HitterGameStats(
            mlbam_id=1,
            game_id=2,
            hits=2,
            home_runs=1,
            runs=1,
            rbi=2,
            walks=1,
            stolen_bases=1,
        )
        self.assertEqual(score_hitter_game(stats), 26.0)

    def test_dk_pitcher_scoring_uses_outs_not_baseball_decimal(self) -> None:
        stats = PitcherGameStats(
            mlbam_id=1,
            game_id=2,
            outs_recorded=18,
            strikeouts=8,
            win=True,
            earned_runs=2,
            hits_allowed=5,
            walks_allowed=2,
            hit_batters=1,
        )
        self.assertAlmostEqual(score_pitcher_game(stats), 24.7)

    def test_dk_pitcher_bonuses_are_cumulative_per_game(self) -> None:
        stats = PitcherGameStats(
            mlbam_id=1,
            game_id=2,
            outs_recorded=27,
            strikeouts=10,
            win=True,
            complete_game=True,
            complete_game_shutout=True,
            no_hitter=True,
        )
        self.assertAlmostEqual(score_pitcher_game(stats), 54.25)

    def test_projection_strictly_excludes_cutoff_date_and_future(self) -> None:
        history = [
            HistoricalFantasyGame(1, 10, date(2026, 6, 30), "hitter", 10.0),
            HistoricalFantasyGame(1, 11, date(2026, 7, 1), "hitter", 1000.0),
            HistoricalFantasyGame(1, 12, date(2026, 7, 2), "hitter", 1000.0),
        ]
        projection, audit = project_player(
            history,
            mlbam_id=1,
            role="hitter",
            cutoff=datetime(2026, 7, 1, 23, 5, tzinfo=UTC),
            prior_weight=0,
        )
        self.assertEqual(projection, 10.0)
        self.assertEqual(audit["history_games_used"], 1)
        self.assertEqual(audit["cutoff_or_future_rows_ignored"], 2)
        self.assertEqual(
            audit["cutoff_timestamp_exclusive"], "2026-07-01T23:05:00+00:00"
        )

    def test_identity_mapping_requires_explicit_resolution_for_ambiguity(self) -> None:
        platform = [PlatformPlayerIdentity("dk-1", "Jose Ramirez Jr.", "CLE")]
        candidates = [
            MlbIdentity(1, "José Ramírez", "CLE"),
            MlbIdentity(2, "Jose Ramirez", "CLE"),
        ]
        self.assertEqual(normalize_name("José Ramírez Jr."), "jose ramirez")
        with self.assertRaises(IdentityMappingError) as context:
            map_identities(platform, candidates)
        self.assertEqual(context.exception.decisions[0].status, "ambiguous")
        mapping, decisions = map_identities(platform, candidates, overrides={"dk-1": 2})
        self.assertEqual(mapping, {"dk-1": 2})
        self.assertEqual(decisions[0].method, "explicit_override")

    def test_postgame_provenance_requires_finalized_content(self) -> None:
        with self.assertRaises(ValidationError):
            RawArtifact(
                artifact_id="postgame",
                role="postgame_mlb_stats",
                source_name="test",
                source_url="https://example.invalid/postgame",
                local_path="postgame.json",
                sha256="0" * 64,
                acquired_at="2026-07-03T00:00:00Z",
                effective_at="2026-07-02T06:00:00Z",
                timestamp_basis="source_payload",
                temporal_class="postgame",
                pregame_semantics=False,
                license_status="verified_redistributable",
                redistribution_included=False,
                finalized=False,
            )

    def test_merely_relabeling_fixture_as_real_fails_contract(self) -> None:
        feature_path = next(FIXTURE_DIR.glob("*.features.json"))
        payload = json.loads(feature_path.read_text())
        payload["data_kind"] = "real"
        with self.assertRaises(ValidationError):
            SlateFeatureSnapshot.model_validate(payload)


    def test_fixture_bundle_builds_and_runs_all_methods(self) -> None:
        bundle = FIXTURE_DIR.parent / "historical-builder" / "bundle.json"
        with (
            tempfile.TemporaryDirectory() as build_dir,
            tempfile.TemporaryDirectory() as output_dir,
        ):
            result = HistoricalSlateBuilder(bundle, Path(build_dir)).build()
            self.assertEqual(result["data_kind"], "fixture")
            self.assertEqual(result["qualified_real_slates_in_manifest"], 0)
            self.assertFalse((Path(build_dir) / "provenance-manifest.json").exists())

            summary = run_backtest(
                BacktestConfig(
                    seed=20260729,
                    site="dk",
                    slate_dir=Path(build_dir),
                    lineups_per_method=2,
                    output_dir=Path(output_dir),
                    bootstrap_samples=20,
                )
            )
            self.assertEqual(summary["valid_slates_total"], 1)
            self.assertEqual(summary["valid_real_slates"], 0)
            self.assertEqual(summary["failed_or_skipped_slates"], 0)
            self.assertEqual(summary["gates"]["minimum_real_slates"]["status"], "FAIL")
            slate = summary["slates"][0]
            self.assertEqual(slate["lineups_per_method"], 2)

    def test_historical_builder_rejects_missing_full_pool_postgame_evidence(self) -> None:
        source_root = FIXTURE_DIR.parent / "historical-builder"
        with tempfile.TemporaryDirectory() as temp_root, tempfile.TemporaryDirectory() as output_dir:
            copied = Path(temp_root) / "historical-builder"
            shutil.copytree(source_root, copied)
            postgame_path = copied / "raw-input" / "fixture-postgame-stats.json"
            payload = json.loads(postgame_path.read_text())
            removed = payload["rows"].pop()
            postgame_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            bundle_path = copied / "bundle.json"
            bundle = json.loads(bundle_path.read_text())
            for artifact in bundle["artifacts"]:
                if artifact["role"] == "postgame_mlb_stats":
                    artifact["sha256"] = hashlib.sha256(postgame_path.read_bytes()).hexdigest()
            bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
            with self.assertRaisesRegex(
                HistoricalBuilderError, "lacks explicit full-pool player evidence"
            ):
                HistoricalSlateBuilder(bundle_path, Path(output_dir)).build()
            self.assertIsInstance(removed["mlbam_id"], int)

    def test_real_contract_without_manifest_is_rejected_by_runner(self) -> None:
        with (
            tempfile.TemporaryDirectory() as input_dir,
            tempfile.TemporaryDirectory() as output_dir,
        ):
            root = Path(input_dir)
            feature_source = next(FIXTURE_DIR.glob("*.features.json"))
            actual_source = next(FIXTURE_DIR.glob("*.actuals.json"))
            features = json.loads(feature_source.read_text())
            actuals = json.loads(actual_source.read_text())
            lock = features["lock_time"]
            features.update(
                {
                    "schema_version": "1.1",
                    "data_kind": "real",
                    "contest_style": "classic",
                    "provider_slate_id": "draftgroup-test-only",
                    "game_ids": [1, 2],
                    "games": [
                        {
                            "game_id": 1,
                            "away_team": "LAD",
                            "home_team": "NYY",
                            "scheduled_start": lock,
                            "source_record_id": "test-game-1",
                        },
                        {
                            "game_id": 2,
                            "away_team": "ATL",
                            "home_team": "HOU",
                            "scheduled_start": "2026-07-02T00:05:00Z",
                            "source_record_id": "test-game-2",
                        },
                    ],
                    "sources": [
                        self._real_source("slate", "platform_slate_snapshot"),
                        self._real_source("salary", "platform_salary_snapshot"),
                        self._real_source("stats", "pregame_mlb_stats"),
                    ],
                }
            )
            for player in features["players"]:
                player["game_id"] = 1 if player["team"] in {"LAD", "NYY"} else 2
            actuals.update(
                {
                    "schema_version": "1.1",
                    "data_kind": "real",
                    "source_final": True,
                    "raw_stats_artifact_ids": ["postgame"],
                    "scoring_rules_artifact_id": "rules",
                }
            )
            feature_path = root / feature_source.name.replace("fixture-", "real-")
            actual_path = root / actual_source.name.replace("fixture-", "real-")
            features["slate_id"] = feature_path.name.replace(".features.json", "")
            actuals["slate_id"] = features["slate_id"]
            feature_path.write_text(json.dumps(features, sort_keys=True, indent=2) + "\n")
            actual_path.write_text(json.dumps(actuals, sort_keys=True, indent=2) + "\n")

            summary = run_backtest(
                BacktestConfig(
                    seed=1,
                    site="dk",
                    slate_dir=root,
                    lineups_per_method=1,
                    output_dir=Path(output_dir),
                    bootstrap_samples=20,
                )
            )
            self.assertEqual(summary["valid_real_slates"], 0)
            self.assertEqual(summary["failed_or_skipped_slates"], 1)
            self.assertEqual(summary["failures"][0]["reason_type"], "ProvenanceError")
            self.assertIn("Missing provenance manifest", summary["failures"][0]["reason"])

    @staticmethod
    def _real_source(name: str, role: str) -> dict[str, object]:
        digest = hashlib.sha256(name.encode()).hexdigest()
        return {
            "source": f"test-{name}",
            "fetched_at": "2026-07-01T22:00:00Z",
            "published_at": "2026-07-01T22:00:00Z",
            "source_record_id": name,
            "role": role,
            "artifact_id": name,
            "source_url": f"https://example.invalid/{name}",
            "raw_sha256": digest,
            "available_at": "2026-07-01T22:00:00Z",
            "retrieved_at": "2026-07-03T12:00:00Z",
            "timestamp_basis": "archive_capture",
        }


if __name__ == "__main__":
    unittest.main()
