from __future__ import annotations

import unittest
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

from models.schemas import GameSummary, Player, PlayerPoolResponse, Starter
from services import lineup_data
from services.cache_store import LocalJsonCacheStore
from services.lineup_data import _players_from_boxscore_side


class LineupDataTests(unittest.TestCase):
    def tearDown(self) -> None:
        lineup_data._player_pool_cache = None
        lineup_data._player_pool_cached_at = 0.0

    @patch.dict("os.environ", {"USE_MOCK_DATA": "true"})
    def test_selected_slate_mock_mode_uses_cached_full_pool_without_network(self) -> None:
        now = datetime.now(UTC)
        slate = {
            "last_updated": now.isoformat(),
            "source": "daily_fantasy_fuel",
            "players": [
                {
                    "name": f"Slate Player {index}",
                    "team": "LAD" if index % 2 else "NYY",
                    "opponent": "NYY" if index % 2 else "LAD",
                    "positions": ["P"] if index < 4 else ["OF"],
                    "salary": 3000 + index * 100,
                    "projected_points": 5.0 + index,
                    "lineup_status": "expected",
                }
                for index in range(30)
            ],
        }
        with (
            patch.object(lineup_data, "load_salary_slate", return_value=slate),
            patch.object(lineup_data, "_get_live_player_pool") as live_pool,
        ):
            response = lineup_data.get_player_pool_for_slate("dk", "24F83")

        live_pool.assert_not_called()
        self.assertEqual(len(response.players), 30)
        self.assertEqual(response.data_status, "mock")
        self.assertIn("cached public slate player pool", response.warnings[0])

    @patch.dict("os.environ", {"USE_MOCK_DATA": "false"})
    def test_selected_slate_missing_cache_fails_fast_for_background_refresh(self) -> None:
        with (
            patch.object(lineup_data, "load_salary_slate", return_value={"players": []}),
            patch.object(lineup_data, "_get_live_player_pool") as live_pool,
        ):
            with self.assertRaises(lineup_data.SlateDataUnavailable):
                lineup_data.get_player_pool_for_slate("dk", "missing")

        live_pool.assert_not_called()

    def test_players_from_boxscore_side_marks_confirmed_starters(self) -> None:
        boxscore = {
            "away": {
                "battingOrder": [660271, 605141],
                "players": {
                    "ID660271": {
                        "person": {"id": 660271, "fullName": "Shohei Ohtani"},
                        "position": {"abbreviation": "DH"},
                        "allPositions": [{"abbreviation": "DH"}],
                    },
                    "ID605141": {
                        "person": {"id": 605141, "fullName": "Mookie Betts"},
                        "position": {"abbreviation": "RF"},
                        "allPositions": [{"abbreviation": "RF"}],
                    },
                },
            }
        }

        players = _players_from_boxscore_side(
            boxscore,
            side="away",
            team="LAD",
            opponent="NYY",
            opposing_pitcher=Starter(name="Gerrit Cole", mlbam_id=543037, hand="R"),
            lineup_confirmed=True,
            now=datetime(2026, 7, 1, tzinfo=UTC),
        )

        self.assertEqual([player.mlbam_id for player in players], [660271, 605141])
        self.assertEqual(players[0].batting_order, 1)
        self.assertEqual(players[0].lineup_status, "confirmed")
        self.assertEqual(players[0].position, ["UTIL"])
        self.assertEqual(players[1].position, ["OF"])

    @patch.dict(
        "os.environ",
        {"USE_MOCK_DATA": "false", "PERSIST_PLAYER_POOL_SNAPSHOTS": "false"},
    )
    def test_player_pool_reuses_recent_response(self) -> None:
        empty_pool = ([], [], [])
        with patch.object(lineup_data, "_get_live_player_pool", return_value=empty_pool) as live_pool:
            with patch.object(lineup_data, "get_todays_games", return_value=[]):
                first = lineup_data.get_todays_player_pool()
                second = lineup_data.get_todays_player_pool()

        self.assertIsInstance(first, PlayerPoolResponse)
        self.assertEqual(first, second)
        self.assertEqual(live_pool.call_count, 1)

    @patch.dict(
        "os.environ",
        {"USE_MOCK_DATA": "false", "PERSIST_PLAYER_POOL_SNAPSHOTS": "false"},
    )
    def test_force_refresh_bypasses_player_pool_cache(self) -> None:
        empty_pool = ([], [], [])
        with patch.object(lineup_data, "_get_live_player_pool", return_value=empty_pool) as live_pool:
            with patch.object(lineup_data, "get_todays_games", return_value=[]):
                lineup_data.get_todays_player_pool()
                lineup_data.get_todays_player_pool(force_refresh=True)

        self.assertEqual(live_pool.call_count, 2)

    def test_adds_dff_hitter_before_official_lineup(self) -> None:
        slate = {
            "players": [{
                "name": "Shohei Ohtani",
                "team": "LAD",
                "opponent": "NYY",
                "positions": ["OF"],
                "salary": 6500,
                "projected_points": 14.2,
                "last_10_avg": 13.8,
                "batting_order": 1,
                "lineup_status": "confirmed",
                "injury_status": "DTD",
            }]
        }
        games = [GameSummary(
            game_id=1,
            game_time="2026-07-23T23:00:00Z",
            away_team="LAD",
            home_team="NYY",
            home_starter=Starter(name="Gerrit Cole", mlbam_id=543037, hand="R"),
        )]
        with (
            patch.object(lineup_data, "load_salary_slate", return_value=slate),
            patch.object(lineup_data, "_season_player_ids", return_value={}),
            patch.object(lineup_data, "_has_authoritative_identity_directory", return_value=False),
        ):
            players: list[Player] = []
            added = lineup_data._add_salary_slate_candidates(
                players, games, datetime(2026, 7, 23, tzinfo=UTC)
            )

        self.assertEqual(added, 1)
        self.assertLess(players[0].mlbam_id, 0)
        self.assertEqual(players[0].lineup_status, "expected")
        self.assertEqual(players[0].opposing_pitcher, "Gerrit Cole")
        self.assertEqual(players[0].projected_dk, 14.2)

    def test_unresolved_identity_is_excluded_when_directory_is_authoritative(self) -> None:
        slate = {
            "players": [{
                "name": "Stale Player",
                "team": "SDP",
                "opponent": "LAD",
                "positions": ["3B"],
                "salary": 3000,
                "projected_points": 6.0,
                "lineup_status": "unconfirmed",
            }]
        }
        with (
            patch.object(lineup_data, "load_salary_slate", return_value=slate),
            patch.object(lineup_data, "_season_player_ids", return_value={}),
            patch.object(lineup_data, "_has_authoritative_identity_directory", return_value=True),
        ):
            players: list[Player] = []
            lineup_data._add_salary_slate_candidates(
                players, [], datetime(2026, 7, 23, tzinfo=UTC)
            )

        self.assertLess(players[0].mlbam_id, 0)
        self.assertEqual(players[0].lineup_status, "dnp")

    def test_strong_unavailable_status_excludes_unconfirmed_player(self) -> None:
        player = Player(
            mlbam_id=-1,
            name="Unavailable Player",
            team="LAD",
            opponent="NYY",
            position=["OF"],
            salary_dk=3000,
            salary_fd=2500,
            injury_status="10-Day IL",
            projected_dk=5,
            projected_fd=6,
            projection_source="daily_fantasy_fuel",
            last_updated=datetime(2026, 7, 23, tzinfo=UTC),
        )

        unavailable, conflicts = lineup_data._apply_injury_availability([player])

        self.assertEqual((unavailable, conflicts), (1, 0))
        self.assertEqual(player.lineup_status, "dnp")

    def test_new_official_lineup_marks_omitted_confirmed_player_dnp(self) -> None:
        old = Player(
            mlbam_id=1,
            name="Removed Player",
            team="LAD",
            opponent="NYY",
            position=["OF"],
            salary_dk=3000,
            salary_fd=2500,
            batting_order=3,
            lineup_status="confirmed",
            projected_dk=8,
            projected_fd=9,
            projection_source="season_avg_fallback",
            last_updated=datetime(2026, 7, 23, tzinfo=UTC),
        )
        previous = PlayerPoolResponse(
            game_date=date.today().isoformat(),
            last_updated=datetime(2026, 7, 23, tzinfo=UTC),
            games=[],
            players=[old],
        )
        games = [GameSummary(
            game_id=1,
            game_time="2026-07-23T23:00:00Z",
            away_team="LAD",
            home_team="NYY",
            away_lineup_confirmed=True,
        )]
        warnings: list[str] = []
        players: list[Player] = []

        changes = lineup_data._apply_snapshot_transitions(
            previous, games, players, datetime(2026, 7, 23, 1, tzinfo=UTC), warnings
        )

        self.assertEqual(players[0].lineup_status, "dnp")
        self.assertEqual(changes["status_changed"], 1)
        self.assertIn("previously confirmed", warnings[0])

    def test_mlb_directory_resolves_unique_player_identity(self) -> None:
        class FakeStatsApi:
            @staticmethod
            def get(endpoint: str, params: dict) -> dict:
                self.assertEqual(endpoint, "sports_players")
                self.assertEqual(params["sportId"], 1)
                return {
                    "people": [{
                        "id": 660271,
                        "fullName": "Shohei Ohtani",
                        "active": True,
                        "currentTeam": {"id": 119},
                        "primaryPosition": {"abbreviation": "DH"},
                    }]
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            store = LocalJsonCacheStore(Path(temp_dir))
            with (
                patch.object(lineup_data, "cache_store", store),
                patch.object(lineup_data, "load_season_splits", return_value={"players": {}}),
            ):
                directory = lineup_data._ensure_mlb_player_directory(
                    FakeStatsApi, datetime(2026, 7, 23, tzinfo=UTC)
                )
                identities = lineup_data._season_player_ids()

        self.assertEqual(len(directory["players"]), 1)
        self.assertEqual(identities["shoheiohtani"], 660271)

    def test_player_pool_snapshot_survives_memory_cache_reset(self) -> None:
        response = PlayerPoolResponse(
            game_date="2026-07-23",
            last_updated=datetime(2026, 7, 23, tzinfo=UTC),
            games=[],
            players=[],
            changes={"added": 0, "removed": 0, "batting_order_changed": 0, "status_changed": 0},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LocalJsonCacheStore(Path(temp_dir))
            with patch.object(lineup_data, "cache_store", store):
                lineup_data._write_player_pool_snapshot(response)
                loaded = lineup_data._load_player_pool_snapshot("2026-07-23")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.game_date, "2026-07-23")
        self.assertTrue(
            lineup_data._snapshot_is_fresh(
                loaded, datetime(2026, 7, 23, 0, 10, tzinfo=UTC)
            )
        )
        self.assertFalse(
            lineup_data._snapshot_is_fresh(
                loaded, datetime(2026, 7, 23, 1, tzinfo=UTC)
            )
        )

    @patch.dict(
        "os.environ",
        {
            "USE_MOCK_DATA": "false",
            "DFF_REFRESH_MINUTES": "10",
            "PERSIST_PLAYER_POOL_SNAPSHOTS": "false",
        },
    )
    def test_selected_slate_filters_player_pool_and_applies_site_salary(self) -> None:
        now = datetime.now(UTC)
        slate = {
            "provider_slate_id": "24E59",
            "last_updated": now.isoformat(),
            "players": [{
                "name": "Shohei Ohtani",
                "team": "LAD",
                "opponent": "PHI",
                "positions": ["OF"],
                "salary": 6700,
                "projected_points": 14.2,
            }],
        }
        games = [
            GameSummary(
                game_id=1,
                game_time=now.isoformat(),
                away_team="LAD",
                home_team="PHI",
            ),
            GameSummary(
                game_id=2,
                game_time=now.isoformat(),
                away_team="NYY",
                home_team="BOS",
            ),
        ]
        players = [
            Player(
                mlbam_id=660271,
                name="Shohei Ohtani",
                team="LAD",
                opponent="PHI",
                position=["OF"],
                salary_dk=0,
                salary_fd=0,
                projected_dk=10,
                projected_fd=12,
                projection_source="season_avg_fallback",
                last_updated=now,
            ),
            Player(
                mlbam_id=1,
                name="Other Game Player",
                team="NYY",
                opponent="BOS",
                position=["OF"],
                salary_dk=5000,
                salary_fd=4000,
                projected_dk=9,
                projected_fd=11,
                projection_source="season_avg_fallback",
                last_updated=now,
            ),
        ]
        with (
            patch.object(lineup_data, "load_salary_slate", return_value=slate),
            patch.object(lineup_data, "_get_live_player_pool", return_value=(games, players, [])),
        ):
            response = lineup_data.get_player_pool_for_slate("dk", "24E59")

        self.assertEqual(response.site, "dk")
        self.assertEqual(response.slate_key, "dff:dk:24E59")
        self.assertEqual([player.name for player in response.players], ["Shohei Ohtani"])
        self.assertEqual(response.players[0].salary_dk, 6700)
        self.assertEqual([game.game_id for game in response.games], [1])

    def test_minute_cache_freshness_does_not_round_to_an_hour(self) -> None:
        now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

        self.assertTrue(
            lineup_data._cache_is_recent_minutes(
                datetime(2026, 7, 23, 11, 51, tzinfo=UTC),
                now,
                minutes=10,
            )
        )
        self.assertFalse(
            lineup_data._cache_is_recent_minutes(
                datetime(2026, 7, 23, 11, 49, tzinfo=UTC),
                now,
                minutes=10,
            )
        )

    @patch.dict(
        "os.environ",
        {
            "USE_MOCK_DATA": "false",
            "PERSIST_PLAYER_POOL_SNAPSHOTS": "true",
            "DFF_REFRESH_MINUTES": "10",
        },
    )
    def test_selected_slate_uses_persisted_pool_without_live_fanout(self) -> None:
        now = datetime.now(UTC)
        target_date = date.today().isoformat()
        slate = {
            "last_updated": now.isoformat(),
            "players": [{
                "name": "Shohei Ohtani",
                "team": "LAD",
                "opponent": "PHI",
                "positions": ["OF"],
                "salary": 6700,
                "projected_points": 14.2,
            }],
        }
        player = Player(
            mlbam_id=660271,
            name="Shohei Ohtani",
            team="LAD",
            opponent="PHI",
            position=["OF"],
            salary_dk=0,
            salary_fd=0,
            projected_dk=10,
            projected_fd=12,
            projection_source="season_avg_fallback",
            last_updated=now,
        )
        snapshot = PlayerPoolResponse(
            game_date=target_date,
            last_updated=now,
            games=[GameSummary(
                game_id=1,
                game_time=now.isoformat(),
                away_team="LAD",
                home_team="PHI",
            )],
            players=[player],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LocalJsonCacheStore(Path(temp_dir))
            store.write_json(
                f"{lineup_data.PLAYER_POOL_SNAPSHOT_PREFIX}/{target_date}",
                snapshot.model_dump(mode="json"),
            )
            with (
                patch.object(lineup_data, "cache_store", store),
                patch.object(lineup_data, "load_salary_slate", return_value=slate),
                patch.object(lineup_data, "_get_live_player_pool") as live_pool,
            ):
                response = lineup_data.get_player_pool_for_slate("dk", "24E59")

        live_pool.assert_not_called()
        self.assertEqual(response.data_status, "cached")
        self.assertEqual(len(response.players), 1)
        self.assertEqual(response.last_updated, now)

    def test_cross_platform_salary_gaps_do_not_mark_slates_missing(self) -> None:
        now = datetime(2026, 7, 23, tzinfo=UTC)
        players = [
            Player(
                mlbam_id=1,
                name="DK Player",
                team="LAD",
                opponent="NYY",
                position=["OF"],
                salary_dk=4000,
                salary_fd=0,
                projected_dk=8,
                projected_fd=0,
                projection_source="daily_fantasy_fuel",
                last_updated=now,
            ),
            Player(
                mlbam_id=2,
                name="FD Player",
                team="NYY",
                opponent="LAD",
                position=["OF"],
                salary_dk=0,
                salary_fd=3000,
                projected_dk=0,
                projected_fd=9,
                projection_source="daily_fantasy_fuel",
                last_updated=now,
            ),
        ]
        games = [GameSummary(
            game_id=1,
            game_time="2026-07-23T23:00:00Z",
            away_team="LAD",
            home_team="NYY",
        )]

        self.assertIsNone(lineup_data._player_pool_message(games, players, False))
        self.assertEqual(lineup_data._data_status(games, players, []), "live")

    def test_salary_slate_union_is_canonical_player_pool(self) -> None:
        now = datetime(2026, 7, 23, tzinfo=UTC)
        dff_player = Player(
            mlbam_id=1,
            name="DFF Player",
            team="LAD",
            opponent="NYY",
            position=["OF"],
            salary_dk=4000,
            salary_fd=3500,
            projected_dk=8,
            projected_fd=9,
            projection_source="daily_fantasy_fuel",
            last_updated=now,
        )
        mlb_only_player = Player(
            mlbam_id=2,
            name="MLB Only Player",
            team="NYY",
            opponent="LAD",
            position=["OF"],
            salary_dk=0,
            salary_fd=0,
            projected_dk=7,
            projected_fd=8,
            projection_source="season_avg_fallback",
            last_updated=now,
        )
        slate = {
            "players": [{
                "name": "DFF Player",
                "team": "LAD",
                "salary": 4000,
            }]
        }
        players = [dff_player, mlb_only_player]

        with patch.object(lineup_data, "load_salary_slate", return_value=slate):
            removed = lineup_data._retain_salary_slate_players(players, "2026-07-23")

        self.assertEqual(removed, 1)
        self.assertEqual([player.name for player in players], ["DFF Player"])


if __name__ == "__main__":
    unittest.main()
