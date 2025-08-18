import os

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("LUCKY_POT_DISCORD_TOKEN")
TESTING_GUILD_ID = os.getenv("LUCKY_POT_TESTING_GUILD_ID")
DEBUG_MODE = os.getenv("LUCKY_POT_DEBUG_MODE", "false").lower() == "true"

STACKCOIN_BOT_TOKEN = os.getenv("LUCKY_POT_STACKCOIN_BOT_TOKEN")
STACKCOIN_BASE_URL = (
    os.getenv("LUCKY_POT_STACKCOIN_BASE_URL") or "https://stackcoin.world"
)
