from __future__ import annotations

import csv
import json
import re
import shutil
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backtest.contracts import (
    ActualPointsRecord,
    FrozenPlayer,
    SlateActualPoints,
    SlateFeatureSnapshot,
    SlateGame,
    SourceTimestamp,
)
from backtest.historical.identity import (
    IDENTITY_VERSION,
    IdentityMappingError,
    MlbIdentity,
    PlatformPlayerIdentity,
    map_identities,
)
from backtest.historical.projection import (
    PROJECTION_VERSION,
    HistoricalFantasyGame,
    project_player,
)
from backtest.historical.scoring import (
    DK_MLB_CLASSIC_RULES_VERSION,
    HitterGameStats,
    PitcherGameStats,
    score_hitter_game,
    score_pitcher_game,
)
from backtest.io import load_json, write_json
from backtest.provenance import (
    DatasetManifest,
    RawArtifact,
    SlateManifestEntry,
    sha256_path,
)
from models.schemas import OptimizerSettings


TRANSFORM_VERSION = "dk-mlb-classic-historical-builder-v1"
SOURCE_AUDIT_VERSION = "public-source-audit-2026-07-29-v1"
_REQUIRED_DK_COLUMNS = {
    "Position",
    "Name + ID",
    "Name",
    "ID",
    "Roster Position",
    "Salary",
    "Game Info",
    "TeamAbbrev",
    "AvgPointsPerGame",
}
_GAME_INFO_RE = re.compile(
    r"^(?P<away>[A-Z0-9]+)@(?P<home>[A-Z0-9]+)\s+"
    r"(?P<date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<time>\d{1,2}:\d{2}(?:AM|PM))\s+ET$"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuildBundle(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    data_kind: Literal["real", "fixture"]
    dataset_id: str = Field(min_length=1)
    slate_id: str = Field(min_length=1)
    site: Literal["dk"]
    contest_style: Literal["classic"]
    provider_slate_id: str = Field(min_length=1)
    snapshot_as_of: datetime
    lock_time: datetime
    created_at: datetime
    games: list[SlateGame] = Field(min_length=2)
    settings: OptimizerSettings
    artifacts: list[RawArtifact] = Field(min_length=6)
    identity_overrides: dict[str, int] = Field(default_factory=dict)

    @field_validator("snapshot_as_of", "lock_time", "created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("bundle timestamps must include a timezone offset")
        return value

    @model_validator(mode="after")
    def enforce_cutoff_and_roles(self) -> BuildBundle:
        if self.snapshot_as_of > self.lock_time:
            raise ValueError("snapshot_as_of must be at or before lock_time")
        first_pitch = min(item.scheduled_start for item in self.games)
        if first_pitch != self.lock_time:
            raise ValueError("lock_time must equal earliest game start")
        roles = {item.role for item in self.artifacts}
        required = {
            "platform_slate_snapshot",
            "platform_salary_snapshot",
            "pregame_mlb_stats",
            "postgame_mlb_stats",
            "scoring_rules",
            "identity_reference",
        }
        missing = sorted(required - roles)
        if missing:
            raise ValueError(f"bundle lacks required artifact roles: {missing}")
        if self.data_kind == "real":
            for item in self.artifacts:
                if item.temporal_class == "pregame":
                    assert item.effective_at is not None
                    if item.effective_at > self.snapshot_as_of:
                        raise ValueError(
                            f"pregame artifact {item.artifact_id} became effective after snapshot"
                        )
                if item.temporal_class == "postgame":
                    assert item.effective_at is not None
                    if not item.finalized:
                        raise ValueError(
                            f"postgame artifact {item.artifact_id} is not finalized"
                        )
                    if item.effective_at < self.lock_time:
                        raise ValueError(
                            f"postgame artifact {item.artifact_id} predates lock"
                        )
        return self


class HistoricalBuilderError(ValueError):
    pass


class HistoricalSlateBuilder:
    def __init__(self, bundle_path: Path, output_dir: Path):
        self.bundle_path = bundle_path.resolve()
        self.bundle_root = self.bundle_path.parent
        self.output_dir = output_dir.resolve()
        self.bundle = BuildBundle.model_validate(load_json(self.bundle_path))
        self.artifacts_by_role: dict[str, list[RawArtifact]] = defaultdict(list)
        for artifact in self.bundle.artifacts:
            self.artifacts_by_role[artifact.role].append(artifact)

    def build(self) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        copied_artifacts = self._copy_and_verify_artifacts()
        artifact_by_role: dict[str, list[RawArtifact]] = defaultdict(list)
        for artifact in copied_artifacts:
            artifact_by_role[artifact.role].append(artifact)

        salary_artifact = self._single(artifact_by_role, "platform_salary_snapshot")
        identity_artifact = self._single(artifact_by_role, "identity_reference")
        pregame_artifact = self._single(artifact_by_role, "pregame_mlb_stats")
        postgame_artifact = self._single(artifact_by_role, "postgame_mlb_stats")
        rules_artifact = self._single(artifact_by_role, "scoring_rules")

        salary_rows = self._read_salary_csv(self.output_dir / salary_artifact.local_path)
        identities = self._read_identities(self.output_dir / identity_artifact.local_path)
        platform_identities = [
            PlatformPlayerIdentity(
                external_id=row["ID"],
                name=row["Name"],
                team=row["TeamAbbrev"],
            )
            for row in salary_rows
        ]
        try:
            mapping, decisions = map_identities(
                platform_identities,
                identities,
                overrides=self.bundle.identity_overrides,
            )
        except IdentityMappingError as exc:
            self._write_identity_report(exc.decisions, status="FAIL")
            raise HistoricalBuilderError(str(exc)) from exc
        identity_report_path = self._write_identity_report(decisions, status="PASS")

        history = self._read_historical_stats(self.output_dir / pregame_artifact.local_path)
        postgame_rows = self._read_postgame_stats(self.output_dir / postgame_artifact.local_path)
        game_lookup = self._game_lookup()
        players: list[FrozenPlayer] = []
        projection_audit: list[dict[str, Any]] = []
        role_by_mlbam: dict[int, Literal["hitter", "pitcher"]] = {}
        game_by_mlbam: dict[int, int] = {}

        for row in salary_rows:
            external_id = row["ID"]
            mlbam_id = mapping[external_id]
            role: Literal["hitter", "pitcher"] = (
                "pitcher" if _is_pitcher(row["Position"], row["Roster Position"]) else "hitter"
            )
            game = self._match_game_info(row["Game Info"], game_lookup)
            team = row["TeamAbbrev"].upper()
            opponent = game.home_team if team == game.away_team else game.away_team
            projection, audit = project_player(
                history,
                mlbam_id=mlbam_id,
                role=role,
                cutoff=self.bundle.lock_time,
            )
            projection_audit.append(
                {
                    "mlbam_id": mlbam_id,
                    "external_id": external_id,
                    "role": role,
                    **audit,
                }
            )
            role_by_mlbam[mlbam_id] = role
            game_by_mlbam[mlbam_id] = game.game_id
            players.append(
                FrozenPlayer(
                    mlbam_id=mlbam_id,
                    name=row["Name"],
                    team=team,
                    opponent=opponent,
                    position=_parse_positions(row["Position"], row["Roster Position"]),
                    salary=_parse_positive_int(row["Salary"], "Salary"),
                    projected_points=projection,
                    lock=False,
                    exclude=False,
                    max_exposure=1.0,
                    lineup_status="unconfirmed",
                    external_id=external_id,
                    name_id=row["Name + ID"],
                    availability="unconfirmed",
                    batting_order=None,
                    projection_source=PROJECTION_VERSION,
                    feature_values={
                        "projection_version": PROJECTION_VERSION,
                        "cutoff_date_exclusive": audit["cutoff_date_exclusive"],
                        "history_games_used": audit["history_games_used"],
                        "role_prior": audit["role_prior"],
                    },
                    game_id=game.game_id,
                )
            )

        actual_by_id = self._score_actuals(
            postgame_rows,
            players=players,
            role_by_mlbam=role_by_mlbam,
            game_by_mlbam=game_by_mlbam,
        )

        sources = [
            _source_timestamp(item)
            for item in copied_artifacts
            if item.temporal_class == "pregame"
            and item.role
            in {"platform_slate_snapshot", "platform_salary_snapshot", "pregame_mlb_stats"}
        ]
        features = SlateFeatureSnapshot(
            schema_version="1.1",
            data_kind=self.bundle.data_kind,
            slate_id=self.bundle.slate_id,
            site="dk",
            contest_style="classic" if self.bundle.data_kind == "real" else None,
            provider_slate_id=(
                self.bundle.provider_slate_id if self.bundle.data_kind == "real" else None
            ),
            slate_start=self.bundle.lock_time,
            lock_time=self.bundle.lock_time,
            snapshot_as_of=self.bundle.snapshot_as_of,
            game_ids=(
                [item.game_id for item in self.bundle.games]
                if self.bundle.data_kind == "real"
                else []
            ),
            games=self.bundle.games if self.bundle.data_kind == "real" else [],
            sources=sources,
            settings=self.bundle.settings,
            players=players,
        )
        actuals = SlateActualPoints(
            schema_version="1.1",
            data_kind=self.bundle.data_kind,
            slate_id=self.bundle.slate_id,
            site="dk",
            scoring_source="independent_official_stat_reconstruction",
            scoring_rules_version=DK_MLB_CLASSIC_RULES_VERSION,
            acquired_at=postgame_artifact.acquired_at,
            source_timestamp=postgame_artifact.effective_at or postgame_artifact.acquired_at,
            source_record_id=postgame_artifact.artifact_id,
            source_final=postgame_artifact.finalized,
            raw_stats_artifact_ids=(
                [postgame_artifact.artifact_id] if self.bundle.data_kind == "real" else []
            ),
            scoring_rules_artifact_id=(
                rules_artifact.artifact_id if self.bundle.data_kind == "real" else None
            ),
            points=[
                ActualPointsRecord(
                    mlbam_id=item.mlbam_id,
                    actual_points=actual_by_id[item.mlbam_id],
                )
                for item in sorted(players, key=lambda value: value.mlbam_id)
            ],
        )

        feature_path = self.output_dir / f"{self.bundle.slate_id}.features.json"
        actual_path = self.output_dir / f"{self.bundle.slate_id}.actuals.json"
        write_json(feature_path, features.model_dump(mode="json"))
        write_json(actual_path, actuals.model_dump(mode="json"))
        qa_report_path = self._write_qa_report(
            features=features,
            actuals=actuals,
            projection_audit=projection_audit,
            identity_report_path=identity_report_path,
        )

        manifest_path = self.output_dir / "provenance-manifest.json"
        if self.bundle.data_kind == "real":
            manifest = self._update_manifest(
                manifest_path=manifest_path,
                artifacts=copied_artifacts,
                feature_path=feature_path,
                actual_path=actual_path,
                qa_report_path=qa_report_path,
                identity_report_path=identity_report_path,
            )
            manifest_hash = sha256_path(manifest_path)
            qualified = len(manifest.slates)
        else:
            manifest_hash = None
            qualified = 0

        return {
            "slate_id": self.bundle.slate_id,
            "data_kind": self.bundle.data_kind,
            "players": len(players),
            "feature_file": feature_path.name,
            "feature_sha256": sha256_path(feature_path),
            "actuals_file": actual_path.name,
            "actuals_sha256": sha256_path(actual_path),
            "identity_report": identity_report_path.relative_to(self.output_dir).as_posix(),
            "qa_report": qa_report_path.relative_to(self.output_dir).as_posix(),
            "provenance_manifest_sha256": manifest_hash,
            "qualified_real_slates_in_manifest": qualified,
        }

    def _copy_and_verify_artifacts(self) -> list[RawArtifact]:
        copied: list[RawArtifact] = []
        for artifact in self.bundle.artifacts:
            source = (self.bundle_root / artifact.local_path).resolve()
            if source != self.bundle_root and self.bundle_root not in source.parents:
                raise HistoricalBuilderError(
                    f"artifact path escapes bundle root: {artifact.local_path}"
                )
            if not source.exists():
                raise HistoricalBuilderError(
                    f"missing bundle artifact {artifact.artifact_id}: {artifact.local_path}"
                )
            actual_hash = sha256_path(source)
            if actual_hash != artifact.sha256:
                raise HistoricalBuilderError(
                    f"artifact hash mismatch for {artifact.artifact_id}: "
                    f"expected {artifact.sha256}, got {actual_hash}"
                )
            suffix = source.suffix or ".bin"
            relative = Path("raw") / self.bundle.slate_id / f"{artifact.artifact_id}{suffix}"
            destination = self.output_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            copied.append(artifact.model_copy(update={"local_path": relative.as_posix()}))
        return copied

    def _read_salary_csv(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or [])
            missing = sorted(_REQUIRED_DK_COLUMNS - fields)
            if missing:
                raise HistoricalBuilderError(
                    f"salary CSV is not a recognized DK export; missing columns: {missing}"
                )
            rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
        if not rows:
            raise HistoricalBuilderError("salary CSV is empty")
        external_ids = [item["ID"] for item in rows]
        if any(not item for item in external_ids) or len(external_ids) != len(set(external_ids)):
            raise HistoricalBuilderError("salary CSV external IDs must be non-empty and unique")
        return rows

    def _read_identities(self, path: Path) -> list[MlbIdentity]:
        payload = load_json(path)
        rows = payload if isinstance(payload, list) else payload.get("players", [])
        identities = [
            MlbIdentity(
                mlbam_id=int(item["mlbam_id"]),
                name=str(item["name"]),
                team=str(item["team"]),
            )
            for item in rows
        ]
        if not identities:
            raise HistoricalBuilderError("identity reference has no players")
        return identities

    def _read_historical_stats(self, path: Path) -> list[HistoricalFantasyGame]:
        rows = _read_json_rows(path)
        history: list[HistoricalFantasyGame] = []
        for row in rows:
            role = row["role"]
            game_date = date.fromisoformat(row["game_date"])
            if role == "hitter":
                score = score_hitter_game(_hitter_stats(row))
            elif role == "pitcher":
                score = score_pitcher_game(_pitcher_stats(row))
            else:
                raise HistoricalBuilderError(f"unsupported historical role: {role}")
            history.append(
                HistoricalFantasyGame(
                    mlbam_id=int(row["mlbam_id"]),
                    game_id=int(row["game_id"]),
                    game_date=game_date,
                    role=role,
                    dk_points=score,
                )
            )
        return history

    def _read_postgame_stats(self, path: Path) -> list[dict[str, Any]]:
        return _read_json_rows(path)

    def _score_actuals(
        self,
        rows: list[dict[str, Any]],
        *,
        players: list[FrozenPlayer],
        role_by_mlbam: dict[int, Literal["hitter", "pitcher"]],
        game_by_mlbam: dict[int, int],
    ) -> dict[int, float]:
        slate_game_ids = {item.game_id for item in self.bundle.games}
        score_by_id: dict[int, float] = {item.mlbam_id: 0.0 for item in players}
        seen_pairs: set[tuple[int, int]] = set()
        for row in rows:
            mlbam_id = int(row["mlbam_id"])
            game_id = int(row["game_id"])
            pair = (mlbam_id, game_id)
            if pair in seen_pairs:
                raise HistoricalBuilderError(f"duplicate postgame player/game row: {pair}")
            seen_pairs.add(pair)
            if game_id not in slate_game_ids:
                raise HistoricalBuilderError(
                    f"postgame row references game outside slate: {game_id}"
                )
            if mlbam_id not in score_by_id:
                # Preserve the full raw artifact, but rows for non-platform players do not
                # affect scoring and are reported as extras rather than silently mapped.
                continue
            if game_by_mlbam[mlbam_id] != game_id:
                raise HistoricalBuilderError(
                    f"player {mlbam_id} postgame game does not match salary game assignment"
                )
            expected_role = role_by_mlbam[mlbam_id]
            if row["role"] != expected_role:
                raise HistoricalBuilderError(
                    f"player {mlbam_id} role mismatch: {row['role']} vs {expected_role}"
                )
            if expected_role == "hitter":
                score_by_id[mlbam_id] += score_hitter_game(_hitter_stats(row))
            else:
                score_by_id[mlbam_id] += score_pitcher_game(_pitcher_stats(row))
        return {key: round(value, 10) for key, value in score_by_id.items()}

    def _game_lookup(self) -> dict[tuple[str, str, datetime], SlateGame]:
        result: dict[tuple[str, str, datetime], SlateGame] = {}
        for game in self.bundle.games:
            key = (game.away_team.upper(), game.home_team.upper(), game.scheduled_start)
            result[key] = game
        return result

    def _match_game_info(
        self, game_info: str, lookup: dict[tuple[str, str, datetime], SlateGame]
    ) -> SlateGame:
        match = _GAME_INFO_RE.match(game_info)
        if not match:
            raise HistoricalBuilderError(f"unrecognized DK Game Info: {game_info!r}")
        local = datetime.strptime(
            f"{match.group('date')} {match.group('time')}", "%m/%d/%Y %I:%M%p"
        ).replace(tzinfo=ZoneInfo("America/New_York"))
        key = (
            match.group("away").upper(),
            match.group("home").upper(),
            local.astimezone(self.bundle.lock_time.tzinfo),
        )
        game = lookup.get(key)
        if game is None:
            # Compare in UTC to avoid timezone object representation differences.
            for candidate_key, candidate in lookup.items():
                if (
                    candidate_key[0] == key[0]
                    and candidate_key[1] == key[1]
                    and candidate_key[2].timestamp() == key[2].timestamp()
                ):
                    return candidate
            raise HistoricalBuilderError(
                f"DK Game Info is not present in the declared provider slate: {game_info!r}"
            )
        return game

    def _write_identity_report(self, decisions: list[Any], *, status: str) -> Path:
        path = self.output_dir / "identity" / f"{self.bundle.slate_id}.identity.json"
        write_json(
            path,
            {
                "schema_version": "1.0",
                "identity_version": IDENTITY_VERSION,
                "slate_id": self.bundle.slate_id,
                "status": status,
                "platform_player_count": len(decisions),
                "matched_count": sum(item.status == "matched" for item in decisions),
                "unmatched_count": sum(item.status == "unmatched" for item in decisions),
                "ambiguous_count": sum(item.status == "ambiguous" for item in decisions),
                "invalid_override_count": sum(
                    item.status == "invalid_override" for item in decisions
                ),
                "decisions": [item.to_dict() for item in decisions],
            },
        )
        return path

    def _write_qa_report(
        self,
        *,
        features: SlateFeatureSnapshot,
        actuals: SlateActualPoints,
        projection_audit: list[dict[str, Any]],
        identity_report_path: Path,
    ) -> Path:
        position_counts: dict[str, int] = defaultdict(int)
        for player in features.players:
            for position in player.position:
                position_counts[position] += 1
        actual_ids = {item.mlbam_id for item in actuals.points}
        feature_ids = {item.mlbam_id for item in features.players}
        checks = {
            "site_is_dk": features.site == "dk",
            "contest_style_is_classic": (
                features.contest_style == "classic" if features.data_kind == "real" else True
            ),
            "at_least_two_games": len(self.bundle.games) >= 2,
            "lock_matches_first_pitch": features.lock_time
            == min(item.scheduled_start for item in self.bundle.games),
            "all_players_have_actuals": feature_ids.issubset(actual_ids),
            "identity_report_pass": load_json(identity_report_path)["status"] == "PASS",
            "has_two_pitchers": position_counts.get("P", 0) >= 2,
            "has_catcher": position_counts.get("C", 0) >= 1,
            "has_first_base": position_counts.get("1B", 0) >= 1,
            "has_second_base": position_counts.get("2B", 0) >= 1,
            "has_third_base": position_counts.get("3B", 0) >= 1,
            "has_shortstop": position_counts.get("SS", 0) >= 1,
            "has_three_outfielders": position_counts.get("OF", 0) >= 3,
            "strict_projection_cutoff": all(
                item["cutoff_date_exclusive"] == self.bundle.lock_time.date().isoformat()
                for item in projection_audit
            ),
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        path = self.output_dir / "qa" / f"{self.bundle.slate_id}.qa.json"
        write_json(
            path,
            {
                "schema_version": "1.0",
                "slate_id": self.bundle.slate_id,
                "status": status,
                "checks": checks,
                "player_count": len(features.players),
                "game_count": len(self.bundle.games),
                "position_counts": dict(sorted(position_counts.items())),
                "projection_audit": sorted(
                    projection_audit, key=lambda item: (item["mlbam_id"], item["external_id"])
                ),
                "zero_actual_count": sum(item.actual_points == 0 for item in actuals.points),
            },
        )
        if status != "PASS":
            failed = sorted(name for name, passed in checks.items() if not passed)
            raise HistoricalBuilderError(f"slate QA failed: {failed}")
        return path

    def _update_manifest(
        self,
        *,
        manifest_path: Path,
        artifacts: list[RawArtifact],
        feature_path: Path,
        actual_path: Path,
        qa_report_path: Path,
        identity_report_path: Path,
    ) -> DatasetManifest:
        if manifest_path.exists():
            manifest = DatasetManifest.model_validate(load_json(manifest_path))
            if (
                manifest.dataset_id != self.bundle.dataset_id
                or manifest.site != "dk"
                or manifest.contest_style != "classic"
            ):
                raise HistoricalBuilderError("existing manifest belongs to a different dataset")
        else:
            manifest = DatasetManifest(
                dataset_id=self.bundle.dataset_id,
                site="dk",
                contest_style="classic",
                created_at=self.bundle.created_at,
                source_audit_version=SOURCE_AUDIT_VERSION,
                artifacts=[],
                slates=[],
            )

        artifacts_by_id = {item.artifact_id: item for item in manifest.artifacts}
        for artifact in artifacts:
            prior = artifacts_by_id.get(artifact.artifact_id)
            if prior and prior != artifact:
                raise HistoricalBuilderError(
                    f"artifact ID collision with different metadata: {artifact.artifact_id}"
                )
            artifacts_by_id[artifact.artifact_id] = artifact

        slates_by_id = {item.slate_id: item for item in manifest.slates}
        entry = SlateManifestEntry(
            slate_id=self.bundle.slate_id,
            site="dk",
            contest_style="classic",
            provider_slate_id=self.bundle.provider_slate_id,
            game_ids=[item.game_id for item in self.bundle.games],
            lock_time=self.bundle.lock_time,
            snapshot_as_of=self.bundle.snapshot_as_of,
            feature_file=feature_path.relative_to(self.output_dir).as_posix(),
            feature_sha256=sha256_path(feature_path),
            actuals_file=actual_path.relative_to(self.output_dir).as_posix(),
            actuals_sha256=sha256_path(actual_path),
            qa_report_file=qa_report_path.relative_to(self.output_dir).as_posix(),
            qa_report_sha256=sha256_path(qa_report_path),
            identity_report_file=identity_report_path.relative_to(self.output_dir).as_posix(),
            identity_report_sha256=sha256_path(identity_report_path),
            artifact_ids=sorted(item.artifact_id for item in artifacts),
            transform_version=TRANSFORM_VERSION,
            scoring_rules_version=DK_MLB_CLASSIC_RULES_VERSION,
            qualification_status="qualified",
        )
        prior_entry = slates_by_id.get(entry.slate_id)
        if prior_entry and prior_entry != entry:
            raise HistoricalBuilderError(
                f"slate {entry.slate_id} already exists with different bytes/metadata"
            )
        slates_by_id[entry.slate_id] = entry
        updated = manifest.model_copy(
            update={
                "artifacts": sorted(artifacts_by_id.values(), key=lambda item: item.artifact_id),
                "slates": sorted(slates_by_id.values(), key=lambda item: item.slate_id),
            }
        )
        write_json(manifest_path, updated.model_dump(mode="json"))
        return updated

    @staticmethod
    def _single(mapping: dict[str, list[RawArtifact]], role: str) -> RawArtifact:
        values = mapping.get(role, [])
        if len(values) != 1:
            raise HistoricalBuilderError(
                f"exactly one {role} artifact is required per build bundle; got {len(values)}"
            )
        return values[0]


def _source_timestamp(artifact: RawArtifact) -> SourceTimestamp:
    role_map = {
        "platform_slate_snapshot": "platform_slate_snapshot",
        "platform_salary_snapshot": "platform_salary_snapshot",
        "pregame_mlb_stats": "pregame_mlb_stats",
    }
    return SourceTimestamp(
        source=artifact.source_name,
        fetched_at=artifact.effective_at or artifact.acquired_at,
        published_at=artifact.effective_at,
        source_record_id=artifact.artifact_id,
        role=role_map[artifact.role],
        artifact_id=artifact.artifact_id,
        source_url=artifact.source_url,
        raw_sha256=artifact.sha256,
        available_at=artifact.effective_at,
        retrieved_at=artifact.acquired_at,
        timestamp_basis=artifact.timestamp_basis,
    )


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise HistoricalBuilderError(
                        f"invalid JSONL at {path.name}:{line_number}: {exc}"
                    ) from exc
                if not isinstance(value, dict):
                    raise HistoricalBuilderError(
                        f"JSONL rows must be objects: {path.name}:{line_number}"
                    )
                rows.append(value)
        return rows
    payload = load_json(path)
    if isinstance(payload, list):
        return payload
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HistoricalBuilderError(f"JSON artifact lacks a rows array: {path.name}")
    return rows


def _hitter_stats(row: dict[str, Any]) -> HitterGameStats:
    return HitterGameStats(
        mlbam_id=int(row["mlbam_id"]),
        game_id=int(row["game_id"]),
        hits=int(row.get("hits", 0)),
        doubles=int(row.get("doubles", 0)),
        triples=int(row.get("triples", 0)),
        home_runs=int(row.get("home_runs", 0)),
        runs=int(row.get("runs", 0)),
        rbi=int(row.get("rbi", 0)),
        walks=int(row.get("walks", 0)),
        hit_by_pitch=int(row.get("hit_by_pitch", 0)),
        stolen_bases=int(row.get("stolen_bases", 0)),
    )


def _pitcher_stats(row: dict[str, Any]) -> PitcherGameStats:
    return PitcherGameStats(
        mlbam_id=int(row["mlbam_id"]),
        game_id=int(row["game_id"]),
        outs_recorded=int(row.get("outs_recorded", 0)),
        strikeouts=int(row.get("strikeouts", 0)),
        win=bool(row.get("win", False)),
        earned_runs=int(row.get("earned_runs", 0)),
        hits_allowed=int(row.get("hits_allowed", 0)),
        walks_allowed=int(row.get("walks_allowed", 0)),
        hit_batters=int(row.get("hit_batters", 0)),
        complete_game=bool(row.get("complete_game", False)),
        complete_game_shutout=bool(row.get("complete_game_shutout", False)),
        no_hitter=bool(row.get("no_hitter", False)),
    )


def _parse_positions(position: str, roster_position: str) -> list[str]:
    raw = position or roster_position
    values = []
    for item in re.split(r"[/,]", raw.upper()):
        item = item.strip()
        if item in {"SP", "RP", "P"}:
            item = "P"
        if item in {"UTIL", "H", "FLEX"} or not item:
            continue
        if item not in values:
            values.append(item)
    if not values:
        raise HistoricalBuilderError(
            f"could not derive DK roster positions from {position!r}/{roster_position!r}"
        )
    return values


def _is_pitcher(position: str, roster_position: str) -> bool:
    return "P" in _parse_positions(position, roster_position)


def _parse_positive_int(value: str, field: str) -> int:
    try:
        parsed = int(value.replace(",", ""))
    except ValueError as exc:
        raise HistoricalBuilderError(f"{field} must be an integer: {value!r}") from exc
    if parsed <= 0:
        raise HistoricalBuilderError(f"{field} must be positive")
    return parsed
