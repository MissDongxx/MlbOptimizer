from __future__ import annotations

import hashlib
import time
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

from models.schemas import Lineup, LineupPlayer, OptimizeRequest, OptimizeResponse, PlayerInput
from services.lineup_rules import (
    DK_SLOTS as _DK_SLOTS,
    FD_SLOTS as _FD_SLOTS,
    LineupValidationError,
    ValidationIssue,
    eligible_for_slot,
    lineup_identity,
    max_exposure_count,
    roster_slots,
    salary_cap,
    validate_lineup,
    validate_lineup_set,
)


DK_SLOTS = list(_DK_SLOTS)
FD_SLOTS = list(_FD_SLOTS)

Method = Literal["optimized", "random"]
MAX_FALLBACK_SEARCH_NODES = 1_500_000


class OptimizerError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "optimization_failed",
        details: dict[str, object] | None = None,
        issues: Sequence[ValidationIssue] = (),
    ):
        self.code = code
        self.details = details or {}
        self.issues = tuple(issues)
        super().__init__(message)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "message": str(self),
            "details": self.details,
        }
        if self.issues:
            payload["issues"] = [issue.to_dict() for issue in self.issues]
        return payload


@dataclass(frozen=True)
class _CandidateLineup:
    players: tuple[PlayerInput, ...]
    assigned_slots: tuple[str, ...]
    objective: float


class _SearchLimitReached(RuntimeError):
    pass


def run_optimizer_sync(request: OptimizeRequest) -> OptimizeResponse:
    """Backward-compatible API entry point using the optimized deterministic strategy."""

    return generate_lineups(request, method="optimized", seed=request.seed)


def generate_lineups(
    request: OptimizeRequest,
    *,
    method: Method,
    seed: int,
    prefer_pydfs: bool = False,
) -> OptimizeResponse:
    start = time.perf_counter()
    available = _eligible_players(request.players)
    _validate_optimizer_request(request, available)

    warnings: list[str] = []
    lineups: list[Lineup] | None = None
    pydfs_error: Exception | None = None
    if prefer_pydfs:
        try:
            lineups = _run_pydfs_optimizer(request, method=method, seed=seed)
        except OptimizerError:
            raise
        except Exception as exc:  # dependency/adapter failures only; constraints are never relaxed
            pydfs_error = exc

    if lineups is None:
        if pydfs_error is not None:
            warnings.append(f"Using strict built-in solver because pydfs was unavailable or incompatible: {pydfs_error}")
        lineups = _run_fallback_optimizer(request, method=method, seed=seed)

    try:
        validate_lineup_set(request, lineups)
    except LineupValidationError as exc:
        raise OptimizerError(
            "Generated lineups failed canonical validation; no partial result was returned.",
            code="generated_lineup_invalid",
            issues=exc.issues,
        ) from exc

    return OptimizeResponse(
        lineups=lineups,
        solve_time_ms=int((time.perf_counter() - start) * 1000),
        warnings=warnings,
        method=method,
        seed=seed,
    )


def _eligible_players(players: Iterable[PlayerInput]) -> list[PlayerInput]:
    return [
        player
        for player in players
        if not player.exclude and player.lineup_status != "dnp" and player.projected_points > 0
    ]


