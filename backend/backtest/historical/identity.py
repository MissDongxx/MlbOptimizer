from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable


IDENTITY_VERSION = "mlbam-name-team-explicit-override-v1"
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


@dataclass(frozen=True)
class PlatformPlayerIdentity:
    external_id: str
    name: str
    team: str


@dataclass(frozen=True)
class MlbIdentity:
    mlbam_id: int
    name: str
    team: str


@dataclass(frozen=True)
class IdentityDecision:
    external_id: str
    platform_name: str
    platform_team: str
    status: str
    mlbam_id: int | None
    matched_name: str | None
    method: str | None
    candidates: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "external_id": self.external_id,
            "platform_name": self.platform_name,
            "platform_team": self.platform_team,
            "status": self.status,
            "mlbam_id": self.mlbam_id,
            "matched_name": self.matched_name,
            "method": self.method,
            "candidates": list(self.candidates),
        }


class IdentityMappingError(ValueError):
    def __init__(self, decisions: list[IdentityDecision]):
        self.decisions = decisions
        failures = [item for item in decisions if item.status != "matched"]
        super().__init__(
            f"identity mapping failed for {len(failures)} of {len(decisions)} platform players"
        )


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_team(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def map_identities(
    platform_players: Iterable[PlatformPlayerIdentity],
    mlb_identities: Iterable[MlbIdentity],
    *,
    overrides: dict[str, int] | None = None,
) -> tuple[dict[str, int], list[IdentityDecision]]:
    overrides = overrides or {}
    candidates = list(mlb_identities)
    by_id = {item.mlbam_id: item for item in candidates}
    by_name_team: dict[tuple[str, str], list[MlbIdentity]] = {}
    for item in candidates:
        by_name_team.setdefault(
            (normalize_name(item.name), normalize_team(item.team)), []
        ).append(item)

    mapping: dict[str, int] = {}
    decisions: list[IdentityDecision] = []
    seen_external_ids: set[str] = set()
    for player in platform_players:
        if player.external_id in seen_external_ids:
            raise ValueError(f"duplicate platform external_id: {player.external_id}")
        seen_external_ids.add(player.external_id)

        override_id = overrides.get(player.external_id)
        if override_id is not None:
            target = by_id.get(override_id)
            if target is None:
                decisions.append(
                    IdentityDecision(
                        external_id=player.external_id,
                        platform_name=player.name,
                        platform_team=player.team,
                        status="invalid_override",
                        mlbam_id=None,
                        matched_name=None,
                        method="explicit_override",
                        candidates=(),
                    )
                )
                continue
            mapping[player.external_id] = target.mlbam_id
            decisions.append(
                IdentityDecision(
                    external_id=player.external_id,
                    platform_name=player.name,
                    platform_team=player.team,
                    status="matched",
                    mlbam_id=target.mlbam_id,
                    matched_name=target.name,
                    method="explicit_override",
                    candidates=(target.mlbam_id,),
                )
            )
            continue

        matches = by_name_team.get(
            (normalize_name(player.name), normalize_team(player.team)), []
        )
        if len(matches) == 1:
            target = matches[0]
            mapping[player.external_id] = target.mlbam_id
            decisions.append(
                IdentityDecision(
                    external_id=player.external_id,
                    platform_name=player.name,
                    platform_team=player.team,
                    status="matched",
                    mlbam_id=target.mlbam_id,
                    matched_name=target.name,
                    method="normalized_name_team",
                    candidates=(target.mlbam_id,),
                )
            )
        elif not matches:
            decisions.append(
                IdentityDecision(
                    external_id=player.external_id,
                    platform_name=player.name,
                    platform_team=player.team,
                    status="unmatched",
                    mlbam_id=None,
                    matched_name=None,
                    method=None,
                    candidates=(),
                )
            )
        else:
            decisions.append(
                IdentityDecision(
                    external_id=player.external_id,
                    platform_name=player.name,
                    platform_team=player.team,
                    status="ambiguous",
                    mlbam_id=None,
                    matched_name=None,
                    method=None,
                    candidates=tuple(sorted(item.mlbam_id for item in matches)),
                )
            )

    if any(item.status != "matched" for item in decisions):
        raise IdentityMappingError(decisions)
    if len(set(mapping.values())) != len(mapping):
        duplicates: dict[int, list[str]] = {}
        for external_id, mlbam_id in mapping.items():
            duplicates.setdefault(mlbam_id, []).append(external_id)
        collision = {key: value for key, value in duplicates.items() if len(value) > 1}
        raise ValueError(f"multiple platform IDs mapped to one MLBAM ID: {collision}")
    return mapping, decisions
