from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from services.lineup_data import get_todays_games, get_todays_player_pool
from services.season_cache import refresh_batter_hand_splits, refresh_season_splits
from services.vegas import refresh_vegas_lines
from services.weather import refresh_weather_contexts

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def get_refresh_interval_seconds(first_pitch: datetime | None = None, game_in_progress: bool = False) -> int:
    if game_in_progress:
        return 300
    if not first_pitch:
        return 7200

    diff = first_pitch - datetime.now(UTC)
    if diff > timedelta(hours=3):
        return 7200
    if timedelta(minutes=90) < diff <= timedelta(hours=3):
        return 600
    if timedelta(0) <= diff <= timedelta(minutes=90):
        return 120
    return 300


def refresh_all_data() -> None:
    refresh_vegas_lines()
    games = get_todays_games()
    refresh_weather_contexts(games)
    response = get_todays_player_pool()
    hitter_ids = [
        player.mlbam_id
        for player in response.players
        if "P" not in getattr(player, "position", [])
    ]
    if hitter_ids:
        refresh_batter_hand_splits(hitter_ids)
    first_pitch = _first_pitch_from_games(response.games)
    _reschedule_lineup_refresh(first_pitch)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler = scheduler
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


def _first_pitch_from_games(games: list[object]) -> datetime | None:
    first_pitch: datetime | None = None
    for game in games:
        raw_time = getattr(game, "game_time", None)
        if not raw_time:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        if first_pitch is None or parsed < first_pitch:
            first_pitch = parsed
    return first_pitch


def _reschedule_lineup_refresh(first_pitch: datetime | None) -> None:
    if not _scheduler:
        return
    seconds = get_refresh_interval_seconds(first_pitch)
    job = _scheduler.get_job("lineup_refresh")
    if job and getattr(job.trigger, "interval", None) and int(job.trigger.interval.total_seconds()) == seconds:
        return
    try:
        _scheduler.reschedule_job("lineup_refresh", trigger="interval", seconds=seconds)
    except Exception:
        logger.exception("failed to reschedule lineup refresh")
