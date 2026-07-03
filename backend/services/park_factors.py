from __future__ import annotations

from typing import Any


DEFAULT_PARK_FACTOR = {
    "run_factor": 1.0,
    "hr_factor": 1.0,
    "source": "neutral_default",
}

PARK_FACTORS: dict[str, dict[str, Any]] = {
    "american family field": {"run_factor": 1.02, "hr_factor": 1.08},
    "angel stadium": {"run_factor": 0.99, "hr_factor": 1.02},
    "busch stadium": {"run_factor": 0.96, "hr_factor": 0.92},
    "chase field": {"run_factor": 1.03, "hr_factor": 0.98},
    "citi field": {"run_factor": 0.96, "hr_factor": 0.94},
    "citizens bank park": {"run_factor": 1.03, "hr_factor": 1.12},
    "comerica park": {"run_factor": 0.99, "hr_factor": 0.88},
    "coors field": {"run_factor": 1.18, "hr_factor": 1.15},
    "dodger stadium": {"run_factor": 0.99, "hr_factor": 1.05},
    "fenway park": {"run_factor": 1.05, "hr_factor": 0.96},
    "globe life field": {"run_factor": 1.01, "hr_factor": 1.03},
    "great american ball park": {"run_factor": 1.04, "hr_factor": 1.18},
    "guaranteed rate field": {"run_factor": 1.01, "hr_factor": 1.08},
    "kauffman stadium": {"run_factor": 1.01, "hr_factor": 0.88},
    "loandepot park": {"run_factor": 0.94, "hr_factor": 0.89},
    "minute maid park": {"run_factor": 1.01, "hr_factor": 1.03},
    "nationals park": {"run_factor": 1.0, "hr_factor": 1.01},
    "oakland coliseum": {"run_factor": 0.94, "hr_factor": 0.87},
    "oracle park": {"run_factor": 0.91, "hr_factor": 0.78},
    "oriole park at camden yards": {"run_factor": 1.0, "hr_factor": 0.97},
    "petco park": {"run_factor": 0.94, "hr_factor": 0.88},
    "pnc park": {"run_factor": 0.97, "hr_factor": 0.91},
    "progressive field": {"run_factor": 0.98, "hr_factor": 0.96},
    "rogers centre": {"run_factor": 1.01, "hr_factor": 1.06},
    "t-mobile park": {"run_factor": 0.93, "hr_factor": 0.91},
    "target field": {"run_factor": 0.98, "hr_factor": 1.0},
    "truist park": {"run_factor": 1.02, "hr_factor": 1.06},
    "sutter health park": {"run_factor": 1.0, "hr_factor": 1.0},
    "wrigley field": {"run_factor": 1.0, "hr_factor": 1.04},
    "yankee stadium": {"run_factor": 1.01, "hr_factor": 1.12},
}


def get_park_factor(venue: str | None) -> dict[str, Any]:
    if not venue:
        return DEFAULT_PARK_FACTOR.copy()
    factor = PARK_FACTORS.get(_normalize_venue(venue))
    if not factor:
        return DEFAULT_PARK_FACTOR.copy()
    return {**factor, "source": "static_park_factors"}


def hitter_park_multiplier(venue: str | None) -> float:
    factor = get_park_factor(venue)
    run_factor = float(factor.get("run_factor", 1.0) or 1.0)
    hr_factor = float(factor.get("hr_factor", 1.0) or 1.0)
    multiplier = 1 + ((run_factor - 1) * 0.65) + ((hr_factor - 1) * 0.35)
    return round(_clamp(multiplier, 0.93, 1.08), 3)


def _normalize_venue(venue: str) -> str:
    return " ".join(venue.strip().lower().split())


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
