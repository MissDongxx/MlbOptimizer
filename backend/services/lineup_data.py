from __future__ import annotations

import os
from datetime import UTC, date, datetime

from models.schemas import GameSummary, Player, PlayerPoolResponse, Starter
from services.cache_store import cache_store
from services.mock_data import mock_games, mock_players
from services.projections import get_pitcher_projection, get_split_projection

_last_refresh_timestamp: datetime | None = None
_last_player_count = 0
_last_data_status = "mock"
_last_data_warnings: list[str] = []
HAND_CACHE_KEY = "player_handedness"


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
    global _last_refresh_timestamp, _last_player_count, _last_data_status, _last_data_warnings
    now = datetime.now(UTC)
    use_mock = os.getenv("USE_MOCK_DATA", "true").lower() == "true"
    if use_mock:
        games = mock_games()
        players = mock_players()
        data_status = "mock"
        warnings = ["Using mock data. Disable USE_MOCK_DATA for live production traffic."]
    else:
        games, players, warnings = _get_live_player_pool(now)
        if not games:
            games = get_todays_games()
        data_status = _data_status(games, players, warnings)
    _last_refresh_timestamp = now
    _last_player_count = len(players)
    _last_data_status = data_status
    _last_data_warnings = warnings
    return PlayerPoolResponse(
        game_date=date.today().isoformat(),
        last_updated=now,
        data_status=data_status,
        warnings=warnings,
        games=games,
        players=players,
        message=_player_pool_message(games, players, use_mock),
    )


def get_last_refresh_timestamp() -> datetime | None:
    return _last_refresh_timestamp


def get_player_count() -> int:
    return _last_player_count


def get_data_status() -> str:
    return _last_data_status


def get_data_warnings() -> list[str]:
    return _last_data_warnings[:]


def _get_live_player_pool(now: datetime) -> tuple[list[GameSummary], list[Player], list[str]]:
    try:
        import statsapi  # type: ignore
    except ImportError:
        return [], [], ["MLB StatsAPI package is not available."]

    games: list[GameSummary] = []
    players: list[Player] = []
    warnings: list[str] = []
    try:
        schedule = statsapi.schedule(date=date.today().isoformat())
    except Exception:
        return [], [], ["MLB StatsAPI schedule request failed."]

    for game in schedule:
        away_team = str(game.get("away_name") or game.get("away_team") or "")
        home_team = str(game.get("home_name") or game.get("home_team") or "")
        game_id = int(game["game_id"])
        game_summary = GameSummary(
            game_id=game_id,
            game_time=str(game.get("game_datetime") or game.get("game_date") or ""),
            away_team=away_team,
            home_team=home_team,
            away_starter=_starter_from_schedule(str(game.get("away_probable_pitcher") or ""), statsapi),
            home_starter=_starter_from_schedule(str(game.get("home_probable_pitcher") or ""), statsapi),
            venue=game.get("venue_name"),
        )

        try:
            boxscore = statsapi.boxscore_data(game_id)
        except Exception:
            warnings.append(f"Boxscore unavailable for game {game_id}.")
            games.append(game_summary)
            continue

        team_info = boxscore.get("teamInfo", {})
        away_abbr = str(team_info.get("away", {}).get("abbreviation") or away_team)
        home_abbr = str(team_info.get("home", {}).get("abbreviation") or home_team)
        game_summary.away_team = away_abbr
        game_summary.home_team = home_abbr
        game_summary.away_lineup_confirmed = len(boxscore.get("away", {}).get("battingOrder") or []) >= 8
        game_summary.home_lineup_confirmed = len(boxscore.get("home", {}).get("battingOrder") or []) >= 8

        players.extend(
            _players_from_boxscore_side(
                boxscore,
                side="away",
                team=away_abbr,
                opponent=home_abbr,
                opposing_pitcher=game_summary.home_starter,
                lineup_confirmed=game_summary.away_lineup_confirmed,
                venue=game_summary.venue,
                now=now,
            )
        )
        players.extend(
            _players_from_boxscore_side(
                boxscore,
                side="home",
                team=home_abbr,
                opponent=away_abbr,
                opposing_pitcher=game_summary.away_starter,
                lineup_confirmed=game_summary.home_lineup_confirmed,
                venue=game_summary.venue,
                now=now,
            )
        )
        players.extend(_probable_pitchers_from_game(game_summary, now))
        games.append(game_summary)
    return games, players, warnings


def _players_from_boxscore_side(
    boxscore: dict,
    side: str,
    team: str,
    opponent: str,
    opposing_pitcher: Starter | None,
    lineup_confirmed: bool,
    now: datetime,
    venue: str | None = None,
) -> list[Player]:
    side_data = boxscore.get(side, {})
    batting_order = side_data.get("battingOrder") or []
    raw_players = side_data.get("players", {})
    players: list[Player] = []
    for index, player_id in enumerate(batting_order[:9], start=1):
        raw_player = raw_players.get(f"ID{player_id}") or {}
        person = raw_player.get("person", {})
        mlbam_id = int(person.get("id") or player_id)
        position = _dfs_positions(raw_player)
        opposing_hand = opposing_pitcher.hand if opposing_pitcher and opposing_pitcher.hand else ""
        projection_dk = get_split_projection(
            mlbam_id,
            opposing_hand,
            index,
            site="dk",
            venue=venue,
            team=team,
        )
        projection_fd = get_split_projection(
            mlbam_id,
            opposing_hand,
            index,
            site="fd",
            venue=venue,
            team=team,
        )
        projected_dk = float(projection_dk["projected_points"])
        projected_fd = float(projection_fd["projected_points"])
        players.append(
            Player(
                mlbam_id=mlbam_id,
                name=str(person.get("fullName") or ""),
                team=team,
                opponent=opponent,
                position=position,
                salary_dk=0,
                salary_fd=0,
                batting_order=index,
                opposing_pitcher=opposing_pitcher.name if opposing_pitcher else None,
                opposing_pitcher_hand=opposing_pitcher.hand if opposing_pitcher else None,
                lineup_status="confirmed" if lineup_confirmed else "expected",
                projected_dk=projected_dk,
                projected_fd=projected_fd,
                projection_source=projection_dk["projection_source"],
                last_15_avg_dk=float(projection_dk["base_projection"]),
                vs_lhp_avg=projected_dk,
                vs_rhp_avg=projected_dk,
                last_updated=now,
            )
        )
    return players


