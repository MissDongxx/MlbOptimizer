from __future__ import annotations

import fcntl
import logging
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except ImportError:  # runtime dependency; non-scheduler commands/tests remain usable
    BackgroundScheduler = None  # type: ignore[assignment,misc]

from services.cache_store import DEFAULT_CACHE_DIR, cache_store
from services.lineup_data import get_todays_games, get_todays_player_pool
from services.season_cache import refresh_batter_hand_splits, refresh_season_splits
from services.slate_data import refresh_salary_slates
from services.vegas import refresh_vegas_lines
from services.weather import refresh_weather_contexts

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None
REFRESH_STATUS_KEY = "refresh_status/data_refresh"
REFRESH_LOCK_FILENAME = "data_refresh.lock"


def get_refresh_interval_seconds(
    first_pitch: datetime | None = None,
    game_in_progress: bool = False,
) -> int:
    if game_in_progress:
        return 300
    if not first_pitch:
        return 7200

    diff = first_pitch - datetime.now(UTC)
    if diff > timedelta(hours=3):
        return 600
    if timedelta(minutes=90) < diff <= timedelta(hours=3):
        return 600
    if timedelta(0) <= diff <= timedelta(minutes=90):
        return 120
    return 300


def refresh_all_data() -> dict[str, Any]:
    with refresh_lock() as acquired:
        if not acquired:
            status = get_refresh_status()
            status["skipped_locked"] = int(status.get("skipped_locked", 0) or 0) + 1
            status["last_skipped_locked"] = datetime.now(UTC).isoformat()
            cache_store.write_json(REFRESH_STATUS_KEY, status)
            logger.warning("data refresh skipped because another refresh holds the lock")
            return status

        started = datetime.now(UTC)
        status = get_refresh_status()
        status.update(
            {
                "in_progress": True,
                "last_started": started.isoformat(),
                "worker_pid": os.getpid(),
            }
        )
        status.setdefault("sources", {})
        cache_store.write_json(REFRESH_STATUS_KEY, status)

        salary_result = _run_source(status, "salary_slates", refresh_salary_slates)
        _record_slate_sources(status, salary_result)
        _run_source(status, "vegas", refresh_vegas_lines)
        games = _run_source(status, "mlb_schedule", get_todays_games) or []
        _run_source(status, "weather", lambda: refresh_weather_contexts(games))
        response = _run_source(
            status,
            "player_pool",
            lambda: get_todays_player_pool(force_refresh=True),
        )
        if response is not None:
            hitter_ids = [
                player.mlbam_id
                for player in response.players
                if "P" not in getattr(player, "position", []) and player.mlbam_id > 0
            ]
            if hitter_ids:
                _run_source(
                    status,
                    "handedness_splits",
                    lambda: refresh_batter_hand_splits(hitter_ids),
                )
            _reschedule_lineup_refresh(_first_pitch_from_games(response.games))

        completed = datetime.now(UTC)
        failures = [
            name
            for name, source in status.get("sources", {}).items()
            if source.get("last_run_status") == "error"
        ]
        status.update(
            {
                "in_progress": False,
                "last_completed": completed.isoformat(),
                "duration_ms": int((completed - started).total_seconds() * 1000),
                "last_run_status": "partial" if failures else "success",
                "failed_sources": failures,
            }
        )
        cache_store.write_json(REFRESH_STATUS_KEY, status)
        return status


