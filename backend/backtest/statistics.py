from __future__ import annotations

import math
import random
from statistics import fmean, stdev
from typing import Callable, Sequence


def standard_error(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    return stdev(values) / math.sqrt(len(values))


def paired_bootstrap_ci(
    pairs: Sequence[tuple[float, float]],
    *,
    statistic: Callable[[Sequence[tuple[float, float]]], float],
    seed: int,
    samples: int = 2000,
    alpha: float = 0.05,
) -> tuple[float | None, float | None]:
    if not pairs:
        return None, None
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(samples):
        resample = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
        estimates.append(statistic(resample))
    estimates.sort()
    low_index = max(0, math.floor((alpha / 2) * (len(estimates) - 1)))
    high_index = min(
        len(estimates) - 1,
        math.ceil((1 - alpha / 2) * (len(estimates) - 1)),
    )
    return estimates[low_index], estimates[high_index]


def mean_difference(pairs: Sequence[tuple[float, float]]) -> float:
    return fmean(left - right for left, right in pairs)


def relative_mean_difference(pairs: Sequence[tuple[float, float]]) -> float:
    left = fmean(item[0] for item in pairs)
    right = fmean(item[1] for item in pairs)
    if right == 0:
        return math.inf if left > 0 else 0.0
    return (left - right) / abs(right)
