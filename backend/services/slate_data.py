from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from models.schemas import SlateListResponse, SlateSummary
from services.cache_store import cache_store
from services.provider_data import parse_dff_html, parse_dff_player_data, parse_dff_projection_html, parse_rotowire_html

logger = logging.getLogger(__name__)

SLATE_CACHE_PREFIX = "slates"
DFF_URLS = {"dk": "https://www.dailyfantasyfuel.com/mlb/", "fd": "https://www.dailyfantasyfuel.com/mlb/?platform=fd"}
DFF_PROJECTION_URLS = {
    "dk": "https://www.dailyfantasyfuel.com/mlb/projections/draftkings",
    "fd": "https://www.dailyfantasyfuel.com/mlb/projections/fanduel",
}
DFF_SLATE_INDEX_URL = "https://www.dailyfantasyfuel.com/data/slates/next/mlb/{site}?x=1"
ROTOWIRE_URL = "https://www.rotowire.com/baseball/daily-lineups.php"
ROTOWIRE_STATUS_KEY = "refresh_status/rotowire_validation"
ROTOWIRE_DETAIL_PREFIX = "sources/rotowire"
_rotowire_summary: dict[str, Any] | None = None
_rotowire_checked_at: datetime | None = None

TEAM_ALIASES = {
    "AZ": "ARI",
    "CWS": "CHW",
    "KC": "KCR",
    "LAA": "LAA",
    "LAD": "LAD",
    "NYM": "NYM",
    "NYY": "NYY",
    "OAK": "ATH",
    "SD": "SDP",
    "SF": "SFG",
    "TB": "TBR",
    "WSH": "WAS",
}


def refresh_salary_slates(game_date: str | None = None) -> dict[str, Any]:
    """Refresh configured DK/FD salary CSV feeds without blocking request traffic."""
    target_date = game_date or date.today().isoformat()
    result: dict[str, Any] = {}
    for site in ("dk", "fd"):
        url = os.getenv(f"{site.upper()}_SALARY_CSV_URL", "").strip()
        if not url:
            index: SlateListResponse | None = None
            try:
                index = get_dff_slates(site, target_date, force_refresh=True)
                result[f"{site}_slates"] = index.model_dump(mode="json")
            except Exception:
                logger.exception("failed to refresh Daily Fantasy Fuel %s slate index", site.upper())
            classic_details = (
                refresh_dff_classic_slates(site, target_date, index)
                if index is not None
                else {}
            )
            result[f"{site}_classic_slates"] = {
                slate_id: len(data.get("players", []))
                for slate_id, data in classic_details.items()
            }
            current = load_salary_slate(site, target_date)
            if current.get("players") and current.get("source") not in {"missing", "daily_fantasy_fuel"}:
                result[site] = current
                continue
            default_slate = (
                next((slate for slate in index.slates if slate.is_default), None)
                if index is not None
                else None
            )
            default_data = (
                classic_details.get(default_slate.provider_slate_id)
                if default_slate is not None
                else None
            )
            if default_data and default_data.get("players"):
                cache_store.write_json(_cache_key(site, target_date), default_data)
                _mark_default_dff_slate(
                    site,
                    target_date,
                    default_slate.provider_slate_id,
                )
                result[site] = default_data
                continue
            if current.get("source") == "daily_fantasy_fuel" and _is_fresh(
                current.get("last_updated"), int(os.getenv("DFF_REFRESH_MINUTES", "10"))
            ):
                result[site] = current
                continue
            try:
                result[site] = refresh_dff_slate(site, target_date)
            except Exception:
                logger.exception("failed to refresh Daily Fantasy Fuel %s slate", site.upper())
                result[site] = current
            continue
        try:
            request = Request(url, headers={"User-Agent": "LineupLab/0.1"})
            with urlopen(request, timeout=20) as response:
                csv_text = response.read().decode("utf-8-sig")
            result[site] = import_salary_csv(site, csv_text, target_date, source=url)
        except Exception:
            logger.exception("failed to refresh %s salary slate", site.upper())
            result[site] = load_salary_slate(site, target_date)
    return result


