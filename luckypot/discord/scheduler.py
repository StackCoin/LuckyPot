"""Asyncio-based daily draw scheduler."""
import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from luckypot import config
from luckypot.game import daily_pot_draw, AnnounceFn


async def run_daily_draw_loop(announce_fn: AnnounceFn = None):
    """Run the daily pot draw at the configured UTC time.

    Runs forever, sleeping until the next draw time, then calling
    ``game.daily_pot_draw()``. If the draw time has already passed
    today, waits until tomorrow.
    """
    while True:
        now = datetime.now(timezone.utc)
        next_draw = now.replace(
            hour=config.DAILY_DRAW_HOUR,
            minute=config.DAILY_DRAW_MINUTE,
            second=0,
            microsecond=0,
        )
        if next_draw <= now:
            next_draw += timedelta(days=1)

        sleep_seconds = (next_draw - now).total_seconds()
        logger.info(f"Next daily draw at {next_draw.isoformat()} (in {sleep_seconds:.0f}s)")
        await asyncio.sleep(sleep_seconds)

        logger.info("Running daily pot draw...")
        try:
            await daily_pot_draw(announce_fn=announce_fn)
        except Exception as e:
            logger.error(f"Daily draw failed: {e}")
