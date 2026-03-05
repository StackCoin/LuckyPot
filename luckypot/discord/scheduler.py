import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from luckypot.config import settings
from luckypot.game import daily_pot_draw, RawAnnounceFn, RawEditAnnounceFn


def next_draw_time() -> datetime:
    """Calculate the next draw time based on current config.

    In interval mode, returns now + interval. Otherwise returns the next
    occurrence of the configured daily draw time.
    """
    now = datetime.now(timezone.utc)
    if settings.draw_interval_minutes > 0:
        return now + timedelta(minutes=settings.draw_interval_minutes)

    next_draw = now.replace(
        hour=settings.daily_draw_hour,
        minute=settings.daily_draw_minute,
        second=0,
        microsecond=0,
    )
    if next_draw <= now:
        next_draw += timedelta(days=1)
    return next_draw


async def run_daily_draw_loop(
    announce: RawAnnounceFn = None,
    edit_announce: RawEditAnnounceFn = None,
):
    """Run the pot draw on a schedule.

    When ``draw_interval_minutes`` is set (>0), runs on a repeating interval
    (useful for testing). Otherwise, runs once per day at the configured
    ``daily_draw_hour:daily_draw_minute`` UTC time.

    ``announce`` and ``edit_announce`` are the raw bot functions that
    take ``guild_id`` as their first argument. ``daily_pot_draw`` will
    create per-guild partials internally.
    """
    while True:
        next_draw = next_draw_time()
        now = datetime.now(timezone.utc)
        sleep_seconds = (next_draw - now).total_seconds()
        logger.info(f"Next draw at {next_draw.isoformat()} (in {sleep_seconds:.0f}s)")

        await asyncio.sleep(sleep_seconds)

        logger.info("Running daily pot draw...")
        try:
            await daily_pot_draw(announce=announce, edit_announce=edit_announce)
        except Exception as e:
            logger.error(f"Daily draw failed: {e}")