def refresh_dff_classic_slates(
    site: str,
    game_date: str,
    index: SlateListResponse,
) -> dict[str, dict[str, Any]]:
    """Warm every Classic Slate so user requests never need a DFF network fetch."""
    refresh_minutes = int(os.getenv("DFF_REFRESH_MINUTES", "10"))
    details: dict[str, dict[str, Any]] = {}
    for slate in index.slates:
        if slate.slate_type != "classic":
            continue
        cached = load_salary_slate(site, game_date, slate.provider_slate_id)
        if cached.get("players") and _is_fresh(cached.get("last_updated"), refresh_minutes):
            details[slate.provider_slate_id] = cached
            continue
        try:
            details[slate.provider_slate_id] = refresh_dff_slate(
                site,
                game_date,
                slate.provider_slate_id,
            )
        except Exception:
            logger.exception(
                "failed to warm DFF %s Classic Slate %s",
                site.upper(),
                slate.provider_slate_id,
            )
            if cached.get("players"):
                details[slate.provider_slate_id] = cached
    return details


def get_dff_slates(
    site: str,
    game_date: str | None = None,
    force_refresh: bool = False,
) -> SlateListResponse:
    normalized_site = _validate_site(site)
    target_date = game_date or date.today().isoformat()
    cached = load_dff_slate_index(normalized_site, target_date)
    if not force_refresh and cached.slates:
        return cached
    return refresh_dff_slate_index(normalized_site, target_date)


