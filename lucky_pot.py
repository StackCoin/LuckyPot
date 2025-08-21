import random
import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from typing_extensions import TypedDict

from hikari.impl.special_endpoints import ContainerComponentBuilder
import hikari
import lightbulb
import schedule
from loguru import logger
import db
import stk
import config


POT_ENTRY_COST = 5
CHECK_INTERVAL_SECONDS = 30
DAILY_DRAW_CHANCE = 0.6
RANDOM_WIN_CHANCE = 0.05

MESSAGES = {
    "not_registered": "❌ You are not registered with StackCoin! Please run `/dole` first.",
    "payment_request_failed": "❌ Failed to create payment request.",
    "already_entered": "❌ You have already entered this pot! You can only enter once per pot.",
    "no_active_pot": "🎲 No active pot! Use `/enter-pot` to start one.",
    "pot_status_error": "❌ Error retrieving pot status. Please try again later.",
    "debug_no_active_pot": "❌ No active pot to end!",
    "debug_no_participants": "❌ Cannot end pot with no participants!",
    "debug_no_confirmed_participants": "❌ No confirmed participants found!",
}


def announce_winner(
    guild_id: str, winner_id: str, winning_amount: int, win_type: str = "DAILY DRAW"
):
    """Create winner announcement message"""
    return (
        f"🎉 **{win_type} WINNER!** 🎉\n\n"
        f"<@{winner_id}> has won the pot of **{winning_amount} STK**!\n"
        f"Congratulations! 🎊\n\n"
        f"A new pot has started - use `/enter-pot` to join!"
    )


def announce_daily_draw_no_winner(guild_id: str, pot_amount: int):
    """Create daily draw no winner announcement"""
    return (
        f"🎲 Daily draw occurred, but the pot continues! No winner this time.\n"
        f"Current pot: **{pot_amount} STK**\n"
        f"Use `/enter-pot` to increase your chances!"
    )


def create_pot_status_container(status):
    """Create container component for pot status display"""

    container = ContainerComponentBuilder(accent_color=hikari.Color(0x00FF00))
    container.add_text_display("🎰 Lucky Pot Status")
    container.add_text_display(f"💰 Total Pot: {status['total_amount']} STK")

    container.add_text_display(f"👥 Participants: {status['participant_count']}")

    if status.get("participants"):
        participant_list = []
        for p in status["participants"][:10]:
            participant_list.append(f"<@{p['discord_id']}>")

        if participant_list:
            participant_text = "\n".join(participant_list)
            container.add_text_display(f"🏆 Participants\n{participant_text}")

    next_draw = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)

    container.add_text_display(
        f"⏰ Next Daily Draw: <t:{int(next_draw.timestamp())}:R>"
    )

    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)

    container.add_text_display(f"Pot ID: {status['pot_id']}")

    return container


def get_instant_win_message(username: str, pot_total: int):
    """Get instant win message"""
    return (
        f"🎉 **INSTANT WIN!** {username}, you've won the entire pot of {pot_total} STK!"
    )


def get_entry_confirmation_message(username: str):
    """Get entry confirmation message"""
    return f"🎲 {username}, accept the {POT_ENTRY_COST} STK payment request from StackCoin via DMs, and you're in the pot!"


def get_debug_success_message(winner_id: str, winning_amount: int):
    """Get debug success message"""
    return f"✅ Pot ended! Winner: <@{winner_id}> won {winning_amount} STK"


class WinnerInfo(TypedDict):
    winner_id: str
    winning_amount: int
    participant_count: int


logger.add("lucky_pot.log", rotation="1 day", retention="7 days", level="INFO")
logger.info("Starting LuckyPot Discord Bot")

if not config.DISCORD_TOKEN:
    raise ValueError("LUCKY_POT_DISCORD_TOKEN is not set")


async def send_winnings_to_user(winner_discord_id: str, amount: int) -> bool:
    """Send STK winnings to the winner"""
    return await stk.send_stk(winner_discord_id, amount, "Lucky Pot Winnings")


async def announce_to_guild(guild_id: str, message: str) -> None:
    """Send announcement to guild's designated channel"""
    channel_snowflake = await stk.get_guild_channel(guild_id)

    if channel_snowflake:
        channel_id = int(channel_snowflake)
        channel = bot.cache.get_guild_channel(channel_id)

        if channel and isinstance(channel, hikari.TextableGuildChannel):
            await channel.send(message)
            logger.info(f"Announced to guild {guild_id}: {message}")
        else:
            logger.warning(f"Could not find channel {channel_id} in guild {guild_id}")
    else:
        logger.warning(f"No designated channel found for guild {guild_id}")


