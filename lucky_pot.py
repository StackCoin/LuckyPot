import os
import random
import asyncio
from datetime import datetime, timedelta, timezone

import hikari
import lightbulb
import schedule
from dotenv import load_dotenv
from loguru import logger
import db
import stk

load_dotenv()

# Configure loguru
logger.add("lucky_pot.log", rotation="1 day", retention="7 days", level="INFO")
logger.info("Starting LuckyPot Discord Bot")

token = os.getenv("LUCKY_POT_DISCORD_TOKEN")
testing_guild_id = os.getenv("LUCKY_POT_TESTING_GUILD_ID")
debug_mode = os.getenv("LUCKY_POT_DEBUG_MODE", "false").lower() == "true"

if not token:
    raise ValueError("LUCKY_POT_DISCORD_TOKEN is not set")


async def send_winnings_to_user(winner_discord_id: str, amount: int) -> bool:
    """Send STK winnings to the winner"""
    return await stk.send_stk(winner_discord_id, amount, "Lucky Pot Winnings")


async def announce_to_guild(guild_id: str, message: str) -> None:
    """Send announcement to guild's designated channel"""
    try:
        channel_snowflake = await stk.get_guild_channel(guild_id)

        if channel_snowflake:
            channel_id = int(channel_snowflake)
            channel = bot.cache.get_guild_channel(channel_id)

            if channel and isinstance(channel, hikari.TextableGuildChannel):
                await channel.send(message)
                logger.info(f"Announced to guild {guild_id}: {message}")
            else:
                logger.warning(
                    f"Could not find channel {channel_id} in guild {guild_id}"
                )
        else:
            logger.warning(f"No designated channel found for guild {guild_id}")

    except Exception as e:
        logger.error(f"Error announcing to guild {guild_id}: {e}")


async def process_stackcoin_requests():
    """Background task to process StackCoin requests"""
    try:
        unconfirmed_entries = db.get_unconfirmed_entries()
        accepted_requests = await stk.get_accepted_requests()

        for entry in unconfirmed_entries:
            try:
                # Check if this entry's request was accepted
                for request in accepted_requests:
                    if request["id"] == entry["stackcoin_request_id"]:
                        db.confirm_entry(entry["entry_id"])
                        logger.info(
                            f"Confirmed entry {entry['entry_id']} for request {request['id']}"
                        )

                        # Handle instant win
                        if entry["status"] == "instant_win":
                            pot_status = db.get_pot_status(entry["pot_guild_id"])
                            if pot_status is not None:
                                winning_amount = pot_status["total_amount"]
                                if await send_winnings_to_user(
                                    entry["discord_id"], winning_amount
                                ):
                                    db.win_pot(
                                        entry["pot_guild_id"],
                                        entry["discord_id"],
                                        winning_amount,
                                    )
                                    await announce_to_guild(
                                        entry["pot_guild_id"],
                                        f"🎉 **INSTANT WIN!** 🎉\n\n"
                                        f"<@{entry['discord_id']}> has won the pot of **{winning_amount} STK**!\n"
                                        f"Congratulations! 🎊\n\n"
                                        f"A new pot has started - use `/enter-pot` to join!",
                                    )
                        break

            except Exception as e:
                logger.error(f"Error processing entry {entry['entry_id']}: {e}")

        # Handle expired entries
        expired_entries = db.get_expired_entries()
        for entry in expired_entries:
            try:
                if await stk.deny_request(entry["stackcoin_request_id"]):
                    db.deny_entry(entry["entry_id"])
                    logger.info(f"Denied expired entry {entry['entry_id']}")
            except Exception as e:
                logger.error(f"Error denying expired entry {entry['entry_id']}: {e}")

    except Exception as e:
        logger.error(f"Error in process_stackcoin_requests: {e}")


