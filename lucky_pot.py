"""
LuckyPot Discord bot runner.

This is a thin wrapper that sets up the Discord bot commands and delegates
all business logic to the ``luckypot.game`` module.

The actual gateway connection and event dispatch will be added in a later task.
For now this file defines the command handlers and can be run as a script.
"""
import asyncio

from loguru import logger

from luckypot import db
from luckypot import config
from luckypot.game import (
    enter_pot,
    daily_pot_draw,
    on_request_accepted,
    on_request_denied,
    POT_ENTRY_COST,
)
from luckypot.gateway import StackCoinGateway


# ---------------------------------------------------------------------------
# Discord command handlers (to be wired up to a bot framework)
# ---------------------------------------------------------------------------

async def handle_enter_pot(discord_id: str, guild_id: str, respond_fn=None, announce_fn=None):
    """Handle the /enter-pot slash command."""
    result = await enter_pot(discord_id, guild_id, announce_fn=announce_fn)

    if respond_fn:
        await respond_fn(result.get("message", "Something went wrong."))

    return result


async def handle_pot_status(guild_id: str) -> dict:
    """Handle the /pot-status slash command."""
    conn = db.get_connection()
    try:
        return db.get_pot_status(conn, guild_id)
    finally:
        conn.close()


async def handle_pot_history(guild_id: str, limit: int = 5) -> list[dict]:
    """Handle the /pot-history slash command."""
    conn = db.get_connection()
    try:
        return db.get_pot_history(conn, guild_id, limit=limit)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Event dispatch (called from the WebSocket event listener)
# ---------------------------------------------------------------------------

async def dispatch_event(event: dict, announce_fn=None):
    """Route an incoming StackCoin event to the appropriate handler."""
    event_type = event.get("type", "")
    data = event.get("data", {})

    if event_type == "request.accepted":
        await on_request_accepted(data, announce_fn=announce_fn)
    elif event_type == "request.denied":
        await on_request_denied(data, announce_fn=announce_fn)
    else:
        logger.debug(f"Ignoring event type: {event_type}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    """Initialize DB and start the gateway connection."""
    logger.info("LuckyPot starting up...")
    db.init_database()

    gateway = StackCoinGateway(config.STACKCOIN_API_URL, config.STACKCOIN_API_TOKEN)

    # Wire event handlers -- the gateway sends full event payloads
    # which dispatch_event routes to the appropriate game handlers
    async def handle_event(payload):
        await dispatch_event(payload)

    gateway.register_handler("request.accepted", handle_event)
    gateway.register_handler("request.denied", handle_event)

    async def run():
        await gateway.connect()

    logger.info("Starting StackCoin gateway connection...")
    asyncio.run(run())


if __name__ == "__main__":
    main()