async def process_stackcoin_requests():
    """Background task to process StackCoin requests"""
    with db.get_connection() as conn:
        unconfirmed_entries = db.get_unconfirmed_entries(conn)

    accepted_requests = await stk.get_accepted_requests()

    for entry in unconfirmed_entries:
        for request in accepted_requests:
            if str(request.id) == entry["stackcoin_request_id"]:
                if entry["status"] == "instant_win":
                    with db.get_transaction() as conn:
                        db.confirm_entry(conn, entry["entry_id"])
                        pot_status = db.get_pot_status(conn, entry["pot_guild_id"])
                        if pot_status is not None:
                            winning_amount = pot_status["total_amount"]
                            await process_pot_win(
                                conn,
                                entry["pot_guild_id"],
                                entry["discord_id"],
                                winning_amount,
                                "INSTANT WIN",
                            )
                else:
                    with db.get_transaction() as conn:
                        db.confirm_entry(conn, entry["entry_id"])

                logger.info(
                    f"Confirmed entry {entry['entry_id']} for request {request.id}"
                )
                break

    with db.get_connection() as conn:
        expired_entries = db.get_expired_entries(conn)

    for entry in expired_entries:
        if await stk.deny_request(entry["stackcoin_request_id"]):
            with db.get_transaction() as conn:
                db.deny_entry(conn, entry["entry_id"])
            logger.info(f"Denied expired entry {entry['entry_id']}")


def select_random_winner(participants: list[db.Participant]) -> str:
    """Select a random winner from participants"""
    participant_ids = [p["discord_id"] for p in participants]
    return random.choice(participant_ids)


async def process_pot_win(
    conn: sqlite3.Connection,
    guild_id: str,
    winner_id: str,
    winning_amount: int,
    win_type: str = "DAILY DRAW",
) -> bool:
    """Process a pot win: send winnings and announce"""
    if await send_winnings_to_user(winner_id, winning_amount):
        db.win_pot(conn, guild_id, winner_id, winning_amount)

        await announce_to_guild(
            guild_id, announce_winner(guild_id, winner_id, winning_amount, win_type)
        )

        logger.info(
            f"{win_type} winner in guild {guild_id}: {winner_id} won {winning_amount} STK"
        )
        return True
    else:
        logger.error(f"Failed to send winnings to {winner_id} in guild {guild_id}")
        return False


async def end_pot_with_winner(
    guild_id: str, win_type: str = "DAILY DRAW"
) -> WinnerInfo | None:
    """End a pot by selecting and paying a winner. Returns winner info or None if failed."""
    with db.get_transaction() as conn:
        pot_status = db.get_pot_status(conn, guild_id)

        if pot_status is None or pot_status["participant_count"] == 0:
            return None

        participants = db.get_active_pot_participants(conn, guild_id)
        if not participants:
            return None

        winner_id = select_random_winner(participants)
        winning_amount = pot_status["total_amount"]

        if await process_pot_win(conn, guild_id, winner_id, winning_amount, win_type):
            return WinnerInfo(
                winner_id=winner_id,
                winning_amount=winning_amount,
                participant_count=pot_status["participant_count"],
            )

    return None


async def daily_pot_draw():
    """Daily pot draw at UTC 0 with 40% win chance"""
    with db.get_connection() as conn:
        all_guilds = db.get_all_active_guilds(conn)

    for guild_id in all_guilds:
        with db.get_connection() as conn:
            pot_status = db.get_pot_status(conn, guild_id)

            if pot_status is None or pot_status["participant_count"] == 0:
                continue

            if random.random() < DAILY_DRAW_CHANCE:
                winner_info = await end_pot_with_winner(guild_id, "DAILY DRAW")
                if not winner_info:
                    await announce_to_guild(
                        guild_id,
                        announce_daily_draw_no_winner(
                            guild_id, pot_status["total_amount"]
                        ),
                    )
            else:
                await announce_to_guild(
                    guild_id,
                    announce_daily_draw_no_winner(guild_id, pot_status["total_amount"]),
                )


