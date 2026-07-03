from __future__ import annotations

import unittest

from services.vegas import _build_vegas_cache, implied_runs_multiplier


class VegasTests(unittest.TestCase):
    def test_build_vegas_cache_derives_implied_runs_from_total_and_spread(self) -> None:
        events = [
            {
                "id": "game-1",
                "commence_time": "2026-07-02T23:05:00Z",
                "home_team": "Los Angeles Dodgers",
                "away_team": "Miami Marlins",
                "bookmakers": [
                    {
                        "key": "fanduel",
                        "markets": [
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": -110, "point": 9.0},
                                    {"name": "Under", "price": -110, "point": 9.0},
                                ],
                            },
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "Los Angeles Dodgers", "price": -110, "point": -1.5},
                                    {"name": "Miami Marlins", "price": -110, "point": 1.5},
                                ],
                            },
                        ],
                    }
                ],
            }
        ]

        cache = _build_vegas_cache(events, "2026-07-02")

        self.assertEqual(cache["teams"]["LAD"]["implied_runs"], 5.25)
        self.assertEqual(cache["teams"]["MIA"]["implied_runs"], 3.75)
        self.assertGreater(cache["teams"]["LAD"]["multiplier"], 1.0)
        self.assertLess(cache["teams"]["MIA"]["multiplier"], 1.0)

    def test_implied_runs_multiplier_is_clamped(self) -> None:
        self.assertEqual(implied_runs_multiplier(4.4), 1.0)
        self.assertLessEqual(implied_runs_multiplier(7.5), 1.12)
        self.assertGreaterEqual(implied_runs_multiplier(2.0), 0.88)


if __name__ == "__main__":
    unittest.main()
