"""Configuration loading from environment variables."""
import os

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
STACKCOIN_API_URL = os.getenv("STACKCOIN_API_URL", "http://localhost:4000")
STACKCOIN_API_TOKEN = os.getenv("STACKCOIN_API_TOKEN", "")
STACKCOIN_WS_URL = os.getenv("STACKCOIN_WS_URL", "ws://localhost:4000/socket/websocket")
DB_PATH = os.getenv("LUCKYPOT_DB_PATH", "luckypot.db")

# Discord bot settings
TESTING_GUILD_ID = os.getenv("TESTING_GUILD_ID", "")
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# Daily draw schedule (UTC)
DAILY_DRAW_HOUR = int(os.getenv("DAILY_DRAW_HOUR", "0"))
DAILY_DRAW_MINUTE = int(os.getenv("DAILY_DRAW_MINUTE", "0"))
