import asyncio
import hikari
from loguru import logger

from luckypot import db
from luckypot.config import settings
import stackcoin
from luckypot.game import on_request_accepted, on_request_denied
from luckypot.stk import get_client as get_stk_client
from luckypot.discord.bot import (
    create_bot,
    create_lightbulb_client,
    make_announce_fn,
    make_edit_announce_fn,
)
from luckypot.discord.commands import register_commands
from luckypot.discord.scheduler import run_daily_draw_loop


logger.add("lucky_pot.log", rotation="1 day", retention="7 days", level="INFO")


logger.info("LuckyPot starting up...")
db.init_database()

bot = create_bot()
client = create_lightbulb_client(bot)
register_commands(client, bot)

bot.subscribe(hikari.StartingEvent, client.start)

background_tasks: list[asyncio.Task] = []


@bot.listen()
async def on_started(_event: hikari.StartedEvent) -> None:
    announce = make_announce_fn(bot)
    edit_announce = make_edit_announce_fn(bot)

    conn = db.get_connection()
    try:
        last_event_id = db.get_last_event_id(conn)
    finally:
        conn.close()
    logger.info(f"Resuming gateway from event {last_event_id}")

    def persist_event_id(event_id: int) -> None:
        c = db.get_connection()
        try:
            db.set_last_event_id(c, event_id)
        finally:
            c.close()

    gateway = stackcoin.Gateway(
        ws_url=settings.stackcoin_ws_url,
        token=settings.stackcoin_api_token,
        client=get_stk_client(),
        last_event_id=last_event_id,
        on_event_id=persist_event_id,
    )

    async def handle_accepted(event: stackcoin.RequestAcceptedEvent):
        await on_request_accepted(event.data, announce=announce)

    async def handle_denied(event: stackcoin.RequestDeniedEvent):
        await on_request_denied(event.data, announce=announce)

    gateway.register_handler("request.accepted", handle_accepted)
    gateway.register_handler("request.denied", handle_denied)

    gateway_task = asyncio.create_task(gateway.connect())
    background_tasks.append(gateway_task)
    logger.info("StackCoin gateway started")

    draw_task = asyncio.create_task(
        run_daily_draw_loop(
            announce=announce,
            edit_announce=edit_announce,
        )
    )
    background_tasks.append(draw_task)
    logger.info("Daily draw scheduler started")


@bot.listen()
async def on_stopping(_event: hikari.StoppingEvent) -> None:
    for task in background_tasks:
        task.cancel()
    logger.info("Background tasks cancelled")


if settings.debug_mode:
    logger.info("DEBUG MODE ENABLED — /force-end-pot command available")

bot.run()
