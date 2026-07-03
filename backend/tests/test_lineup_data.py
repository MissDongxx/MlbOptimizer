from __future__ import annotations

import unittest
from datetime import UTC, datetime

from models.schemas import Starter
from services.lineup_data import _players_from_boxscore_side


class LineupDataTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