def _probable_pitchers_from_game(game: GameSummary, now: datetime) -> list[Player]:
    pitchers: list[Player] = []
    for starter, team, opponent in (
        (game.away_starter, game.away_team, game.home_team),
        (game.home_starter, game.home_team, game.away_team),
    ):
        if not starter or not starter.mlbam_id:
            continue
        projection_dk = get_pitcher_projection(starter.mlbam_id, 0, site="dk")
        projection_fd = get_pitcher_projection(starter.mlbam_id, 0, site="fd")
        projected_dk = float(projection_dk["projected_points"])
        projected_fd = float(projection_fd["projected_points"])
        pitchers.append(
            Player(
                mlbam_id=starter.mlbam_id,
                name=starter.name,
                team=team,
                opponent=opponent,
                position=["P"],
                salary_dk=0,
                salary_fd=0,
                batting_order=None,
                opposing_pitcher=opponent,
                opposing_pitcher_hand=None,
                lineup_status="expected",
                projected_dk=projected_dk,
                projected_fd=projected_fd,
                projection_source=projection_dk["projection_source"],
                last_updated=now,
            )
        )
    return pitchers


def _starter_from_schedule(name: str, statsapi_module: object) -> Starter:
    if not name:
        return Starter(name="")
    try:
        matches = statsapi_module.lookup_player(name)
    except Exception:
        matches = []
    if not matches:
        return Starter(name=name)
    match = matches[0]
    mlbam_id = match.get("id")
    hand = _hand_from_payload(match) or _cached_pitcher_hand(mlbam_id, statsapi_module)
    return Starter(name=str(match.get("fullName") or name), mlbam_id=mlbam_id, hand=hand)


def _hand_from_payload(payload: dict) -> str | None:
    raw = payload.get("pitchHand") or payload.get("throwingHand") or {}
    hand = raw.get("code") if isinstance(raw, dict) else raw
    return hand if hand in {"L", "R"} else None


def _cached_pitcher_hand(mlbam_id: int | None, statsapi_module: object) -> str | None:
    if not mlbam_id:
        return None
    cache = _load_hand_cache()
    key = str(mlbam_id)
    cached = cache.get(key)
    if cached in {"L", "R"}:
        return cached

    hand = _fetch_pitcher_hand(mlbam_id, statsapi_module)
    if hand:
        cache[key] = hand
        _write_hand_cache(cache)
    return hand


def _fetch_pitcher_hand(mlbam_id: int, statsapi_module: object) -> str | None:
    try:
        data = statsapi_module.get("person", {"personId": mlbam_id})
    except Exception:
        return None
    people = data.get("people", []) if isinstance(data, dict) else []
    if not people:
        return None
    return _hand_from_payload(people[0])


def _load_hand_cache() -> dict[str, str]:
    data = cache_store.read_json(HAND_CACHE_KEY, default={})
    return data if isinstance(data, dict) else {}


def _write_hand_cache(data: dict[str, str]) -> None:
    cache_store.write_json(HAND_CACHE_KEY, data)


def _dfs_positions(raw_player: dict) -> list[str]:
    positions = [
        _position_to_dfs(item.get("abbreviation"))
        for item in raw_player.get("allPositions", [])
        if item.get("abbreviation")
    ]
    if not positions:
        positions = [_position_to_dfs(raw_player.get("position", {}).get("abbreviation"))]
    return sorted({position for position in positions if position})


def _position_to_dfs(position: str | None) -> str:
    if position in {"LF", "CF", "RF"}:
        return "OF"
    if position == "DH":
        return "UTIL"
    if position in {"P", "C", "1B", "2B", "3B", "SS", "OF"}:
        return position
    return "UTIL"


def _player_pool_message(games: list[GameSummary], players: list[Player], use_mock: bool) -> str | None:
    if not games:
        return "No games scheduled today"
    if use_mock:
        return None
    if not players:
        return "Live schedule loaded, but no confirmed or expected lineups were available yet"
    if any(player.salary_dk == 0 or player.salary_fd == 0 for player in players):
        return "Live lineups loaded from statsapi. Upload a DK/FD salary CSV before optimizing."
    return None


def _data_status(games: list[GameSummary], players: list[Player], warnings: list[str]) -> str:
    if warnings:
        return "partial" if games or players else "error"
    if not games:
        return "error"
    if not players:
        return "partial"
    if any(player.salary_dk == 0 or player.salary_fd == 0 for player in players):
        return "partial"
    return "live"
