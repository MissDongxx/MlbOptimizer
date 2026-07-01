from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


Site = Literal["dk", "fd"]
LineupStatus = Literal["confirmed", "expected", "unconfirmed", "dnp"]
ProjectionSource = Literal[
    "15d_counts_cached_season_splits",
    "season_avg_fallback",
    "mock_projection",
    "user_override",
]


class Starter(BaseModel):
    name: str
    mlbam_id: int | None = None
    hand: Literal["L", "R"] | None = None


class LineupEntry(BaseModel):
    name: str
    mlbam_id: int
    batting_order: int | None = None
    position: str


class GameSummary(BaseModel):
    game_id: int
    game_time: str
    away_team: str
    home_team: str
    away_starter: Starter | None = None
    home_starter: Starter | None = None
    away_lineup_confirmed: bool = False
    home_lineup_confirmed: bool = False
    venue: str | None = None


class Player(BaseModel):
    mlbam_id: int
    name: str
    team: str
    opponent: str
    position: list[str]
    salary_dk: int
    salary_fd: int
    batting_order: int | None = None
    opposing_pitcher: str | None = None
    opposing_pitcher_hand: Literal["L", "R"] | None = None
    lineup_status: LineupStatus = "unconfirmed"
    projected_dk: float
    projected_fd: float
    projection_source: ProjectionSource
    last_15_avg_dk: float = 0
    vs_lhp_avg: float = 0
    vs_rhp_avg: float = 0
    last_updated: datetime


class PlayerPoolResponse(BaseModel):
    game_date: str
    last_updated: datetime
    games: list[GameSummary]
    players: list[Player]
    message: str | None = None


class PlayerInput(BaseModel):
    mlbam_id: int
    name: str
    team: str
    position: list[str]
    salary: int
    projected_points: float = Field(ge=0)
    lock: bool = False
    exclude: bool = False
    max_exposure: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("position")
    @classmethod
    def require_position(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("position must contain at least one roster position")
        return value


class OptimizerSettings(BaseModel):
    stack_team: str | None = None
    stack_count: int = Field(default=4, ge=0, le=6)
    pitcher_vs_batter_same_team: Literal["allow", "avoid"] = "avoid"
    min_salary_used: int = Field(default=49500, ge=0)
    unique_lineups: bool = True


class OptimizeRequest(BaseModel):
    site: Site
    num_lineups: int = Field(ge=1, le=20)
    players: list[PlayerInput]
    settings: OptimizerSettings


class LineupPlayer(BaseModel):
    mlbam_id: int
    name: str
    position_slot: str
    salary: int
    projected_points: float
    team: str


class Lineup(BaseModel):
    lineup_number: int
    players: list[LineupPlayer]
    total_salary: int
    projected_points: float


class OptimizeResponse(BaseModel):
    lineups: list[Lineup]
    solve_time_ms: int
    warnings: list[str] = []


class HealthResponse(BaseModel):
    status: str
    cache_age_seconds: int | None
    last_lineup_refresh: datetime | None
    players_loaded: int