async def daily_pot_draw():
    """Daily pot draw at UTC 0 with 40% win chance"""
    try:
        all_guilds = db.get_all_active_guilds()

        for guild_id in all_guilds:
            pot_status = db.get_pot_status(guild_id)

            if pot_status is None or pot_status["participant_count"] == 0:
                continue

            if random.random() < 0.4:  # 40% chance to win
                participants = db.get_active_pot_participants(guild_id)
                if participants:
                    # Weight by number of entries
                    weighted_participants = []
                    for p in participants:
                        weighted_participants.extend([p["discord_id"]] * p["entries"])

                    winner_id = random.choice(weighted_participants)
                    winning_amount = pot_status["total_amount"]

                    # Send winnings to winner
                    if await send_winnings_to_user(winner_id, winning_amount):
                        db.win_pot(guild_id, winner_id, winning_amount)

                        # Announce win
                        await announce_to_guild(
                            guild_id,
                            f"🎉 **DAILY DRAW WINNER!** 🎉\n\n"
                            f"<@{winner_id}> has won the daily pot of **{winning_amount} STK**!\n"
                            f"Congratulations! 🎊\n\n"
                            f"A new pot has started - use `/enter-pot` to join!",
                        )

                        logger.info(
                            f"Daily draw winner in guild {guild_id}: {winner_id} won {winning_amount} STK"
                        )
                    else:
                        logger.error(
                            f"Failed to send winnings to {winner_id} in guild {guild_id}"
                        )
                else:
                    await announce_to_guild(
                        guild_id,
                        f"🎲 Daily draw occurred, but the pot continues! No winner this time.\n"
                        f"Current pot: **{pot_status['total_amount']} STK**\n"
                        f"Use `/enter-pot` to increase your chances!",
                    )

    except Exception as e:
        logger.error(f"Error in daily_pot_draw: {e}")


async def background_tasks():
    """Run background tasks periodically"""
    while True:
        await process_stackcoin_requests()

        # Run scheduled tasks
        schedule.run_pending()

        await asyncio.sleep(30)  # Check every 30 seconds


# Schedule daily draw
schedule.every().day.at("00:00").do(lambda: asyncio.create_task(daily_pot_draw()))


db.init_database()

bot = hikari.GatewayBot(token=token)
lightbulb_client = lightbulb.client_from_app(bot)

bot.subscribe(hikari.StartingEvent, lightbulb_client.start)


@bot.listen()
async def on_starting(event: hikari.StartingEvent) -> None:
    """Start background tasks when bot starts"""
    asyncio.create_task(background_tasks())


guilds = [int(testing_guild_id)] if testing_guild_id else []


