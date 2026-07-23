from __future__ import annotations

import unittest
from unittest.mock import patch

from services.park_factors import hitter_park_multiplier
from datetime import date

from services.projections import (
    _pitcher_usage_summary,
    get_pitcher_projection,
    get_split_projection,
)


class ProjectionTests(unittest.TestCase):
    def test_pitcher_projection_uses_cached_season_rates_and_opponent_context(self) -> None:
        season_cache = {
            "last_updated": "2026-07-22T06:00:00+00:00",
            "pitchers": {
                "543037": {
                    "starts": 20,
                    "innings_per_start": 6.1,
                    "strikeouts_per_start": 7.4,
                    "earned_runs_per_start": 1.9,
                    "win_probability": 0.5,
                }
            },
        }
        with (
            patch("services.projections.load_season_splits", return_value=season_cache),
            patch(
                "services.projections.get_team_vegas_context",
                return_value={"implied_runs": 3.8},
            ),
            patch(
                "services.projections.get_pitcher_recent_usage",
                return_value={"workload_factor": 1.0, "workload_risk": "low"},
            ),
        ):
            result = get_pitcher_projection(543037, site="dk", opposing_team="BOS")

        self.assertEqual(result["projection_source"], "pitcher_season_rates")
        self.assertGreater(result["matchup_factor"], 1)
        self.assertEqual(result["pitcher_rates"]["starts"], 20)

    def test_pitcher_recent_short_rest_reduces_projection(self) -> None:
        starts = [
            {"date": "2026-07-21", "pitches": 91, "innings": 5.0},
            {"date": "2026-07-16", "pitches": 95, "innings": 6.0},
            {"date": "2026-07-10", "pitches": 98, "innings": 6.1},
        ]

        usage = _pitcher_usage_summary(543037, starts, date(2026, 7, 23))

        self.assertEqual(usage["days_rest"], 1)
        self.assertEqual(usage["workload_risk"], "high")
        self.assertEqual(usage["workload_factor"], 0.82)
        self.assertEqual(usage["avg_pitches_last_3"], 94.7)

    def test_low_recent_pitch_counts_flag_possible_limit_without_claiming_one(self) -> None:
        starts = [
            {"date": "2026-07-17", "pitches": 52, "innings": 3.0},
            {"date": "2026-07-11", "pitches": 61, "innings": 3.2},
        ]

        usage = _pitcher_usage_summary(543037, starts, date(2026, 7, 23))

        self.assertEqual(usage["workload_risk"], "medium")
        self.assertEqual(usage["workload_factor"], 0.92)

    def test_projection_blends_recent_form_and_reports_factors(self) -> None:
        season_cache = {
            "last_updated": "2026-07-02T00:00:00+00:00",
            "players": {
                "660271": {
                    "season_rates": {
                        "hits_per_game": 1.0,
                        "hr_per_game": 0.25,
                        "rbi_per_game": 0.7,
                        "runs_per_game": 0.8,
                        "walks_per_game": 0.45,
                        "sb_per_game": 0.1,
                    },
                    "advanced_metrics": {
                        "woba": 0.41,
                        "iso": 0.28,
                        "k_rate": 0.18,
                        "bb_rate": 0.13,
                    },
                    "splits": {"vs_R": {"projection_factor": 1.05}},
                }
            },
        }
        last_15 = {
            "games": 10,
            "hits": 15,
            "doubles": 3,
            "triples": 0,
            "home_runs": 5,
            "rbi": 12,
            "runs": 11,
            "walks": 8,
            "hit_by_pitch": 0,
            "stolen_bases": 2,
        }

        with (
            patch("services.projections.load_season_splits", return_value=season_cache),
            patch("services.projections.get_last_15_day_counts", return_value=last_15),
            patch(
                "services.projections.get_team_vegas_context",
                return_value={"implied_runs": 5.8, "multiplier": 1.11, "source": "the_odds_api"},
            ),
            patch("services.projections.vegas_team_multiplier", return_value=1.11),
            patch(
                "services.projections.get_weather_context",
                return_value={"multiplier": 1.02, "risk": "low", "source": "api.weather.gov"},
            ),
            patch("services.projections.weather_multiplier", return_value=1.02),
        ):
            projection = get_split_projection(660271, "R", 1, site="dk", venue="Coors Field", team="LAD")

        self.assertEqual(projection["projection_source"], "season_with_15d_form_blend")
        self.assertGreater(projection["projected_points"], projection["season_projection"])
        self.assertGreater(projection["recent_form_factor"], 1.0)
        self.assertGreater(projection["skill_factor"], 1.0)
        self.assertEqual(projection["park_factor"]["source"], "static_park_factors")
        self.assertEqual(projection["vegas_context"]["source"], "the_odds_api")
        self.assertGreater(projection["vegas_multiplier"], 1.0)
        self.assertEqual(projection["weather_context"]["source"], "api.weather.gov")
        self.assertGreater(projection["weather_multiplier"], 1.0)
        self.assertLessEqual(projection["final_adjustment"], 1.3)

    def test_projection_uses_season_fallback_with_neutral_park_when_recent_sample_is_small(self) -> None:
        with (
            patch("services.projections.load_season_splits", return_value={"players": {}}),
            patch("services.projections.get_last_15_day_counts", return_value={"games": 2}),
            patch(
                "services.projections.get_team_vegas_context",
                return_value={"implied_runs": None, "multiplier": 1.0, "source": "neutral_default"},
            ),
            patch("services.projections.vegas_team_multiplier", return_value=1.0),
            patch(
                "services.projections.get_weather_context",
                return_value={"multiplier": 1.0, "risk": "neutral", "source": "neutral_default"},
            ),
            patch("services.projections.weather_multiplier", return_value=1.0),
        ):
            projection = get_split_projection(123, "", None, site="fd")

        self.assertEqual(projection["projection_source"], "season_avg_fallback")
        self.assertEqual(projection["recent_form_factor"], 1.0)
        self.assertEqual(projection["park_multiplier"], 1.0)
        self.assertEqual(projection["vegas_multiplier"], 1.0)
        self.assertEqual(projection["weather_multiplier"], 1.0)
        self.assertGreater(projection["projected_points"], 0)

    def test_hitter_park_multiplier_is_conservative(self) -> None:
        self.assertEqual(hitter_park_multiplier(None), 1.0)
        self.assertLess(hitter_park_multiplier("Oracle Park"), 1.0)
        self.assertGreater(hitter_park_multiplier("Yankee Stadium"), 1.0)
        self.assertLessEqual(hitter_park_multiplier("Coors Field"), 1.08)


if __name__ == "__main__":
    unittest.main()
