from fastapi import APIRouter

from models.schemas import HealthResponse
from services.lineup_data import get_last_refresh_timestamp, get_player_count
from services.projections import get_cache_age

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        cache_age_seconds=get_cache_age(),
        last_lineup_refresh=get_last_refresh_timestamp(),
        players_loaded=get_player_count(),
    )
