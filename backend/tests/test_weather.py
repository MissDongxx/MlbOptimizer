from __future__ import annotations

import unittest
from datetime import UTC, datetime

from services.weather import (
    _calculate_weather_multiplier,
    _nearest_period,
    _parse_wind_speed,
    _weather_context_from_period,
)


class WeatherTests(unittest.TestCase):
    def test_weather_multiplier_rewards_warm_clear_weather(self) -> None:
        multiplier = _calculate_weather_multiplier(
            temperature=86,
            wind_speed=7,
            precipitation=5,
            forecast="Sunny",
        )

        self.assertGreater(multiplier, 1.0)

    def test_weather_multiplier_penalizes_rain_and_cold(self) -> None:
        multiplier = _calculate_weather_multiplier(
            temperature=42,
            wind_speed=18,
            precipitation=70,
            forecast="Rain Showers",
        )

        self.assertLess(multiplier, 1.0)
        self.assertGreaterEqual(multiplier, 0.92)

    def test_weather_context_from_nws_period(self) -> None:
        period = {
            "startTime": "2026-07-02T19:00:00-04:00",
            "temperature": 82,
            "windSpeed": "10 to 15 mph",
            "probabilityOfPrecipitation": {"value": 25},
            "shortForecast": "Partly Sunny",
        }

        context = _weather_context_from_period("Yankee Stadium", period)

        self.assertEqual(context["source"], "api.weather.gov")
        self.assertEqual(context["wind_speed_mph"], 12.5)
        self.assertEqual(context["risk"], "low")

    def test_nearest_period_picks_closest_start_time(self) -> None:
        periods = [
            {"startTime": "2026-07-02T18:00:00Z"},
            {"startTime": "2026-07-02T23:00:00Z"},
        ]

        nearest = _nearest_period(periods, datetime(2026, 7, 2, 22, 30, tzinfo=UTC).isoformat())

        self.assertEqual(nearest, periods[1])

    def test_parse_wind_speed_averages_ranges(self) -> None:
        self.assertEqual(_parse_wind_speed("10 to 20 mph"), 15.0)
        self.assertEqual(_parse_wind_speed("12 mph"), 12.0)
        self.assertIsNone(_parse_wind_speed("Calm"))


if __name__ == "__main__":
    unittest.main()
