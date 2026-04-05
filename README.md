# Watering Bot

A Discord bot that monitors weather and alerts you when your trees and shrubs need watering. Uses the free Open-Meteo API for hyper-local historical and forecast weather data to dynamically adjust watering intervals based on rain, temperature, and sun exposure.

## How it works

- Checks weather daily at 8 AM (configurable)
- Calculates a watering interval starting from a 14-day baseline, adjusted for rain, heat, cool weather, and forecast
- Pings you on Discord when watering is due within 2-3 days
- Tracks your watering history when you confirm via command or emoji reaction
- Goes silent during cool/rainy periods (no upper limit on interval)

## Setup

### 1. Create a Discord bot

1. Go to https://discord.com/developers/applications and create a new application
2. Go to **Bot** > **Reset Token** and copy it
3. Under **Privileged Gateway Intents**, enable **Message Content Intent**
4. Go to **OAuth2** > check **bot** scope > check permissions: Send Messages, Read Message History, Add Reactions, View Channels
5. Copy the generated URL, open it in your browser, and invite the bot to your server

### 2. Configure

Enable **Developer Mode** in Discord (Settings > Advanced) to copy IDs.

Edit `config.yaml`:

```yaml
discord_token: "your-bot-token"
channel_id: 123456789        # right-click channel > Copy Channel ID
user_id: 123456789           # right-click your name > Copy User ID
latitude: 45.534709          # your location
longitude: -122.839613
```

All tuning parameters (thresholds, intervals) are also in `config.yaml`.

### 3. Run with Docker Compose

```bash
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f
```

Rebuild after code changes:

```bash
docker compose up -d --build
```

Stop:

```bash
docker compose down
```

### Run without Docker

```bash
pip install -r requirements.txt
python bot.py
```

## Commands

| Command | Description |
|---|---|
| `!status` | Current watering status, weather summary, and next alert estimate |
| `!history` | Last 10 watering dates |
| `!watered` | Log that you watered today |
| `!watered 2026-04-03` | Backdate a watering event |

You can also react to any bot notification with a water emoji to log watering.

## Testing

```bash
pip install pytest
python -m pytest tests/ -v
```
