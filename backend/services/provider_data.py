from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any


class _DffParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.players: list[dict[str, Any]] = []
        self._row: dict[str, Any] | None = None
        self._row_depth = 0
        self._captures: list[tuple[str, int]] = []
        self._name_parts: list[str] = []
        self._row_text: list[str] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        classes = set(attrs.get("class", "").split())
        if self._row is None and tag == "li" and "row" in classes and attrs.get("data-player_id"):
            try:
                salary = int(attrs.get("data-salary", "0"))
            except ValueError:
                return
            self._row = {
                "name": "",
                "team": "",
                "opponent": "",
                "salary": salary,
                "positions": _positions(attrs.get("data-position", ""), attrs.get("data-position_alt", "")),
                "source_player_id": attrs["data-player_id"],
                "projected_points": None,
                "batting_order": None,
                "lineup_status": "unconfirmed",
                "hand": None,
                "value": None,
            }
            self._row_depth = 1
            self._name_parts = []
            self._row_text = []
            return
        if self._row is None:
            return
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self._row_depth += 1
        if tag == "img":
            match = re.search(r"/logos/mlb/([A-Z]+)\.svg", attrs.get("src", ""), re.I)
            if match:
                self._row["team"] = match.group(1).upper()
        if tag == "input" and "optimizer-edit-inline" in classes:
            self._row["projected_points"] = _float_or_none(attrs.get("value"))
        if "mobileOrder" in classes:
            self._captures.append(("order", self._row_depth))
        if tag == "span" and "player-val" in classes:
            self._captures.append(("value", self._row_depth))
        if tag == "span" and {"bold-sm", "bold-md"}.issubset(classes) and "hidden" not in classes:
            self._captures.append(("name", self._row_depth))
        title = attrs.get("title", "").lower()
        if "confirmed starter" in title:
            self._row["lineup_status"] = "confirmed"
        elif "expected starter" in title and self._row["lineup_status"] != "confirmed":
            self._row["lineup_status"] = "expected"

    def handle_data(self, data: str) -> None:
        if self._row is None:
            return
        text = " ".join(data.split())
        if not text:
            return
        self._row_text.append(text)
        if self._captures:
            kind, _ = self._captures[-1]
            if kind == "name":
                self._name_parts.append(text)
            elif kind == "order" and text.isdigit():
                self._row["batting_order"] = int(text)
            elif kind == "value":
                self._row["value"] = _float_or_none(text)

    def handle_endtag(self, tag: str) -> None:
        if self._row is None:
            return
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            return
        if self._captures and self._captures[-1][1] == self._row_depth:
            self._captures.pop()
        self._row_depth -= 1
        if self._row_depth:
            return
        text = " ".join(self._row_text)
        self._row["name"] = " ".join(dict.fromkeys(self._name_parts)).strip()
        hand = re.search(r"[•·]?\s*\(([LRS])\)", text)
        if hand:
            self._row["hand"] = hand.group(1)
        matchup = re.search(r"(?:@|vs\.?)\s+([A-Z]{2,3})\b", text, re.I)
        if matchup:
            self._row["opponent"] = matchup.group(1).upper()
        if self._row["name"] and self._row["team"] and self._row["salary"] > 0:
            self.players.append(self._row)
        self._row = None