async def background_tasks():
    """Run background tasks periodically"""
    while True:
        try:
            await process_stackcoin_requests()

            schedule.run_pending()

        except Exception as e:
            logger.error(f"Error in background tasks: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


schedule.every().day.at("00:00").do(lambda: asyncio.create_task(daily_pot_draw()))


db.init_database()

bot = hikari.GatewayBot(token=config.DISCORD_TOKEN)
lightbulb_client = lightbulb.client_from_app(bot)

bot.subscribe(hikari.StartingEvent, lightbulb_client.start)


@bot.listen()
async def on_starting(event: hikari.StartingEvent) -> None:
    """Start background tasks when bot starts"""
    try:
        asyncio.create_task(background_tasks())
    except Exception as e:
        logger.error(f"Critical startup error: {e}")
        exit(0)


guilds = [int(config.TESTING_GUILD_ID)] if config.TESTING_GUILD_ID else []


@lightbulb_client.register(guilds=guilds)
class EnterPot(
    lightbulb.SlashCommand,
    name="enter-pot",
    description=f"Enter the daily lucky pot (costs {POT_ENTRY_COST} STK)",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        try:
            guild_id = str(ctx.guild_id)
            discord_id = str(ctx.user.id)

            user = await stk.get_user_by_discord_id(discord_id)

            if not user:
                await ctx.respond(MESSAGES["not_registered"])
                return

            if not isinstance(user.id, int):
                raise Exception("User ID is not an integer")

            request_id = await stk.create_payment_request(
                user.id, POT_ENTRY_COST, "Lucky Pot Entry"
            )

            if not request_id:
                await ctx.respond(MESSAGES["payment_request_failed"])
                return

            instant_win = random.random() < RANDOM_WIN_CHANCE

            with db.get_transaction() as conn:
                db.get_or_create_user(conn, discord_id, guild_id)

                current_pot = db.get_current_pot(conn, guild_id)
                if not current_pot:
                    pot_id = db.create_new_pot(conn, guild_id)
                else:
                    pot_id = current_pot["pot_id"]

                if not db.can_user_enter_pot(conn, discord_id, guild_id, pot_id):
                    await ctx.respond(MESSAGES["already_entered"])
                    return

                entry_id = db.create_pot_entry(
                    conn,
                    pot_id,
                    discord_id,
                    guild_id,
                    request_id,
                    instant_win,
                )

                if instant_win:
                    current_status = db.get_pot_status(conn, guild_id)
                    if current_status is None:
                        raise Exception("No active pot, but we just created one?")
                    pot_total = current_status.get("total_amount", 0) + POT_ENTRY_COST
                else:
                    pot_total = None

            logger.debug(f"Pot Entry ID: {entry_id}")

            if instant_win:
                await ctx.respond(
                    get_instant_win_message(user.username, pot_total or 0)
                )
            else:
                await ctx.respond(get_entry_confirmation_message(user.username))

        except Exception as e:
            logger.error(f"Error in EnterPot command for user {ctx.user.id}: {e}")
            await ctx.respond(f"❌ Error creating pot entry: {str(e)}")


@lightbulb_client.register(guilds=guilds)
class PotStatus(
    lightbulb.SlashCommand,
    name="pot-status",
    description="Check the current pot status and participants",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        try:
            guild_id = str(ctx.guild_id)

            with db.get_connection() as conn:
                status = db.get_pot_status(conn, guild_id)

            if status is None:
                await ctx.respond(MESSAGES["no_active_pot"])
                return

            container_builder = create_pot_status_container(status)
            await ctx.respond(components=[container_builder])

        except Exception as e:
            logger.error(f"Error in PotStatus command for guild {ctx.guild_id}: {e}")
            await ctx.respond(MESSAGES["pot_status_error"])


if config.DEBUG_MODE:

    @lightbulb_client.register(guilds=guilds)
    class ForceEndPot(
        lightbulb.SlashCommand,
        name="force-end-pot",
        description="[DEBUG] Force end the current pot with a draw",
    ):
        @lightbulb.invoke
        async def invoke(self, ctx: lightbulb.Context) -> None:
            try:
                guild_id = str(ctx.guild_id)

                with db.get_connection() as conn:
                    pot_status = db.get_pot_status(conn, guild_id)

                if pot_status is None:
                    await ctx.respond(MESSAGES["debug_no_active_pot"])
                    return

                if pot_status["participant_count"] == 0:
                    await ctx.respond(MESSAGES["debug_no_participants"])
                    return

                winner_info = await end_pot_with_winner(guild_id, "DEBUG FORCE END")

                if winner_info:
                    await ctx.respond(
                        get_debug_success_message(
                            winner_info["winner_id"], winner_info["winning_amount"]
                        )
                    )
                else:
                    await ctx.respond(MESSAGES["debug_no_confirmed_participants"])

            except Exception as e:
                logger.error(
                    f"Error in ForceEndPot command for guild {ctx.guild_id}: {e}"
                )
                await ctx.respond(f"❌ Error ending pot: {str(e)}")


if __name__ == "__main__":
    if config.DEBUG_MODE:
        logger.info("DEBUG MODE ENABLED - /force-end-pot command available")
    bot.run()
