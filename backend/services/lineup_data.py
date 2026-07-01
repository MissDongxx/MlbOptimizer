from __future__ import annotations

import os
from datetime import UTC, date, datetime

from models.schemas import GameSummary, Player, PlayerPoolResponse, Starter
from services.mock_data import mock_games, mock_players

_last_refresh_timestamp: datetime | None = None
_last_player_count = 0


def get_todays_games() -> list[GameSummary]:
    if os.getenv("USE_MOCK_DATA", "true").lower() == "true":
        return mock_games()
    try:
        import statsapi  # type: ignore
    except ImportError:
        return mock_games()

    games: list[GameSummary] = []
    for game in statsapi.schedule(date=date.today().isoformat()):
        away_probable = game.get("away_probable_pitcher") or ""
        home_probable = game.get("home_probable_pitcher") or ""
        games.append(
            GameSummary(
                game_id=int(game["game_id"]),
                game_time=str(game.get("game_datetime") or game.get("game_date") or ""),
                away_team=str(game.get("away_name") or game.get("away_team") or ""),
                home_team=str(game.get("home_name") or game.get("home_team") or ""),
                away_starter=Starter(name=away_probable, hand=None),
                home_starter=Starter(name=home_probable, hand=None),
                away_lineup_confirmed=False,
                home_lineup_confirmed=False,
                venue=game.get("venue_name"),
            )
        )
    return games


def get_player_status(mlbam_id: int) -> str:
    return "active" if mlbam_id else "DNP"


def get_todays_player_pool() -> PlayerPoolResponse:
    global _last_refresh_timestamp, _last_player_count
    now = datetime.now(UTC)
    games = get_todays_games()
    players = mock_players()
    _last_refresh_timestamp = now
    _last_player_count = len(players)
    return PlayerPoolResponse(
        game_date=date.today().isoformat(),
        last_updated=now,
        games=games,
        players=players,
        message=None if games else "No games scheduled today",
    )


def get_last_refresh_timestamp() -> datetime | None:
    return _last_refresh_timestamp


def get_player_count() -> int:
    return _last_player_count
