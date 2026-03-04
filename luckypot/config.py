"""Configuration loading from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
STACKCOIN_API_URL = os.getenv("STACKCOIN_API_URL", "http://localhost:4000")
STACKCOIN_API_TOKEN = os.getenv("STACKCOIN_API_TOKEN", "")
STACKCOIN_WS_URL = os.getenv("STACKCOIN_WS_URL", "ws://localhost:4000/socket/websocket")
DB_PATH = os.getenv("LUCKYPOT_DB_PATH", "luckypot.db")
