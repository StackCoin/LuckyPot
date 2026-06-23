import asyncio
import random

import hikari
from loguru import logger

from luckypot import db
from luckypot.config import settings
import stackcoin
from luckypot.game import on_request_accepted, on_request_denied
from luckypot import stk
from luckypot.stk import get_client as get_stk_client
from luckypot.discord.bot import (
    create_bot,
    create_lightbulb_client,
    make_announce_fn,
    make_edit_announce_fn,
)
from luckypot.discord.commands import register_commands
from luckypot.discord.scheduler import run_daily_draw_loop

# Startup retry parameters for reaching StackCoin. Tuned so that luckypot waits
# roughly long enough for stackcoin to come up after a simultaneous restart
# (~16s in practice), but gives up well inside Docker's automatic-restart window
# so the whole container gets recycled by `restart: unless-stopped`.
STACKCOIN_CONNECT_MAX_ATTEMPTS = 12
STACKCOIN_CONNECT_BASE_DELAY = 1.0
STACKCOIN_CONNECT_MAX_DELAY = 30.0


logger.add("lucky_pot.log", rotation="1 day", retention="7 days", level="INFO")


logger.info("LuckyPot starting up...")
db.init_database()

bot = create_bot()
client = create_lightbulb_client(bot)
register_commands(client, bot)

bot.subscribe(hikari.StartingEvent, client.start)

background_tasks: list[asyncio.Task] = []
_gateway: stackcoin.Gateway | None = None


def _task_done_callback(task: asyncio.Task) -> None:
    """Log unhandled exceptions from background tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"Background task {task.get_name()} failed: {exc!r}")


async def _fetch_stackcoin_discord_id_or_die() -> str:
    """Retry ``fetch_stackcoin_discord_id`` against a not-yet-ready StackCoin.

    stackcoin-python normalises transport faults into ``StackCoinError`` (since
    v0.1.6), so we only catch that. If we exhaust all attempts we raise — the
    caller in :func:`on_started` shuts the whole bot down by closing the hikari
    bot, which exits the process non-zero and lets Docker's
    ``restart: unless-stopped`` policy recycle the container. By the next boot
    StackCoin has been up for ages.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, STACKCOIN_CONNECT_MAX_ATTEMPTS + 1):
        try:
            discord_id = await stk.fetch_stackcoin_discord_id()
            if discord_id is not None:
                return discord_id
            # Defence in depth: SDK returned None without raising — treat as a
            # soft miss and retry, since the only None path in stk.py is the
            # StackCoinError swallow at stk.py:40-42.
            last_exc = RuntimeError("fetch_stackcoin_discord_id returned None")
        except stackcoin.StackCoinError as e:
            last_exc = e
        delay = (
            min(
                STACKCOIN_CONNECT_MAX_DELAY,
                STACKCOIN_CONNECT_BASE_DELAY * (2 ** (attempt - 1)),
            )
            + random.random()
        )
        logger.warning(
            f"StackCoin not ready (attempt {attempt}/"
            f"{STACKCOIN_CONNECT_MAX_ATTEMPTS}), retrying in {delay:.1f}s: "
            f"{last_exc!r}"
        )
        await asyncio.sleep(delay)
    raise RuntimeError(
        f"Could not reach StackCoin after {STACKCOIN_CONNECT_MAX_ATTEMPTS} "
        f"attempts; refusing to start half-functional. Last error: {last_exc!r}"
    )


@bot.listen()
async def on_started(_event: hikari.StartedEvent) -> None:
    global _gateway

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

    try:
        await _fetch_stackcoin_discord_id_or_die()
    except RuntimeError as e:
        logger.error(str(e))
        await bot.close()
        return

    _gateway = stackcoin.Gateway(
        ws_url=settings.stackcoin_ws_url,
        token=settings.stackcoin_api_token,
        client=get_stk_client(),
        last_event_id=last_event_id,
        on_event_id=persist_event_id,
    )

    @_gateway.on("request.accepted")
    async def handle_accepted(event: stackcoin.RequestAcceptedEvent):
        await on_request_accepted(event.data, announce=announce)

    @_gateway.on("request.denied")
    async def handle_denied(event: stackcoin.RequestDeniedEvent):
        await on_request_denied(event.data, announce=announce)

    gateway_task = asyncio.create_task(_gateway.connect(), name="stackcoin-gateway")
    gateway_task.add_done_callback(_task_done_callback)
    background_tasks.append(gateway_task)
    logger.info("StackCoin gateway started")

    draw_task = asyncio.create_task(
        run_daily_draw_loop(
            announce=announce,
            edit_announce=edit_announce,
        ),
        name="daily-draw",
    )
    draw_task.add_done_callback(_task_done_callback)
    background_tasks.append(draw_task)
    logger.info("Daily draw scheduler started")


@bot.listen()
async def on_stopping(_event: hikari.StoppingEvent) -> None:
    if _gateway is not None:
        _gateway.stop()

    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
    logger.info("Background tasks cancelled")

    await stk.close_client()
    logger.info("StackCoin client closed")


if settings.debug_mode:
    logger.info("DEBUG MODE ENABLED — /force-end-pot command available")

bot.run()
