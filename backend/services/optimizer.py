from __future__ import annotations

import time
from collections import Counter

from models.schemas import Lineup, LineupPlayer, OptimizeRequest, OptimizeResponse, PlayerInput


DK_SLOTS = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]
FD_SLOTS = ["P", "C/1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"]


class OptimizerError(Exception):
    pass


def run_optimizer_sync(request: OptimizeRequest) -> OptimizeResponse:
    start = time.perf_counter()
    warnings: list[str] = []
    available = [
        player
        for player in request.players
        if not player.exclude and player.lineup_status != "dnp" and player.projected_points > 0
    ]
    locked = [player for player in available if player.lock]

    if not available:
        raise OptimizerError("No eligible players available for optimization")

    _validate_optimizer_request(request, available, locked)

    try:
        response = _run_pydfs_optimizer(request)
        response.solve_time_ms = int((time.perf_counter() - start) * 1000)
        return response
    except OptimizerError:
        raise
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
            avoid_pitcher_vs_batter=request.settings.pitcher_vs_batter_same_team == "avoid",
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
                players=[_serialize_lineup_player(slot, player) for slot, player in chosen],
                total_salary=sum(player.salary for _, player in chosen),
                projected_points=round(sum(player.projected_points for _, player in chosen), 2),
            )
        )

    if not lineups:
        raise OptimizerError(
            "Salary constraint infeasible with current locks/settings. Try removing locks or relaxing settings."
        )

    return OptimizeResponse(
        lineups=lineups,
        solve_time_ms=int((time.perf_counter() - start) * 1000),
        warnings=warnings,
    )


def _run_pydfs_optimizer(request: OptimizeRequest) -> OptimizeResponse:
    try:
        from pydfs_lineup_optimizer import Player, Site, Sport, get_optimizer
        from pydfs_lineup_optimizer.exceptions import GenerateLineupException, LineupOptimizerException
        from pydfs_lineup_optimizer.stacks import TeamStack
    except ImportError as exc:
        raise RuntimeError("pydfs-lineup-optimizer is not installed") from exc

    optimizer_site = Site.DRAFTKINGS if request.site == "dk" else Site.FANDUEL
    optimizer = get_optimizer(optimizer_site, Sport.BASEBALL)
    if request.settings.min_salary_used:
        optimizer.set_min_salary_cap(request.settings.min_salary_used)

    source_by_id: dict[str, PlayerInput] = {}
    pydfs_players = []
    for player in request.players:
        if player.exclude or player.lineup_status == "dnp" or player.projected_points <= 0:
            continue
        if player.salary <= 0:
            raise OptimizerError("Missing salary data. Upload a DK/FD salary CSV before optimizing.")
        pydfs_id = str(player.mlbam_id)
        source_by_id[pydfs_id] = player
        pydfs_players.append(
            Player(
                player_id=pydfs_id,
                first_name=_first_name(player.name),
                last_name=_last_name(player.name),
                positions=_pydfs_positions(player.position, request.site),
                team=player.team,
                salary=player.salary,
                fppg=player.projected_points,
                max_exposure=player.max_exposure,
            )
        )

    if not pydfs_players:
        raise OptimizerError("No eligible players available for optimization")

    optimizer.player_pool.load_players(pydfs_players)

    locked_ids = {str(player.mlbam_id) for player in request.players if player.lock and not player.exclude}
    for locked_id in locked_ids:
        optimizer.player_pool.lock_player(locked_id)

    if request.settings.stack_team and request.settings.stack_count > 0:
        optimizer.add_stack(
            TeamStack(
                request.settings.stack_count,
                for_teams=[request.settings.stack_team],
                for_positions=["C", "1B", "2B", "3B", "SS", "OF"],
            )
        )

    avoid_rule_active = (
        request.settings.pitcher_vs_batter_same_team == "avoid"
        and any(player.opponent for player in source_by_id.values())
    )
    try:
        solved_lineups = list(optimizer.optimize(request.num_lineups * 4 if avoid_rule_active else request.num_lineups))
    except (GenerateLineupException, LineupOptimizerException) as exc:
        raise OptimizerError(
            "Salary or roster constraints are infeasible with current locks/settings. "
            "Try removing locks, lowering min salary, or relaxing stack settings."
        ) from exc

    if not solved_lineups:
        raise OptimizerError("No lineups generated with current settings")

    lineups: list[Lineup] = []
    for solved in solved_lineups:
        solved_sources = [source_by_id[str(lineup_player.id)] for lineup_player in solved]
        if avoid_rule_active and _sources_violate_pitcher_vs_batter_rule(solved_sources):
            continue
        lineup_players: list[LineupPlayer] = []
        for lineup_player in solved:
            source = source_by_id[str(lineup_player.id)]
            lineup_players.append(
                LineupPlayer(
                    mlbam_id=source.mlbam_id,
                    name=source.name,
                    position_slot=str(lineup_player.lineup_position),
                    salary=source.salary,
                    projected_points=round(float(lineup_player.used_fppg), 2),
                    team=source.team,
                    external_id=source.external_id,
                    name_id=source.name_id,
                )
            )
        lineups.append(
            Lineup(
                lineup_number=len(lineups) + 1,
                players=lineup_players,
                total_salary=int(solved.salary_costs),
                projected_points=round(float(solved.fantasy_points_projection), 2),
            )
        )
        if len(lineups) >= request.num_lineups:
            break

    if not lineups and avoid_rule_active:
        retry_request = request.model_copy(deep=True)
        retry_request.settings.pitcher_vs_batter_same_team = "allow"
        response = _run_pydfs_optimizer(retry_request)
        response.warnings.append(
            "Pitcher-vs-batter restriction was relaxed because the current player pool could not "
            "produce a feasible lineup with that rule."
        )
        return response
    if not lineups:
        raise OptimizerError("No lineups generated with current settings")

    return OptimizeResponse(lineups=lineups, solve_time_ms=0, warnings=[])


