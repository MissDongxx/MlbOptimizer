from datetime import date

from fastapi import APIRouter, HTTPException, Query

from models.schemas import PlayerPoolResponse, SlateListResponse
from services.lineup_data import (
    SlateDataUnavailable,
    get_player_pool_for_slate,
    get_todays_player_pool,
)
from services.slate_data import get_dff_slates

router = APIRouter()


@router.get("/today", response_model=PlayerPoolResponse)
async def players_today(
    site: str | None = Query(default=None, pattern="^(dk|fd)$"),
    slate_id: str | None = Query(default=None, min_length=1, max_length=80),
) -> PlayerPoolResponse:
    if bool(site) != bool(slate_id):
        raise HTTPException(
            status_code=400,
            detail="site and slate_id must be provided together",
        )
    if site and slate_id:
        try:
            return get_player_pool_for_slate(site, slate_id)
        except SlateDataUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return get_todays_player_pool()


@router.get("/slates", response_model=SlateListResponse)
async def player_slates(
    site: str = Query(pattern="^(dk|fd)$"),
    game_date: str | None = None,
) -> SlateListResponse:
    target_date = game_date or date.today().isoformat()
    return get_dff_slates(site, target_date)
