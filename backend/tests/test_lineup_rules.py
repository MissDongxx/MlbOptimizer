from __future__ import annotations

from collections import Counter
import unittest

from models.schemas import OptimizeRequest, OptimizerSettings, PlayerInput
from services.lineup_rules import assign_slots, max_exposure_count, validate_lineup, validate_lineup_set
from services.mock_data import mock_players
from services.optimizer import generate_lineups


def _inputs(site: str) -> list[PlayerInput]:
    salary = "salary_dk" if site == "dk" else "salary_fd"
    projection = "projected_dk" if site == "dk" else "projected_fd"
    return [
        PlayerInput(
            mlbam_id=player.mlbam_id,
            name=player.name,
            team=player.team,
            opponent=player.opponent,
            position=player.position,
            salary=getattr(player, salary),
            projected_points=getattr(player, projection),
            lineup_status=player.lineup_status,
        )
        for player in mock_players()
    ]


class LineupRulesTests(unittest.TestCase):
    def test_multi_position_assignment_finds_valid_matching(self) -> None:
        players = [
            PlayerInput(mlbam_id=1, name="P1", team="A", opponent="B", position=["P"], salary=1, projected_points=1),
            PlayerInput(mlbam_id=2, name="P2", team="C", opponent="D", position=["P"], salary=1, projected_points=1),
            PlayerInput(mlbam_id=3, name="C", team="A", opponent="B", position=["C", "1B"], salary=1, projected_points=1),
            PlayerInput(mlbam_id=4, name="1B", team="C", opponent="D", position=["1B"], salary=1, projected_points=1),
            PlayerInput(mlbam_id=5, name="2B", team="A", opponent="B", position=["2B", "SS"], salary=1, projected_points=1),
            PlayerInput(mlbam_id=6, name="3B", team="C", opponent="D", position=["3B"], salary=1, projected_points=1),
            PlayerInput(mlbam_id=7, name="SS", team="A", opponent="B", position=["SS"], salary=1, projected_points=1),
            PlayerInput(mlbam_id=8, name="OF1", team="C", opponent="D", position=["OF"], salary=1, projected_points=1),
            PlayerInput(mlbam_id=9, name="OF2", team="E", opponent="F", position=["OF"], salary=1, projected_points=1),
            PlayerInput(mlbam_id=10, name="OF3", team="G", opponent="H", position=["OF"], salary=1, projected_points=1),
        ]
        assignment = assign_slots("dk", players)
        self.assertIsNotNone(assignment)
        self.assertEqual(len(assignment or ()), 10)

    def test_strict_exposure_uses_floor_ceiling(self) -> None:
        self.assertEqual(max_exposure_count(0.5, 5), 2)
        self.assertEqual(max_exposure_count(0.2, 5), 1)
        self.assertEqual(max_exposure_count(0.19, 5), 0)
        self.assertEqual(max_exposure_count(1.0, 5), 5)


    def test_set_validator_rejects_duplicate_request_ids(self) -> None:
        players = _inputs("dk")
        request = OptimizeRequest(
            site="dk",
            num_lineups=1,
            settings=OptimizerSettings(min_salary_used=0, pitcher_vs_batter_same_team="allow"),
            players=players,
        )
        lineup = generate_lineups(request, method="optimized", seed=10, prefer_pydfs=False).lineups[0]
        duplicate_request = request.model_copy(deep=True)
        duplicate_request.players.append(duplicate_request.players[0].model_copy(deep=True))
        with self.assertRaises(ValueError) as raised:
            validate_lineup_set(duplicate_request, [lineup])
        issues = getattr(raised.exception, "issues", ())
        self.assertIn("duplicate_player_id", {issue.code for issue in issues})

    def test_validator_requires_pitcher_opponent_for_avoid(self) -> None:
        request = OptimizeRequest(
            site="dk",
            num_lineups=1,
            settings=OptimizerSettings(min_salary_used=0, pitcher_vs_batter_same_team="allow"),
            players=_inputs("dk"),
        )
        lineup = generate_lineups(request, method="optimized", seed=11, prefer_pydfs=False).lineups[0]
        strict_request = request.model_copy(deep=True)
        strict_request.settings.pitcher_vs_batter_same_team = "avoid"
        selected_pitcher_ids = {
            player.mlbam_id for player in lineup.players if player.position_slot == "P"
        }
        for player in strict_request.players:
            if player.mlbam_id in selected_pitcher_ids:
                player.opponent = None
        result = validate_lineup(strict_request, lineup)
        self.assertIn("pitcher_opponent_missing", {issue.code for issue in result.issues})

    def test_validator_rejects_duplicate_player_in_lineup(self) -> None:
        request = OptimizeRequest(
            site="dk",
            num_lineups=1,
            settings=OptimizerSettings(min_salary_used=0, pitcher_vs_batter_same_team="allow"),
            players=_inputs("dk"),
        )
        response = generate_lineups(request, method="optimized", seed=1, prefer_pydfs=False)
        lineup = response.lineups[0].model_copy(deep=True)
        lineup.players[-1] = lineup.players[0].model_copy(deep=True)
        lineup.total_salary = sum(player.salary for player in lineup.players)
        result = validate_lineup(request, lineup)
        self.assertFalse(result.valid)
        self.assertIn("duplicate_player", {issue.code for issue in result.issues})

    def test_validator_rejects_exposure_overrun(self) -> None:
        request = OptimizeRequest(
            site="dk",
            num_lineups=2,
            settings=OptimizerSettings(min_salary_used=0, pitcher_vs_batter_same_team="allow"),
            players=_inputs("dk"),
        )
        request.players[0].max_exposure = 0.5
        response = generate_lineups(request, method="optimized", seed=2, prefer_pydfs=False)
        player_id = request.players[0].mlbam_id
        # Make the first lineup appear twice, forcing any included player to 100% exposure.
        duplicate_set = [response.lineups[0], response.lineups[0].model_copy(deep=True)]
        with self.assertRaises(ValueError):
            validate_lineup_set(request, duplicate_set)
        counts = Counter(player.mlbam_id for lineup in duplicate_set for player in lineup.players)
        if counts[player_id] == 2:
            result = validate_lineup(request, duplicate_set[0], exposure_counts=counts)
            self.assertIn("max_exposure", {issue.code for issue in result.issues})

    def test_validator_rejects_incorrect_serialized_slot(self) -> None:
        request = OptimizeRequest(
            site="dk",
            num_lineups=1,
            settings=OptimizerSettings(min_salary_used=0, pitcher_vs_batter_same_team="allow"),
            players=_inputs("dk"),
        )
        lineup = generate_lineups(request, method="optimized", seed=8, prefer_pydfs=False).lineups[0]
        lineup = lineup.model_copy(deep=True)
        lineup.players[0].position_slot = "OF"
        result = validate_lineup(request, lineup)
        codes = {issue.code for issue in result.issues}
        self.assertTrue({"position_slot_set", "position_slot_eligibility"}.intersection(codes))

    def test_validator_rejects_serialized_metadata_tampering(self) -> None:
        request = OptimizeRequest(
            site="dk",
            num_lineups=1,
            settings=OptimizerSettings(min_salary_used=0, pitcher_vs_batter_same_team="allow"),
            players=_inputs("dk"),
        )
        lineup = generate_lineups(request, method="optimized", seed=9, prefer_pydfs=False).lineups[0]
        lineup = lineup.model_copy(deep=True)
        lineup.players[0].salary += 1
        lineup.total_salary += 1
        result = validate_lineup(request, lineup)
        self.assertIn("player_metadata_mismatch", {issue.code for issue in result.issues})


if __name__ == "__main__":
    unittest.main()
