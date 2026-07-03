from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.cache_store import LocalJsonCacheStore


class CacheStoreTests(unittest.TestCase):
    def test_local_json_cache_store_reads_and_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalJsonCacheStore(Path(tmpdir))

            store.write_json("season_splits", {"players": {"1": {"name": "Test"}}})

            self.assertTrue(store.exists("season_splits"))
            self.assertEqual(store.read_json("season_splits")["players"]["1"]["name"], "Test")
            self.assertTrue((Path(tmpdir) / "season_splits.json").exists())

    def test_local_json_cache_store_returns_default_for_missing_or_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = LocalJsonCacheStore(root)
            (root / "bad.json").write_text("{")

            self.assertEqual(store.read_json("missing", default={}), {})
            self.assertEqual(store.read_json("bad", default={"ok": False}), {"ok": False})

    def test_local_json_cache_store_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalJsonCacheStore(Path(tmpdir))

            with self.assertRaises(ValueError):
                store.write_json("../escape", {"nope": True})


if __name__ == "__main__":
    unittest.main()
