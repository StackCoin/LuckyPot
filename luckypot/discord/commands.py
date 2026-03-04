"""Slash commands for the LuckyPot Discord bot."""
from functools import partial

import hikari
import lightbulb
from loguru import logger

from luckypot import config, db
from luckypot.game import enter_pot, end_pot_with_winner, POT_ENTRY_COST
from luckypot.discord import ui
from luckypot.discord.bot import get_guild_ids, make_announce_fn


def register_commands(client: lightbulb.Client, bot: hikari.GatewayBot) -> None:
    """Register all slash commands on the lightbulb client."""
    guilds = get_guild_ids()
    announce = make_announce_fn(bot)

    @client.register(guilds=guilds)
    class EnterPot(
        lightbulb.SlashCommand,
        name="enter-pot",
        description=f"Enter the daily lucky pot (costs {POT_ENTRY_COST} STK)",
    ):
        @lightbulb.invoke
        async def invoke(self, ctx: lightbulb.Context) -> None:
            guild_id = str(ctx.guild_id)
            discord_id = str(ctx.user.id)

            try:
                guild_announce = partial(announce, guild_id)
                result = await enter_pot(discord_id, guild_id, announce_fn=guild_announce)
                status = result.get("status", "error")

                if status == "pending":
                    container = ui.build_entry_pending(
                        request_id=result.get("request_id", 0),
                        amount=POT_ENTRY_COST,
                    )
                    await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)
                elif status == "instant_win":
                    container = ui.build_entry_instant_win()
                    await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)
                elif status == "already_entered":
                    container = ui.build_entry_already_entered()
                    await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)
                else:
                    message = result.get("message", "Something went wrong.")
                    container = ui.build_entry_error(message)
                    await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)

            except Exception as e:
                logger.error(f"Error in /enter-pot for user {ctx.user.id}: {e}")
                container = ui.build_entry_error(f"An unexpected error occurred: {e}")
                await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)

    @client.register(guilds=guilds)
    class PotStatus(
        lightbulb.SlashCommand,
        name="pot-status",
        description="Check the current pot status and participants",
    ):
        @lightbulb.invoke
        async def invoke(self, ctx: lightbulb.Context) -> None:
            guild_id = str(ctx.guild_id)

            try:
                conn = db.get_connection()
                try:
                    status = db.get_pot_status(conn, guild_id)
                finally:
                    conn.close()

                container = ui.build_pot_status(status)
                await ctx.respond(components=[container])

            except Exception as e:
                logger.error(f"Error in /pot-status for guild {ctx.guild_id}: {e}")
                container = ui.build_entry_error("Error retrieving pot status. Please try again later.")
                await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)

    @client.register(guilds=guilds)
    class PotHistory(
        lightbulb.SlashCommand,
        name="pot-history",
        description="View recent pot winners",
    ):
        limit: int = lightbulb.integer("limit", "Number of recent pots to show", default=5, min_value=1, max_value=20)

        @lightbulb.invoke
        async def invoke(self, ctx: lightbulb.Context) -> None:
            guild_id = str(ctx.guild_id)

            try:
                conn = db.get_connection()
                try:
                    history = db.get_pot_history(conn, guild_id, limit=self.limit)
                finally:
                    conn.close()

                container = ui.build_pot_history(history)
                await ctx.respond(components=[container])

            except Exception as e:
                logger.error(f"Error in /pot-history for guild {ctx.guild_id}: {e}")
                container = ui.build_entry_error("Error retrieving pot history.")
                await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)

    if config.DEBUG_MODE:
        @client.register(guilds=guilds)
        class ForceEndPot(
            lightbulb.SlashCommand,
            name="force-end-pot",
            description="[DEBUG] Force end the current pot with a draw",
        ):
            @lightbulb.invoke
            async def invoke(self, ctx: lightbulb.Context) -> None:
                guild_id = str(ctx.guild_id)

                try:
                    conn = db.get_connection()
                    try:
                        status = db.get_pot_status(conn, guild_id)
                    finally:
                        conn.close()

                    if not status.get("active"):
                        container = ui.build_entry_error("No active pot to end!")
                        await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)
                        return

                    if status["participants"] == 0:
                        container = ui.build_entry_error("Cannot end pot with no confirmed participants!")
                        await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)
                        return

                    guild_announce = partial(announce, guild_id)
                    won = await end_pot_with_winner(guild_id, win_type="DEBUG FORCE END", announce_fn=guild_announce)

                    if won:
                        await ctx.respond("✅ Pot ended! Check the channel for the winner announcement.", flags=hikari.MessageFlag.EPHEMERAL)
                    else:
                        container = ui.build_entry_error("No confirmed participants found!")
                        await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)

                except Exception as e:
                    logger.error(f"Error in /force-end-pot for guild {ctx.guild_id}: {e}")
                    container = ui.build_entry_error(f"Error ending pot: {e}")
                    await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)
