from fastapi import APIRouter

from models.schemas import PlayerPoolResponse
from services.lineup_data import get_todays_player_pool

router = APIRouter()


@router.get("/today", response_model=PlayerPoolResponse)
async def players_today() -> PlayerPoolResponse:
    return get_todays_player_pool()
