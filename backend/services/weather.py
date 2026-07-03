from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any
from urllib.request import Request, urlopen

from services.cache_store import cache_store

logger = logging.getLogger(__name__)

WEATHER_CONTEXT_KEY = "weather_contexts"

NEUTRAL_WEATHER = {
    "multiplier": 1.0,
    "risk": "neutral",
    "source": "neutral_default",
}

PARK_COORDINATES = {
    "american family field": (43.0280, -87.9712),
    "angel stadium": (33.8003, -117.8827),
    "busch stadium": (38.6226, -90.1928),
    "chase field": (33.4455, -112.0667),
    "citi field": (40.7571, -73.8458),
    "citizens bank park": (39.9061, -75.1665),
    "comerica park": (42.3390, -83.0485),
    "coors field": (39.7561, -104.9942),
    "dodger stadium": (34.0739, -118.2400),
    "fenway park": (42.3467, -71.0972),
    "globe life field": (32.7473, -97.0842),
    "great american ball park": (39.0979, -84.5082),
    "guaranteed rate field": (41.8300, -87.6338),
    "kauffman stadium": (39.0517, -94.4803),
    "loandepot park": (25.7781, -80.2197),
    "minute maid park": (29.7573, -95.3555),
    "nationals park": (38.8730, -77.0074),
    "oakland coliseum": (37.7516, -122.2005),
    "oracle park": (37.7786, -122.3893),
    "oriole park at camden yards": (39.2839, -76.6217),
    "petco park": (32.7073, -117.1566),
    "pnc park": (40.4469, -80.0057),
    "progressive field": (41.4962, -81.6852),
    "rogers centre": (43.6414, -79.3894),
    "sutter health park": (38.5804, -121.5139),
    "t-mobile park": (47.5914, -122.3325),
    "target field": (44.9817, -93.2776),
    "truist park": (33.8908, -84.4678),
    "wrigley field": (41.9484, -87.6553),
    "yankee stadium": (40.8296, -73.9262),
}

ROOF_VENUES = {
    "american family field",
    "chase field",
    "globe life field",
    "loandepot park",
    "minute maid park",
    "rogers centre",
    "t-mobile park",
}


def refresh_weather_contexts(games: list[object], fetcher: Any | None = None) -> dict[str, Any]:
    cache = load_weather_contexts()
    contexts = cache.get("venues", {})
    for game in games:
        venue = getattr(game, "venue", None)
        game_time = getattr(game, "game_time", None)
        if not venue or not game_time:
            continue
        normalized_venue = _normalize_venue(venue)
        if normalized_venue in ROOF_VENUES:
            contexts[normalized_venue] = {
                **NEUTRAL_WEATHER,
                "venue": venue,
                "source": "roof_or_retractable_neutral",
            }
            continue
        coordinates = PARK_COORDINATES.get(normalized_venue)
        if not coordinates:
            continue
        try:
            forecast = _fetch_nws_hourly_forecast(coordinates[0], coordinates[1], fetcher=fetcher)
            period = _nearest_period(forecast.get("properties", {}).get("periods", []), str(game_time))
            if period:
                contexts[normalized_venue] = _weather_context_from_period(venue, period)
        except Exception:
            logger.exception("failed to refresh weather for %s", venue)
            continue

    data = {
        "last_updated": datetime.now(UTC).isoformat(),
        "source": "api.weather.gov",
        "venues": contexts,
    }
    write_weather_contexts(data)
    return data


def load_weather_contexts() -> dict[str, Any]:
    data = cache_store.read_json(WEATHER_CONTEXT_KEY)
    if data is None:
        return _empty_cache()
    if not isinstance(data, dict):
        logger.error("weather_contexts.json is invalid; using neutral fallback")
        return _empty_cache()
    return data


def write_weather_contexts(data: dict[str, Any]) -> None:
    cache_store.write_json(WEATHER_CONTEXT_KEY, data)


def get_weather_context(venue: str | None) -> dict[str, Any]:
    if not venue:
        return NEUTRAL_WEATHER.copy()
    context = load_weather_contexts().get("venues", {}).get(_normalize_venue(venue))
    if not context:
        return NEUTRAL_WEATHER.copy()
    return context


