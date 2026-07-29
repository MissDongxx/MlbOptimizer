from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal


DK_MLB_CLASSIC_RULES_VERSION = "draftkings-mlb-classic-rules-json-2026-07-29"


@dataclass(frozen=True)
class HitterGameStats:
    mlbam_id: int
    game_id: int
    hits: int = 0
    doubles: int = 0
    triples: int = 0
    home_runs: int = 0
    runs: int = 0
    rbi: int = 0
    walks: int = 0
    hit_by_pitch: int = 0
    stolen_bases: int = 0

    def validate(self) -> None:
        values = vars(self)
        for name, value in values.items():
            if name in {"mlbam_id", "game_id"}:
                continue
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        singles = self.hits - self.doubles - self.triples - self.home_runs
        if singles < 0:
            raise ValueError("hits cannot be lower than doubles + triples + home_runs")


@dataclass(frozen=True)
class PitcherGameStats:
    mlbam_id: int
    game_id: int
    outs_recorded: int = 0
    strikeouts: int = 0
    win: bool = False
    earned_runs: int = 0
    hits_allowed: int = 0
    walks_allowed: int = 0
    hit_batters: int = 0
    complete_game: bool = False
    complete_game_shutout: bool = False
    no_hitter: bool = False

    def validate(self) -> None:
        for name in (
            "outs_recorded",
            "strikeouts",
            "earned_runs",
            "hits_allowed",
            "walks_allowed",
            "hit_batters",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.complete_game_shutout and not self.complete_game:
            raise ValueError("complete_game_shutout requires complete_game")
        if self.no_hitter and not self.complete_game:
            raise ValueError("no_hitter requires complete_game")
        if self.complete_game_shutout and self.earned_runs != 0:
            raise ValueError("complete_game_shutout requires zero earned runs")
        if self.no_hitter and self.hits_allowed != 0:
            raise ValueError("no_hitter requires zero hits allowed")


PlayerRole = Literal["hitter", "pitcher"]


def score_hitter_game(stats: HitterGameStats) -> float:
    stats.validate()
    singles = stats.hits - stats.doubles - stats.triples - stats.home_runs
    score = (
        singles * 3
        + stats.doubles * 5
        + stats.triples * 8
        + stats.home_runs * 10
        + stats.rbi * 2
        + stats.runs * 2
        + stats.walks * 2
        + stats.hit_by_pitch * 2
        + stats.stolen_bases * 5
    )
    return float(score)


def score_pitcher_game(stats: PitcherGameStats) -> float:
    stats.validate()
    score = (
        stats.outs_recorded * 0.75
        + stats.strikeouts * 2
        + (4 if stats.win else 0)
        - stats.earned_runs * 2
        - stats.hits_allowed * 0.6
        - stats.walks_allowed * 0.6
        - stats.hit_batters * 0.6
        + (2.5 if stats.complete_game else 0)
        + (2.5 if stats.complete_game_shutout else 0)
        + (5 if stats.no_hitter else 0)
    )
    return round(score, 10)


def aggregate_player_score(
    *,
    role: PlayerRole,
    hitter_games: Iterable[HitterGameStats] = (),
    pitcher_games: Iterable[PitcherGameStats] = (),
) -> float:
    """Aggregate per-game scoring while keeping DK bonus categories game-scoped."""
    if role == "hitter":
        return round(sum(score_hitter_game(item) for item in hitter_games), 10)
    if role == "pitcher":
        return round(sum(score_pitcher_game(item) for item in pitcher_games), 10)
    raise ValueError(f"Unsupported role: {role}")
