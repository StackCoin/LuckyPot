import os
import sqlite3
import random
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

import hikari
import lightbulb
import schedule
from dotenv import load_dotenv
from loguru import logger
from stackcoin_python import AuthenticatedClient
from stackcoin_python.types import Unset
from stackcoin_python.models import (
    UsersResponse,
    CreateRequestParams,
    CreateRequestResponse,
    RequestsResponse,
    SendStkParams,
    SendStkResponse,
    DiscordGuildResponse,
)
from stackcoin_python.api.default import (
    stackcoin_users,
    stackcoin_create_request,
    stackcoin_requests,
    stackcoin_deny_request,
    stackcoin_discord_guild,
    stackcoin_send_stk,
)

load_dotenv()

# Configure loguru
logger.add("lucky_pot.log", rotation="1 day", retention="7 days", level="INFO")
logger.info("Starting LuckyPot Discord Bot")

token = os.getenv("LUCKY_POT_DISCORD_TOKEN")
stackcoin_bot_token = os.getenv("LUCKY_POT_STACKCOIN_BOT_TOKEN")
stackcoin_base_url = (
    os.getenv("LUCKY_POT_STACKCOIN_BASE_URL") or "https://stackcoin.world"
)

testing_guild_id = os.getenv("LUCKY_POT_TESTING_GUILD_ID")
debug_mode = os.getenv("LUCKY_POT_DEBUG_MODE", "false").lower() == "true"

if not token:
    raise ValueError("LUCKY_POT_DISCORD_TOKEN is not set")

if not stackcoin_bot_token:
    raise ValueError("LUCKY_POT_STACKCOIN_BOT_TOKEN is not set")


def get_client():
    global stackcoin_base_url, stackcoin_bot_token

    if not stackcoin_base_url or not stackcoin_bot_token:
        raise ValueError(
            "LUCKY_POT_STACKCOIN_BASE_URL or LUCKY_POT_STACKCOIN_BOT_TOKEN is not set"
        )

    return AuthenticatedClient(base_url=stackcoin_base_url, token=stackcoin_bot_token)


