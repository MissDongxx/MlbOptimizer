from __future__ import annotations

import unittest

from models.schemas import OptimizeRequest, OptimizerSettings, PlayerInput
from services.mock_data import mock_players
from services.optimizer import DK_SLOTS, FD_SLOTS, OptimizerError, generate_lineups, run_optimizer_sync


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
    def test_fallback_slots_match_current_classic_rosters(self) -> None:
        self.assertEqual(DK_SLOTS, ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"])
        self.assertEqual(FD_SLOTS, ["P", "C/1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"])

    def test_dk_generates_exact_count_under_constraints(self) -> None:
        players = _mock_inputs("dk")
        players[0].lock = True
        request = OptimizeRequest(
            site="dk",
            num_lineups=5,
            seed=7,
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
        self.assertEqual(response.method, "optimized")
        for lineup in response.lineups:
            self.assertEqual(len(lineup.players), 10)
            self.assertGreaterEqual(lineup.total_salary, 45000)
            self.assertLessEqual(lineup.total_salary, 50000)
            self.assertIn(660271, {player.mlbam_id for player in lineup.players})
            self.assertGreaterEqual(
                sum(1 for player in lineup.players if player.team == "LAD" and player.position_slot != "P"),
                4,
            )

    def test_large_dk_pool_with_high_minimum_salary_does_not_hit_search_limit(self) -> None:
        base = _mock_inputs("dk")
        players: list[PlayerInput] = []
        for copy_number in range(8):
            for player in base:
                clone = player.model_copy(deep=True)
                clone.mlbam_id = player.mlbam_id + (copy_number + 1) * 1_000_000
                clone.name = f"{player.name} {copy_number}"
                clone.projected_points += copy_number * 0.01
                players.append(clone)
        request = OptimizeRequest(
            site="dk",
            num_lineups=5,
            seed=42,
            settings=OptimizerSettings(
                min_salary_used=49500,
                pitcher_vs_batter_same_team="allow",
                unique_lineups=True,
            ),
            players=players,
        )

        response = run_optimizer_sync(request)

        self.assertEqual(len(response.lineups), 5)
        self.assertTrue(all(49500 <= lineup.total_salary <= 50000 for lineup in response.lineups))
        identities = {
            tuple(sorted(player.mlbam_id for player in lineup.players))
            for lineup in response.lineups
        }
        self.assertEqual(len(identities), 5)

    def test_dual_position_player_role_is_determined_by_assigned_slot(self) -> None:
        players = _mock_inputs("dk")
        players[0].position = ["P", "OF"]
        players[0].lock = True
        request = OptimizeRequest(
            site="dk",
            num_lineups=1,
            seed=5,
            settings=OptimizerSettings(
                stack_team="LAD",
                stack_count=5,
                min_salary_used=43000,
                pitcher_vs_batter_same_team="allow",
            ),
            players=players,
        )
        lineup = run_optimizer_sync(request).lineups[0]
        ohtani = next(player for player in lineup.players if player.mlbam_id == 660271)
        self.assertEqual(ohtani.position_slot, "OF")
        self.assertEqual(
            sum(player.team == "LAD" and player.position_slot != "P" for player in lineup.players),
            5,
        )

    def test_pitcher_vs_batter_is_never_relaxed(self) -> None:
        request = OptimizeRequest(
            site="dk",
            num_lineups=5,
            settings=OptimizerSettings(
                pitcher_vs_batter_same_team="avoid",
                min_salary_used=49500,
            ),
            players=_mock_inputs("dk"),
        )

        with self.assertRaises(OptimizerError) as raised:
            run_optimizer_sync(request)

        self.assertEqual(raised.exception.code, "pitcher_batter_infeasible")


    def test_missing_pitcher_opponent_is_strictly_infeasible_under_avoid(self) -> None:
        players = _mock_inputs("dk")
        for player in players:
            if any(position in {"P", "SP", "RP"} for position in player.position):
                player.opponent = None
        request = OptimizeRequest(
            site="dk",
            num_lineups=1,
            settings=OptimizerSettings(
                min_salary_used=43000,
                pitcher_vs_batter_same_team="avoid",
            ),
            players=players,
        )
        with self.assertRaises(OptimizerError) as raised:
            run_optimizer_sync(request)
        self.assertEqual(raised.exception.code, "pitcher_batter_infeasible")

    def test_site_team_limit_infeasibility_has_specific_reason(self) -> None:
        specifications = [
            (1, "P", "C"),
            (2, "C/1B", "A"),
            (3, "2B", "A"),
            (4, "3B", "A"),
            (5, "SS", "A"),
            (6, "OF", "A"),
            (7, "OF", "B"),
            (8, "OF", "B"),
            (9, "1B", "B"),
        ]
        players = [
            PlayerInput(
                mlbam_id=player_id,
                name=f"Player {player_id}",
                team=team,
                opponent="Z",
                position=[position],
                salary=3000,
                projected_points=10.0,
            )
            for player_id, position, team in specifications
        ]
        request = OptimizeRequest(
            site="fd",
            num_lineups=1,
            settings=OptimizerSettings(
                min_salary_used=0,
                pitcher_vs_batter_same_team="allow",
            ),
            players=players,
        )
        with self.assertRaises(OptimizerError) as raised:
            run_optimizer_sync(request)
        self.assertEqual(raised.exception.code, "team_limit_infeasible")

    def test_fd_generates_nine_player_rosters_with_hitter_team_limit(self) -> None:
        request = OptimizeRequest(
            site="fd",
            num_lineups=5,
            seed=11,
            settings=OptimizerSettings(
                pitcher_vs_batter_same_team="allow",
                min_salary_used=30000,
            ),
            players=_mock_inputs("fd"),
        )

        response = run_optimizer_sync(request)

        self.assertEqual(len(response.lineups), 5)
        for lineup in response.lineups:
            self.assertEqual(len(lineup.players), 9)
            hitters_by_team: dict[str, int] = {}
            total_by_team: dict[str, int] = {}
            for player in lineup.players:
                total_by_team[player.team] = total_by_team.get(player.team, 0) + 1
                if player.position_slot != "P":
                    hitters_by_team[player.team] = hitters_by_team.get(player.team, 0) + 1
            self.assertLessEqual(max(hitters_by_team.values()), 4)
            self.assertLessEqual(max(total_by_team.values()), 5)

    def test_infeasible_locks_raise_structured_optimizer_error(self) -> None:
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

        with self.assertRaises(OptimizerError) as raised:
            run_optimizer_sync(request)
        self.assertEqual(raised.exception.code, "lock_conflict")

    def test_duplicate_player_ids_are_rejected(self) -> None:
        players = _mock_inputs("dk")
        players.append(players[0].model_copy(deep=True))
        request = OptimizeRequest(
            site="dk",
            num_lineups=1,
            settings=OptimizerSettings(min_salary_used=0, pitcher_vs_batter_same_team="allow"),
            players=players,
        )
        with self.assertRaises(OptimizerError) as raised:
            run_optimizer_sync(request)
        self.assertEqual(raised.exception.code, "duplicate_player_id")

    def test_same_seed_is_byte_equivalent_at_model_dump_level(self) -> None:
        request = OptimizeRequest(
            site="dk",
            num_lineups=3,
            seed=12345,
            settings=OptimizerSettings(
                min_salary_used=43000,
                pitcher_vs_batter_same_team="allow",
            ),
            players=_mock_inputs("dk"),
        )
        first = run_optimizer_sync(request).model_dump(mode="json")
        second = run_optimizer_sync(request).model_dump(mode="json")
        # solve_time_ms is operational, not lineup output. The generated content must match exactly.
        first.pop("solve_time_ms")
        second.pop("solve_time_ms")
        self.assertEqual(first, second)

    def test_random_baseline_is_seeded_and_does_not_use_projection_order(self) -> None:
        request = OptimizeRequest(
            site="dk",
            num_lineups=2,
            settings=OptimizerSettings(
                min_salary_used=43000,
                pitcher_vs_batter_same_team="allow",
            ),
            players=_mock_inputs("dk"),
        )
        first = generate_lineups(request, method="random", seed=77, prefer_pydfs=False)
        reversed_projection_request = request.model_copy(deep=True)
        for player in reversed_projection_request.players:
            player.projected_points = 100 - player.projected_points
        second = generate_lineups(
            reversed_projection_request, method="random", seed=77, prefer_pydfs=False
        )
        self.assertEqual(
            [[player.mlbam_id for player in lineup.players] for lineup in first.lineups],
            [[player.mlbam_id for player in lineup.players] for lineup in second.lineups],
        )

    def test_excluded_players_never_appear(self) -> None:
        players = _mock_inputs("dk")
        excluded_id = players[0].mlbam_id
        players[0].exclude = True
        request = OptimizeRequest(
            site="dk",
            num_lineups=2,
            seed=4,
            settings=OptimizerSettings(
                min_salary_used=43000,
                pitcher_vs_batter_same_team="allow",
            ),
            players=players,
        )
        response = run_optimizer_sync(request)
        self.assertTrue(
            all(excluded_id not in {player.mlbam_id for player in lineup.players} for lineup in response.lineups)
        )

    def test_max_exposure_is_enforced_across_the_complete_set(self) -> None:
        players = _mock_inputs("dk")
        controlled = players[0]
        controlled.projected_points = 100.0
        controlled.max_exposure = 0.34  # floor(0.34 * 3) == 1
        request = OptimizeRequest(
            site="dk",
            num_lineups=3,
            seed=13,
            settings=OptimizerSettings(
                min_salary_used=43000,
                pitcher_vs_batter_same_team="allow",
            ),
            players=players,
        )
        response = run_optimizer_sync(request)
        appearances = sum(
            player.mlbam_id == controlled.mlbam_id
            for lineup in response.lineups
            for player in lineup.players
        )
        self.assertEqual(appearances, 1)

    def test_unique_lineups_are_distinct(self) -> None:
        request = OptimizeRequest(
            site="dk",
            num_lineups=4,
            seed=19,
            settings=OptimizerSettings(
                min_salary_used=43000,
                pitcher_vs_batter_same_team="allow",
                unique_lineups=True,
            ),
            players=_mock_inputs("dk"),
        )
        response = run_optimizer_sync(request)
        identities = [tuple(sorted(player.mlbam_id for player in lineup.players)) for lineup in response.lineups]
        self.assertEqual(len(identities), len(set(identities)))

    def test_salary_infeasibility_has_specific_reason(self) -> None:
        players = _mock_inputs("dk")
        for player in players:
            player.salary = 1000
        request = OptimizeRequest(
            site="dk",
            num_lineups=1,
            settings=OptimizerSettings(
                min_salary_used=49000,
                pitcher_vs_batter_same_team="allow",
            ),
            players=players,
        )
        with self.assertRaises(OptimizerError) as raised:
            run_optimizer_sync(request)
        self.assertEqual(raised.exception.code, "salary_infeasible")

    def test_stack_above_site_limit_is_rejected_before_solving(self) -> None:
        request = OptimizeRequest(
            site="fd",
            num_lineups=1,
            settings=OptimizerSettings(
                stack_team="LAD",
                stack_count=5,
                min_salary_used=0,
                pitcher_vs_batter_same_team="allow",
            ),
            players=_mock_inputs("fd"),
        )
        with self.assertRaises(OptimizerError) as raised:
            run_optimizer_sync(request)
        self.assertEqual(raised.exception.code, "stack_infeasible")
        self.assertEqual(raised.exception.details["site_maximum_hitters"], 4)

    def test_lock_and_exclude_conflict_is_rejected(self) -> None:
        players = _mock_inputs("dk")
        players[0].lock = True
        players[0].exclude = True
        request = OptimizeRequest(
            site="dk",
            num_lineups=1,
            settings=OptimizerSettings(min_salary_used=0, pitcher_vs_batter_same_team="allow"),
            players=players,
        )
        with self.assertRaises(OptimizerError) as raised:
            run_optimizer_sync(request)
        self.assertEqual(raised.exception.code, "lock_conflict")

    def test_request_never_returns_a_partial_lineup_set(self) -> None:
        base_players = _mock_inputs("dk")
        one = generate_lineups(
            OptimizeRequest(
                site="dk",
                num_lineups=1,
                settings=OptimizerSettings(min_salary_used=0, pitcher_vs_batter_same_team="allow"),
                players=base_players,
            ),
            method="optimized",
            seed=1,
            prefer_pydfs=False,
        ).lineups[0]
        selected_ids = {player.mlbam_id for player in one.players}
        exact_pool = [player for player in base_players if player.mlbam_id in selected_ids]
        request = OptimizeRequest(
            site="dk",
            num_lineups=2,
            settings=OptimizerSettings(
                min_salary_used=0,
                pitcher_vs_batter_same_team="allow",
                unique_lineups=True,
            ),
            players=exact_pool,
        )
        with self.assertRaises(OptimizerError) as raised:
            run_optimizer_sync(request)
        self.assertEqual(raised.exception.code, "exposure_or_uniqueness_infeasible")
        self.assertEqual(raised.exception.details["generated_before_failure"], 1)


if __name__ == "__main__":
    unittest.main()
