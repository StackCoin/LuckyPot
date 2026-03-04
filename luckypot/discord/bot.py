import hikari
import lightbulb
from loguru import logger

from luckypot import stk
from luckypot.config import settings


def create_bot() -> hikari.GatewayBot:
    if not settings.discord_token:
        raise ValueError("LUCKYPOT_DISCORD_TOKEN is not set")
    return hikari.GatewayBot(token=settings.discord_token)


def create_lightbulb_client(bot: hikari.GatewayBot) -> lightbulb.Client:
    return lightbulb.client_from_app(bot)


def get_guild_ids() -> list[int]:
    """Get the guild IDs to register slash commands to."""
    if settings.testing_guild_id:
        return [int(settings.testing_guild_id)]
    return []


def make_announce_fn(bot: hikari.GatewayBot):
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
