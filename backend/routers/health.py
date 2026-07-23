import os

from fastapi import APIRouter

from models.schemas import HealthResponse
from services.lineup_data import (
    get_data_status,
    get_data_warnings,
    get_last_refresh_timestamp,
    get_player_count,
)
from services.projections import get_cache_age
from services.scheduler import get_refresh_status, refresh_worker_enabled
from services.season_cache import season_cache_health
from services.slate_data import ROTOWIRE_STATUS_KEY
from services.cache_store import cache_store

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    season_cache = season_cache_health()
    refresh_status = get_refresh_status()
    rotowire_status = cache_store.read_json(ROTOWIRE_STATUS_KEY, default={})
    if isinstance(rotowire_status, dict) and rotowire_status:
        refresh_status = {
            **refresh_status,
            "sources": {
                **refresh_status.get("sources", {}),
                "rotowire_validation": rotowire_status,
            },
        }
    return HealthResponse(
        status="ok",
        app_env=os.getenv("APP_ENV", "development"),
        use_mock_data=os.getenv("USE_MOCK_DATA", "true").lower() == "true",
        data_status=get_data_status(),
        data_warnings=get_data_warnings(),
        cache_age_seconds=get_cache_age(),
        season_cache_exists=bool(season_cache["exists"]),
        season_cache_age_hours=season_cache["age_hours"],
        season_cache_players=int(season_cache["players"]),
        last_lineup_refresh=get_last_refresh_timestamp(),
        players_loaded=get_player_count(),
        statsapi_available=_statsapi_available(),
        refresh_worker_enabled=refresh_worker_enabled(),
        refresh_in_progress=bool(refresh_status.get("in_progress")),
        refresh_status=refresh_status,
    )


def _statsapi_available() -> bool:
    try:
        import statsapi  # type: ignore # noqa: F401
    except ImportError:
        return False
    return True
