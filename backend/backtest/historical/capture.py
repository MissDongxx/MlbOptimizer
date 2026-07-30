from __future__ import annotations

import csv
import hashlib
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from backtest.io import load_json, write_json


CAPTURE_VERSION = "dk-current-slate-capture-v1"
_REQUIRED_COLUMNS = {
    "Position",
    "Name + ID",
    "Name",
    "ID",
    "Roster Position",
    "Salary",
    "Game Info",
    "TeamAbbrev",
}
_GAME_INFO_RE = re.compile(
    r"^(?P<away>[A-Z0-9]+)@(?P<home>[A-Z0-9]+)\s+"
    r"(?P<date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<time>\d{1,2}:\d{2}(?:AM|PM))\s+ET$"
)


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SlateCaptureError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SlateCaptureError("source URL must be an absolute http(s) URL")
    return value


def _parse_capture_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SlateCaptureError("captured_at must include a timezone offset")
    return value


def _parse_salary_csv(path: Path) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = sorted(_REQUIRED_COLUMNS - fields)
        if missing:
            raise SlateCaptureError(f"salary CSV lacks required DraftKings columns: {missing}")
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    if not rows:
        raise SlateCaptureError("salary CSV is empty")
    external_ids = [row["ID"] for row in rows]
    if any(not value for value in external_ids):
        raise SlateCaptureError("salary CSV contains an empty player ID")
    if len(external_ids) != len(set(external_ids)):
        raise SlateCaptureError("salary CSV player IDs must be unique")

    eastern = ZoneInfo("America/New_York")
    games: dict[tuple[str, str, str], dict[str, Any]] = {}
    for line_number, row in enumerate(rows, start=2):
        match = _GAME_INFO_RE.fullmatch(row["Game Info"])
        if not match:
            raise SlateCaptureError(
                f"unrecognized Game Info at CSV line {line_number}: {row['Game Info']!r}"
            )
        scheduled = datetime.strptime(
            f"{match.group('date')} {match.group('time')}", "%m/%d/%Y %I:%M%p"
        ).replace(tzinfo=eastern)
        away = match.group("away")
        home = match.group("home")
        if row["TeamAbbrev"] not in {away, home}:
            raise SlateCaptureError(
                f"team {row['TeamAbbrev']} is not in Game Info at CSV line {line_number}"
            )
        key = (away, home, scheduled.isoformat())
        games[key] = {
            "away_team": away,
            "home_team": home,
            "scheduled_start": scheduled.isoformat(),
            "game_info": row["Game Info"],
        }
    return rows, [games[key] for key in sorted(games)]


