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


def _get_guild_channel(bot: hikari.GatewayBot, guild_id: str):
    """Resolve the designated textable channel for a guild. Returns (channel, channel_id) or (None, None)."""

    async def resolve():
        channel_snowflake = await stk.get_guild_channel(guild_id)
        if channel_snowflake is None:
            logger.warning(f"No designated channel for guild {guild_id}")
            return None, None

        cid = int(channel_snowflake)
        channel = bot.cache.get_guild_channel(cid)

        if channel and isinstance(channel, hikari.TextableGuildChannel):
            return channel, cid

        logger.warning(f"Could not find textable channel {cid} for guild {guild_id}")
        return None, None

    return resolve()


def make_announce_fn(bot: hikari.GatewayBot):
    async def announce(guild_id: str, message: str) -> hikari.Message | None:
        try:
            channel, channel_id = await _get_guild_channel(bot, guild_id)
            if channel is None:
                return None

            msg = await channel.send(message)
            logger.info(f"Announced to guild {guild_id} channel {channel_id}")
            return msg
        except Exception as e:
            logger.error(f"Failed to announce to guild {guild_id}: {e}")
            return None

    return announce


def make_edit_announce_fn(bot: hikari.GatewayBot):
    async def edit_announce(
        guild_id: str, message: hikari.Message, new_content: str
    ) -> hikari.Message | None:
        try:
            msg = await message.edit(new_content)
            logger.info(f"Edited announcement in guild {guild_id}")
            return msg
        except Exception as e:
            logger.error(f"Failed to edit announcement in guild {guild_id}: {e}")
            return None

    return edit_announce