def weather_multiplier(venue: str | None) -> float:
    context = get_weather_context(venue)
    return float(context.get("multiplier", 1.0) or 1.0)


def _fetch_nws_hourly_forecast(lat: float, lon: float, fetcher: Any | None = None) -> dict[str, Any]:
    points_url = f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
    points = _fetch_json(points_url, fetcher=fetcher)
    forecast_hourly_url = points.get("properties", {}).get("forecastHourly")
    if not forecast_hourly_url:
        return {}
    return _fetch_json(forecast_hourly_url, fetcher=fetcher)


def _fetch_json(url: str, fetcher: Any | None = None) -> dict[str, Any]:
    if fetcher:
        return fetcher(url)
    request = Request(
        url,
        headers={
            "Accept": "application/geo+json",
            "User-Agent": os.getenv("NWS_USER_AGENT", "LineupLab/0.1 contact@example.com"),
        },
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _nearest_period(periods: list[dict[str, Any]], game_time: str) -> dict[str, Any] | None:
    target = _parse_time(game_time)
    if not target:
        return periods[0] if periods else None
    best_period = None
    best_seconds = None
    for period in periods:
        start = _parse_time(str(period.get("startTime") or ""))
        if not start:
            continue
        seconds = abs((start - target).total_seconds())
        if best_seconds is None or seconds < best_seconds:
            best_period = period
            best_seconds = seconds
    return best_period


def _weather_context_from_period(venue: str, period: dict[str, Any]) -> dict[str, Any]:
    temperature = _float_value(period.get("temperature"))
    wind_speed = _parse_wind_speed(period.get("windSpeed"))
    precipitation = _precip_probability(period)
    forecast = str(period.get("shortForecast") or "")
    multiplier = _calculate_weather_multiplier(temperature, wind_speed, precipitation, forecast)
    return {
        "venue": venue,
        "forecast_time": period.get("startTime"),
        "temperature": temperature,
        "wind_speed_mph": wind_speed,
        "precipitation_probability": precipitation,
        "short_forecast": forecast,
        "multiplier": multiplier,
        "risk": _weather_risk(precipitation, forecast),
        "source": "api.weather.gov",
    }


def _calculate_weather_multiplier(
    temperature: float | None,
    wind_speed: float | None,
    precipitation: float | None,
    forecast: str,
) -> float:
    multiplier = 1.0
    if temperature is not None:
        if temperature >= 85:
            multiplier += 0.025
        elif temperature >= 75:
            multiplier += 0.015
        elif temperature <= 45:
            multiplier -= 0.03
        elif temperature <= 55:
            multiplier -= 0.015
    if wind_speed is not None and wind_speed >= 15:
        multiplier -= 0.015
    if precipitation is not None and precipitation >= 50:
        multiplier -= 0.04
    if _forecast_mentions_rain(forecast):
        multiplier -= 0.02
    return round(_clamp(multiplier, 0.92, 1.05), 3)


def _weather_risk(precipitation: float | None, forecast: str) -> str:
    if precipitation is not None and precipitation >= 60:
        return "high"
    if precipitation is not None and precipitation >= 35:
        return "moderate"
    if _forecast_mentions_rain(forecast):
        return "moderate"
    return "low"


def _precip_probability(period: dict[str, Any]) -> float | None:
    raw = period.get("probabilityOfPrecipitation")
    if isinstance(raw, dict):
        return _float_value(raw.get("value"))
    return _float_value(raw)


def _parse_wind_speed(value: Any) -> float | None:
    if value is None:
        return None
    matches = re.findall(r"\d+(?:\.\d+)?", str(value))
    if not matches:
        return None
    return sum(float(match) for match in matches) / len(matches)


def _forecast_mentions_rain(forecast: str) -> bool:
    lowered = forecast.lower()
    return any(term in lowered for term in ("rain", "showers", "thunderstorm", "drizzle"))


def _float_value(value: Any) -> float | None:
    if value is None or value != value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _normalize_venue(venue: str) -> str:
    return " ".join(venue.strip().lower().split())


def _empty_cache() -> dict[str, Any]:
    return {"last_updated": None, "source": "neutral_default", "venues": {}}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
