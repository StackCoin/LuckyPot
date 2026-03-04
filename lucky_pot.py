"""
LuckyPot Discord bot runner.

Wires together three concurrent systems:
1. Hikari Discord bot (slash commands)
2. StackCoin WebSocket gateway (real-time event delivery)
3. Daily draw scheduler (asyncio sleep loop)
"""
import asyncio
from functools import partial

import hikari
from loguru import logger

from luckypot import config, db
from luckypot.gateway import StackCoinGateway
from luckypot.game import on_request_accepted, on_request_denied
from luckypot.discord.bot import create_bot, create_lightbulb_client, make_announce_fn
from luckypot.discord.commands import register_commands
from luckypot.discord.scheduler import run_daily_draw_loop


logger.add("lucky_pot.log", rotation="1 day", retention="7 days", level="INFO")


def main():
    """Initialize and run the LuckyPot bot."""
    logger.info("LuckyPot starting up...")
    db.init_database()

    bot = create_bot()
    client = create_lightbulb_client(bot)
    register_commands(client, bot)

    # Subscribe lightbulb to handle its startup
    bot.subscribe(hikari.StartingEvent, client.start)

    # Background tasks started once the bot is ready
    background_tasks: list[asyncio.Task] = []

    @bot.listen()
    async def on_started(event: hikari.StartedEvent) -> None:
        announce = make_announce_fn(bot)

        # --- StackCoin WebSocket gateway ---
        gateway = StackCoinGateway(config.STACKCOIN_API_URL, config.STACKCOIN_API_TOKEN)

        async def handle_accepted(payload):
            guild_id = payload.get("data", {}).get("guild_id")
            ann_fn = partial(announce, guild_id) if guild_id else None
            await on_request_accepted(payload.get("data", {}), announce_fn=ann_fn)

        async def handle_denied(payload):
            guild_id = payload.get("data", {}).get("guild_id")
            ann_fn = partial(announce, guild_id) if guild_id else None
            await on_request_denied(payload.get("data", {}), announce_fn=ann_fn)

        gateway.register_handler("request.accepted", handle_accepted)
        gateway.register_handler("request.denied", handle_denied)

        gateway_task = asyncio.create_task(gateway.connect())
        background_tasks.append(gateway_task)
        logger.info("StackCoin gateway started")

        # --- Daily draw scheduler ---
        draw_task = asyncio.create_task(run_daily_draw_loop(announce_fn=None))
        background_tasks.append(draw_task)
        logger.info("Daily draw scheduler started")

    @bot.listen()
    async def on_stopping(event: hikari.StoppingEvent) -> None:
        for task in background_tasks:
            task.cancel()
        logger.info("Background tasks cancelled")

    if config.DEBUG_MODE:
        logger.info("DEBUG MODE ENABLED — /force-end-pot command available")

    bot.run()


if __name__ == "__main__":
    main()
