from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from models.schemas import Player
from services import slate_data
from services.cache_store import LocalJsonCacheStore


DK_CSV = """Position,Name + ID,Name,ID,Roster Position,Salary,TeamAbbrev
OF,Shohei Ohtani (12345),Shohei Ohtani,12345,OF,6400,LAD
SS,Mookie Betts Jr. (67890),Mookie Betts Jr.,67890,SS/OF,5900,LAD
"""

DFF_HTML = """
<li class="row" data-player_id="B1952" data-salary="6700" data-position="1B" data-position_alt="OF">
 <img src="/logos/mlb/LAD.svg"><div class="playername-desktop">
 <span class="bold-sm bold-md">Shohei</span><span class="bold-sm bold-md">Ohtani</span><span>• (L)</span></div>
 <div>LAD @ PHI</div><span class="mobileOrder">1</span>
 <span title="Expected Starter">E</span><input class="optimizer-edit-inline" value="12.4">
 <span class="player-val">1.9</span>
</li>
"""

ROTOWIRE_HTML = """
<div class="lineup__abbr">LAD</div><div class="lineup__abbr">PHI</div>
<ul class="lineup__list is-visit"><li class="lineup__status is-confirmed">Confirmed Lineup</li>
<li class="lineup__player"><div class="lineup__pos">DH</div><a title="Shohei Ohtani">S. Ohtani</a><span class="lineup__bats">L</span></li>
<li class="salaries hide">$6,700</li></ul>
"""

DFF_PLAYER_DATA = [{
    "team": "LAD", "location": "@", "opp": "PHI", "first_name": "Shohei", "last_name": "Ohtani",
    "position_code": "1B", "position_code_alt": "OF", "hand": "L", "player_id": "B1952",
    "salary": 6700, "ppg": "12.400", "value": "1.85", "depth_rank": 1,
    "injury_status": "", "starter_flag": 0, "probable_flag": 0,
}]

DFF_PROJECTION_HTML = """
<tr class="projections-listing" data-start_date="2026-07-23"
 data-name="Shohei Ohtani" data-pos="1B" data-pos_alt="OF" data-spread="-1.5"
 data-ou="9.5" data-inj="DTD" data-team="LAD" data-opp="PHI" data-loc="@"
 data-proj_score="5.4" data-salary="6700" data-hand="L" data-l5_avg="14.2"
 data-l10_avg="13.7" data-szn_avg="12.9" data-ppg_proj="14.0"
 data-value_proj="2.09" data-player_id="B1952" data-starter_flag="0"
 data-depth_rank="1"></tr>
"""

DFF_SLATE_INDEX = [
    {
        "sport": "MLB",
        "team_count": 6,
        "game_count": 3,
        "slate_type": "",
        "url": "24E59",
        "start_string": "Jul 23, 12:15 PM ET",
        "future_rank": "1",
        "showdown_flag": 0,
    },
    {
        "sport": "MLB",
        "team_count": 2,
        "game_count": 1,
        "slate_type": "SD @ ATL",
        "url": "24E5D",
        "start_string": "Jul 23, 12:15 PM ET",
        "future_rank": "2",
        "showdown_flag": 1,
    },
]


class SlateDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = LocalJsonCacheStore(Path(self.temp_dir.name))
        self.cache_patch = patch.object(slate_data, "cache_store", self.store)
        self.cache_patch.start()

    def tearDown(self) -> None:
        slate_data._rotowire_summary = None
        slate_data._rotowire_checked_at = None
        self.cache_patch.stop()
        self.temp_dir.cleanup()

    def test_imports_and_loads_draftkings_salary_csv(self) -> None:
        imported = slate_data.import_salary_csv("dk", DK_CSV, "2026-07-22")
        loaded = slate_data.load_salary_slate("dk", "2026-07-22")

        self.assertEqual(len(imported["players"]), 2)
        self.assertEqual(loaded["players"][0]["salary"], 6400)
        self.assertEqual(loaded["players"][0]["external_id"], "12345")
        self.assertEqual(loaded["players"][1]["positions"], ["SS", "OF"])

    def test_applies_salary_using_normalized_name(self) -> None:
        slate_data.import_salary_csv("dk", DK_CSV, "2026-07-22")
        player = Player(
            mlbam_id=1,
            name="Mookie Betts",
            team="LAD",
            opponent="SFG",
            position=["OF"],
            salary_dk=0,
            salary_fd=0,
            projected_dk=10,
            projected_fd=12,
            projection_source="season_avg_fallback",
            last_updated=datetime(2026, 7, 22, tzinfo=UTC),
        )

        matched = slate_data.apply_salary_slates([player], "2026-07-22")

        self.assertEqual(matched, {"dk": 1, "fd": 0})
        self.assertEqual(player.salary_dk, 5900)
        self.assertEqual(player.position_dk, ["SS", "OF"])
        self.assertEqual(player.external_id_dk, "67890")

    def test_dff_cannot_promote_player_to_confirmed(self) -> None:
        slate_data.import_salary_csv("dk", DK_CSV, "2026-07-22")
        cached = slate_data.load_salary_slate("dk", "2026-07-22")
        cached["players"][0]["lineup_status"] = "confirmed"
        self.store.write_json("slates/2026-07-22_dk", cached)
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
            last_updated=datetime(2026, 7, 22, tzinfo=UTC),
        )

        slate_data.apply_salary_slates([player], "2026-07-22")

        self.assertEqual(player.lineup_status, "expected")

    def test_parses_daily_fantasy_fuel_public_player_row(self) -> None:
        players = slate_data.parse_dff_html(DFF_HTML)

        self.assertEqual(players[0]["name"], "Shohei Ohtani")
        self.assertEqual(players[0]["positions"], ["1B", "OF"])
        self.assertEqual(players[0]["salary"], 6700)
        self.assertEqual(players[0]["projected_points"], 12.4)
        self.assertEqual(players[0]["batting_order"], 1)
        self.assertEqual(players[0]["lineup_status"], "expected")

    def test_parses_daily_fantasy_fuel_show_all_player_data(self) -> None:
        players = slate_data.parse_dff_player_data(DFF_PLAYER_DATA)

        self.assertEqual(players[0]["name"], "Shohei Ohtani")
        self.assertEqual(players[0]["opponent"], "PHI")
        self.assertEqual(players[0]["positions"], ["1B", "OF"])
        self.assertEqual(players[0]["projected_points"], 12.4)
        self.assertEqual(players[0]["batting_order"], 1)
        self.assertEqual(players[0]["lineup_status"], "expected")
        self.assertEqual(players[0]["starter_flag"], 0)
        self.assertEqual(players[0]["probable_flag"], 0)

    def test_refreshes_and_caches_dff_slate_index(self) -> None:
        response = slate_data.refresh_dff_slate_index(
            "dk",
            "2026-07-23",
            fetcher=lambda _url: DFF_SLATE_INDEX,
        )
        cached = slate_data.load_dff_slate_index("dk", "2026-07-23")

        self.assertEqual(len(response.slates), 2)
        self.assertEqual(response.slates[0].slate_key, "dff:dk:24E59")
        self.assertEqual(response.slates[0].slate_type, "classic")
        self.assertTrue(response.slates[0].is_default)
        self.assertEqual(response.slates[1].slate_type, "showdown")
        self.assertEqual(cached.slates[0].provider_slate_id, "24E59")
        self.assertEqual(
            response.slates[0].lock_time.isoformat(),
            "2026-07-23T16:15:00+00:00",
        )

        slate_data.update_dff_slate_membership(
            "dk",
            "2026-07-23",
            "24E59",
            teams=["SD", "ATL", "TB", "TOR"],
            game_ids=[2, 1, 2],
        )
        enriched = slate_data.load_dff_slate_index("dk", "2026-07-23")
        self.assertEqual(enriched.slates[0].teams, ["ATL", "SDP", "TBR", "TOR"])
        self.assertEqual(enriched.slates[0].game_ids, [1, 2])
        self.assertEqual(enriched.slates[0].game_count, 3)

    def test_parses_and_merges_daily_fantasy_fuel_projection_row(self) -> None:
        projection_players = slate_data.parse_dff_projection_html(DFF_PROJECTION_HTML)
        players = slate_data.parse_dff_player_data(DFF_PLAYER_DATA)

        enriched = slate_data._merge_dff_projection_rows(players, projection_players)

        self.assertEqual(enriched, 1)
        self.assertEqual(projection_players[0]["last_5_avg"], 14.2)
        self.assertEqual(projection_players[0]["last_10_avg"], 13.7)
        self.assertEqual(projection_players[0]["season_avg"], 12.9)
        self.assertEqual(players[0]["game_total"], 9.5)
        self.assertEqual(players[0]["implied_team_total"], 5.4)
        self.assertEqual(players[0]["injury_status"], "DTD")

    def test_warms_only_classic_dff_slates(self) -> None:
        index = slate_data.refresh_dff_slate_index(
            "dk",
            "2026-07-23",
            fetcher=lambda _url: DFF_SLATE_INDEX,
        )
        with (
            patch.object(slate_data, "load_salary_slate", return_value={"players": []}),
            patch.object(
                slate_data,
                "refresh_dff_slate",
                return_value={"players": [{"name": "Player"}]},
            ) as refresh,
        ):
            details = slate_data.refresh_dff_classic_slates(
                "dk",
                "2026-07-23",
                index,
            )

        self.assertEqual(list(details), ["24E59"])
        refresh.assert_called_once_with("dk", "2026-07-23", "24E59")

    def test_parses_rotowire_validation_row(self) -> None:
        players = slate_data.parse_rotowire_html(ROTOWIRE_HTML)

        self.assertEqual(players[0]["team"], "LAD")
        self.assertEqual(players[0]["name"], "Shohei Ohtani")
        self.assertEqual(players[0]["salary_dk"], 6700)
        self.assertEqual(players[0]["batting_order"], 1)
        self.assertEqual(players[0]["lineup_status"], "confirmed")

    def test_rotowire_validation_persists_normalized_daily_snapshot(self) -> None:
        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return ROTOWIRE_HTML.encode("utf-8")

        player = SimpleNamespace(
            name="Shohei Ohtani",
            salary_dk=6700,
            batting_order=1,
            lineup_status="confirmed",
        )
        with patch.object(slate_data, "urlopen", return_value=FakeResponse()):
            summary = slate_data.validate_with_rotowire([player])

        snapshot = self.store.read_json(
            f"{slate_data.ROTOWIRE_DETAIL_PREFIX}/{slate_data.date.today().isoformat()}"
        )
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(snapshot["source"], "rotowire_public_daily_lineups")
        self.assertEqual(snapshot["players"][0]["name"], "Shohei Ohtani")
        self.assertEqual(snapshot["summary"]["salary_conflicts"], 0)


if __name__ == "__main__":
    unittest.main()
