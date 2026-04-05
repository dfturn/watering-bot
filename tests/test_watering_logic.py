"""Tests for watering_logic.py — algorithm and formatting."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from watering_logic import (
    WateringConfig,
    WateringStatus,
    calculate_effective_interval,
    calculate_watering_status,
    format_alert_message,
    format_status_message,
)
from weather import WeatherData


def make_weather(
    past_rain: float = 0.0,
    past_temp: float = 75.0,
    forecast_rain_7d: float = 0.0,
    forecast_rain_3d: float = 0.0,
    forecast_temp: float = 75.0,
) -> WeatherData:
    """Helper to create WeatherData with sensible defaults."""
    return WeatherData(
        past_week_rain_inches=past_rain,
        past_week_avg_max_temp_f=past_temp,
        forecast_week_rain_inches=forecast_rain_7d,
        forecast_3day_rain_inches=forecast_rain_3d,
        forecast_avg_max_temp_f=forecast_temp,
    )


DEFAULT_CONFIG = WateringConfig()


class TestCalculateEffectiveInterval:
    """Tests for the core interval calculation."""

    def test_baseline_no_adjustments(self):
        """Mild weather, no rain, established plants → baseline minus nothing special."""
        config = WateringConfig(young_plants=False)
        weather = make_weather(past_rain=0, past_temp=75)
        interval, rain, temp, forecast, young = calculate_effective_interval(weather, config)
        assert interval == 14
        assert rain == 0
        assert temp == 0
        assert forecast == 0
        assert young == 0

    def test_young_plants_reduces_interval(self):
        weather = make_weather()
        interval, _, _, _, young = calculate_effective_interval(weather, DEFAULT_CONFIG)
        assert young == -2
        assert interval == 12  # 14 - 2

    def test_heavy_rain_extends_interval(self):
        weather = make_weather(past_rain=2.5)
        interval, rain, _, _, _ = calculate_effective_interval(weather, DEFAULT_CONFIG)
        assert rain == 5
        assert interval == 17  # 14 + 5 - 2 (young)

    def test_moderate_rain_extends_interval(self):
        weather = make_weather(past_rain=1.5)
        interval, rain, _, _, _ = calculate_effective_interval(weather, DEFAULT_CONFIG)
        assert rain == 3
        assert interval == 15  # 14 + 3 - 2

    def test_light_rain_small_extension(self):
        weather = make_weather(past_rain=0.7)
        interval, rain, _, _, _ = calculate_effective_interval(weather, DEFAULT_CONFIG)
        assert rain == 1
        assert interval == 13  # 14 + 1 - 2

    def test_no_rain_no_adjustment(self):
        weather = make_weather(past_rain=0.3)
        _, rain, _, _, _ = calculate_effective_interval(weather, DEFAULT_CONFIG)
        assert rain == 0

    def test_extreme_heat_shortens_interval(self):
        weather = make_weather(past_temp=97)
        interval, _, temp, _, _ = calculate_effective_interval(weather, DEFAULT_CONFIG)
        assert temp == -4
        assert interval == 8  # 14 - 4 - 2

    def test_hot_weather_shortens_interval(self):
        weather = make_weather(past_temp=90)
        interval, _, temp, _, _ = calculate_effective_interval(weather, DEFAULT_CONFIG)
        assert temp == -2
        assert interval == 10  # 14 - 2 - 2

    def test_cool_weather_extends_interval(self):
        weather = make_weather(past_temp=55)
        interval, _, temp, _, _ = calculate_effective_interval(weather, DEFAULT_CONFIG)
        assert temp == 2
        assert interval == 14  # 14 + 2 - 2

    def test_forecast_rain_extends_interval(self):
        weather = make_weather(forecast_rain_3d=1.0)
        interval, _, _, forecast, _ = calculate_effective_interval(weather, DEFAULT_CONFIG)
        assert forecast == 2
        assert interval == 14  # 14 + 2 - 2

    def test_forecast_rain_below_threshold_no_adjustment(self):
        weather = make_weather(forecast_rain_3d=0.3)
        _, _, _, forecast, _ = calculate_effective_interval(weather, DEFAULT_CONFIG)
        assert forecast == 0

    def test_minimum_clamp(self):
        """Extreme heat + young plants should not go below min_interval_days."""
        weather = make_weather(past_temp=100)
        interval, _, _, _, _ = calculate_effective_interval(weather, DEFAULT_CONFIG)
        assert interval >= DEFAULT_CONFIG.min_interval_days
        assert interval == 8  # 14 - 4 - 2 = 8, above min of 5

    def test_minimum_clamp_enforced(self):
        """Artificially low baseline to test clamp."""
        config = WateringConfig(baseline_interval_days=6, young_plants=True, min_interval_days=5)
        weather = make_weather(past_temp=97)  # -4 adjustment
        interval, _, _, _, _ = calculate_effective_interval(weather, config)
        # 6 - 4 - 2 = 0, should clamp to 5
        assert interval == 5

    def test_no_maximum_clamp(self):
        """Rainy + cool + forecast rain → interval can grow unbounded."""
        weather = make_weather(past_rain=3.0, past_temp=50, forecast_rain_3d=2.0)
        config = WateringConfig(young_plants=False)
        interval, rain, temp, forecast, _ = calculate_effective_interval(weather, config)
        assert rain == 5
        assert temp == 2
        assert forecast == 2
        assert interval == 23  # 14 + 5 + 2 + 2

    def test_winter_portland_scenario(self):
        """Typical Portland winter: constant rain, cool temps."""
        weather = make_weather(past_rain=2.5, past_temp=48, forecast_rain_3d=1.5)
        interval, _, _, _, _ = calculate_effective_interval(weather, DEFAULT_CONFIG)
        # 14 + 5 (heavy rain) + 2 (cool) + 2 (forecast) - 2 (young) = 21
        assert interval == 21

    def test_summer_portland_scenario(self):
        """Typical Portland summer: hot, dry."""
        weather = make_weather(past_rain=0, past_temp=92, forecast_rain_3d=0)
        interval, _, _, _, _ = calculate_effective_interval(weather, DEFAULT_CONFIG)
        # 14 - 2 (hot) - 2 (young) = 10
        assert interval == 10

    def test_hot_but_rainy(self):
        """Hot week but also rainy — adjustments stack."""
        weather = make_weather(past_rain=1.5, past_temp=90)
        interval, rain, temp, _, _ = calculate_effective_interval(weather, DEFAULT_CONFIG)
        assert rain == 3
        assert temp == -2
        # 14 + 3 - 2 - 2 = 13
        assert interval == 13


class TestCalculateWateringStatus:
    def test_no_history_alerts_immediately(self):
        weather = make_weather()
        status = calculate_watering_status(None, weather, DEFAULT_CONFIG, today=date(2026, 7, 15))
        assert status.should_alert is True
        assert status.days_since_last_watering is None
        assert status.days_until_due is None

    def test_recently_watered_no_alert(self):
        weather = make_weather()
        status = calculate_watering_status(
            date(2026, 7, 13), weather, DEFAULT_CONFIG, today=date(2026, 7, 15)
        )
        assert status.should_alert is False
        assert status.days_since_last_watering == 2
        # interval = 12 (14 - 2 young), due in 10 days
        assert status.days_until_due == 10

    def test_due_soon_alerts(self):
        weather = make_weather()
        status = calculate_watering_status(
            date(2026, 7, 4), weather, DEFAULT_CONFIG, today=date(2026, 7, 15)
        )
        # 11 days since watering, interval = 12, due in 1 day
        assert status.days_since_last_watering == 11
        assert status.days_until_due == 1
        assert status.should_alert is True

    def test_overdue_alerts(self):
        weather = make_weather()
        status = calculate_watering_status(
            date(2026, 6, 20), weather, DEFAULT_CONFIG, today=date(2026, 7, 15)
        )
        assert status.days_since_last_watering == 25
        assert status.days_until_due < 0
        assert status.should_alert is True

    def test_alert_window_boundary(self):
        """Exactly at alert_window_days should trigger."""
        weather = make_weather()
        # interval = 12, watered 9 days ago → due in 3 days = alert_window_days
        status = calculate_watering_status(
            date(2026, 7, 6), weather, DEFAULT_CONFIG, today=date(2026, 7, 15)
        )
        assert status.days_until_due == 3
        assert status.should_alert is True

    def test_one_day_past_alert_window(self):
        """One day past alert window should NOT trigger."""
        weather = make_weather()
        # interval = 12, watered 8 days ago → due in 4 days > alert_window_days
        status = calculate_watering_status(
            date(2026, 7, 7), weather, DEFAULT_CONFIG, today=date(2026, 7, 15)
        )
        assert status.days_until_due == 4
        assert status.should_alert is False

    def test_winter_no_alert(self):
        """Winter scenario: long interval means no alert even after weeks."""
        weather = make_weather(past_rain=2.5, past_temp=48, forecast_rain_3d=1.5)
        # interval = 21
        status = calculate_watering_status(
            date(2026, 1, 1), weather, DEFAULT_CONFIG, today=date(2026, 1, 15)
        )
        assert status.effective_interval == 21
        assert status.days_since_last_watering == 14
        assert status.days_until_due == 7
        assert status.should_alert is False


class TestFormatAlertMessage:
    def test_basic_alert(self):
        weather = make_weather(past_rain=0.1, past_temp=89, forecast_rain_3d=0.0)
        status = WateringStatus(
            effective_interval=10,
            days_since_last_watering=8,
            days_until_due=2,
            should_alert=True,
            rain_adjustment=0,
            temp_adjustment=-2,
            forecast_adjustment=0,
            young_plants_adjustment=-2,
        )
        msg = format_alert_message(123456789, status, weather)
        assert "<@123456789>" in msg
        assert "2 days" in msg
        assert "0.1\" rain" in msg
        assert "89F" in msg
        assert "!watered" in msg

    def test_no_history_alert(self):
        weather = make_weather()
        status = WateringStatus(
            effective_interval=12,
            days_since_last_watering=None,
            days_until_due=None,
            should_alert=True,
            rain_adjustment=0,
            temp_adjustment=0,
            forecast_adjustment=0,
            young_plants_adjustment=-2,
        )
        msg = format_alert_message(123456789, status, weather)
        assert "No watering history" in msg
        assert "Never recorded" in msg

    def test_overdue_alert(self):
        weather = make_weather()
        status = WateringStatus(
            effective_interval=12,
            days_since_last_watering=15,
            days_until_due=-3,
            should_alert=True,
            rain_adjustment=0,
            temp_adjustment=0,
            forecast_adjustment=0,
            young_plants_adjustment=-2,
        )
        msg = format_alert_message(123456789, status, weather)
        assert "due for watering now" in msg

    def test_singular_day(self):
        weather = make_weather()
        status = WateringStatus(
            effective_interval=12,
            days_since_last_watering=11,
            days_until_due=1,
            should_alert=True,
            rain_adjustment=0,
            temp_adjustment=0,
            forecast_adjustment=0,
            young_plants_adjustment=-2,
        )
        msg = format_alert_message(123456789, status, weather)
        assert "1 day." in msg  # singular, no "s"


class TestFormatStatusMessage:
    def test_basic_status(self):
        weather = make_weather(past_rain=0.5, past_temp=80, forecast_rain_3d=0.2, forecast_rain_7d=1.0)
        status = WateringStatus(
            effective_interval=12,
            days_since_last_watering=5,
            days_until_due=7,
            should_alert=False,
            rain_adjustment=1,
            temp_adjustment=0,
            forecast_adjustment=0,
            young_plants_adjustment=-2,
        )
        msg = format_status_message(status, weather)
        assert "Watering Status" in msg
        assert "5 days ago" in msg
        assert "12 days" in msg
        assert "In ~7 days" in msg
        assert "Rain: +1" in msg
        assert "Young plants: -2" in msg

    def test_no_history_status(self):
        weather = make_weather()
        status = WateringStatus(
            effective_interval=12,
            days_since_last_watering=None,
            days_until_due=None,
            should_alert=True,
            rain_adjustment=0,
            temp_adjustment=0,
            forecast_adjustment=0,
            young_plants_adjustment=-2,
        )
        msg = format_status_message(status, weather)
        assert "Never recorded" in msg
        assert "Due now (no history)" in msg

    def test_overdue_status(self):
        weather = make_weather()
        status = WateringStatus(
            effective_interval=12,
            days_since_last_watering=15,
            days_until_due=-3,
            should_alert=True,
            rain_adjustment=0,
            temp_adjustment=0,
            forecast_adjustment=0,
            young_plants_adjustment=-2,
        )
        msg = format_status_message(status, weather)
        assert "Due now" in msg
