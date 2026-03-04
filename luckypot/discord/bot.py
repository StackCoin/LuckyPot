"""Hikari bot lifecycle, lightbulb client setup, and channel announcements."""
import hikari
import lightbulb
from loguru import logger

from luckypot import config, stk


def create_bot() -> hikari.GatewayBot:
    """Create and return a configured hikari GatewayBot."""
    if not config.DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN is not set")
    return hikari.GatewayBot(token=config.DISCORD_TOKEN)


def create_lightbulb_client(bot: hikari.GatewayBot) -> lightbulb.Client:
    """Create a lightbulb client from the bot."""
    return lightbulb.client_from_app(bot)


def get_guild_ids() -> list[int]:
    """Get the guild IDs to register slash commands to.

    If TESTING_GUILD_ID is set, commands are guild-scoped (instant registration).
    Otherwise, commands are global (may take up to an hour to propagate).
    """
    if config.TESTING_GUILD_ID:
        return [int(config.TESTING_GUILD_ID)]
    return []


def make_announce_fn(bot: hikari.GatewayBot):
    """Create an announce function that posts to a guild's designated channel.

    Returns an async function with signature:
        async def announce(guild_id: str, message: str) -> None

    Note: game.py's AnnounceFn expects (message: str) -> None, so the caller
    must partial-apply the guild_id. See commands.py for usage.
    """
    async def announce(guild_id: str, message: str) -> None:
        try:
            channel_snowflake = await stk.get_guild_channel(guild_id)
            if channel_snowflake is None:
                logger.warning(f"No designated channel for guild {guild_id}")
                return

            channel_id = int(channel_snowflake)
            channel = bot.cache.get_guild_channel(channel_id)

            if channel and isinstance(channel, hikari.TextableGuildChannel):
                await channel.send(message)
                logger.info(f"Announced to guild {guild_id} channel {channel_id}")
            else:
                logger.warning(f"Could not find textable channel {channel_id} for guild {guild_id}")
        except Exception as e:
            logger.error(f"Failed to announce to guild {guild_id}: {e}")

    return announce
