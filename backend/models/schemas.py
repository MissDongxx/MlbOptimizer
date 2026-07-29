from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


Site = Literal["dk", "fd"]
LineupStatus = Literal["confirmed", "expected", "unconfirmed", "dnp"]
DataStatus = Literal["live", "cached", "partial", "mock", "error"]
SlateType = Literal["classic", "showdown", "tiers", "unknown"]
ProjectionSource = Literal[
    "15d_counts_cached_season_splits",
    "season_with_15d_form_blend",
    "season_avg_fallback",
    "pitcher_season_rates",
    "daily_fantasy_fuel",
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


class SlateSummary(BaseModel):
    site: Site
    slate_key: str
    provider: str
    provider_slate_id: str
    name: str
    slate_type: SlateType = "unknown"
    game_date: str
    start_time: str
    lock_time: datetime | None = None
    game_count: int = 0
    team_count: int = 0
    game_ids: list[int] = Field(default_factory=list)
    teams: list[str] = Field(default_factory=list)
    is_default: bool = False
    fetched_at: datetime


class SlateListResponse(BaseModel):
    game_date: str
    site: Site
    last_updated: datetime
    slates: list[SlateSummary]
    warnings: list[str] = Field(default_factory=list)


class Player(BaseModel):
    mlbam_id: int
    name: str
    team: str
    opponent: str
    position: list[str]
    position_dk: list[str] | None = None
    position_fd: list[str] | None = None
    salary_dk: int
    salary_fd: int
    external_id_dk: str | None = None
    external_id_fd: str | None = None
    name_id_dk: str | None = None
    name_id_fd: str | None = None
    salary_source_dk: str | None = None
    salary_source_fd: str | None = None
    source_projection_dk: float | None = None
    source_projection_fd: float | None = None
    source_l5_avg_dk: float | None = None
    source_l5_avg_fd: float | None = None
    source_l10_avg_dk: float | None = None
    source_l10_avg_fd: float | None = None
    source_season_avg_dk: float | None = None
    source_season_avg_fd: float | None = None
    source_game_total: float | None = None
    source_implied_team_total: float | None = None
    injury_status: str | None = None
    pitcher_last_start_date: str | None = None
    pitcher_days_rest: int | None = None
    pitcher_last_start_pitches: int | None = None
    pitcher_avg_pitches_last_3: float | None = None
    pitcher_avg_innings_last_3: float | None = None
    pitcher_workload_risk: Literal["low", "medium", "high", "unknown"] | None = None
    pitcher_workload_factor: float | None = None
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
    site: Site | None = None
    slate_key: str | None = None
    last_updated: datetime
    data_status: DataStatus = "live"
    warnings: list[str] = []
    changes: dict[str, int] = Field(default_factory=dict)
    games: list[GameSummary]
    players: list[Player]
    message: str | None = None


class PlayerInput(BaseModel):
    mlbam_id: int
    name: str
    team: str
    opponent: str | None = None
    position: list[str]
    salary: int
    projected_points: float = Field(ge=0)
    lock: bool = False
    exclude: bool = False
    max_exposure: float = Field(default=1.0, ge=0.0, le=1.0)
    lineup_status: LineupStatus | None = None
    external_id: str | None = None
    name_id: str | None = None

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
    seed: int = 0


class LineupPlayer(BaseModel):
    mlbam_id: int
    name: str
    position_slot: str
    salary: int
    projected_points: float
    team: str
    external_id: str | None = None
    name_id: str | None = None


class Lineup(BaseModel):
    lineup_number: int
    players: list[LineupPlayer]
    total_salary: int
    projected_points: float


class OptimizeResponse(BaseModel):
    lineups: list[Lineup]
    solve_time_ms: int
    warnings: list[str] = []
    method: Literal["optimized", "random", "legacy"] | None = None
    seed: int | None = None


class HealthResponse(BaseModel):
    status: str
    app_env: str
    use_mock_data: bool
    data_status: DataStatus
    data_warnings: list[str] = []
    cache_age_seconds: int | None
    season_cache_exists: bool
    season_cache_age_hours: float | None
    season_cache_players: int
    last_lineup_refresh: datetime | None
    players_loaded: int
    statsapi_available: bool
    refresh_worker_enabled: bool = False
    refresh_in_progress: bool = False
    refresh_status: dict[str, object] = Field(default_factory=dict)


class ContactRequest(BaseModel):
    email: EmailStr
    message: str | None = Field(default=None, max_length=2000)
    company: str | None = Field(default=None, max_length=120)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        return trimmed or None


class ContactResponse(BaseModel):
    ok: bool
    message: str
