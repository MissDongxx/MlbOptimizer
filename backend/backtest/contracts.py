from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.schemas import OptimizerSettings, PlayerInput, Site


PROHIBITED_FEATURE_KEYS = {
    "actual_points",
    "actual_dk_points",
    "actual_fd_points",
    "final_score",
    "game_result",
    "box_score",
    "postgame",
    "post_game",
    "winner",
    "outcome",
}
PROHIBITED_KEY_TOKENS = {"actual", "final", "result", "outcome", "winner", "postgame", "boxscore"}
AMBIGUOUS_PROJECTION_SOURCES = {"draftkings_export_avg_points_per_game", "avg_points_per_game"}
DataKind = Literal["real", "fixture", "synthetic"]
SourceRole = Literal[
    "platform_slate_snapshot",
    "platform_salary_snapshot",
    "pregame_mlb_stats",
    "pregame_platform_projection",
    "other_pregame",
]
TimestampBasis = Literal[
    "source_payload",
    "http_last_modified",
    "archive_capture",
    "platform_export_metadata",
    "repository_commit",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return value


def _is_prohibited_feature_key(key: object) -> bool:
    text = str(key).strip().lower()
    if text in PROHIBITED_FEATURE_KEYS:
        return True
    normalized = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    compact = normalized.replace("_", "")
    tokens = set(normalized.split("_"))
    return bool(tokens.intersection(PROHIBITED_KEY_TOKENS)) or any(
        fragment in compact for fragment in ("actualpoints", "finalscore", "gameresult", "boxscore")
    )


class SourceTimestamp(StrictModel):
    source: str = Field(min_length=1)
    fetched_at: datetime
    published_at: datetime | None = None
    source_record_id: str | None = None
    role: SourceRole | None = None
    artifact_id: str | None = None
    source_url: str | None = None
    raw_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    available_at: datetime | None = None
    retrieved_at: datetime | None = None
    timestamp_basis: TimestampBasis | None = None

    @field_validator("fetched_at", "published_at", "available_at", "retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime | None, info: Any) -> datetime | None:
        if value is None:
            return None
        return _require_aware(value, info.field_name)


class SlateGame(StrictModel):
    game_id: int
    away_team: str = Field(min_length=2)
    home_team: str = Field(min_length=2)
    scheduled_start: datetime
    source_record_id: str = Field(min_length=1)

    @field_validator("scheduled_start")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        return _require_aware(value, "scheduled_start")

    @model_validator(mode="after")
    def reject_same_team(self) -> SlateGame:
        if self.away_team == self.home_team:
            raise ValueError("away_team and home_team must differ")
        return self


class FrozenPlayer(PlayerInput):
    availability: Literal["active", "expected", "confirmed", "unconfirmed", "dnp"]
    batting_order: int | None = Field(default=None, ge=1, le=9)
    projection_source: str = Field(min_length=1)
    feature_values: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    game_id: int | None = None

    @field_validator("feature_values")
    @classmethod
    def reject_postgame_feature_names(
        cls, value: dict[str, float | int | str | bool | None]
    ) -> dict[str, float | int | str | bool | None]:
        prohibited = sorted(key for key in value if _is_prohibited_feature_key(key))
        if prohibited:
            raise ValueError(f"post-game feature keys are prohibited: {prohibited}")
        return value

    @model_validator(mode="after")
    def enforce_availability_consistency(self) -> FrozenPlayer:
        if self.availability in {"expected", "confirmed", "unconfirmed", "dnp"}:
            if self.lineup_status != self.availability:
                raise ValueError("availability and lineup_status must agree")
        elif self.lineup_status == "dnp":
            raise ValueError("availability=active cannot be paired with lineup_status=dnp")
        return self


class SlateFeatureSnapshot(StrictModel):
    schema_version: Literal["1.0", "1.1", "1.2", "1.3"] = "1.3"
    data_kind: DataKind
    slate_id: str = Field(min_length=1)
    site: Site
    contest_style: Literal["classic"] | None = None
    provider_slate_id: str | None = None
    scope: Literal["provider_game_set", "historical_daily_pool"] = "provider_game_set"
    provider_game_set_verified: bool = True
    validation_scope: Literal["FULL_RESEARCH", "LIMITED_SINGLE_SLATE_VALIDATION"] = "FULL_RESEARCH"
    warnings: list[str] = Field(default_factory=list)
    slate_start: datetime
    lock_time: datetime
    snapshot_as_of: datetime
    game_ids: list[int] = Field(default_factory=list)
    games: list[SlateGame] = Field(default_factory=list)
    sources: list[SourceTimestamp] = Field(min_length=1)
    settings: OptimizerSettings
    players: list[FrozenPlayer] = Field(min_length=1)

    @field_validator("slate_start", "lock_time", "snapshot_as_of")
    @classmethod
    def require_timezone(cls, value: datetime, info: Any) -> datetime:
        return _require_aware(value, info.field_name)

    @model_validator(mode="before")
    @classmethod
    def reject_prohibited_keys_anywhere(cls, raw: Any) -> Any:
        found: set[str] = set()

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    if _is_prohibited_feature_key(key):
                        found.add(str(key))
                    walk(nested)
            elif isinstance(value, list):
                for nested in value:
                    walk(nested)

        walk(raw)
        if found:
            raise ValueError(
                "post-game fields are prohibited in feature snapshots: "
                f"{sorted(found)}"
            )
        return raw

    @model_validator(mode="after")
    def enforce_temporal_boundary_and_identity(self) -> SlateFeatureSnapshot:
        if self.snapshot_as_of > self.lock_time:
            raise ValueError("snapshot_as_of must be at or before lock_time")
        if self.slate_start < self.lock_time:
            raise ValueError("slate_start must be at or after lock_time")

        for source in self.sources:
            if self.data_kind == "real":
                required = {
                    "role": source.role,
                    "artifact_id": source.artifact_id,
                    "source_url": source.source_url,
                    "raw_sha256": source.raw_sha256,
                    "available_at": source.available_at,
                    "retrieved_at": source.retrieved_at,
                    "timestamp_basis": source.timestamp_basis,
                }
                missing = sorted(name for name, value in required.items() if value is None)
                if missing:
                    raise ValueError(
                        f"real source {source.source!r} lacks provenance fields: {missing}"
                    )
                assert source.available_at is not None
                if source.available_at > self.snapshot_as_of:
                    raise ValueError(
                        f"source {source.source!r} available_at is after snapshot_as_of"
                    )
                if source.published_at and source.published_at > self.snapshot_as_of:
                    raise ValueError(
                        f"source {source.source!r} published_at is after snapshot_as_of"
                    )
            else:
                if source.fetched_at > self.snapshot_as_of:
                    raise ValueError(f"source {source.source!r} fetched_at is after snapshot_as_of")
                if source.published_at and source.published_at > self.snapshot_as_of:
                    raise ValueError(
                        f"source {source.source!r} published_at is after snapshot_as_of"
                    )

        ids = [player.mlbam_id for player in self.players]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate player IDs are prohibited in a feature snapshot")

        if self.data_kind == "real":
            if self.site != "dk":
                raise ValueError("this qualified historical builder currently supports DK only")
            if self.contest_style != "classic":
                raise ValueError("real DK slates must declare contest_style=classic")
            if not self.provider_slate_id:
                raise ValueError("real slates require provider_slate_id")
            if len(self.games) < 2:
                raise ValueError("real DK Classic slates require at least two games")
            derived_game_ids = [game.game_id for game in self.games]
            if len(derived_game_ids) != len(set(derived_game_ids)):
                raise ValueError("duplicate game IDs are prohibited")
            if self.game_ids != derived_game_ids:
                raise ValueError("game_ids must exactly match games order")
            first_pitch = min(game.scheduled_start for game in self.games)
            if self.lock_time != first_pitch or self.slate_start != first_pitch:
                raise ValueError("real slate lock_time/slate_start must equal earliest game start")
            game_by_id = {game.game_id: game for game in self.games}
            for player in self.players:
                if player.game_id not in game_by_id:
                    raise ValueError(
                        f"player {player.mlbam_id} is missing a valid game_id assignment"
                    )
                if not player.external_id:
                    raise ValueError(
                        f"player {player.mlbam_id} is missing the platform external_id"
                    )
                game = game_by_id[player.game_id]
                expected_teams = {game.away_team, game.home_team}
                if player.team not in expected_teams:
                    raise ValueError(
                        f"player {player.mlbam_id} team is not in assigned game"
                    )
                expected_opponent = (
                    game.home_team if player.team == game.away_team else game.away_team
                )
                if player.opponent != expected_opponent:
                    raise ValueError(
                        f"player {player.mlbam_id} opponent disagrees with assigned game"
                    )
            if self.scope == "provider_game_set":
                if not self.provider_game_set_verified:
                    raise ValueError("provider_game_set scope requires provider_game_set_verified=true")
                required_projection_role = "pregame_mlb_stats"
            else:
                if self.provider_game_set_verified:
                    raise ValueError("historical_daily_pool requires provider_game_set_verified=false")
                if self.validation_scope != "LIMITED_SINGLE_SLATE_VALIDATION":
                    raise ValueError("historical_daily_pool is restricted to LIMITED_SINGLE_SLATE_VALIDATION")
                required_warnings = {
                    "provider_game_set_unverified",
                    "uniform_salary_warning",
                    "projection_untrusted_field_excluded",
                }
                missing_warnings = sorted(required_warnings - set(self.warnings))
                if missing_warnings:
                    raise ValueError(f"historical_daily_pool lacks warnings: {missing_warnings}")
                required_projection_role = None
            roles = {source.role for source in self.sources}
            required_roles = {
                "platform_slate_snapshot",
                "platform_salary_snapshot",
            }
            if required_projection_role is not None:
                required_roles.add(required_projection_role)
            if not required_roles.issubset(roles):
                raise ValueError(
                    f"real features lack required source roles: {sorted(required_roles - roles)}"
                )
            ambiguous_players = [
                player.mlbam_id
                for player in self.players
                if player.projection_source.strip().lower() in AMBIGUOUS_PROJECTION_SOURCES
                or any("avgpointspergame" in re.sub(r"[^a-z0-9]", "", str(key).lower())
                       for key in player.feature_values)
            ]
            if ambiguous_players:
                raise ValueError(
                    "ambiguous AvgPointsPerGame projections must be excluded or isolated; "
                    f"players={ambiguous_players[:20]}"
                )
        return self


class ActualPointsRecord(StrictModel):
    mlbam_id: int
    actual_points: float
    status: Literal["played", "dnp_not_in_final_boxscore", "dnp_no_game_appearance"] | None = None
    source_game_id: int | None = None
    source_evidence_id: str | None = None
    scoring_components: dict[str, float | int | str | bool] = Field(default_factory=dict)

    @field_validator("actual_points")
    @classmethod
    def require_finite_points(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("actual_points must be finite")
        return value


class ActualCoverageSummary(StrictModel):
    feature_player_count: int = Field(ge=1)
    records_count: int = Field(ge=1)
    played_count: int = Field(ge=0)
    dnp_count: int = Field(ge=0)
    missing_ids: list[int] = Field(default_factory=list)
    extra_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_counts(self) -> ActualCoverageSummary:
        if self.played_count + self.dnp_count != self.records_count:
            raise ValueError("played_count + dnp_count must equal records_count")
        if len(self.missing_ids) != len(set(self.missing_ids)):
            raise ValueError("coverage missing_ids must be unique")
        if len(self.extra_ids) != len(set(self.extra_ids)):
            raise ValueError("coverage extra_ids must be unique")
        return self


class SlateActualPoints(StrictModel):
    schema_version: Literal["1.0", "1.1", "1.2", "1.3"] = "1.3"
    data_kind: DataKind
    slate_id: str = Field(min_length=1)
    site: Site
    scoring_source: str = Field(min_length=1)
    scoring_rules_version: str = Field(min_length=1)
    acquired_at: datetime
    source_timestamp: datetime
    source_record_id: str | None = None
    source_final: bool = False
    validation_scope: Literal["FULL_RESEARCH", "LIMITED_SINGLE_SLATE_VALIDATION"] = "FULL_RESEARCH"
    coverage_scope: Literal["all_feature_players", "selected_lineup_players"] = "all_feature_players"
    warnings: list[str] = Field(default_factory=list)
    selection_seed: int | None = None
    selection_feature_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    limited_mode_acknowledgement: Literal["SELECTED_ONLY_ACTUALS_NOT_GENERALIZABLE"] | None = None
    coverage_summary: ActualCoverageSummary | None = None
    raw_stats_artifact_ids: list[str] = Field(default_factory=list)
    scoring_rules_artifact_id: str | None = None
    points: list[ActualPointsRecord] = Field(min_length=1)

    @field_validator("acquired_at", "source_timestamp")
    @classmethod
    def require_timezone(cls, value: datetime, info: Any) -> datetime:
        return _require_aware(value, info.field_name)

    @model_validator(mode="after")
    def enforce_identity_and_provenance(self) -> SlateActualPoints:
        ids = [record.mlbam_id for record in self.points]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate player IDs are prohibited in actual-points data")
        if self.acquired_at < self.source_timestamp:
            raise ValueError("acquired_at must be at or after source_timestamp")
        if self.data_kind == "real":
            if not self.source_final:
                raise ValueError("real actuals require source_final=true")
            if not self.raw_stats_artifact_ids:
                raise ValueError("real actuals require raw_stats_artifact_ids")
            if not self.scoring_rules_artifact_id:
                raise ValueError("real actuals require scoring_rules_artifact_id")
            if self.coverage_scope == "selected_lineup_players":
                if self.validation_scope != "LIMITED_SINGLE_SLATE_VALIDATION":
                    raise ValueError("selected lineup actual coverage is limited-validation only")
                required_warnings = {
                    "selected_lineup_actuals_only",
                    "selected_only_seed_bound",
                    "selected_only_feature_bound",
                }
                missing_warnings = sorted(required_warnings - set(self.warnings))
                if missing_warnings:
                    raise ValueError(
                        f"selected lineup actual coverage lacks warnings: {missing_warnings}"
                    )
                if self.selection_seed is None:
                    raise ValueError("selected lineup actual coverage requires selection_seed")
                if self.selection_feature_sha256 is None:
                    raise ValueError(
                        "selected lineup actual coverage requires selection_feature_sha256"
                    )
                if self.limited_mode_acknowledgement != "SELECTED_ONLY_ACTUALS_NOT_GENERALIZABLE":
                    raise ValueError(
                        "selected lineup actual coverage requires explicit limited-mode acknowledgement"
                    )
            elif (
                self.selection_seed is not None
                or self.selection_feature_sha256 is not None
                or self.limited_mode_acknowledgement is not None
            ):
                raise ValueError("selection-only metadata is prohibited for full-pool actuals")
        if self.schema_version == "1.3":
            if self.coverage_summary is None:
                raise ValueError("schema 1.3 actuals require coverage_summary")
            summary = self.coverage_summary
            if summary.records_count != len(self.points):
                raise ValueError("coverage records_count must equal points length")
            if self.coverage_scope == "all_feature_players":
                if summary.missing_ids or summary.extra_ids:
                    raise ValueError("full-pool coverage cannot contain missing or extra IDs")
                if summary.feature_player_count != summary.records_count:
                    raise ValueError("full-pool coverage count must equal feature player count")
        return self


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