def _validate_optimizer_request(
    request: OptimizeRequest,
    available: list[PlayerInput],
    locked: list[PlayerInput],
) -> None:
    slots = DK_SLOTS if request.site == "dk" else FD_SLOTS
    salary_cap = 50000 if request.site == "dk" else 35000

    missing_salary = [player.name for player in available if player.salary <= 0]
    if missing_salary:
        sample = ", ".join(missing_salary[:5])
        suffix = "..." if len(missing_salary) > 5 else ""
        raise OptimizerError(
            f"Missing salary data for {len(missing_salary)} eligible players: {sample}{suffix}. "
            "Upload a DK/FD salary CSV or exclude those players."
        )

    if request.settings.min_salary_used > salary_cap:
        raise OptimizerError(
            f"Minimum salary used (${request.settings.min_salary_used:,}) exceeds the "
            f"{request.site.upper()} salary cap (${salary_cap:,})."
        )

    locked_pitchers = [player.name for player in locked if "P" in player.position]
    pitcher_slots = slots.count("P")
    if len(locked_pitchers) > pitcher_slots:
        raise OptimizerError(
            f"You locked {len(locked_pitchers)} pitchers, but {request.site.upper()} allows {pitcher_slots}."
        )

    if len(locked) > len(slots):
        raise OptimizerError(
            f"You locked {len(locked)} players, but a {request.site.upper()} lineup only has {len(slots)} roster slots."
        )

    if request.settings.stack_team and request.settings.stack_count > 0:
        stackable = [
            player
            for player in available
            if player.team == request.settings.stack_team and "P" not in player.position
        ]
        if len(stackable) < request.settings.stack_count:
            raise OptimizerError(
                f"Stack requires {request.settings.stack_count} {request.settings.stack_team} hitters, "
                f"but only {len(stackable)} are eligible."
            )


def _serialize_lineup_player(slot: str, player: PlayerInput) -> LineupPlayer:
    return LineupPlayer(
        mlbam_id=player.mlbam_id,
        name=player.name,
        position_slot=slot,
        salary=player.salary,
        projected_points=round(player.projected_points, 2),
        team=player.team,
        external_id=player.external_id,
        name_id=player.name_id,
    )


def _pydfs_positions(positions: list[str], site: str) -> list[str]:
    mapped: list[str] = []
    for position in positions:
        if position == "P":
            mapped.append("SP" if site == "dk" else "P")
        elif position == "C/1B":
            mapped.extend(["C", "1B"])
        elif position == "UTIL":
            mapped.extend(["C", "1B", "2B", "3B", "SS", "OF"])
        else:
            mapped.append(position)
    return sorted(set(mapped))


def _first_name(full_name: str) -> str:
    parts = full_name.strip().split()
    return parts[0] if parts else full_name


def _last_name(full_name: str) -> str:
    parts = full_name.strip().split()
    return " ".join(parts[1:]) if len(parts) > 1 else ""


def _build_best_lineup(
    slots: list[str],
    candidates: list[PlayerInput],
    locked: list[PlayerInput],
    salary_cap: int,
    min_salary: int,
    stack_team: str | None,
    stack_count: int,
    avoid_pitcher_vs_batter: bool,
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
            if avoid_pitcher_vs_batter and _lineup_violates_pitcher_vs_batter_rule(lineup):
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


def _first_open_slot(slots: list[str], chosen: list[tuple[str, PlayerInput]], player: PlayerInput) -> str | None:
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


def _lineup_violates_pitcher_vs_batter_rule(lineup: list[tuple[str, PlayerInput]]) -> bool:
    return _sources_violate_pitcher_vs_batter_rule([player for _, player in lineup])


def _sources_violate_pitcher_vs_batter_rule(players: list[PlayerInput]) -> bool:
    pitcher_opponents = {
        player.opponent
        for player in players
        if "P" in player.position and player.opponent
    }
    if not pitcher_opponents:
        return False
    return any("P" not in player.position and player.team in pitcher_opponents for player in players)
