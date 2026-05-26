# Watering Bot Design Spec

## Overview

A Discord bot that monitors weather conditions for a specific location and alerts the user when their young trees and shrubs need watering. It uses historical and forecast weather data to calculate dynamic watering intervals, adjusting for rain, temperature, and sun exposure.

## Goals

- Check weather daily using Open-Meteo (free, no API key)
- Calculate watering needs based on past week's weather + next week's forecast
- Ping the user on Discord when watering is due within 2-3 days
- Track watering history via user confirmation (`!watered` or reaction)
- Never nag during cool/rainy periods (no upper cap on interval)
- All watering logic must be testable independent of Discord

## Location & Plant Context

- Coordinates: 45.534709, -122.839613 (Portland, OR area)
- Plants: Trees and shrubs, 1-2 years old (not fully established)
- Sun exposure: Mostly full sun
- Climate: Mild wet winters, warm dry summers

## Project Structure

```
watering_bot/
├── bot.py                  # Discord bot — event handling, commands, scheduled task
├── watering_logic.py       # Pure functions — algorithm, scoring, decisions
├── weather.py              # Open-Meteo API client — fetch and parse weather data
├── config.yaml             # User configuration
├── watering_history.json   # Auto-managed watering event log
├── requirements.txt        # discord.py, pyyaml, requests
├── tests/
│   ├── test_watering_logic.py
│   └── test_weather.py
└── .env                    # Discord token (alternative to config.yaml)
```

## Configuration

**config.yaml:**

```yaml
discord_token: "YOUR_TOKEN"
channel_id: 123456789
user_id: 123456789
latitude: 45.534709
longitude: -122.839613
timezone: "America/Los_Angeles"
check_time_hour: 8  # Daily check at 8 AM local

# Tuning parameters
baseline_interval_days: 14
rain_threshold_inches: 1.0
heavy_rain_threshold_inches: 2.0
hot_temp_threshold_f: 85
extreme_heat_threshold_f: 95
mild_temp_threshold_f: 75
cool_temp_threshold_f: 65
forecast_rain_skip_inches: 0.5
alert_window_days: 3
min_interval_days: 5
young_plants: true  # retained for back-compat; no longer affects interval
```

All thresholds are configurable. No hardcoded magic numbers in the logic.

## Weather Data (Open-Meteo)

**Two API calls per day:**

1. **Historical (past 7 days):** daily precipitation sum (mm, converted to inches), max temperature (converted to F), shortwave radiation
2. **Forecast (next 7 days):** same fields

**weather.py** is responsible for:
- Making HTTP requests to Open-Meteo
- Parsing the JSON response
- Converting units (mm to inches, C to F)
- Returning a simple data structure (dataclass or dict) with the fields the algorithm needs

Open-Meteo endpoints:
- Historical: `https://archive-api.open-meteo.com/v1/archive`
- Forecast: `https://api.open-meteo.com/v1/forecast`

## Watering Algorithm

Implemented as pure functions in **watering_logic.py**.

### Core calculation

```
Input:
  - last_watered_date (date or None)
  - past_7_days_rain_inches (float)
  - avg_max_temp_f (float) — average of daily max temps over past 7 days
  - forecast_rain_next_3_days_inches (float)
  - config parameters (baseline, thresholds, etc.)

Output:
  - effective_interval (int, days)
  - days_since_last_watering (int)
  - days_until_due (int)
  - should_alert (bool)
  - summary (dict of contributing factors for the notification message)
```

### Algorithm

```
effective_interval = baseline_interval_days  # default: 14

# Rain adjustment (past 7 days)
if past_week_rain > 2.0":  effective_interval += 5
elif past_week_rain > 1.0": effective_interval += 3
elif past_week_rain > 0.5": effective_interval += 1

# Temperature adjustment (past 7 days avg max temp)
# The baseline only drops below 14 when it's genuinely hot; mild/cool
# weeks extend it. (Revised 2026-05-25: watering was firing too often in
# mild weather — see note below.)
if avg_max_temp > 95F: effective_interval -= 4
elif avg_max_temp > 85F: effective_interval -= 2
elif avg_max_temp < 65F: effective_interval += 5
elif avg_max_temp < 75F: effective_interval += 3   # mild (e.g. 69F)

# Forecast adjustment
if forecast_rain_next_3_days > 0.5": effective_interval += 2

# Young plants modifier — disabled 2026-05-25.
# Previously subtracted 2 days unconditionally, which pushed the interval
# below baseline even in cool/wet weather. Kept as a config flag for
# back-compat but no longer affects the interval.

# Clamp — minimum only, no maximum
effective_interval = max(effective_interval, min_interval_days)  # default min: 5

# Alert decision
days_since = today - last_watered_date
days_until_due = effective_interval - days_since
should_alert = days_until_due <= alert_window_days
```

