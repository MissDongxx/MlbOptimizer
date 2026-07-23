from __future__ import annotations

import os
import time
import hashlib
import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from typing import Any

from models.schemas import GameSummary, Player, PlayerPoolResponse, Starter
from services.cache_store import cache_store
from services.mock_data import mock_games, mock_players
from services.projections import get_pitcher_projection, get_split_projection
from services.season_cache import load_season_splits
from services.slate_data import (
    apply_salary_slates,
    load_salary_slate,
    refresh_dff_slate,
    update_dff_slate_membership,
    validate_with_rotowire,
)

_last_refresh_timestamp: datetime | None = None
_last_player_count = 0
_last_data_status = "mock"
_last_data_warnings: list[str] = []
_player_pool_cache: PlayerPoolResponse | None = None
_player_pool_cached_at = 0.0
HAND_CACHE_KEY = "player_handedness"
PLAYER_DIRECTORY_KEY = "mlb_player_directory"
PLAYER_POOL_SNAPSHOT_PREFIX = "player_pool_snapshots"
MLB_TEAM_CODES = {
    108: "LAA", 109: "ARI", 110: "BAL", 111: "BOS", 112: "CHC",
    113: "CIN", 114: "CLE", 115: "COL", 116: "DET", 117: "HOU",
    118: "KCR", 119: "LAD", 120: "WAS", 121: "NYM", 133: "ATH",
    134: "PIT", 135: "SDP", 136: "SEA", 137: "SFG", 138: "STL",
    139: "TBR", 140: "TEX", 141: "TOR", 142: "MIN", 143: "PHI",
    144: "ATL", 145: "CHW", 146: "MIA", 147: "NYY", 158: "MIL",
}
# Scheduled refreshes bypass this cache and keep lineup data current. The longer
# request-path TTL prevents a visitor from paying for the slow MLB API fan-out.
PLAYER_POOL_CACHE_SECONDS = int(os.getenv("PLAYER_POOL_CACHE_SECONDS", "7200"))
PERSISTED_SNAPSHOT_MAX_AGE_SECONDS = int(
    os.getenv("PERSISTED_SNAPSHOT_MAX_AGE_SECONDS", "900")
)


def get_todays_games() -> list[GameSummary]:
    use_mock = os.getenv("USE_MOCK_DATA", "true").lower() == "true"
    if use_mock:
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


