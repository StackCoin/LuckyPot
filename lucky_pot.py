import asyncio
import hikari
from loguru import logger

from luckypot import db
from luckypot.config import settings
import stackcoin
from luckypot.game import on_request_accepted, on_request_denied
from luckypot.stk import get_client
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

    async def handle_accepted(event: stackcoin.RequestAcceptedEvent):
        await on_request_accepted(event.data, announce=announce)

    async def handle_denied(event: stackcoin.RequestDeniedEvent):
        await on_request_denied(event.data, announce=announce)

    async def catch_up_via_rest(since_id: int) -> int:
        """Paginate through missed events via REST, process relevant ones.

        Returns the last event ID seen (for use as the new gateway cursor).
        """
        logger.info(f"Catching up on missed events via REST (since_id={since_id})")
        client = get_client()
        events = await client.get_events(since_id=since_id)
        cursor = since_id
        for event in events:
            if isinstance(event, stackcoin.RequestAcceptedEvent):
                await handle_accepted(event)
            elif isinstance(event, stackcoin.RequestDeniedEvent):
                await handle_denied(event)
            if event.id > cursor:
                cursor = event.id
        persist_event_id(cursor)
        logger.info(f"Caught up on {len(events)} events, cursor now at {cursor}")
        return cursor

    async def run_gateway():
        """Connect to the gateway, catching up via REST if too far behind."""
        cursor = last_event_id

        while True:
            gateway = stackcoin.Gateway(
                ws_url=settings.stackcoin_ws_url,
                token=settings.stackcoin_api_token,
                last_event_id=cursor,
                on_event_id=persist_event_id,
            )
            gateway.register_handler("request.accepted", handle_accepted)
            gateway.register_handler("request.denied", handle_denied)

            try:
                await gateway.connect()
            except stackcoin.TooManyMissedEventsError as e:
                logger.warning(
                    f"Gateway rejected join: {e.missed_count} missed events "
                    f"(limit {e.replay_limit}). Catching up via REST..."
                )
                cursor = await catch_up_via_rest(cursor)
                # Loop back to reconnect with updated cursor
            except Exception:
                logger.exception("Gateway connection failed, retrying in 5s...")
                await asyncio.sleep(5)

    gateway_task = asyncio.create_task(run_gateway())
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
