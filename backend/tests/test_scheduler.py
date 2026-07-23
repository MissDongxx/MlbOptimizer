from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services import scheduler
from services.cache_store import LocalJsonCacheStore


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = LocalJsonCacheStore(Path(self.temp_dir.name))
        self.cache_patch = patch.object(scheduler, "cache_store", self.store)
        self.env_patch = patch.dict(os.environ, {"CACHE_DIR": self.temp_dir.name})
        self.cache_patch.start()
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.cache_patch.stop()
        self.temp_dir.cleanup()

    def test_refresh_records_per_source_status(self) -> None:
        response = SimpleNamespace(players=[], games=[])
        with (
            patch.object(
                scheduler,
                "refresh_salary_slates",
                return_value={
                    "dk": {"players": [{"name": "A"}], "source": "daily_fantasy_fuel"},
                    "fd": {"players": [{"name": "B"}], "source": "daily_fantasy_fuel"},
                },
            ),
            patch.object(scheduler, "refresh_vegas_lines", return_value={"games": []}),
            patch.object(scheduler, "get_todays_games", return_value=[]),
            patch.object(scheduler, "refresh_weather_contexts", return_value={"venues": {}}),
            patch.object(scheduler, "get_todays_player_pool", return_value=response),
        ):
            status = scheduler.refresh_all_data()

        self.assertEqual(status["last_run_status"], "success")
        self.assertFalse(status["in_progress"])
        self.assertEqual(status["sources"]["dff_dk"]["records"], 1)
        self.assertEqual(status["sources"]["dff_fd"]["records"], 1)
        self.assertEqual(status["sources"]["player_pool"]["last_run_status"], "success")

    def test_refresh_lock_skips_overlapping_run(self) -> None:
        with scheduler.refresh_lock() as acquired:
            self.assertTrue(acquired)
            status = scheduler.refresh_all_data()

        self.assertEqual(status["skipped_locked"], 1)
        self.assertIsNotNone(status["last_skipped_locked"])

    def test_known_future_schedule_refreshes_at_least_every_ten_minutes(self) -> None:
        first_pitch = datetime.now(UTC) + timedelta(hours=4)

        self.assertEqual(scheduler.get_refresh_interval_seconds(first_pitch), 600)


if __name__ == "__main__":
    unittest.main()
