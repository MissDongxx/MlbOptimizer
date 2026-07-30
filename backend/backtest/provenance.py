from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backtest.io import load_json


ArtifactRole = Literal[
    "platform_slate_snapshot",
    "platform_salary_snapshot",
    "pregame_mlb_stats",
    "pregame_platform_projection",
    "postgame_mlb_stats",
    "scoring_rules",
    "identity_reference",
    "identity_overrides",
]
TimestampBasis = Literal[
    "source_payload",
    "http_last_modified",
    "archive_capture",
    "platform_export_metadata",
    "repository_commit",
]
TemporalClass = Literal["pregame", "postgame", "static"]
LicenseStatus = Literal[
    "verified_redistributable",
    "public_access_use_only",
    "unknown_no_redistribution",
]


class ProvenanceError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawArtifact(StrictModel):
    artifact_id: str = Field(min_length=1)
    role: ArtifactRole
    source_name: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    immutable_url: str | None = None
    local_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquired_at: datetime
    effective_at: datetime | None = None
    timestamp_basis: TimestampBasis
    temporal_class: TemporalClass
    pregame_semantics: bool = False
    license_status: LicenseStatus
    redistribution_included: bool = False
    finalized: bool = False
    notes: str | None = None

    @field_validator("acquired_at", "effective_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("provenance timestamps must include a timezone offset")
        return value

    @field_validator("source_url", "immutable_url")
    @classmethod
    def require_http_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source URLs must use http or https")
        return value

    @model_validator(mode="after")
    def enforce_semantics(self) -> RawArtifact:
        if self.temporal_class == "pregame":
            if not self.pregame_semantics:
                raise ValueError("pregame artifacts must explicitly assert pregame semantics")
            if self.effective_at is None:
                raise ValueError("pregame artifacts require effective_at")
        if self.temporal_class == "postgame":
            if self.effective_at is None:
                raise ValueError("postgame artifacts require effective_at")
            if not self.finalized:
                raise ValueError("postgame artifacts must explicitly assert finalized content")
        if self.redistribution_included and self.license_status != "verified_redistributable":
            raise ValueError(
                "raw data may only be bundled when redistribution rights are verified"
            )
        return self


class SlateManifestEntry(StrictModel):
    slate_id: str = Field(min_length=1)
    site: Literal["dk", "fd"]
    contest_style: Literal["classic"]
    provider_slate_id: str = Field(min_length=1)
    game_ids: list[int] = Field(min_length=2)
    lock_time: datetime
    snapshot_as_of: datetime
    feature_file: str = Field(min_length=1)
    feature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    actuals_file: str = Field(min_length=1)
    actuals_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qa_report_file: str = Field(min_length=1)
    qa_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity_report_file: str = Field(min_length=1)
    identity_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_ids: list[str] = Field(min_length=4)
    transform_version: str = Field(min_length=1)
    scoring_rules_version: str = Field(min_length=1)
    scope: Literal["provider_game_set", "historical_daily_pool"] = "provider_game_set"
    provider_game_set_verified: bool = True
    validation_scope: Literal["FULL_RESEARCH", "LIMITED_SINGLE_SLATE_VALIDATION"] = "FULL_RESEARCH"
    warnings: list[str] = Field(default_factory=list)
    qualification_status: Literal["qualified", "qualified_limited"]

    @field_validator("lock_time", "snapshot_as_of")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("slate manifest timestamps must include a timezone offset")
        return value

    @model_validator(mode="after")
    def enforce_unique_games_and_cutoff(self) -> SlateManifestEntry:
        if len(self.game_ids) != len(set(self.game_ids)):
            raise ValueError("manifest game_ids must be unique")
        if self.snapshot_as_of > self.lock_time:
            raise ValueError("manifest snapshot_as_of must be at or before lock_time")
        if len(self.artifact_ids) != len(set(self.artifact_ids)):
            raise ValueError("manifest artifact_ids must be unique")
        if self.scope == "historical_daily_pool":
            if self.provider_game_set_verified:
                raise ValueError("historical_daily_pool cannot verify a provider Game Set")
            if self.validation_scope != "LIMITED_SINGLE_SLATE_VALIDATION":
                raise ValueError("historical_daily_pool is limited-validation only")
            if self.qualification_status != "qualified_limited":
                raise ValueError("historical_daily_pool must use qualified_limited")
            required = {
                "provider_game_set_unverified",
                "uniform_salary_warning",
                "projection_untrusted_field_excluded",
            }
            if not required.issubset(self.warnings):
                raise ValueError("historical_daily_pool lacks required warnings")
        return self


class DatasetManifest(StrictModel):
    schema_version: Literal["1.0", "1.1"] = "1.1"
    dataset_id: str = Field(min_length=1)
    site: Literal["dk", "fd"]
    contest_style: Literal["classic"]
    created_at: datetime
    source_audit_version: str = Field(min_length=1)
    artifacts: list[RawArtifact] = Field(min_length=1)
    slates: list[SlateManifestEntry] = Field(default_factory=list)

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def enforce_unique_ids_and_site(self) -> DatasetManifest:
        artifact_ids = [item.artifact_id for item in self.artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("duplicate artifact IDs in provenance manifest")
        slate_ids = [item.slate_id for item in self.slates]
        if len(slate_ids) != len(set(slate_ids)):
            raise ValueError("duplicate slate IDs in provenance manifest")
        for slate in self.slates:
            if slate.site != self.site or slate.contest_style != self.contest_style:
                raise ValueError("slate manifest entry disagrees with dataset site/style")
        return self


class ProvenanceIndex:
    def __init__(self, root: Path, manifest_path: Path, manifest: DatasetManifest):
        self.root = root.resolve()
        self.manifest_path = manifest_path.resolve()
        self.manifest = manifest
        self.manifest_sha256 = sha256_path(self.manifest_path)
        self.artifacts = {item.artifact_id: item for item in manifest.artifacts}
        self.slates = {item.slate_id: item for item in manifest.slates}

    @classmethod
    def load(cls, root: Path, manifest_path: Path | None = None) -> ProvenanceIndex:
        path = manifest_path or root / "provenance-manifest.json"
        if not path.exists():
            raise ProvenanceError(f"Missing provenance manifest: {path}")
        manifest = DatasetManifest.model_validate(load_json(path))
        index = cls(root, path, manifest)
        index._validate_artifact_files()
        return index

    def validate_real_slate(
        self,
        *,
        slate_id: str,
        site: str,
        contest_style: str,
        provider_slate_id: str,
        game_ids: list[int],
        lock_time: datetime,
        snapshot_as_of: datetime,
        scope: str,
        provider_game_set_verified: bool,
        validation_scope: str,
        warnings: list[str],
        feature_path: Path,
        actuals_path: Path,
        scoring_rules_version: str,
        feature_sources: list[object],
        raw_stats_artifact_ids: list[str],
        scoring_rules_artifact_id: str | None,
        actuals_source_record_id: str | None,
        actuals_source_timestamp: datetime,
        actuals_acquired_at: datetime,
        actuals_source_final: bool,
    ) -> SlateManifestEntry:
        entry = self.slates.get(slate_id)
        if entry is None:
            raise ProvenanceError(f"No qualified manifest entry for real slate {slate_id!r}")
        comparisons = {
            "site": (entry.site, site),
            "contest_style": (entry.contest_style, contest_style),
            "provider_slate_id": (entry.provider_slate_id, provider_slate_id),
            "game_ids": (entry.game_ids, game_ids),
            "lock_time": (entry.lock_time, lock_time),
            "snapshot_as_of": (entry.snapshot_as_of, snapshot_as_of),
            "scope": (entry.scope, scope),
            "provider_game_set_verified": (entry.provider_game_set_verified, provider_game_set_verified),
            "validation_scope": (entry.validation_scope, validation_scope),
            "warnings": (entry.warnings, warnings),
            "scoring_rules_version": (entry.scoring_rules_version, scoring_rules_version),
        }
        mismatches = [name for name, (left, right) in comparisons.items() if left != right]
        if mismatches:
            raise ProvenanceError(
                f"Manifest metadata mismatch for {slate_id}: {', '.join(mismatches)}"
            )
        self._verify_bound_file(entry.feature_file, entry.feature_sha256, feature_path)
        self._verify_bound_file(entry.actuals_file, entry.actuals_sha256, actuals_path)
        self._verify_report(entry.qa_report_file, entry.qa_report_sha256, "QA")
        self._verify_report(
            entry.identity_report_file, entry.identity_report_sha256, "identity"
        )

        artifacts = []
        for artifact_id in entry.artifact_ids:
            artifact = self.artifacts.get(artifact_id)
            if artifact is None:
                raise ProvenanceError(
                    f"Slate {slate_id} references missing artifact {artifact_id!r}"
                )
            artifacts.append(artifact)

        roles = {item.role for item in artifacts}
        projection_role = None if entry.scope == "historical_daily_pool" else "pregame_mlb_stats"
        required_roles = {
            "platform_slate_snapshot",
            "platform_salary_snapshot",
            "postgame_mlb_stats",
            "scoring_rules",
            "identity_reference",
        }
        if projection_role is not None:
            required_roles.add(projection_role)
        missing_roles = sorted(required_roles - roles)
        if missing_roles:
            raise ProvenanceError(
                f"Slate {slate_id} is missing required provenance roles: {missing_roles}"
            )
        for role in required_roles:
            count = sum(item.role == role for item in artifacts)
            if role == "postgame_mlb_stats":
                if count < 1:
                    raise ProvenanceError(
                        f"Slate {slate_id} must reference at least one postgame artifact"
                    )
            elif count != 1:
                raise ProvenanceError(
                    f"Slate {slate_id} must reference exactly one {role} artifact; got {count}"
                )

        self._validate_feature_source_bindings(
            slate_id=slate_id,
            feature_sources=feature_sources,
            artifacts=artifacts,
            required_projection_role=projection_role,
        )
        self._validate_actual_source_bindings(
            slate_id=slate_id,
            raw_stats_artifact_ids=raw_stats_artifact_ids,
            scoring_rules_artifact_id=scoring_rules_artifact_id,
            actuals_source_record_id=actuals_source_record_id,
            actuals_source_timestamp=actuals_source_timestamp,
            actuals_acquired_at=actuals_acquired_at,
            actuals_source_final=actuals_source_final,
            artifacts=artifacts,
        )

        for artifact in artifacts:
            if artifact.temporal_class == "pregame":
                assert artifact.effective_at is not None
                if artifact.effective_at > snapshot_as_of:
                    raise ProvenanceError(
                        f"Pregame artifact {artifact.artifact_id} became effective after snapshot"
                    )
            if artifact.temporal_class == "postgame":
                assert artifact.effective_at is not None
                if artifact.effective_at < lock_time:
                    raise ProvenanceError(
                        f"Postgame artifact {artifact.artifact_id} predates slate lock"
                    )
        return entry


    def _validate_feature_source_bindings(
        self,
        *,
        slate_id: str,
        feature_sources: list[object],
        artifacts: list[RawArtifact],
        required_projection_role: str | None,
    ) -> None:
        artifacts_by_id = {item.artifact_id: item for item in artifacts}
        required_roles = {
            "platform_slate_snapshot",
            "platform_salary_snapshot",
        }
        if required_projection_role is not None:
            required_roles.add(required_projection_role)
        seen_roles: set[str] = set()
        for source in feature_sources:
            artifact_id = getattr(source, "artifact_id", None)
            role = getattr(source, "role", None)
            if role not in required_roles:
                continue
            if role in seen_roles:
                raise ProvenanceError(
                    f"Slate {slate_id} has duplicate feature source role {role}"
                )
            seen_roles.add(role)
            artifact = artifacts_by_id.get(artifact_id)
            if artifact is None:
                raise ProvenanceError(
                    f"Feature source {artifact_id!r} is not bound by the slate manifest"
                )
            comparisons = {
                "role": (artifact.role, role),
                "source_url": (artifact.source_url, getattr(source, "source_url", None)),
                "raw_sha256": (artifact.sha256, getattr(source, "raw_sha256", None)),
                "available_at": (artifact.effective_at, getattr(source, "available_at", None)),
                "retrieved_at": (artifact.acquired_at, getattr(source, "retrieved_at", None)),
                "timestamp_basis": (
                    artifact.timestamp_basis,
                    getattr(source, "timestamp_basis", None),
                ),
            }
            mismatches = [name for name, values in comparisons.items() if values[0] != values[1]]
            if mismatches:
                raise ProvenanceError(
                    f"Feature source {artifact_id!r} disagrees with provenance artifact: "
                    f"{', '.join(mismatches)}"
                )
        missing = sorted(required_roles - seen_roles)
        if missing:
            raise ProvenanceError(
                f"Slate {slate_id} lacks bound feature source roles: {missing}"
            )

    def _validate_actual_source_bindings(
        self,
        *,
        slate_id: str,
        raw_stats_artifact_ids: list[str],
        scoring_rules_artifact_id: str | None,
        actuals_source_record_id: str | None,
        actuals_source_timestamp: datetime,
        actuals_acquired_at: datetime,
        actuals_source_final: bool,
        artifacts: list[RawArtifact],
    ) -> None:
        artifacts_by_id = {item.artifact_id: item for item in artifacts}
        if not raw_stats_artifact_ids:
            raise ProvenanceError(
                f"Slate {slate_id} must bind at least one postgame statistics artifact"
            )
        if len(raw_stats_artifact_ids) != len(set(raw_stats_artifact_ids)):
            raise ProvenanceError("actuals postgame artifact IDs must be unique")
        postgames: list[RawArtifact] = []
        for postgame_id in raw_stats_artifact_ids:
            postgame = artifacts_by_id.get(postgame_id)
            if postgame is None or postgame.role != "postgame_mlb_stats":
                raise ProvenanceError(
                    f"Actuals postgame artifact {postgame_id!r} is missing or has the wrong role"
                )
            postgames.append(postgame)
        if not actuals_source_final or any(not item.finalized for item in postgames):
            raise ProvenanceError("real actuals must be bound to finalized postgame content")
        expected_record_id = ";".join(raw_stats_artifact_ids)
        if actuals_source_record_id not in {expected_record_id, raw_stats_artifact_ids[0]}:
            raise ProvenanceError(
                "actuals source_record_id must bind the ordered postgame artifact IDs"
            )
        expected_source_timestamp = max(item.effective_at for item in postgames if item.effective_at)
        if expected_source_timestamp != actuals_source_timestamp:
            raise ProvenanceError(
                "actuals source_timestamp disagrees with the bound postgame artifacts"
            )
        expected_acquired_at = max(
            [actuals_source_timestamp] + [item.acquired_at for item in postgames]
        )
        if expected_acquired_at != actuals_acquired_at:
            raise ProvenanceError(
                "actuals acquired_at disagrees with the bound postgame artifacts"
            )
        rules = artifacts_by_id.get(scoring_rules_artifact_id or "")
        if rules is None or rules.role != "scoring_rules":
            raise ProvenanceError(
                f"Actuals scoring rules artifact {scoring_rules_artifact_id!r} is missing "
                "or has the wrong role"
            )

    def _validate_artifact_files(self) -> None:
        for artifact in self.manifest.artifacts:
            path = self._resolve(artifact.local_path)
            if not path.exists():
                raise ProvenanceError(
                    f"Missing raw artifact {artifact.artifact_id}: {artifact.local_path}"
                )
            actual_hash = sha256_path(path)
            if actual_hash != artifact.sha256:
                raise ProvenanceError(
                    f"Raw artifact hash mismatch for {artifact.artifact_id}: "
                    f"expected {artifact.sha256}, got {actual_hash}"
                )

    def _verify_bound_file(self, declared: str, expected_hash: str, actual_path: Path) -> None:
        declared_path = self._resolve(declared)
        if declared_path != actual_path.resolve():
            raise ProvenanceError(
                f"Manifest path {declared!r} does not bind to {actual_path.name!r}"
            )
        actual_hash = sha256_path(actual_path)
        if actual_hash != expected_hash:
            raise ProvenanceError(
                f"Bound file hash mismatch for {actual_path.name}: "
                f"expected {expected_hash}, got {actual_hash}"
            )

    def _verify_report(self, relative_path: str, expected_hash: str, label: str) -> None:
        path = self._resolve(relative_path)
        if not path.exists():
            raise ProvenanceError(f"Missing {label} report: {relative_path}")
        actual_hash = sha256_path(path)
        if actual_hash != expected_hash:
            raise ProvenanceError(
                f"{label.capitalize()} report hash mismatch: expected {expected_hash}, "
                f"got {actual_hash}"
            )

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ProvenanceError(f"Path escapes dataset root: {relative_path}")
        return candidate


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
