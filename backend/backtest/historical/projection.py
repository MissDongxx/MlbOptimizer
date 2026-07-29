from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from statistics import fmean
from typing import Iterable, Literal


Role = Literal["hitter", "pitcher"]
PROJECTION_VERSION = "strict-prior-date-shrunk-rolling-v1"
ROLE_PRIORS = {"hitter": 7.0, "pitcher": 14.0}


@dataclass(frozen=True)
class HistoricalFantasyGame:
    mlbam_id: int
    game_id: int
    game_date: date
    role: Role
    dk_points: float


def project_player(
    history: Iterable[HistoricalFantasyGame],
    *,
    mlbam_id: int,
    role: Role,
    cutoff: datetime,
    window: int = 20,
    prior_weight: float = 5.0,
) -> tuple[float, dict[str, int | float | str]]:
    """Projection using only games whose calendar date is strictly before cutoff date.

    A fixed role prior is blended with the most recent `window` games. The formula and
    priors are declared in code and are not tuned per slate.
    """
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("cutoff must include a timezone offset")
    if window < 1:
        raise ValueError("window must be positive")
    if prior_weight < 0:
        raise ValueError("prior_weight cannot be negative")

    eligible = sorted(
        (
            item
            for item in history
            if item.mlbam_id == mlbam_id
            and item.role == role
            and item.game_date < cutoff.date()
        ),
        key=lambda item: (item.game_date, item.game_id),
    )[-window:]
    leaked = [
        item
        for item in history
        if item.mlbam_id == mlbam_id
        and item.role == role
        and item.game_date >= cutoff.date()
    ]
    # Presence of future rows in the source is allowed, but they are never selected.
    # The audit metadata records the exact cutoff and selected game IDs.
    prior = ROLE_PRIORS[role]
    if eligible:
        total = sum(item.dk_points for item in eligible) + prior * prior_weight
        denominator = len(eligible) + prior_weight
        projection = (
            total / denominator
            if denominator
            else fmean(item.dk_points for item in eligible)
        )
    else:
        projection = prior
    metadata: dict[str, int | float | str] = {
        "projection_version": PROJECTION_VERSION,
        "cutoff_date_exclusive": cutoff.date().isoformat(),
        "history_games_used": len(eligible),
        "future_rows_ignored": len(leaked),
        "window": window,
        "prior_weight": prior_weight,
        "role_prior": prior,
    }
    return round(projection, 6), metadata