def refresh_season_data() -> dict[str, Any]:
    status = get_refresh_status()
    status.setdefault("sources", {})
    _run_source(
        status,
        "season_splits",
        lambda: refresh_season_splits(datetime.now(UTC).year),
    )
    cache_store.write_json(REFRESH_STATUS_KEY, status)
    return status


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if BackgroundScheduler is None:
        raise RuntimeError(
            "APScheduler is required to start the in-process refresh scheduler; "
            "install the locked project dependencies first"
        )
    scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler = scheduler
    scheduler.add_job(
        refresh_all_data,
        "interval",
        seconds=get_refresh_interval_seconds(),
        id="lineup_refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        refresh_season_data,
        "cron",
        hour=6,
        minute=0,
        id="season_splits_refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if os.getenv("USE_MOCK_DATA", "true").lower() == "false":
        scheduler.add_job(
            refresh_all_data,
            "date",
            run_date=datetime.now(UTC) + timedelta(seconds=1),
            id="initial_data_refresh",
            replace_existing=True,
        )
    scheduler.start()
    logger.info("data refresh scheduler started in pid %s", os.getpid())
    return scheduler


def get_refresh_status() -> dict[str, Any]:
    data = cache_store.read_json(REFRESH_STATUS_KEY, default={})
    return data if isinstance(data, dict) else {}


def refresh_worker_enabled() -> bool:
    configured = os.getenv("RUN_DATA_SCHEDULER")
    if configured is not None:
        return configured.lower() == "true"
    return os.getenv("APP_ENV", "development").lower() != "production"


@contextmanager
def refresh_lock() -> Iterator[bool]:
    cache_dir = Path(os.getenv("CACHE_DIR", str(DEFAULT_CACHE_DIR)))
    cache_dir.mkdir(parents=True, exist_ok=True)
    lock_path = cache_dir / REFRESH_LOCK_FILENAME
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _run_source(
    status: dict[str, Any],
    name: str,
    function: Callable[[], Any],
) -> Any:
    source = status.setdefault("sources", {}).setdefault(name, {})
    started = datetime.now(UTC)
    source.update({"last_started": started.isoformat(), "last_run_status": "running"})
    cache_store.write_json(REFRESH_STATUS_KEY, status)
    try:
        result = function()
    except Exception as exc:
        completed = datetime.now(UTC)
        source.update(
            {
                "last_run_status": "error",
                "last_failure": completed.isoformat(),
                "duration_ms": int((completed - started).total_seconds() * 1000),
                "consecutive_failures": int(source.get("consecutive_failures", 0) or 0) + 1,
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }
        )
        cache_store.write_json(REFRESH_STATUS_KEY, status)
        logger.exception("%s refresh failed", name)
        return None

    completed = datetime.now(UTC)
    source.update(
        {
            "last_run_status": "success",
            "last_success": completed.isoformat(),
            "duration_ms": int((completed - started).total_seconds() * 1000),
            "consecutive_failures": 0,
            "records": _result_size(result),
        }
    )
    source.pop("error", None)
    cache_store.write_json(REFRESH_STATUS_KEY, status)
    return result


def _record_slate_sources(status: dict[str, Any], result: Any) -> None:
    if not isinstance(result, dict):
        return
    for site in ("dk", "fd"):
        data = result.get(site)
        if not isinstance(data, dict):
            continue
        source = status.setdefault("sources", {}).setdefault(f"dff_{site}", {})
        source.update(
            {
                "last_run_status": "success" if data.get("players") else "error",
                "last_success": (
                    datetime.now(UTC).isoformat() if data.get("players") else source.get("last_success")
                ),
                "records": len(data.get("players", [])),
                "source": data.get("source"),
                "source_updated_at": data.get("last_updated"),
                "slate_key": data.get("slate_key"),
                "consecutive_failures": (
                    0
                    if data.get("players")
                    else int(source.get("consecutive_failures", 0) or 0) + 1
                ),
            }
        )


def _result_size(result: Any) -> int | None:
    if isinstance(result, (list, tuple, set, dict)):
        return len(result)
    players = getattr(result, "players", None)
    if isinstance(players, list):
        return len(players)
    return None


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
    if (
        job
        and getattr(job.trigger, "interval", None)
        and int(job.trigger.interval.total_seconds()) == seconds
    ):
        return
    try:
        _scheduler.reschedule_job("lineup_refresh", trigger="interval", seconds=seconds)
    except Exception:
        logger.exception("failed to reschedule lineup refresh")