def capture_current_dk_slate(
    *,
    salary_csv: Path,
    output_dir: Path,
    source_url: str,
    draft_group_id: str | None = None,
    provider_metadata: Path | None = None,
    provider_metadata_url: str | None = None,
    clock: Clock = _utc_now,
) -> dict[str, Any]:
    """Archive a current/future DK export before its first lock.

    This workflow intentionally cannot backfill historical availability. It archives
    bytes observed now and downgrades provider Game Set status unless an independent
    review later binds the raw provider metadata to a DraftGroup.
    """
    salary_csv = salary_csv.resolve()
    output_dir = output_dir.resolve()
    if not salary_csv.is_file():
        raise SlateCaptureError(f"salary CSV does not exist: {salary_csv}")
    source_url = _validate_url(source_url)
    captured_at = _parse_capture_time(clock())
    rows, games = _parse_salary_csv(salary_csv)
    first_lock = min(datetime.fromisoformat(game["scheduled_start"]) for game in games)
    manifest_path = output_dir / "capture-manifest.json"
    if manifest_path.exists():
        existing = load_json(manifest_path)
        artifacts = existing.get("artifacts", [])
        salary_artifact = next(
            (item for item in artifacts if item.get("artifact_id") == "draftkings-salary-export"),
            None,
        )
        if not isinstance(salary_artifact, dict):
            raise SlateCaptureError("existing capture manifest lacks salary artifact")
        expected_hash = hashlib.sha256(salary_csv.read_bytes()).hexdigest()
        if salary_artifact.get("sha256") != expected_hash:
            raise SlateCaptureError("existing immutable capture belongs to different salary bytes")
        if salary_artifact.get("source_url") != source_url:
            raise SlateCaptureError("existing immutable capture belongs to a different source URL")
        return {
            "status": "CAPTURED_LIMITED",
            "manifest_file": manifest_path.name,
            "manifest_sha256": _sha256(manifest_path),
            "player_count": int(existing["player_count"]),
            "game_count": int(existing["game_count"]),
            "salary_non_uniform": bool(existing["salary"]["non_uniform"]),
            "provider_game_set_verified": False,
            "warnings": list(existing.get("warnings", [])),
            "artifacts": artifacts,
            "replayed_existing_immutable_capture": True,
        }

    if captured_at >= first_lock:
        raise SlateCaptureError(
            "current-slate capture occurred after first pitch; historical availability "
            "cannot be inferred or backfilled"
        )

    salaries: list[int] = []
    for line_number, row in enumerate(rows, start=2):
        try:
            salary = int(row["Salary"])
        except ValueError as exc:
            raise SlateCaptureError(f"invalid salary at CSV line {line_number}") from exc
        if salary <= 0:
            raise SlateCaptureError(f"salary must be positive at CSV line {line_number}")
        salaries.append(salary)

    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    salary_target = raw_dir / "DKSalaries.csv"
    if salary_target.exists() and salary_target.read_bytes() != salary_csv.read_bytes():
        raise SlateCaptureError("immutable capture target already contains different bytes")
    shutil.copyfile(salary_csv, salary_target)

    artifacts = [
        {
            "artifact_id": "draftkings-salary-export",
            "role": "platform_salary_snapshot",
            "source_url": source_url,
            "local_path": salary_target.relative_to(output_dir).as_posix(),
            "original_filename": salary_csv.name,
            "captured_at": captured_at.isoformat(),
            "byte_count": salary_target.stat().st_size,
            "sha256": _sha256(salary_target),
            "immutable_after_capture": True,
        }
    ]

    provider_status = "UNVERIFIED"
    if provider_metadata is not None:
        provider_metadata = provider_metadata.resolve()
        if not provider_metadata.is_file():
            raise SlateCaptureError(f"provider metadata does not exist: {provider_metadata}")
        if provider_metadata_url is None:
            raise SlateCaptureError("provider_metadata_url is required with provider_metadata")
        provider_metadata_url = _validate_url(provider_metadata_url)
        provider_target = raw_dir / f"provider-metadata{provider_metadata.suffix or '.bin'}"
        if provider_target.exists() and provider_target.read_bytes() != provider_metadata.read_bytes():
            raise SlateCaptureError("immutable provider metadata target contains different bytes")
        shutil.copyfile(provider_metadata, provider_target)
        artifacts.append(
            {
                "artifact_id": "draftkings-provider-metadata-unverified",
                "role": "platform_slate_snapshot",
                "source_url": provider_metadata_url,
                "local_path": provider_target.relative_to(output_dir).as_posix(),
                "original_filename": provider_metadata.name,
                "captured_at": captured_at.isoformat(),
                "byte_count": provider_target.stat().st_size,
                "sha256": _sha256(provider_target),
                "immutable_after_capture": True,
            }
        )
        provider_status = "RAW_METADATA_CAPTURED_REQUIRES_INDEPENDENT_VERIFICATION"

    unique_salaries = sorted(set(salaries))
    warnings = ["provider_game_set_unverified"]
    if len(unique_salaries) == 1:
        warnings.append("uniform_salary_warning")
    manifest = {
        "schema_version": "1.0",
        "capture_version": CAPTURE_VERSION,
        "capture_mode": "current_or_future_only",
        "historical_backfill_supported": False,
        "site": "dk",
        "sport": "MLB",
        "contest_style": "classic",
        "captured_at": captured_at.isoformat(),
        "captured_at_source": "runtime_clock_at_archive",
        "first_lock": first_lock.isoformat(),
        "draft_group_id_claimed": draft_group_id,
        "provider_game_set_verified": False,
        "provider_game_set_status": provider_status,
        "classification": "CAPTURED_CURRENT_SLATE_LIMITED_UNTIL_GAME_SET_VERIFIED",
        "player_count": len(rows),
        "game_count": len(games),
        "games": games,
        "salary": {
            "min": min(salaries),
            "max": max(salaries),
            "unique_count": len(unique_salaries),
            "non_uniform": len(unique_salaries) > 1,
        },
        "warnings": warnings,
        "artifacts": artifacts,
        "replayed_existing_immutable_capture": False,
    }
    write_json(manifest_path, manifest)
    return {
        "status": "CAPTURED_LIMITED",
        "manifest_file": manifest_path.name,
        "manifest_sha256": _sha256(manifest_path),
        "player_count": len(rows),
        "game_count": len(games),
        "salary_non_uniform": len(unique_salaries) > 1,
        "provider_game_set_verified": False,
        "warnings": warnings,
        "artifacts": artifacts,
        "replayed_existing_immutable_capture": False,
    }
