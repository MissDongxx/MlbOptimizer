from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from backtest.contracts import SlateActualPoints, SlateFeatureSnapshot
from backtest.historical.capture import SlateCaptureError, capture_current_dk_slate
from backtest.historical.http_cache import HttpCacheError, ImmutableHttpCache
from backtest.historical.mlb_statsapi import StatsApiFullPoolActualsBuilder
from backtest.historical.projection import HistoricalFantasyGame, project_player
from backtest.runner import SELECTED_ACTUALS_ACK, BacktestConfig, run_backtest


BACKTEST_ROOT = Path(__file__).resolve().parents[1] / "backtest"
STATS_FEATURES = BACKTEST_ROOT / "fixtures" / "statsapi-full-pool.features.json"
STATS_CACHE = BACKTEST_ROOT / "fixtures" / "statsapi-cache"
SMOKE_DIR = BACKTEST_ROOT / "fixtures" / "smoke"
DK_FIXTURE_CSV = (
    BACKTEST_ROOT / "fixtures" / "historical-builder" / "raw-input" / "fixture-dk-salaries.csv"
)
LIMITED_REAL_DIR = (
    BACKTEST_ROOT
    / "data"
    / "real-validation"
    / "dk-mlb-2023-03-10-historical-daily-pool"
)


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class HistoricalRiskResolutionTests(unittest.TestCase):
    def test_offline_cache_miss_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as cache_dir:
            cache = ImmutableHttpCache(Path(cache_dir))
            with self.assertRaisesRegex(HttpCacheError, "offline cache miss"):
                cache.fetch_json(
                    "https://statsapi.mlb.com/api/v1.1/game/999999/feed/live",
                    offline=True,
                )

    def test_http_cache_retries_then_replays_identical_bytes_offline(self) -> None:
        calls: list[int] = []
        body = b'{"ok":true}\n'

        def transport(url: str, timeout: float):  # type: ignore[no-untyped-def]
            calls.append(1)
            if len(calls) < 3:
                raise OSError("temporary DNS failure")
            return body, {"Content-Type": "application/json"}

        with tempfile.TemporaryDirectory() as cache_dir:
            cache = ImmutableHttpCache(
                Path(cache_dir),
                transport=transport,
                clock=lambda: datetime(2026, 7, 30, 0, 0, tzinfo=UTC),
                sleep=lambda _: None,
            )
            online = cache.fetch_json("https://example.invalid/test.json", retries=3)
            offline = cache.fetch_json("https://example.invalid/test.json", offline=True)
            self.assertEqual(len(calls), 3)
            self.assertFalse(online.from_cache)
            self.assertTrue(offline.from_cache)
            self.assertEqual(online.body, offline.body)
            self.assertEqual(online.sha256, offline.sha256)

    def test_statsapi_offline_fixture_builds_full_pool_and_marks_dnp_zero(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            result = StatsApiFullPoolActualsBuilder(
                feature_path=STATS_FEATURES,
                output_dir=Path(output_dir),
                cache=ImmutableHttpCache(STATS_CACHE),
                offline=True,
            ).build()
            self.assertEqual(result["status"], "PASS_FULL_POOL")
            self.assertEqual(result["coverage"]["feature_player_count"], 21)
            self.assertEqual(result["coverage"]["records_count"], 21)
            self.assertEqual(result["coverage"]["played_count"], 20)
            self.assertEqual(result["coverage"]["dnp_count"], 1)
            payload = json.loads(
                (Path(output_dir) / "fixture-statsapi-full-pool.actuals.json").read_text()
            )
            dnp = [item for item in payload["points"] if item["status"].startswith("dnp_")]
            self.assertEqual(len(dnp), 1)
            self.assertEqual(dnp[0]["actual_points"], 0.0)
            self.assertEqual(payload["coverage_scope"], "all_feature_players")
            self.assertEqual(len(payload["raw_stats_artifact_ids"]), 2)

    def test_statsapi_offline_generation_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for output in (Path(first), Path(second)):
                StatsApiFullPoolActualsBuilder(
                    feature_path=STATS_FEATURES,
                    output_dir=output,
                    cache=ImmutableHttpCache(STATS_CACHE),
                    offline=True,
                ).build()
            self.assertEqual(_tree_hash(Path(first)), _tree_hash(Path(second)))

    def test_capture_archives_nonuniform_current_slate_before_lock(self) -> None:
        kwargs = dict(
            salary_csv=DK_FIXTURE_CSV,
            source_url="https://www.draftkings.com/draft/contest/fixture",
            clock=lambda: datetime(2026, 7, 1, 21, 0, tzinfo=UTC),
            draft_group_id="fixture-draftgroup-100",
        )
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_result = capture_current_dk_slate(output_dir=Path(first), **kwargs)
            second_result = capture_current_dk_slate(output_dir=Path(second), **kwargs)
            self.assertTrue(first_result["salary_non_uniform"])
            self.assertFalse(first_result["provider_game_set_verified"])
            self.assertIn("provider_game_set_unverified", first_result["warnings"])
            self.assertEqual(first_result["manifest_sha256"], second_result["manifest_sha256"])
            self.assertEqual(_tree_hash(Path(first)), _tree_hash(Path(second)))
            manifest = json.loads((Path(first) / "capture-manifest.json").read_text())
            self.assertFalse(manifest["historical_backfill_supported"])
            self.assertEqual(manifest["capture_mode"], "current_or_future_only")
            replay = capture_current_dk_slate(
                output_dir=Path(first),
                salary_csv=DK_FIXTURE_CSV,
                source_url="https://www.draftkings.com/draft/contest/fixture",
                clock=lambda: datetime(2026, 7, 3, 21, 0, tzinfo=UTC),
            )
            self.assertTrue(replay["replayed_existing_immutable_capture"])
            self.assertEqual(replay["manifest_sha256"], first_result["manifest_sha256"])

    def test_capture_refuses_post_lock_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with self.assertRaisesRegex(SlateCaptureError, "cannot be inferred or backfilled"):
                capture_current_dk_slate(
                    salary_csv=DK_FIXTURE_CSV,
                    output_dir=Path(output_dir),
                    source_url="https://www.draftkings.com/draft/contest/fixture",
                    clock=lambda: datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
                )

    def test_capture_refuses_exact_first_lock_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with self.assertRaisesRegex(SlateCaptureError, "after first pitch"):
                capture_current_dk_slate(
                    salary_csv=DK_FIXTURE_CSV,
                    output_dir=Path(output_dir),
                    source_url="https://www.draftkings.com/draft/contest/fixture",
                    clock=lambda: datetime(2026, 7, 2, 0, 5, tzinfo=UTC),
                )

    def test_statsapi_rejects_boxscore_identity_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as cache_dir, tempfile.TemporaryDirectory() as output_dir:
            cache_path = Path(cache_dir)
            for source in STATS_CACHE.iterdir():
                (cache_path / source.name).write_bytes(source.read_bytes())
            body_path = next(cache_path.glob("*.body"))
            payload = json.loads(body_path.read_text())
            side_players = payload["liveData"]["boxscore"]["teams"]["away"]["players"]
            raw_key = next(iter(side_players))
            side_players[raw_key]["person"]["id"] += 1
            mutated = (json.dumps(payload, sort_keys=True) + "\n").encode()
            body_path.write_bytes(mutated)
            meta_path = body_path.with_name(body_path.name.replace(".body", ".meta.json"))
            metadata = json.loads(meta_path.read_text())
            metadata["byte_count"] = len(mutated)
            metadata["sha256"] = hashlib.sha256(mutated).hexdigest()
            meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
            with self.assertRaisesRegex(ValueError, "identity ambiguity"):
                StatsApiFullPoolActualsBuilder(
                    feature_path=STATS_FEATURES,
                    output_dir=Path(output_dir),
                    cache=ImmutableHttpCache(cache_path),
                    offline=True,
                ).build()

    def test_projection_uses_only_games_completed_before_first_pitch(self) -> None:
        cutoff = datetime(2026, 7, 1, 23, 5, tzinfo=UTC)
        history = [
            HistoricalFantasyGame(
                1,
                10,
                cutoff.date(),
                "hitter",
                10.0,
                completed_at=datetime(2026, 7, 1, 20, 0, tzinfo=UTC),
            ),
            HistoricalFantasyGame(
                1,
                11,
                cutoff.date(),
                "hitter",
                1000.0,
                completed_at=cutoff,
            ),
            HistoricalFantasyGame(
                1,
                12,
                cutoff.date(),
                "hitter",
                1000.0,
                completed_at=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
            ),
        ]
        projection, audit = project_player(
            history, mlbam_id=1, role="hitter", cutoff=cutoff, prior_weight=0
        )
        self.assertEqual(projection, 10.0)
        self.assertEqual(audit["history_game_ids_used"], [10])
        self.assertEqual(audit["cutoff_or_future_rows_ignored"], 2)
        self.assertEqual(audit["cutoff_timestamp_exclusive"], cutoff.isoformat())

    def test_real_feature_contract_rejects_avg_points_projection_semantics(self) -> None:
        payload = json.loads(
            next(LIMITED_REAL_DIR.glob("*.features.json")).read_text()
        )
        payload["players"][0]["projection_source"] = "draftkings_export_avg_points_per_game"
        with self.assertRaisesRegex(ValidationError, "AvgPointsPerGame"):
            SlateFeatureSnapshot.model_validate(payload)

    def test_runner_rejects_missing_full_pool_actual_record(self) -> None:
        with tempfile.TemporaryDirectory() as input_dir, tempfile.TemporaryDirectory() as output_dir:
            root = Path(input_dir)
            for source in SMOKE_DIR.glob("*.json"):
                (root / source.name).write_bytes(source.read_bytes())
            actual_path = next(root.glob("*.actuals.json"))
            payload = json.loads(actual_path.read_text())
            payload["points"].pop()
            actual_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
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
            self.assertEqual(summary["valid_slates_total"], 0)
            self.assertIn("Full-pool actual coverage", summary["failures"][0]["reason"])
            self.assertIn("missing=", summary["failures"][0]["reason"])

    def test_runner_rejects_extra_full_pool_actual_record(self) -> None:
        with tempfile.TemporaryDirectory() as input_dir, tempfile.TemporaryDirectory() as output_dir:
            root = Path(input_dir)
            for source in SMOKE_DIR.glob("*.json"):
                (root / source.name).write_bytes(source.read_bytes())
            actual_path = next(root.glob("*.actuals.json"))
            payload = json.loads(actual_path.read_text())
            extra = dict(payload["points"][0])
            extra["mlbam_id"] = 999999999
            payload["points"].append(extra)
            actual_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
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
            self.assertEqual(summary["valid_slates_total"], 0)
            self.assertIn("Full-pool actual coverage", summary["failures"][0]["reason"])
            self.assertIn("extra=", summary["failures"][0]["reason"])

    def test_selected_only_actuals_require_double_explicit_confirmation(self) -> None:
        payload = json.loads(next(LIMITED_REAL_DIR.glob("*.actuals.json")).read_text())
        payload["limited_mode_acknowledgement"] = None
        with self.assertRaises(ValidationError):
            SlateActualPoints.model_validate(payload)

        with tempfile.TemporaryDirectory() as output_dir:
            summary = run_backtest(
                BacktestConfig(
                    seed=20260729,
                    site="dk",
                    slate_dir=LIMITED_REAL_DIR,
                    lineups_per_method=1,
                    output_dir=Path(output_dir),
                    min_real_slates=1,
                    bootstrap_samples=20,
                )
            )
            self.assertEqual(summary["valid_slates_total"], 0)
            self.assertIn("disabled by default", summary["failures"][0]["reason"])

    def test_selected_only_actuals_are_seed_bound_and_fail_changed_seed(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            summary = run_backtest(
                BacktestConfig(
                    seed=20260730,
                    site="dk",
                    slate_dir=LIMITED_REAL_DIR,
                    lineups_per_method=1,
                    output_dir=Path(output_dir),
                    min_real_slates=1,
                    bootstrap_samples=20,
                    allow_limited_selected_actuals=True,
                    selected_actuals_ack=SELECTED_ACTUALS_ACK,
                )
            )
            self.assertEqual(summary["valid_slates_total"], 0)
            self.assertIn("seed-bound", summary["failures"][0]["reason"])

    def test_selected_only_matching_seed_still_fails_when_projection_changes_selection(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            summary = run_backtest(
                BacktestConfig(
                    seed=20260729,
                    site="dk",
                    slate_dir=LIMITED_REAL_DIR,
                    lineups_per_method=1,
                    output_dir=Path(output_dir),
                    min_real_slates=1,
                    bootstrap_samples=20,
                    allow_limited_selected_actuals=True,
                    selected_actuals_ack=SELECTED_ACTUALS_ACK,
                )
            )
            self.assertEqual(summary["valid_real_slates"], 0)
            self.assertEqual(summary["evaluation_status"], "INSUFFICIENT DATA / NOT EVALUATED")
            self.assertIn("feature-bound", summary["failures"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
