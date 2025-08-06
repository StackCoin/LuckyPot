import hikari
import os
import asyncio
import random
import schedule
import threading
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from stackcoin_python import StackCoinClient
import peewee

load_dotenv()

token = os.getenv("LUCKY_POT_DISCORD_TOKEN")
stackcoin_bot_token = os.getenv("LUCKY_POT_STACKCOIN_BOT_TOKEN")
stackcoin_base_url = os.getenv("LUCKY_POT_STACKCOIN_BASE_URL")

if not token:
    raise ValueError("LUCKY_POT_DISCORD_TOKEN is not set")

if not stackcoin_bot_token:
    raise ValueError("LUCKY_POT_STACKCOIN_BOT_TOKEN is not set")

db = peewee.SqliteDatabase("lottery.db")


class BaseModel(peewee.Model):
    class Meta:
        database = db


class LotteryEntry(BaseModel):
    discord_user_id = peewee.CharField()
    entry_date = peewee.DateField()
    stackcoin_request_id = peewee.CharField(null=True)
    paid = peewee.BooleanField(default=False)

    class Meta:
        indexes = ((("discord_user_id", "entry_date"), True),)


class LotteryState(BaseModel):
    last_lottery_date = peewee.DateField()


db.connect()
db.create_tables([LotteryEntry, LotteryState], safe=True)

bot = hikari.GatewayBot(token=token)


async def get_today_date():
    return datetime.now(timezone.utc).date()


async def check_and_update_paid_entries():
    """Check successful requests and mark entries as paid"""
    try:
        async with StackCoinClient(
            stackcoin_bot_token, base_url=stackcoin_base_url
        ) as client:
            today = await get_today_date()

            async for request in client.stream_requests(
                role="receiver", status="accepted"
            ):
                if request.label == "into the LuckyPot":
                    request_date = datetime.fromisoformat(
                        request.requested_at.replace("Z", "+00:00")
                    ).date()
                    if request_date == today:
                        try:
                            entry = LotteryEntry.get(
                                LotteryEntry.stackcoin_request_id == request.id
                            )
                            if not entry.paid:
                                entry.paid = True
                                entry.save()
                                print(
                                    f"Marked entry as paid for user {entry.discord_user_id}"
                                )
                        except LotteryEntry.DoesNotExist:
                            pass
    except Exception as e:
        print(f"Error checking paid entries: {e}")


async def run_lottery():
    """Run the daily lottery drawing"""
    try:
        today = await get_today_date()

        paid_entries = list(
            LotteryEntry.select().where(
                LotteryEntry.entry_date == today, LotteryEntry.paid == True
            )
        )

        if not paid_entries:
            print("No paid entries for today's lottery")
            LotteryEntry.delete().where(LotteryEntry.entry_date == today).execute()
            LotteryState.delete().execute()
            LotteryState.create(last_lottery_date=today)
            return

        async with StackCoinClient(
            stackcoin_bot_token, base_url=stackcoin_base_url
        ) as client:
            async for request in client.stream_requests(
                role="receiver", status="pending"
            ):
                try:
                    await client.deny_request(request.id)
                    print(f"Denied pending request {request.id}")
                except Exception as e:
                    print(f"Error denying request {request.id}: {e}")

            balance = await client.get_my_balance()
            if balance.balance > 0:
                winner = random.choice(paid_entries)

                try:
                    # Look up the winner's internal StackCoin user ID
                    users = await client.get_users(
                        discord_id=int(winner.discord_user_id)
                    )
                    if users.users:
                        stackcoin_user = users.users[0]
                        await client.send(
                            stackcoin_user.id,
                            balance.balance,
                            f"LuckyPot winner! You won {balance.balance} STK from {len(paid_entries)} entries!",
                        )
                        print(
                            f"Sent {balance.balance} STK to winner {stackcoin_user.username} (Discord ID: {winner.discord_user_id})"
                        )
                    else:
                        print(
                            f"Could not find StackCoin user for Discord ID {winner.discord_user_id}"
                        )
                except Exception as e:
                    print(f"Error sending winnings: {e}")

        LotteryEntry.delete().where(LotteryEntry.entry_date == today).execute()
        LotteryState.delete().execute()
        LotteryState.create(last_lottery_date=today)
        print(f"Lottery completed for {today}")

    except Exception as e:
        print(f"Error running lottery: {e}")


async def check_lottery_schedule():
    """Check if lottery should run and handle missed runs"""
    try:
        today = await get_today_date()

        try:
            last_state = LotteryState.get()
            if last_state.last_lottery_date < today:
                print("Running missed lottery...")
                await run_lottery()
        except LotteryState.DoesNotExist:
            print("Running first lottery...")
            await run_lottery()

    except Exception as e:
        print(f"Error checking lottery schedule: {e}")


@bot.listen()
async def handle_mention(event: hikari.GuildMessageCreateEvent) -> None:
    """Handle lottery entry when bot is mentioned"""

    if not event.is_human:
        return

    me = bot.get_me()

    if me.id in event.message.user_mentions_ids:
        user_id = str(event.author.id)
        today = await get_today_date()

        try:
            existing_entry = LotteryEntry.get(
                LotteryEntry.discord_user_id == user_id,
                LotteryEntry.entry_date == today,
            )
            await event.message.respond(
                "You're already entered in today's LuckyPot! The drawing happens at UTC midnight."
            )
            return
        except LotteryEntry.DoesNotExist:
            pass

        try:
            async with StackCoinClient(
                stackcoin_bot_token, base_url=stackcoin_base_url
            ) as client:
                balance = await client.get_my_balance()

                # Look up the user's internal StackCoin user ID
                users = await client.get_users(discord_id=int(user_id))
                if not users.users:
                    await event.message.respond(
                        "Sorry, I couldn't find your StackCoin account. Make sure you're registered on StackCoin!"
                    )
                    return

                stackcoin_user = users.users[0]
                request_result = await client.request_payment(
                    stackcoin_user.id, 5, "into the LuckyPot"
                )

                LotteryEntry.create(
                    discord_user_id=user_id,
                    entry_date=today,
                    stackcoin_request_id=request_result.request_id,
                    paid=False,
                )

                await event.message.respond(
                    f"🎰 Welcome to LuckyPot! I've requested 5 STK from you ({stackcoin_user.username}). "
                    f"Once you pay, you'll be entered in today's lottery! "
                    f"Drawing happens at UTC midnight. Current pot: {balance.balance} STK"
                )

        except Exception as e:
            print(f"Error handling lottery entry: {e}")
            await event.message.respond(
                "Sorry, there was an error processing your lottery entry. Please try again later."
            )


def run_scheduler():
    """Run the scheduler in a separate thread"""
    while True:
        schedule.run_pending()
        time.sleep(1)


async def periodic_tasks():
    """Run periodic tasks every minute"""
    while True:
        try:
            await check_and_update_paid_entries()
            await check_lottery_schedule()
        except Exception as e:
            print(f"Error in periodic tasks: {e}")
        await asyncio.sleep(60)


@bot.listen()
async def on_started(event: hikari.StartedEvent) -> None:
    """Start background tasks when bot starts"""
    schedule.every().day.at("00:00").do(lambda: asyncio.create_task(run_lottery()))

    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    asyncio.create_task(periodic_tasks())

    print("LuckyPot bot started! Lottery runs daily at UTC midnight.")


if __name__ == "__main__":
    bot.run()
