from __future__ import annotations

import time
from collections import Counter

from models.schemas import Lineup, LineupPlayer, OptimizeRequest, OptimizeResponse, PlayerInput


DK_SLOTS = ["P", "P", "C/1B", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"]
FD_SLOTS = ["P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"]


class OptimizerError(Exception):
    pass


def run_optimizer_sync(request: OptimizeRequest) -> OptimizeResponse:
    start = time.perf_counter()
    warnings: list[str] = []
    available = [p for p in request.players if not p.exclude and p.projected_points > 0]
    locked = [p for p in available if p.lock]

    if not available:
        raise OptimizerError("No eligible players available for optimization")

    try:
        response = _run_pydfs_optimizer(request)
        response.solve_time_ms = int((time.perf_counter() - start) * 1000)
        return response
    except Exception as exc:
        warnings.append(f"Using built-in fallback optimizer: {exc}")

    slots = DK_SLOTS if request.site == "dk" else FD_SLOTS
    salary_cap = 50000 if request.site == "dk" else 35000
    lineups: list[Lineup] = []
    seen: set[tuple[int, ...]] = set()

    candidates = sorted(available, key=lambda p: p.projected_points / max(p.salary, 1), reverse=True)
    for lineup_number in range(1, request.num_lineups + 1):
        chosen = _build_best_lineup(
            slots=slots,
            candidates=candidates,
            locked=locked,
            salary_cap=salary_cap,
            min_salary=request.settings.min_salary_used,
            stack_team=request.settings.stack_team,
            stack_count=request.settings.stack_count,
            seen=seen if request.settings.unique_lineups else set(),
            offset=lineup_number - 1,
        )
        if not chosen:
            break
        ids = tuple(sorted(player.mlbam_id for _, player in chosen))
        seen.add(ids)
        lineups.append(
            Lineup(
                lineup_number=lineup_number,
                players=[
                    LineupPlayer(
                        mlbam_id=player.mlbam_id,
                        name=player.name,
                        position_slot=slot,
                        salary=player.salary,
                        projected_points=round(player.projected_points, 2),
                        team=player.team,
                    )
                    for slot, player in chosen
                ],
                total_salary=sum(player.salary for _, player in chosen),
                projected_points=round(sum(player.projected_points for _, player in chosen), 2),
            )
        )

    if not lineups:
        raise OptimizerError(
            "Salary constraint infeasible with current locks. Try removing some locked players."
        )

    return OptimizeResponse(
        lineups=lineups,
        solve_time_ms=int((time.perf_counter() - start) * 1000),
        warnings=warnings,
    )


def _run_pydfs_optimizer(request: OptimizeRequest) -> OptimizeResponse:
    raise RuntimeError("pydfs-lineup-optimizer adapter is not enabled in MVP fallback build")


def _build_best_lineup(
    slots: list[str],
    candidates: list[PlayerInput],
    locked: list[PlayerInput],
    salary_cap: int,
    min_salary: int,
    stack_team: str | None,
    stack_count: int,
    seen: set[tuple[int, ...]],
    offset: int,
) -> list[tuple[str, PlayerInput]] | None:
    rotated = candidates[offset:] + candidates[:offset]
    chosen: list[tuple[str, PlayerInput]] = []
    used: set[int] = set()

    for player in locked:
        slot = _first_open_slot(slots, chosen, player)
        if slot is None:
            return None
        chosen.append((slot, player))
        used.add(player.mlbam_id)

    open_slots = _remaining_slots(slots, chosen)
    best: list[tuple[str, PlayerInput]] | None = None
    best_points = -1.0

    def search(
        slot_index: int,
        partial: list[tuple[str, PlayerInput]],
        used_ids: set[int],
        salary: int,
        points: float,
    ) -> None:
        nonlocal best, best_points
        if salary > salary_cap:
            return
        if slot_index == len(open_slots):
            lineup = chosen + partial
            total_salary = sum(player.salary for _, player in lineup)
            if total_salary < min_salary:
                return
            ids = tuple(sorted(player.mlbam_id for _, player in lineup))
            if ids in seen:
                return
            if stack_team and stack_count > 0:
                team_counts = Counter(player.team for _, player in lineup if "P" not in player.position)
                if team_counts[stack_team] < stack_count:
                    return
            total_points = sum(player.projected_points for _, player in lineup)
            if total_points > best_points:
                best = lineup
                best_points = total_points
            return

        slot = open_slots[slot_index]
        eligible = [
            player
            for player in rotated
            if player.mlbam_id not in used_ids and _eligible_for_slot(player, slot)
        ]
        for player in eligible[:28]:
            search(
                slot_index + 1,
                partial + [(slot, player)],
                used_ids | {player.mlbam_id},
                salary + player.salary,
                points + player.projected_points,
            )

    locked_salary = sum(player.salary for _, player in chosen)
    locked_points = sum(player.projected_points for _, player in chosen)
    search(0, [], used, locked_salary, locked_points)
    return best


def _remaining_slots(slots: list[str], chosen: list[tuple[str, PlayerInput]]) -> list[str]:
    remaining = slots[:]
    for slot, _ in chosen:
        remaining.remove(slot)
    return remaining


def _first_open_slot(
    slots: list[str], chosen: list[tuple[str, PlayerInput]], player: PlayerInput
) -> str | None:
    used_slots = [slot for slot, _ in chosen]
    for slot in slots:
        if used_slots.count(slot) >= slots.count(slot):
            continue
        if _eligible_for_slot(player, slot):
            return slot
    return None


def _eligible_for_slot(player: PlayerInput, slot: str) -> bool:
    positions = set(player.position)
    if slot == "UTIL":
        return "P" not in positions
    if slot == "C/1B":
        return "C" in positions or "1B" in positions
    return slot in positions
