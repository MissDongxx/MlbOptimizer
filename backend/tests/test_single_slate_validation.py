from __future__ import annotations

import json
import unittest
from pathlib import Path

from backtest.contracts import SlateActualPoints, SlateFeatureSnapshot
from backtest.provenance import ProvenanceIndex


DATA_DIR = (
    Path(__file__).resolve().parents[1]
    / "backtest"
    / "data"
    / "real-validation"
    / "dk-mlb-2023-03-10-historical-daily-pool"
)


class SingleSlateLimitedValidationTests(unittest.TestCase):
    def test_checked_in_daily_pool_contract_and_provenance(self) -> None:
        features = SlateFeatureSnapshot.model_validate_json(
            (DATA_DIR / "dk-mlb-2023-03-10-historical-daily-pool.features.json").read_text()
        )
        actuals = SlateActualPoints.model_validate_json(
            (DATA_DIR / "dk-mlb-2023-03-10-historical-daily-pool.actuals.json").read_text()
        )
        qa = json.loads((DATA_DIR / "qa/dk_mlb_2023-03-10_daily_pool.qa.json").read_text())
        provenance = ProvenanceIndex.load(DATA_DIR, DATA_DIR / "provenance-manifest.json")
        self.assertEqual(features.data_kind, "real")
        self.assertEqual(features.scope, "historical_daily_pool")
        self.assertFalse(features.provider_game_set_verified)
        self.assertEqual(features.validation_scope, "LIMITED_SINGLE_SLATE_VALIDATION")
        self.assertEqual(len(features.players), 345)
        self.assertEqual(actuals.coverage_scope, "selected_lineup_players")
        self.assertEqual(len(actuals.points), 18)
        self.assertEqual(qa["status"], "PASS_WITH_WARNINGS")
        self.assertEqual(len(provenance.manifest.slates), 1)


if __name__ == "__main__":
    unittest.main()
