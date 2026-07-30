from __future__ import annotations

import copy
import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from backtest.io import load_json, write_json


SlateState = Literal["captured", "awaiting-results", "qualified", "rejected", "backtested"]
ALLOWED_TRANSITIONS: dict[str | None, set[str]] = {
    None: {"captured"},
    "captured": {"captured", "awaiting-results", "rejected"},
    "awaiting-results": {"awaiting-results", "qualified", "rejected"},
    "qualified": {"qualified", "backtested", "rejected"},
    "backtested": {"backtested", "rejected"},
    "rejected": {"rejected"},
}


class RegistryError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RegistryError("registry timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_provider_evidence_artifact(
    artifact: dict[str, Any],
    *,
    provider_slate_id: str | None,
    draft_group_id: str | None,
) -> dict[str, Any]:
    path = Path(str(artifact.get("path", "")))
    if not path.is_file():
        raise RegistryError(f"provider evidence artifact is missing: {path}")
    payload = load_json(path)
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise RegistryError("provider evidence must be a schema_version 1.0 JSON object")
    if not str(payload.get("provider", "")).strip():
        raise RegistryError("provider evidence requires provider")
    source_url = str(payload.get("source_url", "")).strip()
    if not source_url.startswith(("https://", "http://")):
        raise RegistryError("provider evidence requires an http(s) source_url")
    if artifact.get("source_url") != source_url:
        raise RegistryError("provider evidence source_url differs from archived artifact metadata")
    claimed_ids = {
        str(value)
        for value in (payload.get("provider_slate_id"), payload.get("draft_group_id"))
        if value is not None and str(value).strip()
    }
    expected_ids = {
        str(value)
        for value in (provider_slate_id, draft_group_id)
        if value is not None and str(value).strip()
    }
    if not claimed_ids or not expected_ids or claimed_ids.isdisjoint(expected_ids):
        raise RegistryError(
            f"provider evidence identity mismatch: claimed={sorted(claimed_ids)} "
            f"expected={sorted(expected_ids)}"
        )
    try:
        captured_at = datetime.fromisoformat(str(payload["captured_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise RegistryError("provider evidence requires a valid captured_at") from exc
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise RegistryError("provider evidence captured_at must be timezone-aware")
    if iso(captured_at) != artifact.get("captured_at"):
        raise RegistryError("provider evidence captured_at differs from archived artifact metadata")
    return payload


@dataclass
class Registry:
    path: Path
    clock: Any = utc_now

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": "1.0",
                "created_at": iso(self.clock()),
                "updated_at": iso(self.clock()),
                "slates": {},
            }
        payload = load_json(self.path)
        if not isinstance(payload, dict) or not isinstance(payload.get("slates"), dict):
            raise RegistryError("registry is malformed")
        if payload.get("schema_version") != "1.0":
            raise RegistryError("unsupported registry schema_version")
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload["updated_at"] = iso(self.clock())
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        write_json(temporary, payload)
        os.replace(temporary, self.path)

    def get(self, slate_id: str) -> dict[str, Any] | None:
        value = self.load()["slates"].get(slate_id)
        return dict(value) if isinstance(value, dict) else None

    def upsert_captured(
        self,
        *,
        slate_id: str,
        data_kind: str,
        site: str,
        captured_at: datetime,
        effective_at: datetime | None,
        provider: str,
        provider_slate_id: str | None,
        draft_group_id: str | None,
        provider_game_set_verified: bool,
        artifacts: list[dict[str, Any]],
        blockers: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = self.load()
        existing = payload["slates"].get(slate_id)
        if existing is not None:
            self._verify_immutable_entry_metadata(
                existing,
                data_kind=data_kind,
                site=site,
                captured_at=captured_at,
                effective_at=effective_at,
                provider=provider,
                provider_slate_id=provider_slate_id,
                draft_group_id=draft_group_id,
            )
            self._verify_immutable_identity(existing, artifacts)
            return existing
        timestamp = iso(self.clock())
        evidence_artifacts = [
            item for item in artifacts if item.get("role") == "provider_game_set_evidence"
        ]
        evidence_ids = sorted(str(item["artifact_id"]) for item in evidence_artifacts)
        if provider_game_set_verified:
            for artifact in evidence_artifacts:
                _validate_provider_evidence_artifact(
                    artifact,
                    provider_slate_id=provider_slate_id,
                    draft_group_id=draft_group_id,
                )
        verified = bool(provider_game_set_verified and evidence_ids)
        effective_blockers = set(blockers or [])
        if provider_game_set_verified and not evidence_ids:
            effective_blockers.add("provider_game_set_evidence_missing")
        entry = {
            "slate_id": slate_id,
            "state": "captured",
            "data_kind": data_kind,
            "site": site,
            "captured_at": iso(captured_at),
            "effective_at": iso(effective_at) if effective_at else None,
            "provider": provider,
            "provider_slate_id": provider_slate_id,
            "draft_group_id": draft_group_id,
            "provider_game_set_verified": verified,
            "provider_verification": (
                {"verified_at": timestamp, "evidence_artifact_ids": evidence_ids}
                if verified
                else None
            ),
            "artifacts": sorted(artifacts, key=lambda item: item["artifact_id"]),
            "feature_file": None,
            "actuals_file": None,
            "provenance_manifest": None,
            "qualification": None,
            "rejection_reasons": [],
            "blockers": sorted(effective_blockers),
            "backtest": None,
            "state_history": [
                {"from": None, "to": "captured", "at": timestamp, "reason": "immutable capture registered"}
            ],
        }
        payload["slates"][slate_id] = entry
        self.save(payload)
        return entry

    def attach_files(
        self,
        slate_id: str,
        *,
        feature_file: str | None = None,
        actuals_file: str | None = None,
        provenance_manifest: str | None = None,
        artifacts: list[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        payload = self.load()
        entry = self._entry(payload, slate_id)
        before = copy.deepcopy(entry)
        self._verify_immutable_identity(entry, list(artifacts))
        known = {item["artifact_id"]: item for item in entry.get("artifacts", [])}
        for artifact in artifacts:
            known.setdefault(artifact["artifact_id"], artifact)
        entry["artifacts"] = sorted(known.values(), key=lambda item: item["artifact_id"])
        for key, value in (
            ("feature_file", feature_file),
            ("actuals_file", actuals_file),
            ("provenance_manifest", provenance_manifest),
        ):
            if value is None:
                continue
            current = entry.get(key)
            if current is not None and current != value:
                raise RegistryError(f"immutable registry field {key} already points to {current}")
            entry[key] = value
        if entry.get("feature_file") and entry.get("state") == "captured":
            reason = (
                "feature snapshot ready; final actuals pending"
                if not entry.get("actuals_file")
                else "feature snapshot and final actuals ready for qualification"
            )
            self._transition_entry(entry, "awaiting-results", reason)
        if entry != before:
            self.save(payload)
        return entry

    def mark_provider_game_set_verified(
        self,
        slate_id: str,
        *,
        provider_slate_id: str | None,
        draft_group_id: str | None,
        evidence_artifact_ids: list[str],
    ) -> dict[str, Any]:
        payload = self.load()
        entry = self._entry(payload, slate_id)
        before = copy.deepcopy(entry)
        evidence_ids = sorted(set(evidence_artifact_ids))
        if not evidence_ids:
            raise RegistryError("provider Game Set verification requires evidence artifacts")
        known = {str(item["artifact_id"]): item for item in entry.get("artifacts", [])}
        missing = [artifact_id for artifact_id in evidence_ids if artifact_id not in known]
        if missing:
            raise RegistryError(f"provider evidence artifacts are not registered: {missing}")
        invalid_roles = [
            artifact_id
            for artifact_id in evidence_ids
            if known[artifact_id].get("role") != "provider_game_set_evidence"
        ]
        if invalid_roles:
            raise RegistryError(f"provider evidence artifacts have invalid roles: {invalid_roles}")
        if not (provider_slate_id or draft_group_id):
            raise RegistryError("provider Game Set verification requires provider_slate_id or draft_group_id")
        for artifact_id in evidence_ids:
            _validate_provider_evidence_artifact(
                known[artifact_id],
                provider_slate_id=provider_slate_id,
                draft_group_id=draft_group_id,
            )
        for field, supplied in (
            ("provider_slate_id", provider_slate_id),
            ("draft_group_id", draft_group_id),
        ):
            existing = entry.get(field)
            if existing is not None and supplied is not None and existing != supplied:
                raise RegistryError(
                    f"provider Game Set identity mismatch for {field}: {existing} != {supplied}"
                )
            if existing is None and supplied is not None:
                entry[field] = supplied
        existing_verification = entry.get("provider_verification")
        if entry.get("provider_game_set_verified"):
            current_ids = sorted((existing_verification or {}).get("evidence_artifact_ids", []))
            if current_ids != evidence_ids:
                raise RegistryError("provider Game Set was already verified with different evidence")
            return entry
        entry["provider_game_set_verified"] = True
        entry["provider_verification"] = {
            "verified_at": iso(self.clock()),
            "evidence_artifact_ids": evidence_ids,
        }
        entry["blockers"] = sorted(
            blocker
            for blocker in set(entry.get("blockers", []))
            if blocker not in {"provider_game_set_unverified", "provider_game_set_evidence_missing"}
        )
        if entry != before:
            self.save(payload)
        return entry

    def transition(
        self,
        slate_id: str,
        state: SlateState,
        reason: str,
        *,
        qualification: dict[str, Any] | None = None,
        rejection_reasons: list[str] | None = None,
        backtest: dict[str, Any] | None = None,
        blockers: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = self.load()
        entry = self._entry(payload, slate_id)
        before = copy.deepcopy(entry)
        self._transition_entry(entry, state, reason)
        if qualification is not None:
            entry["qualification"] = qualification
        if rejection_reasons is not None:
            entry["rejection_reasons"] = sorted(set(rejection_reasons))
        if backtest is not None:
            entry["backtest"] = backtest
        if blockers is not None:
            entry["blockers"] = sorted(set(blockers))
        if entry != before:
            self.save(payload)
        return entry

    def verify_all_artifacts(self) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        payload = self.load()
        for slate_id, entry in sorted(payload["slates"].items()):
            for artifact in entry.get("artifacts", []):
                path = Path(str(artifact["path"]))
                if not path.is_file():
                    failures.append({"slate_id": slate_id, "artifact_id": artifact["artifact_id"], "reason": "missing"})
                    continue
                actual_bytes = path.stat().st_size
                actual_hash = sha256_file(path)
                if actual_bytes != int(artifact["byte_count"]) or actual_hash != artifact["sha256"]:
                    failures.append(
                        {
                            "slate_id": slate_id,
                            "artifact_id": artifact["artifact_id"],
                            "reason": "hash_or_size_mismatch",
                            "expected_bytes": artifact["byte_count"],
                            "actual_bytes": actual_bytes,
                            "expected_sha256": artifact["sha256"],
                            "actual_sha256": actual_hash,
                        }
                    )
        return failures

    def qualified_entries(self) -> list[dict[str, Any]]:
        payload = self.load()
        return [
            dict(entry)
            for _, entry in sorted(payload["slates"].items())
            if entry.get("state") in {"qualified", "backtested"}
        ]

    def _entry(self, payload: dict[str, Any], slate_id: str) -> dict[str, Any]:
        entry = payload["slates"].get(slate_id)
        if not isinstance(entry, dict):
            raise RegistryError(f"unknown slate_id: {slate_id}")
        return entry

    def _transition_entry(self, entry: dict[str, Any], new_state: str, reason: str) -> None:
        current = entry.get("state")
        if new_state not in ALLOWED_TRANSITIONS.get(current, set()):
            raise RegistryError(f"illegal slate transition {current!r} -> {new_state!r}")
        if current == new_state:
            return
        entry["state"] = new_state
        entry.setdefault("state_history", []).append(
            {"from": current, "to": new_state, "at": iso(self.clock()), "reason": reason}
        )

    @staticmethod
    def _verify_immutable_entry_metadata(
        entry: dict[str, Any],
        *,
        data_kind: str,
        site: str,
        captured_at: datetime,
        effective_at: datetime | None,
        provider: str,
        provider_slate_id: str | None,
        draft_group_id: str | None,
    ) -> None:
        supplied = {
            "data_kind": data_kind,
            "site": site,
            "captured_at": iso(captured_at),
            "effective_at": iso(effective_at) if effective_at else None,
            "provider": provider,
            "provider_slate_id": provider_slate_id,
            "draft_group_id": draft_group_id,
        }
        for field, value in supplied.items():
            existing = entry.get(field)
            if existing != value:
                raise RegistryError(
                    f"immutable slate {entry.get('slate_id')} changed field {field}: "
                    f"{existing!r} != {value!r}"
                )

    @staticmethod
    def _verify_immutable_identity(entry: dict[str, Any], artifacts: list[dict[str, Any]]) -> None:
        known = {item["artifact_id"]: item for item in entry.get("artifacts", [])}
        for artifact in artifacts:
            existing = known.get(artifact["artifact_id"])
            if existing is None:
                continue
            for field in (
                "sha256",
                "byte_count",
                "path",
                "source_url",
                "role",
                "captured_at",
                "effective_at",
                "immutable",
            ):
                if existing.get(field) != artifact.get(field):
                    raise RegistryError(
                        f"immutable artifact {artifact['artifact_id']} changed field {field}"
                    )


def archive_artifact(
    source: Path,
    *,
    artifact_dir: Path,
    slate_id: str,
    artifact_id: str,
    role: str,
    captured_at: datetime,
    effective_at: datetime | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    if not source.is_file():
        raise RegistryError(f"artifact source does not exist: {source}")
    digest = sha256_file(source)
    suffix = "".join(source.suffixes) or ".bin"
    target_dir = artifact_dir / slate_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{artifact_id}-{digest[:12]}{suffix}"
    if target.exists():
        if sha256_file(target) != digest:
            raise RegistryError(f"immutable artifact collision at {target}")
    else:
        shutil.copyfile(source, target)
        try:
            target.chmod(0o444)
        except OSError:
            pass
    return {
        "artifact_id": artifact_id,
        "role": role,
        "path": str(target.resolve()),
        "source_url": source_url,
        "captured_at": iso(captured_at),
        "effective_at": iso(effective_at) if effective_at else None,
        "byte_count": target.stat().st_size,
        "sha256": digest,
        "immutable": True,
    }
