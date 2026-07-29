from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from math import floor
from typing import Iterable, Sequence

from models.schemas import Lineup, LineupPlayer, OptimizeRequest, PlayerInput


DK_SLOTS: tuple[str, ...] = ("P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF")
FD_SLOTS: tuple[str, ...] = ("P", "C/1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL")
SALARY_CAPS = {"dk": 50_000, "fd": 35_000}


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    assigned_slots: tuple[str, ...] = ()


class LineupValidationError(ValueError):
    def __init__(self, issues: Sequence[ValidationIssue]):
        self.issues = tuple(issues)
        message = "; ".join(issue.message for issue in self.issues) or "Lineup validation failed"
        super().__init__(message)


def roster_slots(site: str) -> tuple[str, ...]:
    if site == "dk":
        return DK_SLOTS
    if site == "fd":
        return FD_SLOTS
    raise ValueError(f"Unsupported site: {site}")



def normalize_output_slot(site: str, slot: str) -> str:
    normalized = slot.strip().upper()
    if normalized in {"SP", "RP"}:
        return "P"
    if site == "fd" and normalized in {"C", "1B"}:
        return "C/1B"
    return normalized


def salary_cap(site: str) -> int:
    try:
        return SALARY_CAPS[site]
    except KeyError as exc:
        raise ValueError(f"Unsupported site: {site}") from exc


def is_hitter(player: PlayerInput | LineupPlayer) -> bool:
    if isinstance(player, PlayerInput):
        return bool(set(player.position).difference({"P", "SP", "RP"}))
    return player.position_slot not in {"P", "SP", "RP"}


def eligible_for_slot(positions: Iterable[str], slot: str) -> bool:
    normalized = set(positions)
    if slot == "UTIL":
        return bool(normalized.difference({"P", "SP", "RP"}))
    if slot == "C/1B":
        return bool(normalized.intersection({"C", "1B", "C/1B"}))
    if slot == "P":
        return bool(normalized.intersection({"P", "SP", "RP"}))
    return slot in normalized


def assign_slots(site: str, players: Sequence[PlayerInput]) -> tuple[str, ...] | None:
    """Return one deterministic legal slot assignment, or None.

    This is a small bipartite matching problem. Players with fewer eligible slots are assigned first,
    with original index as the stable tie breaker. Returned slots align to the original player order.
    """

    slots = roster_slots(site)
    if len(players) != len(slots):
        return None

    choices: list[tuple[int, tuple[int, ...]]] = []
    for index, player in enumerate(players):
        eligible = tuple(
            slot_index
            for slot_index, slot in enumerate(slots)
            if eligible_for_slot(player.position, slot)
        )
        if not eligible:
            return None
        choices.append((index, eligible))

    choices.sort(key=lambda item: (len(item[1]), item[0]))
    assigned_by_player: list[str | None] = [None] * len(players)
    used_slots: set[int] = set()

    def search(choice_index: int) -> bool:
        if choice_index == len(choices):
            return True
        player_index, eligible_slot_indexes = choices[choice_index]
        for slot_index in eligible_slot_indexes:
            if slot_index in used_slots:
                continue
            used_slots.add(slot_index)
            assigned_by_player[player_index] = slots[slot_index]
            if search(choice_index + 1):
                return True
            assigned_by_player[player_index] = None
            used_slots.remove(slot_index)
        return False

    if not search(0):
        return None
    return tuple(slot for slot in assigned_by_player if slot is not None)


def max_exposure_count(max_exposure: float, requested_lineups: int) -> int:
    """Strict exposure ceiling: produced/requested must not exceed max_exposure."""

    return floor(max_exposure * requested_lineups + 1e-12)


def lineup_identity(players: Sequence[PlayerInput | LineupPlayer]) -> tuple[int, ...]:
    return tuple(sorted(player.mlbam_id for player in players))


