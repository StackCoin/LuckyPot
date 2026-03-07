from functools import partial

import hikari
import lightbulb
from loguru import logger

from luckypot import db
from luckypot.config import settings
from luckypot.game import enter_pot, end_pot_with_winner, POT_ENTRY_COST
from luckypot.discord import ui
from luckypot.discord.bot import get_guild_ids, make_announce_fn, make_edit_announce_fn


def register_commands(client: lightbulb.Client, bot: hikari.GatewayBot) -> None:
    guilds = get_guild_ids()
    announce = make_announce_fn(bot)
    edit_announce = make_edit_announce_fn(bot)

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
                result = await enter_pot(
                    discord_id, guild_id, announce_fn=guild_announce
                )
                status = result.get("status", "error")

                if status == "pending":
                    container = ui.build_entry_pending(amount=POT_ENTRY_COST)
                    await ctx.respond(
                        components=[container], flags=hikari.MessageFlag.EPHEMERAL
                    )
                elif status == "instant_win":
                    amount = result.get("winning_amount", 0)
                    container = ui.build_entry_instant_win(winning_amount=amount)
                    await ctx.respond(
                        components=[container], flags=hikari.MessageFlag.EPHEMERAL
                    )
                elif status == "instant_win_free_entry":
                    container = ui.build_entry_instant_win_free()
                    await ctx.respond(
                        components=[container], flags=hikari.MessageFlag.EPHEMERAL
                    )
                elif status == "already_entered":
                    container = ui.build_entry_already_entered()
                    await ctx.respond(
                        components=[container], flags=hikari.MessageFlag.EPHEMERAL
                    )
                else:
                    message = result.get("message", "Something went wrong.")
                    container = ui.build_entry_error(message)
                    await ctx.respond(
                        components=[container], flags=hikari.MessageFlag.EPHEMERAL
                    )

            except Exception as e:
                logger.error(f"Error in /enter-pot for user {ctx.user.id}: {e}")
                container = ui.build_entry_error(f"An unexpected error occurred: {e}")
                await ctx.respond(
                    components=[container], flags=hikari.MessageFlag.EPHEMERAL
                )

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
                container = ui.build_entry_error(
                    "Error retrieving pot status. Please try again later."
                )
                await ctx.respond(
                    components=[container], flags=hikari.MessageFlag.EPHEMERAL
                )

    @client.register(guilds=guilds)
    class PotHistory(
        lightbulb.SlashCommand,
        name="pot-history",
        description="View recent pot winners",
    ):
        limit: int = lightbulb.integer(
            "limit",
            "Number of recent pots to show",
            default=5,
            min_value=1,
            max_value=20,
        )

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
                await ctx.respond(
                    components=[container], flags=hikari.MessageFlag.EPHEMERAL
                )

    @client.register(guilds=guilds)
    class DisplayAllMessages(
        lightbulb.SlashCommand,
        name="display-all-messages",
        description="[DEBUG] Preview all bot messages for UI review",
    ):
        @lightbulb.invoke
        async def invoke(self, ctx: lightbulb.Context) -> None:
            user_mention = f"<@{ctx.user.id}>"

            # --- Ephemeral slash command responses ---
            await ctx.respond(
                "**--- Slash Command Responses (ephemeral in prod) ---**"
            )

            container = ui.build_entry_pending(amount=5)
            await ctx.respond(components=[container])

            container = ui.build_entry_instant_win(winning_amount=25)
            await ctx.respond(components=[container])

            container = ui.build_entry_instant_win_free()
            await ctx.respond(components=[container])

            container = ui.build_entry_already_entered()
            await ctx.respond(components=[container])

            container = ui.build_entry_error(
                "You don't have a StackCoin account. Please `/dole` first."
            )
            await ctx.respond(components=[container])

            sample_status_active = {
                "active": True,
                "total_amount": 25,
                "participants": 5,
                "pot_id": 42,
            }
            container = ui.build_pot_status(sample_status_active)
            await ctx.respond(components=[container])

            container = ui.build_pot_status({"active": False})
            await ctx.respond(components=[container])

            sample_history = [
                {
                    "winner_discord_id": str(ctx.user.id),
                    "winning_amount": 30,
                    "win_type": "DAILY DRAW",
                    "ended_at": "2026-03-06 18:00:00",
                },
                {
                    "winner_discord_id": str(ctx.user.id),
                    "winning_amount": 15,
                    "win_type": "INSTANT WIN",
                    "ended_at": "2026-03-05 12:30:00",
                },
            ]
            container = ui.build_pot_history(sample_history)
            await ctx.respond(components=[container])

            container = ui.build_pot_history([])
            await ctx.respond(components=[container])

            # --- Channel announcements ---
            await ctx.respond(
                "**--- Channel Announcements ---**"
            )

            await ctx.respond(
                f"{user_mention} entered the pot! The pot is now at 25 STK. Use `/enter-pot` to enter!"
            )

            await ctx.respond(
                f"{user_mention} rolled an instant win, but the pot is empty! They get a free entry instead."
            )

            await ctx.respond(
                f"{user_mention} won 25 STK!"
            )

            await ctx.respond(
                f"{user_mention} won 25 STK! (INSTANT WIN)"
            )

            await ctx.respond(
                "Time for the daily draw!"
            )

            await ctx.respond(
                "The winner is..."
            )

            await ctx.respond(
                f"{user_mention} has won 25 STK!"
            )

            await ctx.respond(
                f"Failed to send winnings to {user_mention}. The pot remains active."
            )

            await ctx.respond(
                f"{user_mention}'s pot entry was cancelled (payment denied)."
            )

    if settings.debug_mode:

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
                        await ctx.respond(
                            components=[container], flags=hikari.MessageFlag.EPHEMERAL
                        )
                        return

                    if status["participants"] == 0:
                        container = ui.build_entry_error(
                            "Cannot end pot with no confirmed participants!"
                        )
                        await ctx.respond(
                            components=[container], flags=hikari.MessageFlag.EPHEMERAL
                        )
                        return

                    guild_announce = partial(announce, guild_id)
                    guild_edit = partial(edit_announce, guild_id)
                    won = await end_pot_with_winner(
                        guild_id,
                        win_type="DEBUG FORCE END",
                        announce_fn=guild_announce,
                        edit_announce_fn=guild_edit,
                    )

                    if won:
                        await ctx.respond(
                            "✅ Pot ended! Check the channel for the winner announcement.",
                            flags=hikari.MessageFlag.EPHEMERAL,
                        )
                    else:
                        container = ui.build_entry_error(
                            "No confirmed participants found!"
                        )
                        await ctx.respond(
                            components=[container], flags=hikari.MessageFlag.EPHEMERAL
                        )

                except Exception as e:
                    logger.error(
                        f"Error in /force-end-pot for guild {ctx.guild_id}: {e}"
                    )
                    container = ui.build_entry_error(f"Error ending pot: {e}")
                    await ctx.respond(
                        components=[container], flags=hikari.MessageFlag.EPHEMERAL
                    )
