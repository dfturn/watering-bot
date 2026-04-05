"""Open-Meteo API client for fetching historical and forecast weather data."""

from dataclasses import dataclass
from datetime import date, timedelta

import requests


MM_PER_INCH = 25.4


@dataclass
class WeatherData:
    """Parsed weather data for the watering algorithm."""

    past_week_rain_inches: float
    past_week_avg_max_temp_f: float
    forecast_week_rain_inches: float
    forecast_3day_rain_inches: float
    forecast_avg_max_temp_f: float


def mm_to_inches(mm: float) -> float:
    """Convert millimeters to inches."""
    return mm / MM_PER_INCH


def celsius_to_fahrenheit(c: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return c * 9.0 / 5.0 + 32.0


def parse_daily_data(
    daily: dict, precip_key: str = "precipitation_sum", temp_key: str = "temperature_2m_max"
) -> tuple[list[float], list[float]]:
    """Extract precipitation and temperature lists from Open-Meteo daily response.

    Returns (precip_inches_list, temp_f_list). Missing values are excluded.
    """
    raw_precip = daily.get(precip_key, [])
    raw_temps = daily.get(temp_key, [])

    precip_inches = [mm_to_inches(p) for p in raw_precip if p is not None]
    temps_f = [celsius_to_fahrenheit(t) for t in raw_temps if t is not None]

    return precip_inches, temps_f


def fetch_historical(latitude: float, longitude: float, target_date: date | None = None) -> dict:
    """Fetch past 7 days of weather data from Open-Meteo Archive API."""
    if target_date is None:
        target_date = date.today()

    end_date = target_date - timedelta(days=1)  # yesterday (today may be incomplete)
    start_date = end_date - timedelta(days=6)  # 7 days total

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": "precipitation_sum,temperature_2m_max",
        "timezone": "auto",
    }

    resp = requests.get("https://archive-api.open-meteo.com/v1/archive", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_forecast(latitude: float, longitude: float) -> dict:
    """Fetch next 7 days of forecast data from Open-Meteo Forecast API."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "precipitation_sum,temperature_2m_max",
        "forecast_days": 7,
        "timezone": "auto",
    }

    resp = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_weather_data(
    latitude: float,
    longitude: float,
    target_date: date | None = None,
    historical_response: dict | None = None,
    forecast_response: dict | None = None,
) -> WeatherData:
    """Fetch and parse weather data into a WeatherData object.

    Accepts optional pre-fetched responses for testing.
    """
    if historical_response is None:
        historical_response = fetch_historical(latitude, longitude, target_date)
    if forecast_response is None:
        forecast_response = fetch_forecast(latitude, longitude)

    hist_precip, hist_temps = parse_daily_data(historical_response.get("daily", {}))
    forecast_precip, forecast_temps = parse_daily_data(forecast_response.get("daily", {}))

    past_week_rain = sum(hist_precip)
    past_week_avg_max = sum(hist_temps) / len(hist_temps) if hist_temps else 0.0

    forecast_week_rain = sum(forecast_precip)
    forecast_3day_rain = sum(forecast_precip[:3])
    forecast_avg_max = sum(forecast_temps) / len(forecast_temps) if forecast_temps else 0.0

    return WeatherData(
        past_week_rain_inches=past_week_rain,
        past_week_avg_max_temp_f=past_week_avg_max,
        forecast_week_rain_inches=forecast_week_rain,
        forecast_3day_rain_inches=forecast_3day_rain,
        forecast_avg_max_temp_f=forecast_avg_max,
    )