class _DffProjectionParser(HTMLParser):
    """Parse the public player rows rendered on DFF's projections page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.players: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        classes = set(attrs.get("class", "").split())
        if tag != "tr" or "projections-listing" not in classes or not attrs.get("data-player_id"):
            return
        name = attrs.get("data-name", "").strip()
        team = attrs.get("data-team", "").strip().upper()
        salary = _int_or_none(attrs.get("data-salary"))
        if not name or not team or not salary or salary <= 0:
            return
        position = attrs.get("data-pos", "")
        depth_rank = _int_or_none(attrs.get("data-depth_rank"))
        starter_flag = _int_or_none(attrs.get("data-starter_flag"))
        lineup_status = "confirmed" if starter_flag == 1 else "unconfirmed"
        if lineup_status == "unconfirmed" and position.upper() != "P" and depth_rank and depth_rank >= 1:
            lineup_status = "expected"
        self.players.append(
            {
                "name": name,
                "team": team,
                "opponent": attrs.get("data-opp", "").strip().upper(),
                "salary": salary,
                "positions": _positions(position, attrs.get("data-pos_alt", "")),
                "source_player_id": attrs["data-player_id"],
                "projected_points": _float_or_none(attrs.get("data-ppg_proj")),
                "batting_order": depth_rank if position.upper() != "P" and depth_rank and depth_rank >= 1 else None,
                "lineup_status": lineup_status,
                "hand": attrs.get("data-hand", "").strip().upper()[:1] or None,
                "value": _float_or_none(attrs.get("data-value_proj")),
                "injury_status": attrs.get("data-inj", "").strip() or None,
                "last_5_avg": _float_or_none(attrs.get("data-l5_avg")),
                "last_10_avg": _float_or_none(attrs.get("data-l10_avg")),
                "season_avg": _float_or_none(attrs.get("data-szn_avg")),
                "game_total": _float_or_none(attrs.get("data-ou")),
                "implied_team_total": _float_or_none(attrs.get("data-proj_score")),
                "spread": _float_or_none(attrs.get("data-spread")),
                "start_date": attrs.get("data-start_date", "").strip() or None,
                "location": attrs.get("data-loc", "").strip() or None,
            }
        )


class _RotoWireParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.players: list[dict[str, Any]] = []
        self._team = ""
        self._game_teams: list[str] = []
        self._status = "unconfirmed"
        self._order = 0
        self._player: dict[str, Any] | None = None
        self._capture = ""
        self._pending: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        classes = set(attrs.get("class", "").split())
        if tag == "div" and "lineup__abbr" in classes:
            self._capture = "team_abbr"
        elif tag == "ul" and "lineup__list" in classes:
            team_index = 0 if "is-visit" in classes else 1
            self._team = self._game_teams[team_index] if len(self._game_teams) > team_index else ""
            self._status = "unconfirmed"
            self._order = 0
            self._capture = "team_from_ul"
        elif tag == "li" and "lineup__status" in classes:
            self._status = "confirmed" if "is-confirmed" in classes else "expected"
        elif tag == "li" and "lineup__player" in classes:
            self._order += 1
            self._player = {"team": self._team, "batting_order": self._order, "position": "", "name": "", "hand": None, "salary_dk": None, "lineup_status": self._status}
        elif self._player is not None and tag == "div" and "lineup__pos" in classes:
            self._capture = "position"
        elif self._player is not None and tag == "a" and attrs.get("title"):
            self._player["name"] = attrs["title"].strip()
        elif self._player is not None and tag == "span" and "lineup__bats" in classes:
            self._capture = "hand"
        elif tag == "li" and "salaries" in classes and self._pending is not None:
            self._capture = "salary"

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._capture == "team_abbr":
            if len(self._game_teams) >= 2:
                self._game_teams = []
            self._game_teams.append(text.upper())
        elif self._capture == "position" and self._player is not None:
            self._player["position"] = text
        elif self._capture == "hand" and self._player is not None:
            self._player["hand"] = text[:1]
        elif self._capture == "salary" and self._pending is not None:
            digits = re.sub(r"\D", "", text)
            self._pending["salary_dk"] = int(digits) if digits else None

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self._player is not None:
            if self._player["name"]:
                self.players.append(self._player)
                self._pending = self._player
            self._player = None
        if tag in {"div", "span", "li"}:
            self._capture = ""


def parse_dff_html(html: str) -> list[dict[str, Any]]:
    parser = _DffParser()
    parser.feed(html)
    return parser.players


def parse_dff_player_data(data: Any) -> list[dict[str, Any]]:
    """Normalize the public JSON used by DFF's “Show all players” interaction."""
    if not isinstance(data, list):
        return []
    players: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = " ".join(
            part.strip() for part in (str(item.get("first_name") or ""), str(item.get("last_name") or "")) if part.strip()
        )
        team = str(item.get("team") or "").strip().upper()
        salary = _int_or_none(item.get("salary"))
        if not name or not team or not salary or salary <= 0:
            continue
        depth_rank = _int_or_none(item.get("depth_rank"))
        starter_flag = _int_or_none(item.get("starter_flag"))
        probable_flag = _int_or_none(item.get("probable_flag"))
        position = str(item.get("position_code") or item.get("position_detailed") or "")
        lineup_status = "unconfirmed"
        if starter_flag == 1:
            lineup_status = "confirmed"
        elif probable_flag == 1 or (position != "P" and depth_rank is not None and depth_rank >= 1):
            lineup_status = "expected"
        players.append(
            {
                "name": name,
                "team": team,
                "opponent": str(item.get("opp") or "").strip().upper(),
                "salary": salary,
                "positions": _positions(position, str(item.get("position_code_alt") or "")),
                "source_player_id": str(item.get("player_id") or "") or None,
                "projected_points": _float_or_none(item.get("ppg")),
                "batting_order": depth_rank if position != "P" and depth_rank and depth_rank >= 1 else None,
                "lineup_status": lineup_status,
                "hand": str(item.get("hand") or "").strip().upper()[:1] or None,
                "value": _float_or_none(item.get("value")),
                "injury_status": str(item.get("injury_status") or "").strip() or None,
                "injury_detail": str(item.get("inj_det") or "").strip() or None,
                "days_rest": _int_or_none(item.get("days_rest")),
                "opponent_rank": _int_or_none(item.get("opp_rank")),
                "starter_flag": starter_flag,
                "probable_flag": probable_flag,
            }
        )
    return players


def parse_dff_projection_html(html: str) -> list[dict[str, Any]]:
    parser = _DffProjectionParser()
    parser.feed(html)
    return parser.players


def parse_rotowire_html(html: str) -> list[dict[str, Any]]:
    """Parse public lineup facts. Callers should retain only aggregate validation results."""
    parser = _RotoWireParser()
    parser.feed(html)
    return parser.players


def _positions(*values: str) -> list[str]:
    result: list[str] = []
    for value in values:
        for raw in re.split(r"[/,]", value):
            position = raw.strip().upper()
            if position in {"LF", "CF", "RF"}:
                position = "OF"
            if position and position not in result:
                result.append(position)
    return result


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