def _validate_optimizer_request(request: OptimizeRequest, available: Sequence[PlayerInput]) -> None:
    if not available:
        raise OptimizerError(
            "No eligible players are available for optimization.",
            code="empty_player_pool",
        )

    ids = [player.mlbam_id for player in request.players]
    duplicates = sorted(player_id for player_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise OptimizerError(
            "Duplicate player IDs make locks, exposure, and uniqueness ambiguous.",
            code="duplicate_player_id",
            details={"player_ids": duplicates},
        )

    missing_salary = [player.name for player in available if player.salary <= 0]
    if missing_salary:
        raise OptimizerError(
            "Eligible players are missing salary data.",
            code="missing_salary",
            details={"players": missing_salary[:20], "count": len(missing_salary)},
        )

    cap = salary_cap(request.site)
    if request.settings.min_salary_used > cap:
        raise OptimizerError(
            f"Minimum salary {request.settings.min_salary_used} exceeds the {cap} cap.",
            code="minimum_salary_above_cap",
            details={"minimum": request.settings.min_salary_used, "cap": cap},
        )

    locked = [player for player in available if player.lock]
    if len(locked) > len(roster_slots(request.site)):
        raise OptimizerError(
            "More players are locked than there are roster slots.",
            code="lock_conflict",
            details={"locked": len(locked), "slots": len(roster_slots(request.site))},
        )

    locked_ids = {player.mlbam_id for player in locked}
    excluded_locked = [
        player.mlbam_id
        for player in request.players
        if player.lock and (player.exclude or player.lineup_status == "dnp" or player.projected_points <= 0)
    ]
    if excluded_locked:
        raise OptimizerError(
            "A player cannot be both locked and ineligible/excluded.",
            code="lock_conflict",
            details={"player_ids": excluded_locked},
        )

    for player in locked:
        allowed = max_exposure_count(player.max_exposure, request.num_lineups)
        if allowed < request.num_lineups:
            raise OptimizerError(
                "A locked player must have 100% exposure because locks apply to every lineup.",
                code="lock_exposure_conflict",
                details={
                    "player_id": player.mlbam_id,
                    "max_exposure": player.max_exposure,
                    "allowed_lineups": allowed,
                    "requested_lineups": request.num_lineups,
                },
            )

    if locked and not _can_assign_partial_locks(request.site, available, locked_ids):
        raise OptimizerError(
            "Locked players cannot be assigned to distinct required positions.",
            code="lock_conflict",
            details={"player_ids": sorted(locked_ids)},
        )

    position_counts = {
        slot: sum(eligible_for_slot(player.position, slot) for player in available)
        for slot in sorted(set(roster_slots(request.site)))
    }
    short = {
        slot: {"available": count, "required": roster_slots(request.site).count(slot)}
        for slot, count in position_counts.items()
        if count < roster_slots(request.site).count(slot)
    }
    if short:
        raise OptimizerError(
            "The player pool does not contain enough eligible players for one or more positions.",
            code="position_pool_insufficient",
            details=short,
        )

    if request.settings.stack_team and request.settings.stack_count > 0:
        site_stack_limit = 5 if request.site == "dk" else 4
        if request.settings.stack_count > site_stack_limit:
            raise OptimizerError(
                "The requested hitter stack exceeds the site's Classic roster limit.",
                code="stack_infeasible",
                details={
                    "team": request.settings.stack_team,
                    "required": request.settings.stack_count,
                    "site_maximum_hitters": site_stack_limit,
                },
            )
        stackable = [
            player
            for player in available
            if player.team == request.settings.stack_team
            and any(position not in {"P", "SP", "RP"} for position in player.position)
        ]
        if len(stackable) < request.settings.stack_count:
            raise OptimizerError(
                "The requested team stack is impossible with the eligible player pool.",
                code="stack_infeasible",
                details={
                    "team": request.settings.stack_team,
                    "required": request.settings.stack_count,
                    "available": len(stackable),
                },
            )


def _can_assign_partial_locks(site: str, available: Sequence[PlayerInput], locked_ids: set[int]) -> bool:
    locked = [player for player in available if player.mlbam_id in locked_ids]
    slots = roster_slots(site)
    choices = [
        (
            player.mlbam_id,
            tuple(index for index, slot in enumerate(slots) if eligible_for_slot(player.position, slot)),
        )
        for player in locked
    ]
    choices.sort(key=lambda item: (len(item[1]), item[0]))
    used: set[int] = set()

    def search(index: int) -> bool:
        if index == len(choices):
            return True
        _, eligible_indexes = choices[index]
        for slot_index in eligible_indexes:
            if slot_index in used:
                continue
            used.add(slot_index)
            if search(index + 1):
                return True
            used.remove(slot_index)
        return False

    return search(0)


def _run_pydfs_optimizer(request: OptimizeRequest, *, method: Method, seed: int) -> list[Lineup]:
    try:
        from pydfs_lineup_optimizer import Player, Site, Sport, get_optimizer
        from pydfs_lineup_optimizer.exceptions import GenerateLineupException, LineupOptimizerException
        from pydfs_lineup_optimizer.stacks import TeamStack
    except ImportError as exc:
        raise RuntimeError("pydfs-lineup-optimizer 3.6.1 is not installed") from exc

    optimizer_site = Site.DRAFTKINGS if request.site == "dk" else Site.FANDUEL
    optimizer = get_optimizer(optimizer_site, Sport.BASEBALL)
    optimizer.set_min_salary_cap(request.settings.min_salary_used)

    source_by_id: dict[str, PlayerInput] = {}
    pydfs_players = []
    for player in _eligible_players(request.players):
        player_id = str(player.mlbam_id)
        source_by_id[player_id] = player
        objective = _objective_value(player, method=method, seed=seed, lineup_number=0, prior_count=0)
        pydfs_players.append(
            Player(
                player_id=player_id,
                first_name=_first_name(player.name),
                last_name=_last_name(player.name),
                positions=_pydfs_positions(player.position, request.site),
                team=player.team,
                salary=player.salary,
                fppg=objective,
                max_exposure=player.max_exposure,
            )
        )
    optimizer.player_pool.load_players(pydfs_players)

    for player in request.players:
        if player.lock and not player.exclude:
            optimizer.player_pool.lock_player(str(player.mlbam_id))

    if request.settings.stack_team and request.settings.stack_count > 0:
        optimizer.add_stack(
            TeamStack(
                request.settings.stack_count,
                for_teams=[request.settings.stack_team],
                for_positions=["C", "1B", "2B", "3B", "SS", "OF"],
            )
        )

    # pydfs cannot apply the opposing-team rule without game_info. The adapter deliberately does
    # not guess game metadata. It may produce candidates, but every result is validated below;
    # any insufficiency falls back to the strict built-in solver without relaxing constraints.
    candidate_count = min(max(request.num_lineups * 20, request.num_lineups), 400)
    try:
        solved_lineups = list(optimizer.optimize(candidate_count))
    except (GenerateLineupException, LineupOptimizerException) as exc:
        raise RuntimeError(f"pydfs could not solve the strict request: {exc}") from exc

    accepted: list[Lineup] = []
    accepted_identities: set[tuple[int, ...]] = set()
    exposure_counts: Counter[int] = Counter()
    for solved in solved_lineups:
        source_players = [source_by_id[str(player.id)] for player in solved]
        lineup_players = [
            LineupPlayer(
                mlbam_id=source.mlbam_id,
                name=source.name,
                position_slot=str(lineup_player.lineup_position),
                salary=source.salary,
                projected_points=round(source.projected_points, 2),
                team=source.team,
                external_id=source.external_id,
                name_id=source.name_id,
            )
            for lineup_player, source in zip(solved, source_players, strict=True)
        ]
        lineup = Lineup(
            lineup_number=len(accepted) + 1,
            players=lineup_players,
            total_salary=sum(player.salary for player in source_players),
            projected_points=round(sum(player.projected_points for player in source_players), 2),
        )
        identity = lineup_identity(lineup.players)
        if request.settings.unique_lineups and identity in accepted_identities:
            continue
        tentative_counts = exposure_counts.copy()
        tentative_counts.update(player.mlbam_id for player in lineup.players)
        if not validate_lineup(request, lineup, exposure_counts=tentative_counts).valid:
            continue
        accepted.append(lineup)
        accepted_identities.add(identity)
        exposure_counts = tentative_counts
        if len(accepted) == request.num_lineups:
            break

    if len(accepted) != request.num_lineups:
        raise RuntimeError(
            f"pydfs produced only {len(accepted)} canonically valid lineups; strict fallback required"
        )
    return accepted


def _run_fallback_optimizer(request: OptimizeRequest, *, method: Method, seed: int) -> list[Lineup]:
    available = _eligible_players(request.players)
    exposure_counts: Counter[int] = Counter()
    seen: set[tuple[int, ...]] = set()
    lineups: list[Lineup] = []

    for lineup_number in range(1, request.num_lineups + 1):
        objective_by_id = {
            player.mlbam_id: _objective_value(
                player,
                method=method,
                seed=seed,
                lineup_number=lineup_number,
                prior_count=exposure_counts[player.mlbam_id],
            )
            for player in available
        }
        try:
            candidate = _find_best_lineup(
                request,
                available,
                objective_by_id=objective_by_id,
                exposure_counts=exposure_counts,
                seen=seen,
            )
        except _SearchLimitReached as exc:
            raise OptimizerError(
                "The strict built-in solver reached its audited search limit; no partial lineup set was returned.",
                code="solver_capacity",
                details={"node_limit": MAX_FALLBACK_SEARCH_NODES, "lineup_number": lineup_number},
            ) from exc

        if candidate is None:
            code, message, details = _diagnose_no_solution(
                request,
                available,
                exposure_counts=exposure_counts,
                seen=seen,
                lineup_number=lineup_number,
            )
            raise OptimizerError(message, code=code, details=details)

        lineup = _serialize_candidate(candidate, lineup_number)
        lineups.append(lineup)
        identity = lineup_identity(lineup.players)
        seen.add(identity)
        exposure_counts.update(player.mlbam_id for player in lineup.players)

    return lineups


def _find_best_lineup(
    request: OptimizeRequest,
    available: Sequence[PlayerInput],
    *,
    objective_by_id: dict[int, float],
    exposure_counts: Counter[int],
    seen: set[tuple[int, ...]],
    enforce_salary: bool = True,
    enforce_team_limits: bool = True,
    enforce_stack: bool = True,
    enforce_pitcher_batter: bool = True,
    enforce_exposure: bool = True,
    enforce_unique: bool = True,
) -> _CandidateLineup | None:
    if all(
        (
            enforce_salary,
            enforce_team_limits,
            enforce_stack,
            enforce_pitcher_batter,
            enforce_exposure,
            enforce_unique,
        )
    ):
        candidate = _find_best_lineup_milp(
            request,
            available,
            objective_by_id=objective_by_id,
            exposure_counts=exposure_counts,
            seen=seen,
        )
        if candidate is not NotImplemented:
            return candidate

    slots = list(roster_slots(request.site))
    cap = salary_cap(request.site)
    locked_ids = {player.mlbam_id for player in available if player.lock}

    usable = []
    for player in available:
        if enforce_exposure:
            allowed = max_exposure_count(player.max_exposure, request.num_lineups)
            if exposure_counts[player.mlbam_id] >= allowed:
                continue
        usable.append(player)

    slot_candidates: dict[int, list[PlayerInput]] = {}
    for slot_index, slot in enumerate(slots):
        candidates = [player for player in usable if eligible_for_slot(player.position, slot)]
        candidates.sort(
            key=lambda player: (
                -objective_by_id.get(player.mlbam_id, 0.0),
                -player.projected_points,
                player.salary,
                player.mlbam_id,
            )
        )
        slot_candidates[slot_index] = candidates

    slot_order = sorted(
        range(len(slots)),
        key=lambda index: (len(slot_candidates[index]), slots[index] == "UTIL", index),
    )
    best: _CandidateLineup | None = None
    nodes = 0

    def recurse(
        depth: int,
        selected: list[PlayerInput],
        assigned: list[tuple[int, str]],
        used_ids: set[int],
        total_salary: int,
        objective: float,
        hitters_by_team: Counter[str],
        total_by_team: Counter[str],
        pitcher_opponents: set[str],
        hitter_teams: set[str],
    ) -> None:
        nonlocal best, nodes
        nodes += 1
        if nodes > MAX_FALLBACK_SEARCH_NODES:
            raise _SearchLimitReached

        remaining = len(slot_order) - depth
        if len(locked_ids.difference(used_ids)) > remaining:
            return
        if enforce_salary and total_salary > cap:
            return

        if depth == len(slot_order):
            if not locked_ids.issubset(used_ids):
                return
            if enforce_salary and total_salary < request.settings.min_salary_used:
                return
            if enforce_stack and request.settings.stack_team and request.settings.stack_count > 0:
                if hitters_by_team[request.settings.stack_team] < request.settings.stack_count:
                    return
            identity = tuple(sorted(used_ids))
            if enforce_unique and request.settings.unique_lineups and identity in seen:
                return
            assigned_by_original_slot = [""] * len(slots)
            player_by_original_slot: list[PlayerInput | None] = [None] * len(slots)
            for player, (slot_index, slot) in zip(selected, assigned, strict=True):
                assigned_by_original_slot[slot_index] = slot
                player_by_original_slot[slot_index] = player
            ordered_players = tuple(player for player in player_by_original_slot if player is not None)
            ordered_slots = tuple(assigned_by_original_slot)
            candidate = _CandidateLineup(ordered_players, ordered_slots, objective)
            if best is None or _candidate_is_better(candidate, best):
                best = candidate
            return

        # Optimistic bound from the best remaining candidate in each slot, ignoring collisions.
        if best is not None:
            optimistic = objective
            for future_depth in range(depth, len(slot_order)):
                index = slot_order[future_depth]
                values = [
                    objective_by_id.get(player.mlbam_id, 0.0)
                    for player in slot_candidates[index]
                    if player.mlbam_id not in used_ids
                ]
                if not values:
                    return
                optimistic += max(values)
            if optimistic < best.objective - 1e-12:
                return

        slot_index = slot_order[depth]
        slot = slots[slot_index]
        for player in slot_candidates[slot_index]:
            if player.mlbam_id in used_ids:
                continue
            is_pitcher = slot == "P"
            if enforce_team_limits:
                if request.site == "dk" and not is_pitcher and hitters_by_team[player.team] >= 5:
                    continue
                if request.site == "fd":
                    if not is_pitcher and hitters_by_team[player.team] >= 4:
                        continue
                    if total_by_team[player.team] >= 5:
                        continue
            if enforce_pitcher_batter and request.settings.pitcher_vs_batter_same_team == "avoid":
                if is_pitcher and not player.opponent:
                    continue
                if is_pitcher and player.opponent in hitter_teams:
                    continue
                if not is_pitcher and player.team in pitcher_opponents:
                    continue

            next_hitters = hitters_by_team.copy()
            next_total = total_by_team.copy()
            next_pitcher_opponents = set(pitcher_opponents)
            next_hitter_teams = set(hitter_teams)
            next_total[player.team] += 1
            if is_pitcher:
                if player.opponent:
                    next_pitcher_opponents.add(player.opponent)
            else:
                next_hitters[player.team] += 1
                next_hitter_teams.add(player.team)

            recurse(
                depth + 1,
                selected + [player],
                assigned + [(slot_index, slot)],
                used_ids | {player.mlbam_id},
                total_salary + player.salary,
                objective + objective_by_id.get(player.mlbam_id, 0.0),
                next_hitters,
                next_total,
                next_pitcher_opponents,
                next_hitter_teams,
            )

    recurse(0, [], [], set(), 0, 0.0, Counter(), Counter(), set(), set())
    return best


def _find_best_lineup_milp(
    request: OptimizeRequest,
    available: Sequence[PlayerInput],
    *,
    objective_by_id: dict[int, float],
    exposure_counts: Counter[int],
    seen: set[tuple[int, ...]],
) -> _CandidateLineup | None | Literal[NotImplemented]:
    """Solve the complete audited constraint set with SciPy/HiGHS.

    Variables represent eligible player/slot assignments, so position legality is structural.
    The canonical validator still checks every returned lineup before it can leave the service.
    """
    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import lil_matrix
    except ImportError:
        return NotImplemented

    slots = list(roster_slots(request.site))
    usable = [
        player
        for player in available
        if exposure_counts[player.mlbam_id]
        < max_exposure_count(player.max_exposure, request.num_lineups)
    ]
    variables = [
        (player_index, slot_index)
        for player_index, player in enumerate(usable)
        for slot_index, slot in enumerate(slots)
        if eligible_for_slot(player.position, slot)
        and not (
            request.settings.pitcher_vs_batter_same_team == "avoid"
            and slot == "P"
            and not player.opponent
        )
    ]
    if not variables:
        return None
    variable_index = {pair: index for index, pair in enumerate(variables)}
    rows: list[dict[int, float]] = []
    lower: list[float] = []
    upper: list[float] = []

    def add(coefficients: dict[int, float], minimum: float, maximum: float) -> None:
        rows.append(coefficients)
        lower.append(minimum)
        upper.append(maximum)

    for slot_index in range(len(slots)):
        add(
            {
                variable_index[(player_index, slot_index)]: 1.0
                for player_index in range(len(usable))
                if (player_index, slot_index) in variable_index
            },
            1.0,
            1.0,
        )
    for player_index, player in enumerate(usable):
        indexes = {
            variable_index[(player_index, slot_index)]: 1.0
            for slot_index in range(len(slots))
            if (player_index, slot_index) in variable_index
        }
        add(indexes, 1.0 if player.lock else 0.0, 1.0)

    salary_coefficients = {
        variable_index[(player_index, slot_index)]: float(usable[player_index].salary)
        for player_index, slot_index in variables
    }
    add(
        salary_coefficients,
        float(request.settings.min_salary_used),
        float(salary_cap(request.site)),
    )

    teams = sorted({player.team for player in usable if player.team})
    for team in teams:
        hitter_coefficients = {
            variable_index[(player_index, slot_index)]: 1.0
            for player_index, slot_index in variables
            if usable[player_index].team == team and slots[slot_index] != "P"
        }
        if hitter_coefficients:
            add(hitter_coefficients, 0.0, 5.0 if request.site == "dk" else 4.0)
        if request.site == "fd":
            total_coefficients = {
                variable_index[(player_index, slot_index)]: 1.0
                for player_index, slot_index in variables
                if usable[player_index].team == team
            }
            if total_coefficients:
                add(total_coefficients, 0.0, 5.0)

    if request.settings.stack_team and request.settings.stack_count > 0:
        stack_coefficients = {
            variable_index[(player_index, slot_index)]: 1.0
            for player_index, slot_index in variables
            if usable[player_index].team == request.settings.stack_team
            and slots[slot_index] != "P"
        }
        add(stack_coefficients, float(request.settings.stack_count), np.inf)

    if request.settings.pitcher_vs_batter_same_team == "avoid":
        pitcher_indexes = {
            player_index: [
                variable_index[(player_index, slot_index)]
                for slot_index, slot in enumerate(slots)
                if slot == "P" and (player_index, slot_index) in variable_index
            ]
            for player_index, player in enumerate(usable)
            if player.opponent
        }
        for pitcher_index, pitcher_variables in pitcher_indexes.items():
            opponent = usable[pitcher_index].opponent
            for batter_index, batter in enumerate(usable):
                if batter.team != opponent:
                    continue
                batter_variables = [
                    variable_index[(batter_index, slot_index)]
                    for slot_index, slot in enumerate(slots)
                    if slot != "P" and (batter_index, slot_index) in variable_index
                ]
                if pitcher_variables and batter_variables:
                    add(
                        {
                            **{index: 1.0 for index in pitcher_variables},
                            **{index: 1.0 for index in batter_variables},
                        },
                        0.0,
                        1.0,
                    )

    player_indexes_by_id = {player.mlbam_id: index for index, player in enumerate(usable)}
    for identity in seen:
        coefficients: dict[int, float] = {}
        for player_id in identity:
            player_index = player_indexes_by_id.get(player_id)
            if player_index is None:
                continue
            for slot_index in range(len(slots)):
                index = variable_index.get((player_index, slot_index))
                if index is not None:
                    coefficients[index] = 1.0
        if coefficients:
            add(coefficients, 0.0, float(len(slots) - 1))

    matrix = lil_matrix((len(rows), len(variables)), dtype=float)
    for row_index, coefficients in enumerate(rows):
        for column_index, value in coefficients.items():
            matrix[row_index, column_index] = value
    objective = np.asarray(
        [
            -objective_by_id.get(usable[player_index].mlbam_id, 0.0)
            for player_index, _ in variables
        ],
        dtype=float,
    )
    result = milp(
        c=objective,
        integrality=np.ones(len(variables), dtype=int),
        bounds=Bounds(np.zeros(len(variables)), np.ones(len(variables))),
        constraints=LinearConstraint(matrix.tocsr(), np.asarray(lower), np.asarray(upper)),
        options={"time_limit": 10.0, "mip_rel_gap": 0.0, "presolve": True},
    )
    if result.status == 2:
        return None
    if not result.success or result.x is None:
        raise _SearchLimitReached(str(result.message))

    selected_by_slot: list[PlayerInput | None] = [None] * len(slots)
    for value, (player_index, slot_index) in zip(result.x, variables, strict=True):
        if value > 0.5:
            selected_by_slot[slot_index] = usable[player_index]
    if any(player is None for player in selected_by_slot):
        raise _SearchLimitReached("HiGHS returned an incomplete integral assignment")
    selected = tuple(player for player in selected_by_slot if player is not None)
    return _CandidateLineup(
        players=selected,
        assigned_slots=tuple(slots),
        objective=sum(objective_by_id.get(player.mlbam_id, 0.0) for player in selected),
    )


def _candidate_is_better(candidate: _CandidateLineup, incumbent: _CandidateLineup) -> bool:
    if candidate.objective > incumbent.objective + 1e-12:
        return True
    if abs(candidate.objective - incumbent.objective) > 1e-12:
        return False
    # Identity-only tie breaking keeps the random baseline independent of projections and salary.
    # The optimized objective already contains projected points explicitly.
    return lineup_identity(candidate.players) < lineup_identity(incumbent.players)


def _serialize_candidate(candidate: _CandidateLineup, lineup_number: int) -> Lineup:
    lineup_players = [
        LineupPlayer(
            mlbam_id=player.mlbam_id,
            name=player.name,
            position_slot=slot,
            salary=player.salary,
            projected_points=round(player.projected_points, 2),
            team=player.team,
            external_id=player.external_id,
            name_id=player.name_id,
        )
        for player, slot in zip(candidate.players, candidate.assigned_slots, strict=True)
    ]
    return Lineup(
        lineup_number=lineup_number,
        players=lineup_players,
        total_salary=sum(player.salary for player in candidate.players),
        projected_points=round(sum(player.projected_points for player in candidate.players), 2),
    )


def _diagnose_no_solution(
    request: OptimizeRequest,
    available: Sequence[PlayerInput],
    *,
    exposure_counts: Counter[int],
    seen: set[tuple[int, ...]],
    lineup_number: int,
) -> tuple[str, str, dict[str, object]]:
    zero_objective = {player.mlbam_id: 0.0 for player in available}
    stages: list[tuple[str, dict[str, bool], str]] = [
        (
            "position_or_lock_infeasible",
            dict(
                enforce_salary=False,
                enforce_team_limits=False,
                enforce_stack=False,
                enforce_pitcher_batter=False,
                enforce_exposure=False,
                enforce_unique=False,
            ),
            "Roster positions and locks cannot be satisfied by the current player pool.",
        ),
        (
            "team_limit_infeasible",
            dict(
                enforce_salary=False,
                enforce_team_limits=True,
                enforce_stack=False,
                enforce_pitcher_batter=False,
                enforce_exposure=False,
                enforce_unique=False,
            ),
            "The site team-limit rules make the roster infeasible for this player pool.",
        ),
        (
            "salary_infeasible",
            dict(
                enforce_salary=True,
                enforce_stack=False,
                enforce_pitcher_batter=False,
                enforce_exposure=False,
                enforce_unique=False,
            ),
            "No legal roster can satisfy both the salary cap and minimum salary.",
        ),
        (
            "stack_infeasible",
            dict(
                enforce_salary=True,
                enforce_stack=True,
                enforce_pitcher_batter=False,
                enforce_exposure=False,
                enforce_unique=False,
            ),
            "The requested stack cannot coexist with the roster and salary constraints.",
        ),
        (
            "pitcher_batter_infeasible",
            dict(
                enforce_salary=True,
                enforce_stack=True,
                enforce_pitcher_batter=True,
                enforce_exposure=False,
                enforce_unique=False,
            ),
            "The pitcher-versus-batter avoidance rule makes the request infeasible.",
        ),
    ]

    previous_feasible = True
    for code, flags, message in stages:
        try:
            feasible = _find_best_lineup(
                request,
                available,
                objective_by_id=zero_objective,
                exposure_counts=Counter(),
                seen=set(),
                **flags,
            ) is not None
        except _SearchLimitReached:
            return (
                "solver_capacity",
                "The strict built-in solver reached its audited search limit while diagnosing infeasibility.",
                {
                    "failed_at_lineup": lineup_number,
                    "node_limit": MAX_FALLBACK_SEARCH_NODES,
                },
            )
        if previous_feasible and not feasible:
            return code, message, {"failed_at_lineup": lineup_number}
        previous_feasible = feasible

    exposure_blocked = sorted(
        {
            player.mlbam_id
            for player in available
            if exposure_counts[player.mlbam_id]
            >= max_exposure_count(player.max_exposure, request.num_lineups)
        }
    )
    return (
        "exposure_or_uniqueness_infeasible",
        "Exposure ceilings or unique-lineup requirements leave too few legal combinations.",
        {
            "failed_at_lineup": lineup_number,
            "generated_before_failure": lineup_number - 1,
            "exposure_blocked_player_ids": exposure_blocked,
            "seen_unique_lineups": len(seen),
        },
    )


def _objective_value(
    player: PlayerInput,
    *,
    method: Method,
    seed: int,
    lineup_number: int,
    prior_count: int,
) -> float:
    random_component = _stable_unit_interval(seed, method, lineup_number, player.mlbam_id)
    if method == "random":
        # Explicit random-utility baseline: each player receives a seeded iid-looking priority;
        # the exact solver chooses the highest-priority legal roster. No rejection sampling and no
        # projection or actual-points field enters this objective.
        return random_component

    # Minimal explainable enhancement over raw projection: keep projection dominant, apply a small
    # deterministic diversity penalty, and use a tiny seeded tie-breaker. No post-game field is used.
    diversity_penalty = 0.035 * player.projected_points * prior_count
    return player.projected_points - diversity_penalty + random_component * 1e-6


def _stable_unit_interval(seed: int, method: str, lineup_number: int, player_id: int) -> float:
    digest = hashlib.sha256(f"{seed}|{method}|{lineup_number}|{player_id}".encode()).digest()
    integer = int.from_bytes(digest[:8], "big")
    return integer / float(2**64 - 1)


def _pydfs_positions(positions: Sequence[str], site: str) -> list[str]:
    mapped: set[str] = set()
    for position in positions:
        if position in {"P", "SP", "RP"}:
            mapped.add("SP" if site == "dk" else "P")
        elif position == "C/1B":
            mapped.update({"C", "1B"})
        elif position == "UTIL":
            mapped.update({"C", "1B", "2B", "3B", "SS", "OF"})
        else:
            mapped.add(position)
    return sorted(mapped)


def _first_name(full_name: str) -> str:
    parts = full_name.strip().split()
    return parts[0] if parts else full_name


def _last_name(full_name: str) -> str:
    parts = full_name.strip().split()
    return " ".join(parts[1:]) if len(parts) > 1 else ""