### Edge cases

- **No watering history (first run):** Treat as immediately due, send alert.
- **Cool rainy winter:** Effective interval grows unbounded — no reminders sent.
- **Hot + rainy:** Heat and rain adjustments stack. A week with 1.5" of rain but 90F avg highs yields: +3 (rain) -2 (heat) = interval of 15. Still alerts appropriately.
- **Mild + light rain:** A week with 0.5" rain and 69F avg highs yields: +0 (rain) +3 (mild) = interval of 17. Watered 11 days ago → due in 6 days, no premature alert.

## Discord Bot Behavior

### Daily scheduled task (bot.py)

Runs once daily at the configured hour (default 8 AM) using `discord.ext.tasks.loop`:

1. Fetch historical and forecast weather from Open-Meteo
2. Read last watering date from `watering_history.json`
3. Run watering algorithm
4. If `should_alert`, send notification to configured channel

### Notification format

```
@user Your trees & shrubs are due for watering in the next X days.

Past week: 0.1" rain, avg high 89F
Next 3 days: 0.0" rain forecast
Last watered: 12 days ago

React with a water emoji or reply !watered when done.
```

### Watering confirmation

Two ways to log watering:

1. **`!watered` command** — logs today's date. Supports optional date: `!watered 2026-04-03`
2. **Reaction on bot message** — any water-related emoji reaction on a bot notification logs today's date

Bot responds with confirmation: "Got it, logged watering for April 5, 2026."

Duplicate entries on the same day are ignored (only one event per day stored).

### Other commands

- **`!status`** — Current state: days since last watering, effective interval, weather summary, estimated next alert
- **`!history`** — Last 10 watering dates

## Watering History Storage

**watering_history.json:**

```json
{
  "watering_events": [
    {"date": "2026-04-01", "source": "user_command"},
    {"date": "2026-03-18", "source": "reaction"}
  ]
}
```

Append-only log. Bot reads the most recent entry for `last_watered_date`. File is created automatically on first run if it doesn't exist.

## Error Handling

- **Open-Meteo unreachable:** Log error, skip check, retry next day. If 3 consecutive failures, notify user: "Weather API has been down for 3 days, you may want to check your plants manually."
- **Bot restarts:** All state lives in `watering_history.json`. The daily task resumes on next scheduled tick.
- **Invalid commands:** Ignore gracefully, no error messages for unrecognized input.
- **Timezone:** All date math uses the configured timezone (default `America/Los_Angeles`).

## Testability

The codebase is split into three modules specifically to enable testing:

### watering_logic.py — pure functions, no side effects

All algorithm functions take simple inputs (numbers, dates, config dicts) and return simple outputs. No API calls, no file I/O, no Discord objects.

**Testable units:**
- `calculate_effective_interval(rain, temp, forecast_rain, config)` — given weather numbers and config, returns adjusted interval
- `calculate_watering_status(last_watered, weather_data, config)` — returns full status including should_alert
- Edge cases: no history, extreme heat + rain, winter conditions, boundary values at thresholds

**Example test cases:**
- Hot dry week (95F, 0" rain) with young plants → interval ~8 days
- Cool rainy week (60F, 2.5" rain) → interval 21+ days, no alert
- Rain in forecast with watering almost due → alert deferred
- First run with no history → immediate alert
- All threshold boundaries tested

### weather.py — API client with injectable responses

- Parsing/conversion functions are pure: given a JSON dict, return structured weather data
- HTTP calls isolated to one function, easily mocked in tests
- Unit tests cover: mm-to-inches conversion, C-to-F conversion, handling of missing/partial API data

### bot.py — thin orchestration layer

Bot code is a thin shell that wires together weather fetching, logic, and Discord I/O. The daily task calls `weather.fetch()` then `watering_logic.calculate()` then sends the result. Minimal logic lives here, so it needs minimal testing.

Commands (`!watered`, `!status`, `!history`) parse user input and delegate to logic/storage functions that are independently testable.

## Dependencies

**requirements.txt:**
```
discord.py>=2.0
requests>=2.28
pyyaml>=6.0
```

**Test dependencies:**
```
pytest
```
