"""Pure watering logic — no side effects, no I/O."""

from dataclasses import dataclass
from datetime import date

from weather import WeatherData


@dataclass
class WateringConfig:
    """Configuration for watering algorithm thresholds."""

    baseline_interval_days: int = 14
    rain_threshold_inches: float = 1.0
    heavy_rain_threshold_inches: float = 2.0
    hot_temp_threshold_f: float = 85.0
    extreme_heat_threshold_f: float = 95.0
    mild_temp_threshold_f: float = 75.0
    cool_temp_threshold_f: float = 65.0
    forecast_rain_skip_inches: float = 0.5
    alert_window_days: int = 3
    min_interval_days: int = 5
    # Kept for backward compatibility / reporting. No longer shortens the
    # interval: the baseline only drops below 14 days when the weather is hot.
    young_plants: bool = True


@dataclass
class WateringStatus:
    """Result of the watering calculation."""

    effective_interval: int
    days_since_last_watering: int | None  # None if no history
    days_until_due: int | None  # None if no history (due now)
    should_alert: bool
    rain_adjustment: int
    temp_adjustment: int
    forecast_adjustment: int
    young_plants_adjustment: int


def calculate_effective_interval(weather: WeatherData, config: WateringConfig) -> tuple[int, int, int, int, int]:
    """Calculate the adjusted watering interval based on weather conditions.

    Returns (effective_interval, rain_adj, temp_adj, forecast_adj, young_adj).
    """
    interval = config.baseline_interval_days

    # Rain adjustment (past 7 days)
    rain_adj = 0
    if weather.past_week_rain_inches > config.heavy_rain_threshold_inches:
        rain_adj = 5
    elif weather.past_week_rain_inches > config.rain_threshold_inches:
        rain_adj = 3
    elif weather.past_week_rain_inches > 0.5:
        rain_adj = 1

    # Temperature adjustment (past 7 days avg max temp). The baseline only
    # drops below 14 days when it's genuinely hot; mild and cool weeks extend
    # it instead of leaving it at baseline.
    temp_adj = 0
    if weather.past_week_avg_max_temp_f > config.extreme_heat_threshold_f:
        temp_adj = -4
    elif weather.past_week_avg_max_temp_f > config.hot_temp_threshold_f:
        temp_adj = -2
    elif weather.past_week_avg_max_temp_f < config.cool_temp_threshold_f:
        temp_adj = 5
    elif weather.past_week_avg_max_temp_f < config.mild_temp_threshold_f:
        temp_adj = 3

    # Forecast adjustment
    forecast_adj = 0
    if weather.forecast_3day_rain_inches > config.forecast_rain_skip_inches:
        forecast_adj = 2

    # Young plants no longer shortens the interval (see WateringConfig).
    young_adj = 0

    interval += rain_adj + temp_adj + forecast_adj + young_adj

    # Clamp — minimum only, no maximum
    interval = max(interval, config.min_interval_days)

    return interval, rain_adj, temp_adj, forecast_adj, young_adj


def calculate_watering_status(
    last_watered: date | None,
    weather: WeatherData,
    config: WateringConfig,
    today: date | None = None,
) -> WateringStatus:
    """Calculate full watering status.

    Args:
        last_watered: Date of last watering, or None if no history.
        weather: Current weather data.
        config: Watering configuration.
        today: Override for current date (for testing).
    """
    if today is None:
        today = date.today()

    interval, rain_adj, temp_adj, forecast_adj, young_adj = calculate_effective_interval(weather, config)

    if last_watered is None:
        # No history — due immediately
        return WateringStatus(
            effective_interval=interval,
            days_since_last_watering=None,
            days_until_due=None,
            should_alert=True,
            rain_adjustment=rain_adj,
            temp_adjustment=temp_adj,
            forecast_adjustment=forecast_adj,
            young_plants_adjustment=young_adj,
        )

    days_since = (today - last_watered).days
    days_until_due = interval - days_since

    return WateringStatus(
        effective_interval=interval,
        days_since_last_watering=days_since,
        days_until_due=days_until_due,
        should_alert=days_until_due <= config.alert_window_days,
        rain_adjustment=rain_adj,
        temp_adjustment=temp_adj,
        forecast_adjustment=forecast_adj,
        young_plants_adjustment=young_adj,
    )


def format_alert_message(
    user_id: int,
    status: WateringStatus,
    weather: WeatherData,
) -> str:
    """Format the Discord alert message."""
    if status.days_until_due is None:
        due_text = "No watering history found — time to water!"
    elif status.days_until_due <= 0:
        due_text = "Your trees & shrubs are due for watering now."
    else:
        due_text = f"Your trees & shrubs are due for watering in the next {status.days_until_due} day{'s' if status.days_until_due != 1 else ''}."

    last_watered_text = (
        f"{status.days_since_last_watering} days ago"
        if status.days_since_last_watering is not None
        else "Never recorded"
    )

    return (
        f"<@{user_id}> {due_text}\n\n"
        f"Past week: {weather.past_week_rain_inches:.1f}\" rain, "
        f"avg high {weather.past_week_avg_max_temp_f:.0f}F\n"
        f"Next 3 days: {weather.forecast_3day_rain_inches:.1f}\" rain forecast\n"
        f"Last watered: {last_watered_text}\n\n"
        f"React with a water emoji or reply `!watered` when done."
    )


def format_status_message(
    status: WateringStatus,
    weather: WeatherData,
) -> str:
    """Format the !status command response."""
    last_watered_text = (
        f"{status.days_since_last_watering} days ago"
        if status.days_since_last_watering is not None
        else "Never recorded"
    )

    if status.days_until_due is None:
        due_text = "Due now (no history)"
    elif status.days_until_due <= 0:
        due_text = "Due now"
    else:
        due_text = f"In ~{status.days_until_due} days"

    return (
        f"**Watering Status**\n"
        f"Last watered: {last_watered_text}\n"
        f"Effective interval: {status.effective_interval} days\n"
        f"Next watering: {due_text}\n\n"
        f"**Weather Summary**\n"
        f"Past week rain: {weather.past_week_rain_inches:.1f}\"\n"
        f"Past week avg high: {weather.past_week_avg_max_temp_f:.0f}F\n"
        f"Forecast rain (3 day): {weather.forecast_3day_rain_inches:.1f}\"\n"
        f"Forecast rain (7 day): {weather.forecast_week_rain_inches:.1f}\"\n\n"
        f"**Adjustments**\n"
        f"Rain: {status.rain_adjustment:+d} days\n"
        f"Temperature: {status.temp_adjustment:+d} days\n"
        f"Forecast: {status.forecast_adjustment:+d} days\n"
        f"Young plants: {status.young_plants_adjustment:+d} days"
    )
