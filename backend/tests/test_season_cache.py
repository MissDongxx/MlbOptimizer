from __future__ import annotations

import unittest

import pandas as pd

from services.season_cache import (
    _build_mlbam_lookup,
    _build_player_id_lookup,
    _extract_hand_splits,
    _float_stat,
)


class FakePybaseball:
    @staticmethod
    def playerid_reverse_lookup(player_ids: list[int], key_type: str) -> pd.DataFrame:
        if key_type != "fangraphs":
            raise AssertionError("expected fangraphs lookup")
        return pd.DataFrame(
            [
                {"key_fangraphs": player_ids[0], "key_mlbam": 660271, "key_bbref": "ohtansh01"},
                {"key_fangraphs": player_ids[1], "key_mlbam": 605141, "key_bbref": "bettsmo01"},
            ]
        )


class SeasonCacheTests(unittest.TestCase):
    def test_build_mlbam_lookup_uses_pybaseball_reverse_lookup(self) -> None:
        stats = pd.DataFrame([{"IDfg": 19755}, {"IDfg": 13611}])

        lookup = _build_mlbam_lookup(stats, FakePybaseball)

        self.assertEqual(lookup, {"13611": 660271, "19755": 605141})

    def test_build_player_id_lookup_includes_bbref_ids(self) -> None:
        stats = pd.DataFrame([{"IDfg": 19755}, {"IDfg": 13611}])

        lookup = _build_player_id_lookup(stats, FakePybaseball)

        self.assertEqual(lookup["13611"]["mlbam_id"], 660271)
        self.assertEqual(lookup["13611"]["bbref_id"], "ohtansh01")

    def test_float_stat_normalizes_percentage_strings(self) -> None:
        row = {"K%": "19.5%", "BB%": 0.112, "wOBA": ".384"}

        self.assertEqual(_float_stat(row, "K%"), 0.195)
        self.assertEqual(_float_stat(row, "BB%"), 0.112)
        self.assertEqual(_float_stat(row, "wOBA"), 0.384)

    def test_extract_hand_splits_from_baseball_reference_shape(self) -> None:
        split_data = pd.DataFrame(
            [
                {"PA": 110, "OPS": 0.910, "AB": 95, "H": 30, "TB": 58, "BB": 14, "SO": 20},
                {"PA": 300, "OPS": 0.780, "AB": 265, "H": 70, "TB": 120, "BB": 28, "SO": 62},
            ],
            index=pd.MultiIndex.from_tuples(
                [("Platoon Splits", "vs LHP"), ("Platoon Splits", "vs RHP")],
                names=["Split Type", "Split"],
            ),
        )

        splits = _extract_hand_splits(
            split_data,
            {
                "vs_L": {"ops": 0.82},
                "vs_R": {"ops": 0.82},
            },
        )

        self.assertEqual(splits["vs_L"]["sample_note"], "baseball_reference_handedness_split")
        self.assertEqual(splits["vs_L"]["pa"], 110)
        self.assertGreater(splits["vs_L"]["projection_factor"], 1.0)
        self.assertLess(splits["vs_R"]["projection_factor"], 1.0)
        self.assertAlmostEqual(splits["vs_L"]["iso"], (58 - 30) / 95, places=3)


if __name__ == "__main__":
    unittest.main()