@lightbulb_client.register(guilds=guilds)
class EnterPot(
    lightbulb.SlashCommand,
    name="enter-pot",
    description="Enter the daily lucky pot for 5 STK!",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        guild_id = str(ctx.guild_id)
        discord_id = str(ctx.user.id)

        user = await stk.get_user_by_discord_id(discord_id)

        if not user:
            await ctx.respond(
                "❌ You are not registered with StackCoin! Please run `/dole` first."
            )
            return

        db.get_or_create_user(discord_id, guild_id)

        current_pot = db.get_current_pot(guild_id)
        if not current_pot:
            pot_id = db.create_new_pot(guild_id)
        else:
            pot_id = current_pot["pot_id"]

        if not db.can_user_enter_pot(discord_id, guild_id, pot_id):
            await ctx.respond("⏰ You can only enter the pot once every 6 hours!")
            return

        try:
            request_id = await stk.create_payment_request(
                user["id"], 5, "Lucky Pot Entry"
            )

            if not request_id:
                await ctx.respond("❌ Failed to create payment request.")
                return

            instant_win = random.random() < 0.05
            entry_id = db.create_pot_entry(
                pot_id,
                discord_id,
                guild_id,
                request_id,
                instant_win,
            )
            logger.debug(f"Pot Entry ID: {entry_id}")

            if instant_win:
                # Get current pot total for instant win
                current_status = db.get_pot_status(guild_id)
                if current_status is None:
                    raise Exception("No active pot, but we just created one?")

                pot_total = (
                    current_status.get("total_amount", 0) + 5
                )  # Include this entry

                await ctx.respond(
                    f"🎉 **INSTANT WIN!** {user['username']}, you've won the entire pot of {pot_total} STK!"
                )
            else:
                await ctx.respond(
                    f"🎲 {user['username']}, you've entered the lucky pot! Please accept the 5 STK payment request. Good luck!"
                )

        except Exception as e:
            await ctx.respond(f"❌ Error creating pot entry: {str(e)}")


@lightbulb_client.register(guilds=guilds)
class PotStatus(
    lightbulb.SlashCommand,
    name="pot-status",
    description="Check the current pot status and participants",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        guild_id = str(ctx.guild_id)
        status = db.get_pot_status(guild_id)

        if status is None:
            await ctx.respond("🎲 No active pot! Use `/enter-pot` to start one.")
            return

        embed = hikari.Embed(
            title="🎰 Lucky Pot Status",
            color=0x00FF00,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="💰 Total Pot", value=f"{status['total_amount']} STK", inline=True
        )

        embed.add_field(
            name="👥 Participants", value=str(status["participant_count"]), inline=True
        )

        if status["participants"]:
            participant_list = []
            for p in status["participants"][:10]:  # Show top 10
                participant_list.append(
                    f"<@{p['discord_id']}>: {p['entry_count']} entries"
                )

            embed.add_field(
                name="🏆 Top Participants",
                value="\n".join(participant_list) if participant_list else "None yet",
                inline=False,
            )

        next_draw = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        embed.add_field(
            name="⏰ Next Daily Draw",
            value=f"<t:{int(next_draw.timestamp())}:R>",
            inline=False,
        )

        embed.set_footer(text=f"Pot ID: {status['pot_id']}")

        await ctx.respond(embed=embed)


if debug_mode:

    @lightbulb_client.register(guilds=guilds)
    class ForceEndPot(
        lightbulb.SlashCommand,
        name="force-end-pot",
        description="[DEBUG] Force end the current pot with a draw",
    ):
        @lightbulb.invoke
        async def invoke(self, ctx: lightbulb.Context) -> None:
            guild_id = str(ctx.guild_id)

            pot_status = db.get_pot_status(guild_id)

            if pot_status is None:
                await ctx.respond("❌ No active pot to end!")
                return

            if pot_status["participant_count"] == 0:
                await ctx.respond("❌ Cannot end pot with no participants!")
                return

            try:
                participants = db.get_active_pot_participants(guild_id)
                if participants:
                    # Weight by number of entries
                    weighted_participants = []
                    for p in participants:
                        weighted_participants.extend([p["discord_id"]] * p["entries"])

                    winner_id = random.choice(weighted_participants)
                    winning_amount = pot_status["total_amount"]

                    # Send winnings to winner
                    if await send_winnings_to_user(winner_id, winning_amount):
                        db.win_pot(guild_id, winner_id, winning_amount)

                        # Announce win
                        await announce_to_guild(
                            guild_id,
                            f"🎉 **DEBUG FORCE END!** 🎉\n\n"
                            f"<@{winner_id}> has won the pot of **{winning_amount} STK**!\n"
                            f"Congratulations! 🎊\n\n"
                            f"A new pot has started - use `/enter-pot` to join!",
                        )

                        await ctx.respond(
                            f"✅ Pot ended! Winner: <@{winner_id}> won {winning_amount} STK"
                        )
                        logger.info(
                            f"DEBUG: Force ended pot in guild {guild_id}: {winner_id} won {winning_amount} STK"
                        )
                    else:
                        await ctx.respond(
                            f"❌ Failed to send winnings to <@{winner_id}>"
                        )
                        logger.error(
                            f"DEBUG: Failed to send winnings to {winner_id} in guild {guild_id}"
                        )
                else:
                    await ctx.respond("❌ No confirmed participants found!")

            except Exception as e:
                await ctx.respond(f"❌ Error ending pot: {str(e)}")
                logger.error(f"DEBUG: Error force ending pot in guild {guild_id}: {e}")


if __name__ == "__main__":
    if debug_mode:
        logger.info("DEBUG MODE ENABLED - /force-end-pot command available")
    bot.run()
