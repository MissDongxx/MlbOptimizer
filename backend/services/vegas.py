from __future__ import annotations

import json
import logging
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from services.cache_store import cache_store

logger = logging.getLogger(__name__)

VEGAS_LINES_KEY = "vegas_lines"

MLB_AVERAGE_IMPLIED_RUNS = 4.4
TEAM_ABBREVIATIONS = {
    "Arizona Diamondbacks": "ARI",
    "Athletics": "ATH",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Oakland Athletics": "OAK",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}


def refresh_vegas_lines(
    game_date: str | None = None,
    api_key: str | None = None,
    fetcher: Any | None = None,
) -> dict[str, Any]:
    key = api_key if api_key is not None else os.getenv("ODDS_API_KEY")
    if not key:
        return load_vegas_lines()

    target_date = game_date or date.today().isoformat()
    events = _fetch_odds_api_events(target_date, key, fetcher=fetcher)
    data = _build_vegas_cache(events, target_date)
    write_vegas_lines(data)
    return data


def load_vegas_lines() -> dict[str, Any]:
    data = cache_store.read_json(VEGAS_LINES_KEY)
    if data is None:
        return _empty_cache()
    if not isinstance(data, dict):
        logger.error("vegas_lines.json is invalid; using neutral fallback")
        return _empty_cache()
    return data


def write_vegas_lines(data: dict[str, Any]) -> None:
    cache_store.write_json(VEGAS_LINES_KEY, data)


def get_team_vegas_context(team: str | None) -> dict[str, Any]:
    if not team:
        return _neutral_team_context()
    cache = load_vegas_lines()
    context = cache.get("teams", {}).get(_normalize_team_key(team))
    if not context:
        return _neutral_team_context()
    return context


def vegas_team_multiplier(team: str | None) -> float:
    context = get_team_vegas_context(team)
    return float(context.get("multiplier", 1.0) or 1.0)


def _fetch_odds_api_events(game_date: str, api_key: str, fetcher: Any | None = None) -> list[dict[str, Any]]:
    start = datetime.fromisoformat(game_date).replace(tzinfo=UTC)
    end = start + timedelta(days=1)
    params = {
        "apiKey": api_key,
        "regions": os.getenv("ODDS_API_REGIONS", "us"),
        "markets": "spreads,totals",
        "oddsFormat": "american",
        "dateFormat": "iso",
        "commenceTimeFrom": start.isoformat().replace("+00:00", "Z"),
        "commenceTimeTo": end.isoformat().replace("+00:00", "Z"),
    }
    bookmakers = os.getenv("ODDS_API_BOOKMAKERS", "").strip()
    if bookmakers:
        params["bookmakers"] = bookmakers
    url = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/?{urlencode(params)}"
    if fetcher:
        return fetcher(url)

    request = Request(url, headers={"User-Agent": "LineupLab/0.1"})
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _build_vegas_cache(events: list[dict[str, Any]], game_date: str) -> dict[str, Any]:
    teams: dict[str, dict[str, Any]] = {}
    games = []
    for event in events:
        home_team = str(event.get("home_team") or "")
        away_team = str(event.get("away_team") or "")
        home_abbr = _team_abbreviation(home_team)
        away_abbr = _team_abbreviation(away_team)
        total = _average_market_point(event, "totals")
        home_spread = _average_spread_point(event, home_team)
        if total is None:
            continue
        if home_spread is None:
            home_implied = away_implied = total / 2
        else:
            home_implied = (total / 2) - (home_spread / 2)
            away_implied = total - home_implied

        for abbr, implied_runs, raw_name in (
            (home_abbr, home_implied, home_team),
            (away_abbr, away_implied, away_team),
        ):
            if not abbr:
                continue
            teams[abbr] = {
                "team": abbr,
                "team_name": raw_name,
                "implied_runs": round(implied_runs, 2),
                "multiplier": implied_runs_multiplier(implied_runs),
                "source": "the_odds_api",
            }
        games.append(
            {
                "event_id": event.get("id"),
                "commence_time": event.get("commence_time"),
                "home_team": home_abbr or home_team,
                "away_team": away_abbr or away_team,
                "total": round(total, 2),
                "home_spread": round(home_spread, 2) if home_spread is not None else None,
            }
        )
    return {
        "last_updated": datetime.now(UTC).isoformat(),
        "game_date": game_date,
        "source": "the_odds_api",
        "teams": teams,
        "games": games,
    }


def implied_runs_multiplier(implied_runs: float) -> float:
    adjustment = ((implied_runs - MLB_AVERAGE_IMPLIED_RUNS) / MLB_AVERAGE_IMPLIED_RUNS) * 0.35
    return round(_clamp(1 + adjustment, 0.88, 1.12), 3)


def _average_market_point(event: dict[str, Any], market_key: str) -> float | None:
    points = []
    for market in _markets(event, market_key):
        for outcome in market.get("outcomes", []):
            point = _float_value(outcome.get("point"))
            if point is not None:
                points.append(point)
    return sum(points) / len(points) if points else None


def _average_spread_point(event: dict[str, Any], team_name: str) -> float | None:
    points = []
    normalized_team = _normalize_name(team_name)
    for market in _markets(event, "spreads"):
        for outcome in market.get("outcomes", []):
            if _normalize_name(outcome.get("name")) != normalized_team:
                continue
            point = _float_value(outcome.get("point"))
            if point is not None:
                points.append(point)
    return sum(points) / len(points) if points else None


def _markets(event: dict[str, Any], market_key: str) -> list[dict[str, Any]]:
    markets = []
    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") == market_key:
                markets.append(market)
    return markets


def _team_abbreviation(team_name: str) -> str | None:
    return TEAM_ABBREVIATIONS.get(team_name)


def _normalize_team_key(team: str) -> str:
    if team in set(TEAM_ABBREVIATIONS.values()):
        return team
    return TEAM_ABBREVIATIONS.get(team, team)


def _normalize_name(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _float_value(value: Any) -> float | None:
    if value is None or value != value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _neutral_team_context() -> dict[str, Any]:
    return {
        "implied_runs": None,
        "multiplier": 1.0,
        "source": "neutral_default",
    }


def _empty_cache() -> dict[str, Any]:
    return {
        "last_updated": None,
        "source": "neutral_default",
        "teams": {},
        "games": [],
    }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