def refresh_dff_slate_index(
    site: str,
    game_date: str | None = None,
    fetcher: Any | None = None,
) -> SlateListResponse:
    normalized_site = _validate_site(site)
    target_date = game_date or date.today().isoformat()
    source_url = DFF_SLATE_INDEX_URL.format(site=normalized_site)
    if fetcher:
        payload = fetcher(source_url)
    else:
        request = Request(
            source_url,
            headers={"User-Agent": "LineupLab/0.1 (+public-data adapter)"},
        )
        with urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    if not isinstance(payload, list):
        raise ValueError("Daily Fantasy Fuel slate index was not a list")

    fetched_at = datetime.now(UTC)
    rows: list[tuple[int, SlateSummary]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        provider_id = str(item.get("url") or "").strip()
        if not provider_id:
            continue
        item_date, lock_time = _parse_dff_slate_start(
            str(item.get("start_string") or ""),
            target_date,
        )
        if item_date != target_date:
            continue
        name = str(item.get("slate_type") or "").strip()
        showdown = bool(_int_or_none(item.get("showdown_flag")) or 0)
        slate_type = "showdown" if showdown else ("tiers" if "tier" in name.lower() else "classic")
        game_count = _int_or_none(item.get("game_count")) or 0
        rank = _int_or_none(item.get("future_rank")) or 999
        rows.append(
            (
                rank,
                SlateSummary(
                    site=normalized_site,
                    slate_key=f"dff:{normalized_site}:{provider_id}",
                    provider="daily_fantasy_fuel",
                    provider_slate_id=provider_id,
                    name=name or f"All {game_count} Games",
                    slate_type=slate_type,
                    game_date=target_date,
                    start_time=str(item.get("start_string") or ""),
                    lock_time=lock_time,
                    game_count=game_count,
                    team_count=_int_or_none(item.get("team_count")) or 0,
                    is_default=False,
                    fetched_at=fetched_at,
                ),
            )
        )
    rows.sort(key=lambda value: (value[0], value[1].lock_time or fetched_at, value[1].name))
    slates = [slate for _, slate in rows]
    default = next((slate for slate in slates if slate.slate_type == "classic"), None)
    if default:
        default.is_default = True
    response = SlateListResponse(
        game_date=target_date,
        site=normalized_site,
        last_updated=fetched_at,
        slates=slates,
        warnings=[] if slates else ["Daily Fantasy Fuel returned no slates for the target date."],
    )
    cache_store.write_json(
        _slate_index_cache_key(normalized_site, target_date),
        response.model_dump(mode="json"),
    )
    return response


def load_dff_slate_index(site: str, game_date: str | None = None) -> SlateListResponse:
    normalized_site = _validate_site(site)
    target_date = game_date or date.today().isoformat()
    data = cache_store.read_json(_slate_index_cache_key(normalized_site, target_date))
    if isinstance(data, dict):
        try:
            return SlateListResponse.model_validate(data)
        except Exception:
            logger.exception("invalid cached DFF %s slate index", normalized_site.upper())
    return SlateListResponse(
        game_date=target_date,
        site=normalized_site,
        last_updated=datetime.fromtimestamp(0, UTC),
        slates=[],
        warnings=["No cached Daily Fantasy Fuel slate index is available."],
    )


def refresh_dff_slate(
    site: str,
    game_date: str | None = None,
    slate_id: str | None = None,
) -> dict[str, Any]:
    normalized_site = _validate_site(site)
    target_date = game_date or date.today().isoformat()
    requested_slate_id = str(slate_id or "").strip() or None
    html = ""
    slate_match = None
    players: list[dict[str, Any]] = []
    source_url = DFF_URLS[normalized_site]
    if requested_slate_id is None:
        request = Request(
            DFF_URLS[normalized_site],
            headers={"User-Agent": "LineupLab/0.1 (+public-data adapter)"},
        )
        with urlopen(request, timeout=25) as response:
            html = response.read().decode("utf-8", errors="replace")
        slate_match = re.search(r"window\.nexturl\s*=\s*['\"]([^'\"]+)['\"]", html)
        if slate_match:
            requested_slate_id = slate_match.group(1)
    if requested_slate_id:
        source_url = (
            "https://www.dailyfantasyfuel.com/data/playerdetails/mlb/"
            f"{normalized_site}/{requested_slate_id}?x=1"
        )
        data_request = Request(source_url, headers={"User-Agent": "LineupLab/0.1 (+public-data adapter)"})
        with urlopen(data_request, timeout=25) as response:
            players = parse_dff_player_data(json.loads(response.read().decode("utf-8", errors="replace")))
    if not players:
        players = parse_dff_html(html)
    if not players:
        raise ValueError("Daily Fantasy Fuel page contained no usable player rows")
    projection_enriched = 0
    projection_url = DFF_PROJECTION_URLS[normalized_site]
    if requested_slate_id:
        projection_url = f"{projection_url}?slate={requested_slate_id}"
    try:
        projection_request = Request(
            projection_url,
            headers={"User-Agent": "LineupLab/0.1 (+public-data adapter)"},
        )
        with urlopen(projection_request, timeout=25) as response:
            projection_players = parse_dff_projection_html(
                response.read().decode("utf-8", errors="replace")
            )
        projection_enriched = _merge_dff_projection_rows(players, projection_players)
    except Exception:
        logger.exception("failed to enrich DFF %s slate from projections page", normalized_site.upper())
    data = {
        "site": normalized_site,
        "slate_key": (
            f"dff:{normalized_site}:{requested_slate_id}" if requested_slate_id else None
        ),
        "provider_slate_id": requested_slate_id,
        "game_date": target_date,
        "last_updated": datetime.now(UTC).isoformat(),
        "source": "daily_fantasy_fuel",
        "source_url": source_url,
        "projection_source_url": projection_url,
        "projection_enriched_players": projection_enriched,
        "complete_public_slate": bool(requested_slate_id and len(players) > 20),
        "players": players,
    }
    if requested_slate_id:
        cache_store.write_json(
            _cache_key(normalized_site, target_date, requested_slate_id),
            data,
        )
        update_dff_slate_membership(
            normalized_site,
            target_date,
            requested_slate_id,
            teams=[
                str(player.get("team") or "")
                for player in players
                if player.get("team")
            ],
        )
    if slate_id is None:
        cache_store.write_json(_cache_key(normalized_site, target_date), data)
        _mark_default_dff_slate(normalized_site, target_date, requested_slate_id)
    return data


def update_dff_slate_membership(
    site: str,
    game_date: str,
    slate_id: str,
    *,
    teams: list[str] | None = None,
    game_ids: list[int] | None = None,
) -> None:
    """Enrich a cached DFF Slate after its player pool and MLB games are resolved."""
    response = load_dff_slate_index(site, game_date)
    changed = False
    for slate in response.slates:
        if slate.provider_slate_id != slate_id:
            continue
        if teams is not None:
            normalized_teams = sorted({_normalize_team(team) for team in teams if team})
            if slate.teams != normalized_teams:
                slate.teams = normalized_teams
                slate.team_count = len(normalized_teams)
                changed = True
        if game_ids is not None:
            normalized_game_ids = sorted({int(game_id) for game_id in game_ids})
            if slate.game_ids != normalized_game_ids:
                slate.game_ids = normalized_game_ids
                changed = True
        break
    if changed:
        cache_store.write_json(
            _slate_index_cache_key(_validate_site(site), game_date),
            response.model_dump(mode="json"),
        )


def _merge_dff_projection_rows(
    players: list[dict[str, Any]],
    projection_players: list[dict[str, Any]],
) -> int:
    by_id = {
        str(item.get("source_player_id")): item
        for item in projection_players
        if item.get("source_player_id")
    }
    by_name_team = {
        (_normalize_name(item.get("name")), _normalize_team(item.get("team"))): item
        for item in projection_players
    }
    fields = (
        "last_5_avg",
        "last_10_avg",
        "season_avg",
        "game_total",
        "implied_team_total",
        "spread",
        "start_date",
        "location",
    )
    enriched = 0
    for player in players:
        item = by_id.get(str(player.get("source_player_id") or ""))
        if item is None:
            item = by_name_team.get(
                (_normalize_name(player.get("name")), _normalize_team(player.get("team")))
            )
        if item is None:
            continue
        for field in fields:
            if item.get(field) is not None:
                player[field] = item[field]
        if not player.get("injury_status") and item.get("injury_status"):
            player["injury_status"] = item["injury_status"]
        enriched += 1
    return enriched


def import_salary_csv(
    site: str,
    csv_text: str,
    game_date: str | None = None,
    source: str = "operator_import",
) -> dict[str, Any]:
    normalized_site = _validate_site(site)
    target_date = game_date or date.today().isoformat()
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    players: list[dict[str, Any]] = []
    for row in reader:
        parsed = _parse_salary_row(normalized_site, row)
        if parsed:
            players.append(parsed)
    if not players:
        raise ValueError("salary CSV contained no usable player rows")
    data = {
        "site": normalized_site,
        "game_date": target_date,
        "last_updated": datetime.now(UTC).isoformat(),
        "source": source,
        "players": players,
    }
    cache_store.write_json(_cache_key(normalized_site, target_date), data)
    return data


def load_salary_slate(
    site: str,
    game_date: str | None = None,
    slate_id: str | None = None,
) -> dict[str, Any]:
    normalized_site = _validate_site(site)
    target_date = game_date or date.today().isoformat()
    data = cache_store.read_json(_cache_key(normalized_site, target_date, slate_id))
    if isinstance(data, dict):
        return data
    return {
        "site": normalized_site,
        "slate_key": f"dff:{normalized_site}:{slate_id}" if slate_id else None,
        "provider_slate_id": slate_id,
        "game_date": target_date,
        "last_updated": None,
        "source": "missing",
        "players": [],
    }


def apply_salary_slates(
    players: list[Any],
    game_date: str | None = None,
    salary_slates: dict[str, dict[str, Any]] | None = None,
) -> dict[str, int]:
    target_date = game_date or date.today().isoformat()
    matched = {"dk": 0, "fd": 0}
    for site in ("dk", "fd"):
        slate = (
            salary_slates.get(site, {})
            if salary_slates is not None
            else load_salary_slate(site, target_date)
        )
        by_key = {
            (_normalize_name(item.get("name")), _normalize_team(item.get("team"))): item
            for item in slate.get("players", [])
        }
        for player in players:
            item = by_key.get((_normalize_name(player.name), _normalize_team(player.team)))
            if not item:
                continue
            setattr(player, f"salary_{site}", int(item["salary"]))
            positions = item.get("positions") or []
            if positions:
                setattr(player, f"position_{site}", positions)
            setattr(player, f"external_id_{site}", item.get("external_id"))
            setattr(player, f"name_id_{site}", item.get("name_id"))
            setattr(player, f"salary_source_{site}", slate.get("source"))
            setattr(player, f"source_projection_{site}", item.get("projected_points"))
            setattr(player, f"source_l5_avg_{site}", item.get("last_5_avg"))
            setattr(player, f"source_l10_avg_{site}", item.get("last_10_avg"))
            setattr(player, f"source_season_avg_{site}", item.get("season_avg"))
            if item.get("game_total") is not None:
                player.source_game_total = item["game_total"]
            if item.get("implied_team_total") is not None:
                player.source_implied_team_total = item["implied_team_total"]
            if item.get("injury_status"):
                player.injury_status = item["injury_status"]
            if player.batting_order is None and item.get("batting_order"):
                player.batting_order = item["batting_order"]
            # DFF is a candidate/expected-lineup source. Only MLB's official
            # batting order may promote a player to confirmed.
            if player.lineup_status == "unconfirmed" and item.get("lineup_status") in {"expected", "confirmed"}:
                player.lineup_status = "expected"
            matched[site] += 1
    return matched


def validate_with_rotowire(players: list[Any]) -> dict[str, Any]:
    """Cross-check and persist the normalized public RotoWire lineup snapshot."""
    global _rotowire_summary, _rotowire_checked_at
    refresh_minutes = int(os.getenv("ROTOWIRE_REFRESH_MINUTES", "10"))
    if _rotowire_summary is not None and _rotowire_checked_at is not None:
        if datetime.now(UTC) - _rotowire_checked_at < timedelta(minutes=refresh_minutes):
            return dict(_rotowire_summary)
    request = Request(ROTOWIRE_URL, headers={"User-Agent": "LineupLab/0.1 (+validation adapter)"})
    with urlopen(request, timeout=25) as response:
        reference = parse_rotowire_html(response.read().decode("utf-8", errors="replace"))
    by_name = {_normalize_name(item.get("name")): item for item in reference}
    matched = salary_checked = salary_conflicts = order_conflicts = status_conflicts = 0
    for player in players:
        item = by_name.get(_normalize_name(player.name))
        if not item:
            continue
        matched += 1
        if item.get("salary_dk") and player.salary_dk:
            salary_checked += 1
            salary_conflicts += int(int(item["salary_dk"]) != int(player.salary_dk))
        if item.get("batting_order") and player.batting_order:
            order_conflicts += int(item["batting_order"] != player.batting_order)
        if item.get("lineup_status") in {"expected", "confirmed"} and player.lineup_status in {"expected", "confirmed"}:
            status_conflicts += int(item["lineup_status"] != player.lineup_status)
    summary = {
        "reference_players": len(reference),
        "matched": matched,
        "salary_checked": salary_checked,
        "salary_conflicts": salary_conflicts,
        "batting_order_conflicts": order_conflicts,
        "lineup_status_conflicts": status_conflicts,
    }
    _rotowire_summary = summary
    _rotowire_checked_at = datetime.now(UTC)
    cache_store.write_json(
        f"{ROTOWIRE_DETAIL_PREFIX}/{date.today().isoformat()}",
        {
            "game_date": date.today().isoformat(),
            "source": "rotowire_public_daily_lineups",
            "source_url": ROTOWIRE_URL,
            "fetched_at": _rotowire_checked_at.isoformat(),
            "summary": summary,
            "players": reference,
        },
    )
    cache_store.write_json(
        ROTOWIRE_STATUS_KEY,
        {**summary, "last_success": _rotowire_checked_at.isoformat()},
    )
    return dict(summary)


def _parse_salary_row(site: str, row: dict[str, str]) -> dict[str, Any] | None:
    name_id = _first(row, "Name + ID", "Name+ID")
    name = _first(row, "Name", "Nickname", "Player", "Player Name")
    if not name and name_id:
        name = re.sub(r"\s*\(\d+\)\s*$", "", name_id).strip()
    salary_raw = _first(row, "Salary")
    team = _first(row, "TeamAbbrev", "Team", "Team Abbrev")
    if not name or not salary_raw or not team:
        return None
    try:
        salary = int(float(salary_raw.replace("$", "").replace(",", "")))
    except ValueError:
        return None
    if salary <= 0:
        return None
    external_id = _first(row, "ID", "PlayerID", "Player ID")
    if not external_id and name_id:
        match = re.search(r"\((\d+)\)\s*$", name_id)
        external_id = match.group(1) if match else ""
    positions = _parse_positions(_first(row, "Roster Position", "RosterPosition", "Position"), site)
    return {
        "name": name,
        "team": team,
        "salary": salary,
        "positions": positions,
        "external_id": external_id or None,
        "name_id": name_id or (f"{name} ({external_id})" if external_id else None),
    }


def _parse_positions(value: str, site: str) -> list[str]:
    positions = []
    for raw in re.split(r"[/,]", value or ""):
        position = raw.strip().upper()
        if not position or position in {"UTIL", "C/1B"}:
            continue
        if position in {"LF", "CF", "RF"}:
            position = "OF"
        if position not in positions:
            positions.append(position)
    if site == "fd" and "C" in positions and "1B" not in positions:
        positions.append("1B")
    return positions


def _normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def _normalize_team(value: Any) -> str:
    team = str(value or "").strip().upper()
    return TEAM_ALIASES.get(team, team)


def _first(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _int_or_none(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _cache_key(site: str, game_date: str, slate_id: str | None = None) -> str:
    if slate_id:
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "", slate_id)
        return f"{SLATE_CACHE_PREFIX}/{game_date}/{site}/{safe_id}"
    return f"{SLATE_CACHE_PREFIX}/{game_date}_{site}"


def _slate_index_cache_key(site: str, game_date: str) -> str:
    return f"{SLATE_CACHE_PREFIX}/{game_date}/{site}/index"


def _mark_default_dff_slate(site: str, game_date: str, slate_id: str | None) -> None:
    if not slate_id:
        return
    index = load_dff_slate_index(site, game_date)
    changed = False
    for slate in index.slates:
        is_default = slate.provider_slate_id == slate_id
        changed = changed or slate.is_default != is_default
        slate.is_default = is_default
    if changed:
        index.last_updated = datetime.now(UTC)
        cache_store.write_json(
            _slate_index_cache_key(site, game_date),
            index.model_dump(mode="json"),
        )


def _parse_dff_slate_start(value: str, fallback_date: str) -> tuple[str, datetime | None]:
    fallback = date.fromisoformat(fallback_date)
    match = re.search(
        r"(?P<month>[A-Za-z]{3})\s+(?P<day>\d{1,2}),\s+"
        r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>AM|PM)\s*ET",
        value,
        re.I,
    )
    if not match:
        return fallback_date, None
    try:
        local = datetime.strptime(
            (
                f"{match.group('month')} {match.group('day')} {fallback.year} "
                f"{match.group('hour')}:{match.group('minute')} {match.group('ampm')}"
            ),
            "%b %d %Y %I:%M %p",
        ).replace(tzinfo=ZoneInfo("America/New_York"))
    except ValueError:
        return fallback_date, None
    return local.date().isoformat(), local.astimezone(UTC)


def _is_fresh(value: Any, minutes: int) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return datetime.now(UTC) - parsed < timedelta(minutes=max(1, minutes))


def _validate_site(site: str) -> str:
    normalized = site.strip().lower()
    if normalized not in {"dk", "fd"}:
        raise ValueError("site must be 'dk' or 'fd'")
    return normalized
