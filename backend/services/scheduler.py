from __future__ import annotations

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler

from services.lineup_data import get_todays_player_pool
from services.season_cache import refresh_season_splits

logger = logging.getLogger(__name__)


def get_refresh_interval_seconds() -> int:
    return 600


def refresh_all_data() -> None:
    get_todays_player_pool()


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        refresh_all_data,
        "interval",
        seconds=get_refresh_interval_seconds(),
        id="lineup_refresh",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: refresh_season_splits(datetime.now(UTC).year),
        "cron",
        hour=6,
        minute=0,
        id="season_splits_refresh",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("scheduler started")
    return scheduler