def validate_lineup(
    request: OptimizeRequest,
    lineup: Lineup,
    *,
    exposure_counts: Counter[int] | None = None,
    lineup_index: int | None = None,
) -> ValidationResult:
    issues: list[ValidationIssue] = []
    slots = roster_slots(request.site)
    player_by_id = {player.mlbam_id: player for player in request.players}

    if len(lineup.players) != len(slots):
        issues.append(
            ValidationIssue(
                "roster_size",
                f"Expected {len(slots)} players but received {len(lineup.players)}.",
                {"expected": len(slots), "actual": len(lineup.players)},
            )
        )

    ids = [player.mlbam_id for player in lineup.players]
    duplicates = sorted(player_id for player_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        issues.append(
            ValidationIssue(
                "duplicate_player",
                "A lineup cannot contain the same player more than once.",
                {"player_ids": duplicates},
            )
        )

    unknown_ids = sorted(set(ids).difference(player_by_id))
    if unknown_ids:
        issues.append(
            ValidationIssue(
                "unknown_player",
                "The lineup contains players outside the request player pool.",
                {"player_ids": unknown_ids},
            )
        )

    source_players = [player_by_id[player_id] for player_id in ids if player_id in player_by_id]
    illegal_selected = sorted(
        player.mlbam_id
        for player in source_players
        if player.exclude or player.lineup_status == "dnp" or player.projected_points <= 0
    )
    if illegal_selected:
        issues.append(
            ValidationIssue(
                "ineligible_player",
                "Excluded, DNP, or non-positive projection players were selected.",
                {"player_ids": illegal_selected},
            )
        )

    invalid_salary_ids = sorted(player.mlbam_id for player in source_players if player.salary <= 0)
    if invalid_salary_ids:
        issues.append(
            ValidationIssue(
                "missing_salary",
                "Every selected player must have a positive site salary.",
                {"player_ids": invalid_salary_ids},
            )
        )

    locked_ids = {
        player.mlbam_id
        for player in request.players
        if player.lock and not player.exclude and player.lineup_status != "dnp" and player.projected_points > 0
    }
    missing_locks = sorted(locked_ids.difference(ids))
    if missing_locks:
        issues.append(
            ValidationIssue(
                "missing_lock",
                "Every locked player must appear in every generated lineup.",
                {"player_ids": missing_locks},
            )
        )

    total_salary = sum(player.salary for player in source_players)
    if lineup.total_salary != total_salary:
        issues.append(
            ValidationIssue(
                "salary_total_mismatch",
                "Serialized total salary does not match the selected players.",
                {"serialized": lineup.total_salary, "calculated": total_salary},
            )
        )
    cap = salary_cap(request.site)
    if total_salary > cap:
        issues.append(
            ValidationIssue(
                "salary_cap",
                f"Lineup salary {total_salary} exceeds the {cap} cap.",
                {"salary": total_salary, "cap": cap},
            )
        )
    if total_salary < request.settings.min_salary_used:
        issues.append(
            ValidationIssue(
                "minimum_salary",
                f"Lineup salary {total_salary} is below the requested minimum.",
                {"salary": total_salary, "minimum": request.settings.min_salary_used},
            )
        )

    assignment = assign_slots(request.site, source_players) if len(source_players) == len(slots) else None
    if assignment is None:
        issues.append(
            ValidationIssue(
                "position_assignment",
                "Selected players cannot be assigned to all required roster positions.",
                {"site": request.site, "required_slots": list(slots)},
            )
        )

    reported_slots = [normalize_output_slot(request.site, player.position_slot) for player in lineup.players]
    if Counter(reported_slots) != Counter(slots):
        issues.append(
            ValidationIssue(
                "position_slot_set",
                "Serialized lineup slots do not exactly match the site's required roster slots.",
                {"reported_slots": reported_slots, "required_slots": list(slots)},
            )
        )
    ineligible_slot_players = []
    for lineup_player in lineup.players:
        source = player_by_id.get(lineup_player.mlbam_id)
        normalized_slot = normalize_output_slot(request.site, lineup_player.position_slot)
        if source is not None and not eligible_for_slot(source.position, normalized_slot):
            ineligible_slot_players.append(
                {
                    "player_id": source.mlbam_id,
                    "positions": source.position,
                    "reported_slot": lineup_player.position_slot,
                }
            )
    if ineligible_slot_players:
        issues.append(
            ValidationIssue(
                "position_slot_eligibility",
                "One or more players are not eligible for their serialized roster slot.",
                {"players": ineligible_slot_players},
            )
        )

    metadata_mismatches = []
    for lineup_player in lineup.players:
        source = player_by_id.get(lineup_player.mlbam_id)
        if source is None:
            continue
        mismatch_fields = []
        if lineup_player.name != source.name:
            mismatch_fields.append("name")
        if lineup_player.team != source.team:
            mismatch_fields.append("team")
        if lineup_player.salary != source.salary:
            mismatch_fields.append("salary")
        if abs(lineup_player.projected_points - round(source.projected_points, 2)) > 1e-9:
            mismatch_fields.append("projected_points")
        if mismatch_fields:
            metadata_mismatches.append(
                {"player_id": source.mlbam_id, "fields": mismatch_fields}
            )
    if metadata_mismatches:
        issues.append(
            ValidationIssue(
                "player_metadata_mismatch",
                "Serialized lineup player data differs from the frozen request player pool.",
                {"players": metadata_mismatches},
            )
        )

    calculated_projection = round(sum(player.projected_points for player in source_players), 2)
    if abs(lineup.projected_points - calculated_projection) > 1e-9:
        issues.append(
            ValidationIssue(
                "projection_total_mismatch",
                "Serialized projected points do not match the selected players.",
                {"serialized": lineup.projected_points, "calculated": calculated_projection},
            )
        )

    hitters_by_team = Counter(
        source.team
        for lineup_player in lineup.players
        if (source := player_by_id.get(lineup_player.mlbam_id)) is not None
        and normalize_output_slot(request.site, lineup_player.position_slot) != "P"
    )
    if request.site == "dk":
        over = {team: count for team, count in hitters_by_team.items() if count > 5}
        if over:
            issues.append(
                ValidationIssue(
                    "team_limit",
                    "DraftKings MLB Classic permits no more than five hitters from one team.",
                    {"hitters_by_team": over, "maximum_hitters": 5},
                )
            )
    else:
        total_by_team = Counter(player.team for player in source_players)
        over_hitters = {team: count for team, count in hitters_by_team.items() if count > 4}
        over_total = {team: count for team, count in total_by_team.items() if count > 5}
        if over_hitters or over_total:
            issues.append(
                ValidationIssue(
                    "team_limit",
                    "FanDuel MLB permits at most four hitters from one team and five total only when one is a pitcher.",
                    {
                        "hitters_by_team": over_hitters,
                        "players_by_team": over_total,
                        "maximum_hitters": 4,
                        "maximum_with_pitcher": 5,
                    },
                )
            )

    if request.settings.stack_team and request.settings.stack_count > 0:
        actual_stack = hitters_by_team[request.settings.stack_team]
        if actual_stack < request.settings.stack_count:
            issues.append(
                ValidationIssue(
                    "stack_requirement",
                    "The requested team stack was not satisfied.",
                    {
                        "team": request.settings.stack_team,
                        "required": request.settings.stack_count,
                        "actual": actual_stack,
                    },
                )
            )

    if request.settings.pitcher_vs_batter_same_team == "avoid":
        pitchers_missing_opponent = sorted(
            source.mlbam_id
            for lineup_player in lineup.players
            if (source := player_by_id.get(lineup_player.mlbam_id)) is not None
            and normalize_output_slot(request.site, lineup_player.position_slot) == "P"
            and not source.opponent
        )
        if pitchers_missing_opponent:
            issues.append(
                ValidationIssue(
                    "pitcher_opponent_missing",
                    "Pitcher opponent metadata is required when pitcher-versus-batter avoidance is enabled.",
                    {"pitcher_player_ids": pitchers_missing_opponent},
                )
            )
        pitcher_opponents = {
            source.opponent
            for lineup_player in lineup.players
            if (source := player_by_id.get(lineup_player.mlbam_id)) is not None
            and normalize_output_slot(request.site, lineup_player.position_slot) == "P"
            and source.opponent
        }
        conflicts = sorted(
            source.mlbam_id
            for lineup_player in lineup.players
            if (source := player_by_id.get(lineup_player.mlbam_id)) is not None
            and normalize_output_slot(request.site, lineup_player.position_slot) != "P"
            and source.team in pitcher_opponents
        )
        if conflicts:
            issues.append(
                ValidationIssue(
                    "pitcher_vs_batter",
                    "A selected hitter opposes a selected pitcher while the avoid rule is enabled.",
                    {"hitter_player_ids": conflicts},
                )
            )

    if exposure_counts is not None:
        for player in source_players:
            allowed = max_exposure_count(player.max_exposure, request.num_lineups)
            count = exposure_counts[player.mlbam_id]
            if count > allowed:
                issues.append(
                    ValidationIssue(
                        "max_exposure",
                        "A player's maximum exposure was exceeded.",
                        {
                            "player_id": player.mlbam_id,
                            "count": count,
                            "allowed": allowed,
                            "requested_lineups": request.num_lineups,
                            "lineup_index": lineup_index,
                        },
                    )
                )

    return ValidationResult(not issues, tuple(issues), assignment or ())


def validate_lineup_set(request: OptimizeRequest, lineups: Sequence[Lineup]) -> None:
    issues: list[ValidationIssue] = []
    request_ids = [player.mlbam_id for player in request.players]
    duplicate_request_ids = sorted(
        player_id for player_id, count in Counter(request_ids).items() if count > 1
    )
    if duplicate_request_ids:
        issues.append(
            ValidationIssue(
                "duplicate_player_id",
                "The request player pool contains duplicate IDs.",
                {"player_ids": duplicate_request_ids},
            )
        )
    conflicting_locks = sorted(
        player.mlbam_id
        for player in request.players
        if player.lock
        and (player.exclude or player.lineup_status == "dnp" or player.projected_points <= 0)
    )
    if conflicting_locks:
        issues.append(
            ValidationIssue(
                "lock_conflict",
                "A locked player cannot also be excluded, DNP, or have a non-positive projection.",
                {"player_ids": conflicting_locks},
            )
        )
    if len(lineups) != request.num_lineups:
        issues.append(
            ValidationIssue(
                "lineup_count",
                f"Requested {request.num_lineups} lineups but generated {len(lineups)}.",
                {"requested": request.num_lineups, "generated": len(lineups)},
            )
        )

    expected_numbers = list(range(1, len(lineups) + 1))
    actual_numbers = [lineup.lineup_number for lineup in lineups]
    if actual_numbers != expected_numbers:
        issues.append(
            ValidationIssue(
                "lineup_number_sequence",
                "Lineup numbers must be consecutive and ordered from 1.",
                {"expected": expected_numbers, "actual": actual_numbers},
            )
        )

    identities: set[tuple[int, ...]] = set()
    exposure_counts: Counter[int] = Counter()
    for lineup_index, lineup in enumerate(lineups, start=1):
        exposure_counts.update(player.mlbam_id for player in lineup.players)
        identity = lineup_identity(lineup.players)
        if request.settings.unique_lineups and identity in identities:
            issues.append(
                ValidationIssue(
                    "duplicate_lineup",
                    "unique_lineups is enabled but duplicate player sets were generated.",
                    {"lineup_index": lineup_index, "player_ids": list(identity)},
                )
            )
        identities.add(identity)

    for lineup_index, lineup in enumerate(lineups, start=1):
        result = validate_lineup(
            request,
            lineup,
            exposure_counts=exposure_counts,
            lineup_index=lineup_index,
        )
        issues.extend(result.issues)

    if issues:
        raise LineupValidationError(issues)
