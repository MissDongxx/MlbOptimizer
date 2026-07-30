from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from statistics import fmean
from typing import Iterable, Literal


Role = Literal["hitter", "pitcher"]
PROJECTION_VERSION = "strict-pre-first-pitch-shrunk-rolling-v2"
ROLE_PRIORS = {"hitter": 7.0, "pitcher": 14.0}


@dataclass(frozen=True)
class HistoricalFantasyGame:
    mlbam_id: int
    game_id: int
    game_date: date
    role: Role
    dk_points: float
    completed_at: datetime | None = None

    def availability_timestamp(self) -> datetime:
        """Return the earliest timestamp at which this final game row was usable.

        Legacy date-only fixtures are treated conservatively as available at the next
        UTC midnight. Real historical inputs must provide completed_at in the builder.
        """
        if self.completed_at is not None:
            if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
                raise ValueError("historical completed_at must include a timezone offset")
            return self.completed_at
        return datetime.combine(self.game_date, time.max, tzinfo=UTC)


def project_player(
    history: Iterable[HistoricalFantasyGame],
    *,
    mlbam_id: int,
    role: Role,
    cutoff: datetime,
    window: int = 20,
    prior_weight: float = 5.0,
) -> tuple[float, dict[str, int | float | str | list[int]]]:
    """Project from final games available strictly before first pitch.

    Rows at the cutoff instant and future rows are excluded. A fixed role prior is
    blended with the most recent ``window`` games. The formula and priors are declared
    in code and are never tuned per slate.
    """
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("cutoff must include a timezone offset")
    if window < 1:
        raise ValueError("window must be positive")
    if prior_weight < 0:
        raise ValueError("prior_weight cannot be negative")

    player_rows = [
        item for item in history if item.mlbam_id == mlbam_id and item.role == role
    ]
    eligible = sorted(
        (item for item in player_rows if item.availability_timestamp() < cutoff),
        key=lambda item: (item.availability_timestamp(), item.game_id),
    )[-window:]
    blocked = [item for item in player_rows if item.availability_timestamp() >= cutoff]
    prior = ROLE_PRIORS[role]
    if eligible:
        total = sum(item.dk_points for item in eligible) + prior * prior_weight
        denominator = len(eligible) + prior_weight
        projection = total / denominator if denominator else fmean(item.dk_points for item in eligible)
    else:
        projection = prior
    metadata: dict[str, int | float | str | list[int]] = {
        "projection_version": PROJECTION_VERSION,
        "cutoff_timestamp_exclusive": cutoff.isoformat(),
        "history_games_used": len(eligible),
        "history_game_ids_used": [item.game_id for item in eligible],
        "cutoff_or_future_rows_ignored": len(blocked),
        "window": window,
        "prior_weight": prior_weight,
        "role_prior": prior,
    }
    return round(projection, 6), metadata
