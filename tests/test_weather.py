"""Tests for weather.py — unit conversion and parsing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from weather import WeatherData, celsius_to_fahrenheit, get_weather_data, mm_to_inches, parse_daily_data


class TestUnitConversions:
    def test_mm_to_inches_zero(self):
        assert mm_to_inches(0) == 0.0

    def test_mm_to_inches_one_inch(self):
        assert abs(mm_to_inches(25.4) - 1.0) < 0.001

    def test_mm_to_inches_typical_rain(self):
        result = mm_to_inches(12.7)
        assert abs(result - 0.5) < 0.001

    def test_celsius_to_fahrenheit_freezing(self):
        assert celsius_to_fahrenheit(0) == 32.0

    def test_celsius_to_fahrenheit_boiling(self):
        assert celsius_to_fahrenheit(100) == 212.0

    def test_celsius_to_fahrenheit_body_temp(self):
        assert abs(celsius_to_fahrenheit(37) - 98.6) < 0.1

    def test_celsius_to_fahrenheit_hot_day(self):
        # 35C = 95F
        assert celsius_to_fahrenheit(35) == 95.0


class TestParseDailyData:
    def test_basic_parsing(self):
        daily = {
            "precipitation_sum": [10.0, 5.0, 0.0],
            "temperature_2m_max": [30.0, 25.0, 20.0],
        }
        precip, temps = parse_daily_data(daily)
        assert len(precip) == 3
        assert len(temps) == 3
        assert abs(precip[0] - mm_to_inches(10.0)) < 0.001
        assert abs(temps[0] - celsius_to_fahrenheit(30.0)) < 0.001

    def test_handles_none_values(self):
        daily = {
            "precipitation_sum": [10.0, None, 5.0],
            "temperature_2m_max": [None, 25.0, 20.0],
        }
        precip, temps = parse_daily_data(daily)
        assert len(precip) == 2  # None excluded
        assert len(temps) == 2

    def test_empty_data(self):
        daily = {}
        precip, temps = parse_daily_data(daily)
        assert precip == []
        assert temps == []

    def test_missing_keys(self):
        daily = {"precipitation_sum": [5.0]}
        precip, temps = parse_daily_data(daily)
        assert len(precip) == 1
        assert temps == []


class TestGetWeatherData:
    def _make_historical_response(self, precip_mm: list[float], temps_c: list[float]) -> dict:
        return {
            "daily": {
                "precipitation_sum": precip_mm,
                "temperature_2m_max": temps_c,
            }
        }

    def _make_forecast_response(self, precip_mm: list[float], temps_c: list[float]) -> dict:
        return {
            "daily": {
                "precipitation_sum": precip_mm,
                "temperature_2m_max": temps_c,
            }
        }

    def test_dry_hot_week(self):
        hist = self._make_historical_response(
            precip_mm=[0, 0, 0, 0, 0, 0, 0],
            temps_c=[35, 36, 34, 35, 37, 35, 36],  # ~95F
        )
        forecast = self._make_forecast_response(
            precip_mm=[0, 0, 0, 0, 0, 0, 0],
            temps_c=[35, 36, 34, 35, 37, 35, 36],
        )
        data = get_weather_data(45.53, -122.84, historical_response=hist, forecast_response=forecast)
        assert isinstance(data, WeatherData)
        assert data.past_week_rain_inches < 0.01
        assert data.past_week_avg_max_temp_f > 93

    def test_rainy_cool_week(self):
        hist = self._make_historical_response(
            precip_mm=[10, 15, 8, 12, 5, 20, 10],  # ~80mm total = ~3.1"
            temps_c=[12, 10, 11, 13, 10, 9, 11],  # ~50-55F
        )
        forecast = self._make_forecast_response(
            precip_mm=[8, 10, 12, 5, 8, 10, 6],
            temps_c=[11, 12, 10, 13, 11, 10, 12],
        )
        data = get_weather_data(45.53, -122.84, historical_response=hist, forecast_response=forecast)
        assert data.past_week_rain_inches > 3.0
        assert data.past_week_avg_max_temp_f < 60

    def test_forecast_3day_subset(self):
        forecast = self._make_forecast_response(
            precip_mm=[25.4, 25.4, 25.4, 0, 0, 0, 0],  # 1" each first 3 days
            temps_c=[20, 20, 20, 20, 20, 20, 20],
        )
        hist = self._make_historical_response(
            precip_mm=[0, 0, 0, 0, 0, 0, 0],
            temps_c=[20, 20, 20, 20, 20, 20, 20],
        )
        data = get_weather_data(45.53, -122.84, historical_response=hist, forecast_response=forecast)
        assert abs(data.forecast_3day_rain_inches - 3.0) < 0.01
        assert data.forecast_week_rain_inches > data.forecast_3day_rain_inches - 0.01

    def test_empty_responses(self):
        hist = {"daily": {}}
        forecast = {"daily": {}}
        data = get_weather_data(45.53, -122.84, historical_response=hist, forecast_response=forecast)
        assert data.past_week_rain_inches == 0.0
        assert data.past_week_avg_max_temp_f == 0.0
