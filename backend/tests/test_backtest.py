from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from backtest.contracts import SlateActualPoints, SlateFeatureSnapshot
from backtest.runner import BacktestConfig, _summarize, run_backtest
from models.schemas import OptimizeResponse


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "backtest" / "fixtures" / "smoke"


def _tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class BacktestTests(unittest.TestCase):
    def test_feature_contract_rejects_future_snapshot(self) -> None:
        path = next(FIXTURE_DIR.glob("*.features.json"))
        payload = json.loads(path.read_text())
        payload["snapshot_as_of"] = "2026-07-01T23:06:00Z"
        with self.assertRaises(ValidationError):
            SlateFeatureSnapshot.model_validate(payload)

    def test_feature_contract_rejects_postgame_field_anywhere(self) -> None:
        path = next(FIXTURE_DIR.glob("*.features.json"))
        payload = json.loads(path.read_text())
        payload["players"][0]["feature_values"]["actual_points"] = 99
        with self.assertRaises(ValidationError):
            SlateFeatureSnapshot.model_validate(payload)

    def test_smoke_backtest_is_byte_reproducible_and_not_evaluated(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = Path(first_dir)
            second = Path(second_dir)
            base = dict(
                seed=20260729,
                site="dk",
                slate_dir=FIXTURE_DIR,
                lineups_per_method=2,
                noninferiority_margin=0.02,
                min_real_slates=30,
                bootstrap_samples=100,
            )
            first_summary = run_backtest(BacktestConfig(output_dir=first, **base))
            second_summary = run_backtest(BacktestConfig(output_dir=second, **base))
            self.assertEqual(first_summary, second_summary)
            self.assertEqual(_tree_hash(first), _tree_hash(second))
            self.assertEqual(first_summary["evaluation_status"], "INSUFFICIENT DATA / NOT EVALUATED")
            self.assertEqual(first_summary["valid_real_slates"], 0)
            self.assertEqual(first_summary["valid_fixture_or_synthetic_slates"], 1)

    def test_real_slate_gate_allows_explicit_single_slate_validation(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            summary = run_backtest(
                BacktestConfig(
                    seed=1,
                    site="dk",
                    slate_dir=FIXTURE_DIR,
                    lineups_per_method=1,
                    output_dir=Path(output_dir),
                    min_real_slates=1,
                )
            )
            self.assertEqual(summary["minimum_real_slates"], 1)
        with tempfile.TemporaryDirectory() as output_dir:
            with self.assertRaisesRegex(ValueError, "at least 1"):
                run_backtest(
                    BacktestConfig(
                        seed=1, site="dk", slate_dir=FIXTURE_DIR, lineups_per_method=1,
                        output_dir=Path(output_dir), min_real_slates=0
                    )
                )

    def test_summary_math_uses_real_slates_only(self) -> None:
        slates = [
            {
                "slate_id": "real-1",
                "site": "dk",
                "data_kind": "real",
                "lineups_per_method": 1,
                "random_mean_actual": 100.0,
                "legacy_mean_actual": 111.0,
                "optimized_mean_actual": 112.0,
                "optimized_vs_random_relative": 0.12,
                "optimized_vs_legacy_relative": 1 / 111,
                "optimized_beats_random": True,
            },
            {
                "slate_id": "fixture-ignored",
                "site": "dk",
                "data_kind": "fixture",
                "lineups_per_method": 1,
                "random_mean_actual": 1.0,
                "legacy_mean_actual": 1.0,
                "optimized_mean_actual": 1000.0,
                "optimized_vs_random_relative": 999.0,
                "optimized_vs_legacy_relative": 999.0,
                "optimized_beats_random": True,
            },
        ]
        config = BacktestConfig(
            seed=1,
            site="dk",
            slate_dir=FIXTURE_DIR,
            lineups_per_method=1,
            output_dir=Path("unused"),
            min_real_slates=1,
            bootstrap_samples=20,
        )
        summary = _summarize(config, slates, [])
        self.assertEqual(summary["valid_real_slates"], 1)
        self.assertEqual(summary["means_real_slates_only"]["optimized_actual"], 112.0)
        self.assertEqual(summary["gates"]["optimized_vs_random_mean"]["status"], "PASS")
        self.assertEqual(summary["gates"]["optimized_vs_random_slate_win_rate"]["status"], "PASS")
        self.assertEqual(summary["gates"]["optimized_vs_legacy_noninferiority"]["status"], "PASS")

    def test_feature_contract_rejects_semantic_postgame_key_variants(self) -> None:
        path = next(FIXTURE_DIR.glob("*.features.json"))
        payload = json.loads(path.read_text())
        payload["players"][0]["feature_values"]["final-fantasy-result"] = 99
        with self.assertRaises(ValidationError):
            SlateFeatureSnapshot.model_validate(payload)

    def test_feature_contract_rejects_availability_status_conflict(self) -> None:
        path = next(FIXTURE_DIR.glob("*.features.json"))
        payload = json.loads(path.read_text())
        payload["players"][0]["availability"] = "dnp"
        with self.assertRaises(ValidationError):
            SlateFeatureSnapshot.model_validate(payload)

    def test_actuals_contract_rejects_naive_or_nonfinite_values(self) -> None:
        path = next(FIXTURE_DIR.glob("*.actuals.json"))
        payload = json.loads(path.read_text())
        payload["acquired_at"] = "2026-07-02T12:00:00"
        with self.assertRaises(ValidationError):
            SlateActualPoints.model_validate(payload)
        payload = json.loads(path.read_text())
        payload["points"][0]["actual_points"] = float("inf")
        with self.assertRaises(ValidationError):
            SlateActualPoints.model_validate(payload)

    def test_method_sample_count_mismatch_fails_the_slate(self) -> None:
        with tempfile.TemporaryDirectory() as input_dir, tempfile.TemporaryDirectory() as output_dir:
            input_path = Path(input_dir)
            for fixture in FIXTURE_DIR.glob("*.json"):
                shutil.copy2(fixture, input_path / fixture.name)
            config = BacktestConfig(
                seed=3,
                site="dk",
                slate_dir=input_path,
                lineups_per_method=2,
                output_dir=Path(output_dir),
                bootstrap_samples=20,
            )
            with patch(
                "backtest.runner.run_legacy_optimizer_sync",
                return_value=OptimizeResponse(lineups=[], solve_time_ms=0, warnings=[]),
            ):
                summary = run_backtest(config)
            self.assertEqual(summary["valid_slates_total"], 0)
            self.assertEqual(summary["failed_or_skipped_slates"], 1)
            failure = json.loads((Path(output_dir) / "failures.json").read_text())[0]
            self.assertIn("expected 2", failure["reason"])

    def test_actuals_before_slate_start_fail_the_slate(self) -> None:
        with tempfile.TemporaryDirectory() as input_dir, tempfile.TemporaryDirectory() as output_dir:
            input_path = Path(input_dir)
            for fixture in FIXTURE_DIR.glob("*.json"):
                shutil.copy2(fixture, input_path / fixture.name)
            actual_path = next(input_path.glob("*.actuals.json"))
            payload = json.loads(actual_path.read_text())
            payload["source_timestamp"] = "2026-07-01T22:00:00Z"
            payload["acquired_at"] = "2026-07-01T22:01:00Z"
            actual_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
            summary = run_backtest(
                BacktestConfig(
                    seed=3,
                    site="dk",
                    slate_dir=input_path,
                    lineups_per_method=1,
                    output_dir=Path(output_dir),
                    bootstrap_samples=20,
                )
            )
            self.assertEqual(summary["valid_slates_total"], 0)
            self.assertEqual(summary["failed_or_skipped_slates"], 1)


if __name__ == "__main__":
    unittest.main()
