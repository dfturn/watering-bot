"""Discord bot for watering reminders."""

import asyncio
import json
import logging
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
import yaml
from discord.ext import commands, tasks

from watering_logic import WateringConfig, calculate_watering_status, format_alert_message, format_status_message
from weather import get_weather_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("discord").setLevel(logging.INFO)
logging.getLogger("discord.gateway").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

HISTORY_FILE = Path(__file__).parent / "watering_history.json"
CONFIG_FILE = Path(__file__).parent / "config.yaml"

WATER_EMOJIS = {
    "\U0001f4a7",  # droplet
    "\U0001f4a6",  # sweat_drops
    "\U0001f30a",  # ocean
    "\U0001faa3",  # bucket  (may not exist on all platforms)
}


def load_config() -> dict:
    """Load configuration from config.yaml."""
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def make_watering_config(cfg: dict) -> WateringConfig:
    """Build a WateringConfig from the raw config dict."""
    return WateringConfig(
        baseline_interval_days=cfg.get("baseline_interval_days", 14),
        rain_threshold_inches=cfg.get("rain_threshold_inches", 1.0),
        heavy_rain_threshold_inches=cfg.get("heavy_rain_threshold_inches", 2.0),
        hot_temp_threshold_f=cfg.get("hot_temp_threshold_f", 85.0),
        extreme_heat_threshold_f=cfg.get("extreme_heat_threshold_f", 95.0),
        cool_temp_threshold_f=cfg.get("cool_temp_threshold_f", 65.0),
        forecast_rain_skip_inches=cfg.get("forecast_rain_skip_inches", 0.5),
        alert_window_days=cfg.get("alert_window_days", 3),
        min_interval_days=cfg.get("min_interval_days", 5),
        young_plants=cfg.get("young_plants", True),
    )


# --- Watering history I/O ---


def load_history() -> list[dict]:
    """Load watering history from JSON file."""
    if not HISTORY_FILE.exists():
        return []
    with open(HISTORY_FILE) as f:
        data = json.load(f)
    return data.get("watering_events", [])


def save_history(events: list[dict]) -> None:
    """Save watering history to JSON file."""
    with open(HISTORY_FILE, "w") as f:
        json.dump({"watering_events": events}, f, indent=2)


def get_last_watered_date() -> date | None:
    """Get the most recent watering date, or None if no history."""
    events = load_history()
    if not events:
        return None
    # Events are stored chronologically; last entry is most recent
    return date.fromisoformat(events[-1]["date"])


def log_watering(watering_date: date, source: str = "user_command") -> bool:
    """Log a watering event. Returns False if already logged for that date."""
    events = load_history()
    date_str = watering_date.isoformat()

    # Deduplicate — one entry per day
    if any(e["date"] == date_str for e in events):
        return False

    events.append({"date": date_str, "source": source})
    events.sort(key=lambda e: e["date"])
    save_history(events)
    return True


# --- Bot setup ---


def create_bot(cfg: dict) -> commands.Bot:
    """Create and configure the Discord bot."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.reactions = True

    bot = commands.Bot(command_prefix="!", intents=intents)
    bot.watering_config = make_watering_config(cfg)
    bot.app_config = cfg
    bot.api_fail_count = 0

    @bot.event
    async def on_ready():
        logger.info(f"Logged in as {bot.user}")
        if not daily_check.is_running():
            daily_check.start()

    tz = ZoneInfo(cfg.get("timezone", "America/Los_Angeles"))

    @tasks.loop(time=time(hour=cfg.get("check_time_hour", 8), tzinfo=tz))
    async def daily_check():
        """Run the daily watering check."""
        channel = bot.get_channel(cfg["channel_id"])
        if channel is None:
            logger.error("Could not find configured channel %s", cfg["channel_id"])
            return

        try:
            weather = await asyncio.to_thread(get_weather_data, cfg["latitude"], cfg["longitude"])
            bot.api_fail_count = 0
        except Exception:
            bot.api_fail_count += 1
            logger.exception("Failed to fetch weather data (failure #%d)", bot.api_fail_count)
            if bot.api_fail_count >= 3:
                await channel.send(
                    f"<@{cfg['user_id']}> Weather API has been down for {bot.api_fail_count} days "
                    f"— you may want to check your plants manually."
                )
            return

        last_watered = get_last_watered_date()
        status = calculate_watering_status(last_watered, weather, bot.watering_config)

        if status.should_alert:
            msg = format_alert_message(cfg["user_id"], status, weather)
            await channel.send(msg)
            logger.info("Sent watering alert (due in %s days)", status.days_until_due)
        else:
            logger.info(
                "No alert needed (due in %s days, interval %d)",
                status.days_until_due,
                status.effective_interval,
            )

    @daily_check.before_loop
    async def before_daily_check():
        await bot.wait_until_ready()

    @daily_check.error
    async def daily_check_error(error):
        logger.exception("daily_check failed", exc_info=error)

    @bot.command(name="watered")
    async def cmd_watered(ctx, date_str: str | None = None):
        """Log a watering event. Optionally provide a date: !watered 2026-04-03"""
        try:
            watering_date = date.fromisoformat(date_str) if date_str else datetime.now(tz).date()
        except ValueError:
            await ctx.send("Invalid date format. Use YYYY-MM-DD, e.g. `!watered 2026-04-03`")
            return

        if log_watering(watering_date, source="user_command"):
            await ctx.send(f"Got it — logged watering for {watering_date.strftime('%B %d, %Y')}.")
        else:
            await ctx.send(f"Watering already logged for {watering_date.strftime('%B %d, %Y')}.")

    @bot.command(name="status")
    async def cmd_status(ctx):
        """Show current watering status."""
        try:
            weather = await asyncio.to_thread(get_weather_data, cfg["latitude"], cfg["longitude"])
        except Exception:
            await ctx.send("Could not fetch weather data. Try again later.")
            return

        last_watered = get_last_watered_date()
        status = calculate_watering_status(last_watered, weather, bot.watering_config)
        msg = format_status_message(status, weather)
        await ctx.send(msg)

    @bot.command(name="history")
    async def cmd_history(ctx):
        """Show last 10 watering dates."""
        events = load_history()
        if not events:
            await ctx.send("No watering history recorded yet.")
            return

        last_10 = events[-10:]
        lines = [f"- {e['date']} ({e.get('source', 'unknown')})" for e in reversed(last_10)]
        await ctx.send("**Watering History (last 10)**\n" + "\n".join(lines))

    @bot.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
        """Handle water emoji reactions on bot messages."""
        if payload.user_id == bot.user.id:
            return

        emoji_str = str(payload.emoji)
        if emoji_str not in WATER_EMOJIS:
            return

        channel = bot.get_channel(payload.channel_id)
        if channel is None:
            return

        message = await channel.fetch_message(payload.message_id)
        if message.author.id != bot.user.id:
            return

        today = datetime.now(tz).date()
        if log_watering(today, source="reaction"):
            await channel.send(f"Got it — logged watering for {today.strftime('%B %d, %Y')}.")

    return bot


def main():
    cfg = load_config()
    bot = create_bot(cfg)
    bot.run(cfg["discord_token"])


if __name__ == "__main__":
    main()