class Database:
    def __init__(self, db_path: str = "lucky_pot.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    discord_id TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    total_wins INTEGER DEFAULT 0,
                    total_winnings INTEGER DEFAULT 0,
                    last_entry_time TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (discord_id, guild_id)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS pots (
                    pot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    winner_id TEXT NULL,
                    winning_amount INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    won_at TIMESTAMP NULL,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS pot_entries (
                    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pot_id INTEGER NOT NULL,
                    discord_id TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    amount INTEGER NOT NULL DEFAULT 5,
                    status TEXT DEFAULT 'unconfirmed',
                    stackcoin_request_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    confirmed_at TIMESTAMP NULL,
                    FOREIGN KEY (pot_id) REFERENCES pots(pot_id),
                    FOREIGN KEY (discord_id, guild_id) REFERENCES users(discord_id, guild_id)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS stackcoin_requests (
                    request_id TEXT PRIMARY KEY,
                    entry_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP NULL,
                    FOREIGN KEY (entry_id) REFERENCES pot_entries(entry_id)
                )
            """)

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pots_guild_active ON pots(guild_id, is_active)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_pot_status ON pot_entries(pot_id, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_user_time ON pot_entries(discord_id, guild_id, created_at)"
            )

            conn.commit()

    def get_or_create_user(self, discord_id: str, guild_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO users (discord_id, guild_id)
                VALUES (?, ?)
            """,
                (discord_id, guild_id),
            )
            conn.commit()

    def get_current_pot(self, guild_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM pots
                WHERE guild_id = ? AND is_active = TRUE AND winner_id IS NULL
                ORDER BY created_at DESC LIMIT 1
            """,
                (guild_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def create_new_pot(self, guild_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO pots (guild_id) VALUES (?)
            """,
                (guild_id,),
            )
            conn.commit()
            last_row_id = cursor.lastrowid
            if last_row_id is None:
                raise Exception("Failed to create new pot")
            return last_row_id

    def can_user_enter_pot(self, discord_id: str, guild_id: str, pot_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM pot_entries
                WHERE discord_id = ? AND guild_id = ? AND pot_id = ?
                  AND created_at > datetime('now', '-6 hours')
                  AND status IN ('confirmed', 'unconfirmed')
            """,
                (discord_id, guild_id, pot_id),
            )
            count = cursor.fetchone()[0]
            return count == 0

    def create_pot_entry(
        self,
        pot_id: int,
        discord_id: str,
        guild_id: str,
        stackcoin_request_id: str,
        is_instant_win: bool = False,
    ) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO pot_entries (pot_id, discord_id, guild_id, stackcoin_request_id)
                VALUES (?, ?, ?, ?)
            """,
                (pot_id, discord_id, guild_id, stackcoin_request_id),
            )

            entry_id = cursor.lastrowid

            if entry_id is None:
                raise Exception("Failed to create pot entry")

            # Mark as instant win in a separate field if needed
            if is_instant_win:
                cursor.execute(
                    """
                    UPDATE pot_entries SET status = 'instant_win' WHERE entry_id = ?
                """,
                    (entry_id,),
                )

            conn.commit()
            return entry_id

    def get_pot_status(self, guild_id: str) -> Dict[str, Any]:
        pot = self.get_current_pot(guild_id)
        if not pot:
            return {"exists": False}

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            cursor = conn.execute(
                """
                SELECT discord_id, COUNT(*) as entry_count, SUM(amount) as total_amount
                FROM pot_entries
                WHERE pot_id = ? AND status = 'confirmed'
                GROUP BY discord_id
                ORDER BY entry_count DESC, total_amount DESC
            """,
                (pot["pot_id"],),
            )

            participants = [dict(row) for row in cursor.fetchall()]

            cursor = conn.execute(
                """
                SELECT SUM(amount) as total_pot FROM pot_entries
                WHERE pot_id = ? AND status = 'confirmed'
            """,
                (pot["pot_id"],),
            )

            total_pot = cursor.fetchone()[0] or 0

            return {
                "exists": True,
                "pot_id": pot["pot_id"],
                "total_amount": total_pot,
                "participant_count": len(participants),
                "participants": participants,
                "created_at": pot["created_at"],
            }

    def confirm_entry(self, entry_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE pot_entries
                SET status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP
                WHERE entry_id = ?
            """,
                (entry_id,),
            )
            conn.commit()

    def deny_entry(self, entry_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE pot_entries 
                SET status = 'denied'
                WHERE entry_id = ?
            """,
                (entry_id,),
            )
            conn.commit()

    def get_unconfirmed_entries(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT pe.*, p.guild_id as pot_guild_id
                FROM pot_entries pe
                JOIN pots p ON pe.pot_id = p.pot_id
                WHERE pe.status = 'unconfirmed'
                  AND pe.created_at > datetime('now', '-1 hour')
                ORDER BY pe.created_at ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_expired_entries(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT pe.*, p.guild_id as pot_guild_id
                FROM pot_entries pe
                JOIN pots p ON pe.pot_id = p.pot_id
                WHERE pe.status = 'unconfirmed'
                  AND pe.created_at <= datetime('now', '-1 hour')
                ORDER BY pe.created_at ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_active_pot_participants(self, guild_id: str) -> List[Dict[str, Any]]:
        pot = self.get_current_pot(guild_id)
        if not pot:
            return []

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT discord_id, COUNT(*) as entries
                FROM pot_entries 
                WHERE pot_id = ? AND status = 'confirmed'
                GROUP BY discord_id
            """,
                (pot["pot_id"],),
            )
            return [dict(row) for row in cursor.fetchall()]

    def win_pot(self, guild_id: str, winner_id: str, winning_amount: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE pots 
                SET winner_id = ?, winning_amount = ?, won_at = CURRENT_TIMESTAMP, is_active = FALSE
                WHERE guild_id = ? AND is_active = TRUE AND winner_id IS NULL
            """,
                (winner_id, winning_amount, guild_id),
            )

            conn.execute(
                """
                UPDATE users 
                SET total_wins = total_wins + 1, total_winnings = total_winnings + ?
                WHERE discord_id = ? AND guild_id = ?
            """,
                (winning_amount, winner_id, guild_id),
            )

            conn.commit()

    def get_all_active_guilds(self) -> List[str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT DISTINCT guild_id FROM pots WHERE is_active = TRUE
            """)
            return [row[0] for row in cursor.fetchall()]


async def send_winnings_to_user(winner_discord_id: str, amount: int) -> bool:
    """Send STK winnings to the winner"""
    try:
        async with get_client() as client:
            # Get winner's StackCoin user info
            users_response = await stackcoin_users.asyncio(
                client=client, discord_id=winner_discord_id
            )

            if not isinstance(users_response, UsersResponse) or isinstance(
                users_response.users, Unset
            ):
                logger.error(f"Failed to get user info for {winner_discord_id}")
                return False

            if len(users_response.users) == 0:
                logger.error(
                    f"No StackCoin user found for Discord ID {winner_discord_id}"
                )
                return False

            winner_user = users_response.users[0]

            winner_user_id = winner_user.id

            if isinstance(winner_user_id, Unset):
                logger.error(f"No StackCoin user ID found for {winner_discord_id}")
                return False

            # Send STK to winner
            send_response = await stackcoin_send_stk.asyncio(
                client=client,
                user_id=winner_user_id,
                body=SendStkParams(amount=int(amount), label="Lucky Pot Winnings"),
            )

            if isinstance(send_response, SendStkResponse) and send_response.success:
                logger.info(f"Successfully sent {amount} STK to {winner_user.username}")
                return True
            else:
                logger.error(f"Failed to send STK to {winner_user.username}")
                return False

    except Exception as e:
        logger.error(f"Error sending winnings to {winner_discord_id}: {e}")
        return False


async def announce_to_guild(guild_id: str, message: str) -> None:
    """Send announcement to guild's designated channel"""
    try:
        async with get_client() as client:
            guild_response = await stackcoin_discord_guild.asyncio(
                client=client, snowflake=guild_id
            )

            if (
                isinstance(guild_response, DiscordGuildResponse)
                and guild_response.designated_channel_snowflake
            ):
                channel_id = int(guild_response.designated_channel_snowflake)
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

    logger.debug("Processing StackCoin requests")

    try:
        async with get_client() as client:
            unconfirmed_entries = db.get_unconfirmed_entries()

            for entry in unconfirmed_entries:
                try:
                    requests_response = await stackcoin_requests.asyncio(
                        client=client, role="requester", status="accepted"
                    )

                    logger.debug(f"Requests response: {requests_response}")

                    if isinstance(
                        requests_response, RequestsResponse
                    ) and not isinstance(requests_response.requests, Unset):
                        for request in requests_response.requests:
                            if str(request.id) == entry["stackcoin_request_id"]:
                                db.confirm_entry(entry["entry_id"])
                                logger.info(
                                    f"Confirmed entry {entry['entry_id']} for request {request.id}"
                                )

                                # Handle instant win
                                if entry["status"] == "instant_win":
                                    pot_status = db.get_pot_status(
                                        entry["pot_guild_id"]
                                    )
                                    if pot_status["exists"]:
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

            expired_entries = db.get_expired_entries()
            for entry in expired_entries:
                try:
                    await stackcoin_deny_request.asyncio(
                        client=client, request_id=int(entry["stackcoin_request_id"])
                    )
                    db.deny_entry(entry["entry_id"])
                    logger.info(f"Denied expired entry {entry['entry_id']}")
                except Exception as e:
                    logger.error(
                        f"Error denying expired entry {entry['entry_id']}: {e}"
                    )

    except Exception as e:
        logger.error(f"Error in process_stackcoin_requests: {e}")


async def daily_pot_draw():
    """Daily pot draw at UTC 0 with 40% win chance"""
    try:
        all_guilds = db.get_all_active_guilds()

        for guild_id in all_guilds:
            pot_status = db.get_pot_status(guild_id)

            if not pot_status["exists"] or pot_status["participant_count"] == 0:
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


db = Database()

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

        async with get_client() as client:
            users = await stackcoin_users.asyncio(client=client, discord_id=discord_id)

            if not isinstance(users, UsersResponse) or isinstance(users.users, Unset):
                await ctx.respond("❌ Failed to verify your StackCoin account.")
                return

            if len(users.users) == 0:
                await ctx.respond(
                    "❌ You are not registered with StackCoin! Please run `/dole` first."
                )
                return

            user = users.users[0]

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
                user_id = user.id
                if isinstance(user_id, Unset):
                    logger.error(f"No StackCoin user ID found for {discord_id}")
                    await ctx.respond("❌ Failed to create payment request.")
                    return

                request_response = await stackcoin_create_request.asyncio(
                    client=client,
                    user_id=user_id,
                    body=CreateRequestParams(amount=5, label="Entry to Lucky Pot"),
                )

                if not isinstance(request_response, CreateRequestResponse):
                    await ctx.respond("❌ Failed to create payment request.")
                    return

                instant_win = random.random() < 0.05
                entry_id = db.create_pot_entry(
                    pot_id,
                    discord_id,
                    guild_id,
                    str(request_response.request_id),
                    instant_win,
                )

                logger.debug(f"Pot entry ID: {entry_id}")

                if instant_win:
                    # Get current pot total for instant win
                    current_status = db.get_pot_status(guild_id)
                    pot_total = (
                        current_status.get("total_amount", 0) + 5
                    )  # Include this entry

                    await ctx.respond(
                        f"🎉 **INSTANT WIN!** {user.username}, you've won the entire pot of {pot_total} STK!"
                    )
                else:
                    await ctx.respond(
                        f"🎲 {user.username}, you've entered the lucky pot! Please accept the 5 STK payment request. Good luck!"
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

        if not status["exists"]:
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

            if not pot_status["exists"]:
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