def get_player_pool_for_slate(site: str, slate_id: str) -> PlayerPoolResponse:
    normalized_site = site.strip().lower()
    if normalized_site not in {"dk", "fd"}:
        raise ValueError("site must be 'dk' or 'fd'")
    normalized_slate_id = re.sub(r"[^A-Za-z0-9_-]", "", slate_id)
    if not normalized_slate_id:
        raise ValueError("slate_id is required")

    now = datetime.now(UTC)
    target_date = date.today().isoformat()
    slate = load_salary_slate(normalized_site, target_date, normalized_slate_id)
    slate_stale = bool(slate.get("players")) and not _cache_is_recent_minutes(
        slate.get("last_updated"),
        now,
        minutes=max(1, int(os.getenv("DFF_REFRESH_MINUTES", "10"))),
    )
    if not slate.get("players"):
        slate = refresh_dff_slate(normalized_site, target_date, normalized_slate_id)
    salary_slates = {normalized_site: slate}

    use_mock = os.getenv("USE_MOCK_DATA", "true").lower() == "true"
    base_updated = now
    used_snapshot = False
    snapshot_stale = False
    if use_mock:
        games = mock_games()
        players = mock_players()
        warnings = ["Using mock data. Disable USE_MOCK_DATA for live production traffic."]
        data_status = "mock"
    else:
        snapshot = _load_player_pool_snapshot(target_date)
        if snapshot is not None:
            used_snapshot = True
            base_updated = snapshot.last_updated
            games = [game.model_copy(deep=True) for game in snapshot.games]
            players = [player.model_copy(deep=True) for player in snapshot.players]
            warnings = _selected_snapshot_warnings(snapshot.warnings)
            snapshot_stale = not _snapshot_is_fresh(snapshot, now)
            if snapshot_stale:
                age_minutes = max(
                    0,
                    int((now - _aware_datetime(snapshot.last_updated)).total_seconds() // 60),
                )
                warnings.append(
                    f"Player data snapshot is {age_minutes} minutes old; background refresh is pending."
                )
        else:
            games, players, warnings = _get_live_player_pool(now)
        if slate_stale:
            warnings.append(
                f"{normalized_site.upper()} salary data is older than the refresh target; "
                "background refresh is pending."
            )
        _add_salary_slate_candidates(players, games, now, salary_slates)
        _retain_salary_slate_players(players, target_date, salary_slates)
        salary_matches = apply_salary_slates(players, target_date, salary_slates)
        unavailable, injury_conflicts = _apply_injury_availability(players)
        if unavailable:
            warnings.append(f"Excluded {unavailable} unavailable players from the selected Slate.")
        if injury_conflicts:
            warnings.append(
                f"Kept {injury_conflicts} MLB-confirmed players despite conflicting injury labels."
            )
        if not salary_matches[normalized_site]:
            warnings.append(f"No {normalized_site.upper()} salaries matched the selected Slate.")

    slate_teams = {
        _team_key(item.get("team"))
        for item in slate.get("players", [])
        if item.get("team")
    }
    selected_games = [
        game
        for game in games
        if _team_key(game.away_team) in slate_teams or _team_key(game.home_team) in slate_teams
    ]
    update_dff_slate_membership(
        normalized_site,
        target_date,
        normalized_slate_id,
        teams=sorted(slate_teams),
        game_ids=[game.game_id for game in selected_games],
    )
    if not use_mock:
        data_status = _selected_slate_status(
            selected_games,
            players,
            warnings,
            normalized_site,
        )
        if used_snapshot and data_status == "live":
            data_status = "cached"
        if snapshot_stale and data_status == "cached":
            data_status = "partial"
    return PlayerPoolResponse(
        game_date=target_date,
        site=normalized_site,
        slate_key=f"dff:{normalized_site}:{normalized_slate_id}",
        last_updated=base_updated,
        data_status=data_status,
        warnings=warnings,
        changes=_snapshot_changes(None, players),
        games=selected_games,
        players=players,
        message=_selected_slate_message(
            selected_games,
            players,
            normalized_site,
            use_mock,
        ),
    )


def get_todays_player_pool(force_refresh: bool = False) -> PlayerPoolResponse:
    global _last_refresh_timestamp, _last_player_count, _last_data_status, _last_data_warnings
    global _player_pool_cache, _player_pool_cached_at
    if (
        not force_refresh
        and _player_pool_cache is not None
        and _player_pool_cache.game_date == date.today().isoformat()
        and time.monotonic() - _player_pool_cached_at < PLAYER_POOL_CACHE_SECONDS
    ):
        return _player_pool_cache.model_copy(deep=True)

    now = datetime.now(UTC)
    target_date = date.today().isoformat()
    if not force_refresh and _player_pool_cache is None:
        persisted = _load_player_pool_snapshot(target_date)
        if persisted is not None and _snapshot_is_fresh(persisted, now):
            persisted.data_status = "cached"
            _player_pool_cache = persisted
            _player_pool_cached_at = time.monotonic()
            _last_refresh_timestamp = persisted.last_updated
            _last_player_count = len(persisted.players)
            _last_data_status = persisted.data_status
            _last_data_warnings = persisted.warnings[:]
            return persisted.model_copy(deep=True)
    previous_snapshot = (
        _player_pool_cache
        if _player_pool_cache is not None and _player_pool_cache.game_date == target_date
        else _load_player_pool_snapshot(target_date)
    )
    use_mock = os.getenv("USE_MOCK_DATA", "true").lower() == "true"
    if use_mock:
        games = mock_games()
        players = mock_players()
        data_status = "mock"
        warnings = ["Using mock data. Disable USE_MOCK_DATA for live production traffic."]
    else:
        games, players, warnings = _get_live_player_pool(now)
        _add_salary_slate_candidates(players, games, now)
        _retain_salary_slate_players(players, target_date)
        unresolved_identities = sum(player.mlbam_id < 0 for player in players)
        if unresolved_identities:
            warnings.append(
                f"Excluded {unresolved_identities} slate players whose MLBAM identities could not be verified."
            )
        salary_matches = apply_salary_slates(players)
        unavailable, injury_conflicts = _apply_injury_availability(players)
        if unavailable:
            warnings.append(f"Excluded {unavailable} unavailable players from the default candidate pool.")
        if injury_conflicts:
            warnings.append(
                f"Kept {injury_conflicts} MLB-confirmed players despite conflicting injury labels."
            )
        changes = _apply_snapshot_transitions(
            previous_snapshot,
            games,
            players,
            now,
            warnings,
        )
        if players and not any(salary_matches.values()):
            warnings.append("No current DK/FD salary slate is available.")
        if players and os.getenv("ROTOWIRE_VALIDATION_ENABLED", "true").lower() == "true":
            try:
                validation = validate_with_rotowire(players)
                if validation["salary_conflicts"]:
                    warnings.append(
                        f"RotoWire validation found {validation['salary_conflicts']} DK salary conflicts "
                        f"across {validation['salary_checked']} checked players."
                    )
                if validation["batting_order_conflicts"] or validation["lineup_status_conflicts"]:
                    warnings.append(
                        "RotoWire lineup validation found "
                        f"{validation['batting_order_conflicts']} batting-order and "
                        f"{validation['lineup_status_conflicts']} status conflicts."
                    )
            except Exception:
                warnings.append("RotoWire validation was unavailable; primary player data was retained.")
        if not games:
            games = get_todays_games()
        data_status = _data_status(games, players, warnings)
    if use_mock:
        changes = _snapshot_changes(
            previous_snapshot,
            players,
        )
    _last_refresh_timestamp = now
    _last_player_count = len(players)
    _last_data_status = data_status
    _last_data_warnings = warnings
    response = PlayerPoolResponse(
        game_date=target_date,
        last_updated=now,
        data_status=data_status,
        warnings=warnings,
        changes=changes,
        games=games,
        players=players,
        message=_player_pool_message(games, players, use_mock),
    )
    _player_pool_cache = response
    _player_pool_cached_at = time.monotonic()
    _write_player_pool_snapshot(response)
    return response.model_copy(deep=True)


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
    try:
        _ensure_mlb_player_directory(statsapi, now)
    except Exception:
        warnings.append("MLB player identity directory refresh failed; cached identities were retained.")

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
        away_abbr = _team_key(team_info.get("away", {}).get("abbreviation") or away_team)
        home_abbr = _team_key(team_info.get("home", {}).get("abbreviation") or home_team)
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


def _add_salary_slate_candidates(
    players: list[Player],
    games: list[GameSummary],
    now: datetime,
    salary_slates: dict[str, dict[str, Any]] | None = None,
) -> int:
    """Create pre-lineup candidates from the cached public DK/FD slates."""
    target_date = date.today().isoformat()
    combined: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for site in ("dk", "fd"):
        slate = (
            salary_slates.get(site, {})
            if salary_slates is not None
            else load_salary_slate(site, target_date)
        )
        for item in slate.get("players", []):
            key = (_normalize_name(item.get("name")), _team_key(item.get("team")))
            if not all(key):
                continue
            combined.setdefault(key, {})[site] = item

    existing = {(_normalize_name(player.name), _team_key(player.team)) for player in players}
    season_ids = _season_player_ids()
    authoritative_identity_directory = _has_authoritative_identity_directory()
    contexts = _game_contexts(games)
    used_ids = {player.mlbam_id for player in players}
    added = 0
    for key, site_items in combined.items():
        if key in existing:
            continue
        dk = site_items.get("dk")
        fd = site_items.get("fd")
        source = dk or fd
        if source is None:
            continue
        team = _team_key(source.get("team"))
        context = contexts.get(team, {})
        positions = _candidate_positions(dk, fd)
        if not positions:
            continue
        projected_dk = _candidate_projection(dk, fd, target="dk")
        projected_fd = _candidate_projection(fd, dk, target="fd")
        if projected_dk <= 0 and projected_fd <= 0:
            continue
        mlbam_id = (
            season_ids.get(f"{key[0]}|{key[1]}")
            or season_ids.get(key[0])
            or _synthetic_player_id(key, used_ids)
        )
        used_ids.add(mlbam_id)
        source_statuses = {str(item.get("lineup_status") or "") for item in site_items.values()}
        lineup_status = "expected" if source_statuses & {"expected", "confirmed"} else "unconfirmed"
        if mlbam_id < 0 and authoritative_identity_directory:
            lineup_status = "dnp"
        batting_order = next(
            (
                int(item["batting_order"])
                for item in site_items.values()
                if item.get("batting_order")
            ),
            None,
        )
        injury_status = next(
            (str(item["injury_status"]) for item in site_items.values() if item.get("injury_status")),
            None,
        )
        opposing_pitcher = context.get("opposing_pitcher")
        players.append(
            Player(
                mlbam_id=mlbam_id,
                name=str(source.get("name") or ""),
                team=team,
                opponent=_team_key(source.get("opponent") or context.get("opponent")),
                position=positions,
                salary_dk=int(dk.get("salary") or 0) if dk else 0,
                salary_fd=int(fd.get("salary") or 0) if fd else 0,
                batting_order=batting_order,
                opposing_pitcher=opposing_pitcher.name if opposing_pitcher else None,
                opposing_pitcher_hand=opposing_pitcher.hand if opposing_pitcher else None,
                lineup_status=lineup_status,
                injury_status=injury_status,
                projected_dk=projected_dk,
                projected_fd=projected_fd,
                projection_source="daily_fantasy_fuel",
                last_15_avg_dk=float((dk or {}).get("last_10_avg") or projected_dk),
                vs_lhp_avg=projected_dk,
                vs_rhp_avg=projected_dk,
                last_updated=now,
            )
        )
        added += 1
    return added


def _retain_salary_slate_players(
    players: list[Player],
    game_date: str,
    salary_slates: dict[str, dict[str, Any]] | None = None,
) -> int:
    """Keep the DK/FD salary-slate union as the canonical DFS candidate pool."""
    slate_keys: set[tuple[str, str]] = set()
    for site in ("dk", "fd"):
        slate = (
            salary_slates.get(site, {})
            if salary_slates is not None
            else load_salary_slate(site, game_date)
        )
        slate_keys.update(
            {
                (_normalize_name(item.get("name")), _team_key(item.get("team")))
                for item in slate.get("players", [])
                if item.get("name") and item.get("team")
            }
        )
    if not slate_keys:
        return 0
    before = len(players)
    players[:] = [
        player
        for player in players
        if (_normalize_name(player.name), _team_key(player.team)) in slate_keys
    ]
    return before - len(players)


def _candidate_projection(
    primary: dict[str, Any] | None,
    fallback: dict[str, Any] | None,
    target: str,
) -> float:
    if primary:
        value = primary.get("projected_points")
        if value is not None:
            return max(0.0, float(value))
    if not fallback or fallback.get("projected_points") is None:
        return 0.0
    value = float(fallback["projected_points"])
    return max(0.0, value * (1.08 if target == "fd" else (1 / 1.08)))


def _candidate_positions(*items: dict[str, Any] | None) -> list[str]:
    positions: list[str] = []
    for item in items:
        for raw in (item or {}).get("positions") or []:
            position = str(raw).upper()
            if position in {"LF", "CF", "RF"}:
                position = "OF"
            elif position == "DH":
                position = "UTIL"
            if position and position not in positions:
                positions.append(position)
    return positions


def _season_player_ids() -> dict[str, int]:
    candidates: dict[str, list[int]] = {}
    directory = cache_store.read_json(PLAYER_DIRECTORY_KEY, default={})
    for item in directory.get("players", []) if isinstance(directory, dict) else []:
        _add_identity_candidate(candidates, item.get("fullName"), item.get("id"))
        team = MLB_TEAM_CODES.get(item.get("team_id"))
        if team:
            _add_identity_candidate(
                candidates,
                f"{_normalize_name(item.get('fullName'))}|{team}",
                item.get("id"),
                normalize=False,
            )
    for raw_id, item in load_season_splits().get("players", {}).items():
        _add_identity_candidate(candidates, item.get("name"), item.get("mlbam_id") or raw_id)
        if item.get("team"):
            _add_identity_candidate(
                candidates,
                f"{_normalize_name(item.get('name'))}|{_team_key(item.get('team'))}",
                item.get("mlbam_id") or raw_id,
                normalize=False,
            )
    return {name: ids[0] for name, ids in candidates.items() if len(set(ids)) == 1}


def _has_authoritative_identity_directory() -> bool:
    data = cache_store.read_json(PLAYER_DIRECTORY_KEY, default={})
    return isinstance(data, dict) and len(data.get("players", [])) >= 100


def _add_identity_candidate(
    candidates: dict[str, list[int]],
    raw_name: Any,
    raw_id: Any,
    normalize: bool = True,
) -> None:
    name = _normalize_name(raw_name) if normalize else str(raw_name or "")
    if not name:
        return
    try:
        mlbam_id = int(raw_id)
    except (TypeError, ValueError):
        return
    candidates.setdefault(name, []).append(mlbam_id)


def _ensure_mlb_player_directory(statsapi_module: object, now: datetime) -> dict[str, Any]:
    cached = cache_store.read_json(PLAYER_DIRECTORY_KEY, default={})
    if (
        isinstance(cached, dict)
        and cached.get("players")
        and cached.get("seasons") == [now.year, now.year - 1]
        and _cache_is_recent(cached.get("last_updated"), now, hours=24)
    ):
        return cached
    people: list[dict[str, Any]] = []
    for season in (now.year, now.year - 1):
        payload = statsapi_module.get(
            "sports_players",
            {"sportId": 1, "season": season},
        )
        if isinstance(payload, dict):
            people.extend(payload.get("people", []))
    unique_people = {int(person["id"]): person for person in people if person.get("id")}
    players = [
        {
            "id": int(person["id"]),
            "fullName": str(person.get("fullName") or ""),
            "active": bool(person.get("active", True)),
            "team_id": (person.get("currentTeam") or {}).get("id"),
            "position": (person.get("primaryPosition") or {}).get("abbreviation"),
        }
        for person in unique_people.values()
        if person.get("id") and person.get("fullName") and person.get("active", True)
    ]
    if not players:
        raise ValueError("MLB player directory contained no active players")
    data = {
        "last_updated": now.isoformat(),
        "seasons": [now.year, now.year - 1],
        "source": "MLB StatsAPI sports_players",
        "players": players,
    }
    cache_store.write_json(PLAYER_DIRECTORY_KEY, data)
    return data


def _cache_is_recent(value: Any, now: datetime, hours: int) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return now - parsed < timedelta(hours=hours)


def _cache_is_recent_minutes(value: Any, now: datetime, minutes: int) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return now - parsed < timedelta(minutes=minutes)


def _synthetic_player_id(key: tuple[str, str], used_ids: set[int]) -> int:
    digest = hashlib.sha256("|".join(key).encode("utf-8")).hexdigest()
    candidate = -(int(digest[:12], 16) + 1)
    while candidate in used_ids:
        candidate -= 1
    return candidate


def _game_contexts(games: list[GameSummary]) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for game in games:
        away = _team_key(game.away_team)
        home = _team_key(game.home_team)
        contexts[away] = {"opponent": home, "opposing_pitcher": game.home_starter}
        contexts[home] = {"opponent": away, "opposing_pitcher": game.away_starter}
    return contexts


def _apply_injury_availability(players: list[Player]) -> tuple[int, int]:
    unavailable = conflicts = 0
    for player in players:
        status = re.sub(r"[^A-Z0-9]+", " ", str(player.injury_status or "").upper()).strip()
        is_unavailable = (
            status in {"OUT", "DNP", "INACTIVE", "SUSPENDED", "SUSPENSION"}
            or " IL" in f" {status}"
            or status.startswith("IL ")
        )
        if not is_unavailable:
            continue
        if player.lineup_status == "confirmed":
            conflicts += 1
            continue
        player.lineup_status = "dnp"
        unavailable += 1
    return unavailable, conflicts


def _apply_snapshot_transitions(
    previous: PlayerPoolResponse | None,
    games: list[GameSummary],
    players: list[Player],
    now: datetime,
    warnings: list[str],
) -> dict[str, int]:
    if previous is None:
        return _snapshot_changes(None, players)
    confirmed_teams: set[str] = set()
    for game in games:
        if game.away_lineup_confirmed:
            confirmed_teams.add(_team_key(game.away_team))
        if game.home_lineup_confirmed:
            confirmed_teams.add(_team_key(game.home_team))
    current = {(_normalize_name(player.name), _team_key(player.team)): player for player in players}
    withdrawn = 0
    for old in previous.players:
        key = (_normalize_name(old.name), _team_key(old.team))
        if old.lineup_status != "confirmed" or key[1] not in confirmed_teams:
            continue
        new = current.get(key)
        if new is not None and new.lineup_status == "confirmed":
            continue
        if new is None:
            new = old.model_copy(deep=True)
            new.last_updated = now
            players.append(new)
            current[key] = new
        new.lineup_status = "dnp"
        withdrawn += 1
    if withdrawn:
        warnings.append(
            f"Marked {withdrawn} previously confirmed players DNP after a newer official team lineup omitted them."
        )
    return _snapshot_changes(previous, players)


def _snapshot_changes(
    previous: PlayerPoolResponse | None,
    players: list[Player],
) -> dict[str, int]:
    current = {(_normalize_name(player.name), _team_key(player.team)): player for player in players}
    if previous is None:
        return {
            "added": len(current),
            "removed": 0,
            "batting_order_changed": 0,
            "status_changed": 0,
        }
    old = {(_normalize_name(player.name), _team_key(player.team)): player for player in previous.players}
    shared = old.keys() & current.keys()
    return {
        "added": len(current.keys() - old.keys()),
        "removed": len(old.keys() - current.keys()),
        "batting_order_changed": sum(
            old[key].batting_order != current[key].batting_order for key in shared
        ),
        "status_changed": sum(old[key].lineup_status != current[key].lineup_status for key in shared),
    }


def _load_player_pool_snapshot(game_date: str) -> PlayerPoolResponse | None:
    if os.getenv("PERSIST_PLAYER_POOL_SNAPSHOTS", "true").lower() != "true":
        return None
    data = cache_store.read_json(f"{PLAYER_POOL_SNAPSHOT_PREFIX}/{game_date}", default=None)
    if not isinstance(data, dict):
        return None
    try:
        return PlayerPoolResponse.model_validate(data)
    except Exception:
        return None


def _selected_snapshot_warnings(warnings: list[str]) -> list[str]:
    """Drop all-day salary warnings that do not apply to one selected site/Slate."""
    salary_phrases = (
        "salary slate is available",
        "salary slate is unavailable",
        "salaries are available",
        "no current dk/fd salary",
    )
    return [
        warning
        for warning in warnings
        if not any(phrase in warning.lower() for phrase in salary_phrases)
    ]


def _aware_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _write_player_pool_snapshot(response: PlayerPoolResponse) -> None:
    if os.getenv("PERSIST_PLAYER_POOL_SNAPSHOTS", "true").lower() != "true":
        return
    cache_store.write_json(
        f"{PLAYER_POOL_SNAPSHOT_PREFIX}/{response.game_date}",
        response.model_dump(mode="json"),
    )


def _snapshot_is_fresh(response: PlayerPoolResponse, now: datetime) -> bool:
    updated = response.last_updated
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return timedelta(0) <= now - updated <= timedelta(
        seconds=PERSISTED_SNAPSHOT_MAX_AGE_SECONDS
    )


def _normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def _team_key(value: Any) -> str:
    team = str(value or "").strip().upper()
    return {
        "AZ": "ARI",
        "CWS": "CHW",
        "KC": "KCR",
        "OAK": "ATH",
        "SD": "SDP",
        "SF": "SFG",
        "TB": "TBR",
        "WSH": "WAS",
    }.get(team, team)


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
        projection_dk = get_pitcher_projection(
            starter.mlbam_id, site="dk", opposing_team=opponent
        )
        projection_fd = get_pitcher_projection(
            starter.mlbam_id, site="fd", opposing_team=opponent
        )
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
                pitcher_last_start_date=projection_dk["recent_usage"].get("last_start_date"),
                pitcher_days_rest=projection_dk["recent_usage"].get("days_rest"),
                pitcher_last_start_pitches=projection_dk["recent_usage"].get("last_start_pitches"),
                pitcher_avg_pitches_last_3=projection_dk["recent_usage"].get("avg_pitches_last_3"),
                pitcher_avg_innings_last_3=projection_dk["recent_usage"].get("avg_innings_last_3"),
                pitcher_workload_risk=projection_dk["recent_usage"].get("workload_risk"),
                pitcher_workload_factor=projection_dk["recent_usage"].get("workload_factor"),
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
    has_dk_salaries = any(player.salary_dk > 0 for player in players)
    has_fd_salaries = any(player.salary_fd > 0 for player in players)
    if not has_dk_salaries and not has_fd_salaries:
        return "Live lineups loaded, but no DK/FD salary slate is available."
    if not has_dk_salaries:
        return "FanDuel salaries are available; the DraftKings slate is unavailable."
    if not has_fd_salaries:
        return "DraftKings salaries are available; the FanDuel slate is unavailable."
    return None


def _selected_slate_message(
    games: list[GameSummary],
    players: list[Player],
    site: str,
    use_mock: bool,
) -> str | None:
    if not games:
        return "No games are available for the selected Slate."
    if use_mock:
        return None
    if not players:
        return "The selected Slate has no confirmed or expected players yet."
    salary_field = "salary_dk" if site == "dk" else "salary_fd"
    if not any(getattr(player, salary_field) > 0 for player in players):
        return f"No {site.upper()} salary data is available for the selected Slate."
    return None


def _selected_slate_status(
    games: list[GameSummary],
    players: list[Player],
    warnings: list[str],
    site: str,
) -> str:
    if warnings:
        return "partial" if games or players else "error"
    if not games:
        return "error"
    if not players:
        return "partial"
    salary_field = "salary_dk" if site == "dk" else "salary_fd"
    return "live" if any(getattr(player, salary_field) > 0 for player in players) else "partial"


def _data_status(games: list[GameSummary], players: list[Player], warnings: list[str]) -> str:
    if warnings:
        return "partial" if games or players else "error"
    if not games:
        return "error"
    if not players:
        return "partial"
    if not any(player.salary_dk > 0 for player in players) or not any(
        player.salary_fd > 0 for player in players
    ):
        return "partial"
    return "live"
