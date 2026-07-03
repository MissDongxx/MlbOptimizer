from __future__ import annotations

import unittest

from models.schemas import OptimizeRequest, OptimizerSettings, PlayerInput
from services.mock_data import mock_players
from services.optimizer import OptimizerError, run_optimizer_sync


def _mock_inputs(site: str = "dk") -> list[PlayerInput]:
    salary_attr = "salary_dk" if site == "dk" else "salary_fd"
    projection_attr = "projected_dk" if site == "dk" else "projected_fd"
    return [
        PlayerInput(
            mlbam_id=player.mlbam_id,
            name=player.name,
            team=player.team,
            opponent=player.opponent,
            position=player.position,
            salary=getattr(player, salary_attr),
            projected_points=getattr(player, projection_attr),
            lineup_status=player.lineup_status,
        )
        for player in mock_players()
    ]


class OptimizerTests(unittest.TestCase):
    def test_dk_uses_pydfs_and_generates_five_lineups_under_constraints(self) -> None:
        players = _mock_inputs("dk")
        players[0].lock = True
        request = OptimizeRequest(
            site="dk",
            num_lineups=5,
            settings=OptimizerSettings(
                stack_team="LAD",
                stack_count=4,
                min_salary_used=45000,
                pitcher_vs_batter_same_team="allow",
            ),
            players=players,
        )

        response = run_optimizer_sync(request)

        self.assertEqual(len(response.lineups), 5)
        self.assertEqual(response.warnings, [])
        self.assertLess(response.solve_time_ms, 5000)
        for lineup in response.lineups:
            self.assertEqual(len(lineup.players), 10)
            self.assertGreaterEqual(lineup.total_salary, 45000)
            self.assertLessEqual(lineup.total_salary, 50000)
            self.assertIn(660271, {player.mlbam_id for player in lineup.players})
            self.assertGreaterEqual(
                sum(1 for player in lineup.players if player.team == "LAD" and player.position_slot != "P"),
                4,
            )

    def test_default_mock_request_relaxes_pitcher_vs_batter_when_pool_is_too_small(self) -> None:
        request = OptimizeRequest(
            site="dk",
            num_lineups=5,
            settings=OptimizerSettings(
                pitcher_vs_batter_same_team="avoid",
                min_salary_used=49500,
            ),
            players=_mock_inputs("dk"),
        )

        response = run_optimizer_sync(request)

        self.assertEqual(len(response.lineups), 5)
        self.assertTrue(
            any("Pitcher-vs-batter restriction was relaxed" in warning for warning in response.warnings)
        )

    def test_infeasible_locks_raise_optimizer_error(self) -> None:
        players = _mock_inputs("dk")
        for player in players:
            if player.position == ["P"]:
                player.lock = True
        request = OptimizeRequest(
            site="dk",
            num_lineups=1,
            settings=OptimizerSettings(min_salary_used=0),
            players=players,
        )

        with self.assertRaises(OptimizerError):
            run_optimizer_sync(request)


if __name__ == "__main__":
    unittest.main()
