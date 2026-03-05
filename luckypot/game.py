import asyncio
import random
from functools import partial
from typing import Any, Callable, Awaitable

from loguru import logger
from luckypot import db, stk

POT_ENTRY_COST = 5
DAILY_DRAW_CHANCE = 0.6
RANDOM_WIN_CHANCE = 0.05

# Guild-bound announce functions (guild_id already applied via partial)
AnnounceFn = Callable[[str], Awaitable[Any]] | None
EditAnnounceFn = Callable[[Any, str], Awaitable[Any]] | None

# Raw announce functions that take guild_id as first arg
RawAnnounceFn = Callable[[str, str], Awaitable[Any]] | None
RawEditAnnounceFn = Callable[[str, Any, str], Awaitable[Any]] | None


async def enter_pot(
    discord_id: str, guild_id: str, announce_fn: AnnounceFn = None
) -> dict:
    """Core pot entry logic.

    1. Looks up the user's StackCoin account by Discord ID.
    2. Ensures an active pot exists for the guild.
    3. Prevents duplicate entries.
    4. Creates a STK *request* (bot requests payment from the user).
    5. Records a pending entry in the local DB.
    6. Rolls for an instant-win.

    Returns a result dict with at least a `status` key:
      - pending - request created, waiting for user to accept
      - instant_win - user got an instant win (still needs payment confirmation)
      - already_entered - user is already in the pot
      - error - something went wrong (see ``message`` key)
    """

    # Look up StackCoin user
    stk_user = await stk.get_user_by_discord_id(discord_id)
    if stk_user is None:
        return {
            "status": "error",
            "message": "You don't have a StackCoin account. Please register first.",
        }

    conn = db.get_connection()
    try:
        pot = db.ensure_active_pot(conn, guild_id)
        pot_id = pot["pot_id"]

        if db.has_user_entered(conn, pot_id, discord_id):
            return {
                "status": "already_entered",
                "message": "You have already entered this pot!",
            }

        if db.has_pending_instant_wins(conn, guild_id):
            return {
                "status": "error",
                "message": "An instant win is being processed. Please try again shortly.",
            }

        stk_user_id = stk_user["id"]
        idempotency_key = f"pot_entry:{pot_id}:{discord_id}"
        req = await stk.create_request(
            to_user_id=stk_user_id,
            amount=POT_ENTRY_COST,
            label=f"LuckyPot entry (pot #{pot_id})",
            idempotency_key=idempotency_key,
        )
        if req is None:
            return {
                "status": "error",
                "message": "Failed to create StackCoin payment request.",
            }

        request_id = str(req["request_id"])

        is_instant_win = random.random() < RANDOM_WIN_CHANCE
        initial_status = "pending"

        entry_id = db.add_entry(
            conn,
            pot_id=pot_id,
            discord_id=discord_id,
            amount=POT_ENTRY_COST,
            stackcoin_request_id=request_id,
            status=initial_status,
        )

        if is_instant_win:
            db.mark_entry_instant_win(conn, entry_id)
            logger.info(
                f"Instant win rolled for discord_id={discord_id} entry_id={entry_id}"
            )
            return {
                "status": "instant_win",
                "entry_id": entry_id,
                "request_id": request_id,
                "message": "You rolled an INSTANT WIN! Accept the payment request to claim your prize!",
            }

        return {
            "status": "pending",
            "entry_id": entry_id,
            "request_id": request_id,
            "message": f"Entry submitted! Accept the {POT_ENTRY_COST} STK request to confirm your spot.",
        }
    finally:
        conn.close()


def select_random_winner(participants: list[dict]) -> dict | None:
    """Select a random winner from a list of participant entry dicts.

    Each participant has a `discord_id` and `amount` field. Selection is
    weighted by contribution amount (though normally everyone pays the same).
    """
    if not participants:
        return None

    total_weight = sum(p["amount"] for p in participants)
    roll = random.uniform(0, total_weight)
    cumulative = 0
    for p in participants:
        cumulative += p["amount"]
        if roll <= cumulative:
            return p
    return participants[-1]


async def send_winnings_to_user(
    winner_discord_id: str, amount: int, idempotency_key: str | None = None
) -> bool:
    """Send STK winnings to the winner, checking bot balance first."""
    bot_balance = await stk.get_bot_balance()
    if bot_balance is None:
        logger.error("Could not check bot balance")
        return False
    if bot_balance < amount:
        logger.error(
            f"Bot balance ({bot_balance}) insufficient to pay {amount} STK to {winner_discord_id}"
        )
        return False

    stk_user = await stk.get_user_by_discord_id(winner_discord_id)
    if stk_user is None:
        logger.error(
            f"Could not find StackCoin user for discord_id={winner_discord_id}"
        )
        return False

    result = await stk.send_stk(
        to_user_id=stk_user["id"],
        amount=amount,
        label="LuckyPot winnings",
        idempotency_key=idempotency_key,
    )
    return result is not None


async def process_pot_win(
    conn,
    guild_id: str,
    winner_id: str,
    winning_amount: int,
    win_type: str = "DAILY DRAW",
    announce_fn: AnnounceFn = None,
    edit_announce_fn: EditAnnounceFn = None,
) -> bool:
    """Process a pot win: send winnings and update DB.

    For daily draws, performs a dramatic staged reveal by sending a message
    and editing it through several stages with delays.
    """
    pot = db.get_active_pot(conn, guild_id)
    if pot is None:
        logger.warning(f"No active pot found for guild {guild_id}")
        return False

    idempotency_key = f"pot_win:{pot['pot_id']}:{winner_id}"
    sent = await send_winnings_to_user(
        winner_id, winning_amount, idempotency_key=idempotency_key
    )
    if sent:
        db.end_pot(conn, pot["pot_id"], winner_id, winning_amount, win_type)
        logger.info(
            f"Pot #{pot['pot_id']} won by {winner_id} for {winning_amount} STK ({win_type})"
        )
        if announce_fn and edit_announce_fn:
            await _dramatic_draw_reveal(
                announce_fn, edit_announce_fn, winner_id, winning_amount, win_type
            )
        elif announce_fn:
            await announce_fn(f"<@{winner_id}> won {winning_amount} STK! ({win_type})")
    else:
        logger.error(f"Failed to send winnings to {winner_id}, pot remains active")
        if announce_fn:
            await announce_fn(
                f"Failed to send winnings to <@{winner_id}>. The pot remains active."
            )
    return sent


async def _dramatic_draw_reveal(
    announce_fn: Callable[[str], Awaitable[Any]],
    edit_announce_fn: Callable[[Any, str], Awaitable[Any]],
    winner_id: str,
    winning_amount: int,
    win_type: str,
) -> None:
    """Send a staged dramatic reveal for a pot draw."""
    label = win_type.lower()
    msg = await announce_fn(f"Time for the {label}!")
    if msg is None:
        return

    await asyncio.sleep(3)
    msg = await edit_announce_fn(msg, "The winner is...")

    await asyncio.sleep(3)
    if msg:
        await edit_announce_fn(
            msg,
            f"<@{winner_id}> has won the {label} of {winning_amount} STK!",
        )


async def end_pot_with_winner(
    guild_id: str,
    win_type: str = "DAILY DRAW",
    announce_fn: AnnounceFn = None,
    edit_announce_fn: EditAnnounceFn = None,
) -> bool:
    """End a pot by selecting and paying a winner."""
    conn = db.get_connection()
    try:
        pot = db.get_active_pot(conn, guild_id)
        if pot is None:
            logger.info(f"No active pot for guild {guild_id}, nothing to draw")
            return False

        participants = db.get_pot_participants(conn, pot["pot_id"])
        if not participants:
            logger.info(f"No participants in pot #{pot['pot_id']}, skipping draw")
            return False

        winner = select_random_winner(participants)
        if winner is None:
            return False

        total_pot = sum(p["amount"] for p in participants)
        return await process_pot_win(
            conn,
            guild_id=guild_id,
            winner_id=winner["discord_id"],
            winning_amount=total_pot,
            win_type=win_type,
            announce_fn=announce_fn,
            edit_announce_fn=edit_announce_fn,
        )
    finally:
        conn.close()


async def daily_pot_draw(
    announce: RawAnnounceFn = None,
    edit_announce: RawEditAnnounceFn = None,
):
    """Daily pot draw

    For each guild with an active pot, rolls DAILY_DRAW_CHANCE to decide
    whether to draw a winner. If no draw, the pot carries over.

    ``announce`` and ``edit_announce`` are the raw bot functions that take
    ``guild_id`` as their first argument. Per-guild partials are created
    internally for each guild being drawn.
    """
    conn = db.get_connection()
    try:
        guilds = db.get_all_active_guilds(conn)
    finally:
        conn.close()

    for guild_id in guilds:
        check_conn = db.get_connection()
        try:
            has_pending = db.has_pending_instant_wins(check_conn, guild_id)
        finally:
            check_conn.close()

        if has_pending:
            logger.info(
                f"Skipping daily draw for guild {guild_id}: pending instant wins"
            )
            continue

        roll = random.random()
        if roll < DAILY_DRAW_CHANCE:
            logger.info(f"Daily draw triggered for guild {guild_id} (roll={roll:.3f})")
            guild_announce = partial(announce, guild_id) if announce else None
            guild_edit = partial(edit_announce, guild_id) if edit_announce else None
            await end_pot_with_winner(
                guild_id,
                win_type="DAILY DRAW",
                announce_fn=guild_announce,
                edit_announce_fn=guild_edit,
            )
        else:
            logger.info(
                f"Daily draw skipped for guild {guild_id} (roll={roll:.3f}, needed < {DAILY_DRAW_CHANCE})"
            )


async def on_request_accepted(event: dict, announce: RawAnnounceFn = None):
    """Handle a payment request being accepted.

    When a user accepts the pot entry payment, we confirm their entry.
    If it was an instant win, we immediately process the win.

    ``announce`` is the raw announce function that takes ``(guild_id, message)``
    — the guild is looked up from the DB entry, not from the event payload.
    """
    request_id = str(event.get("request_id", ""))
    if not request_id:
        logger.warning("on_request_accepted called without request_id")
        return

    conn = db.get_connection()
    try:
        entry = db.get_entry_by_request_id(conn, request_id)
        if entry is None:
            logger.debug(
                f"Request {request_id} not associated with any pot entry (ignoring)"
            )
            return

        entry_id = entry["entry_id"]
        guild_id = entry["pot_guild_id"]
        discord_id = entry["discord_id"]
        announce_fn = partial(announce, guild_id) if announce else None

        if entry["status"] == "instant_win":
            db.confirm_entry(conn, entry_id)
            logger.info(
                f"Instant win confirmed for entry {entry_id}, discord_id={discord_id}"
            )

            pot = db.get_active_pot(conn, guild_id)
            if pot is None:
                logger.error(f"No active pot for guild {guild_id} during instant win")
                return

            participants = db.get_pot_participants(conn, pot["pot_id"])
            total_pot = sum(p["amount"] for p in participants)

            if announce_fn:
                await announce_fn(
                    f"<@{discord_id}> entered the pot and rolled an INSTANT WIN! The pot was at {total_pot} STK!"
                )

            await process_pot_win(
                conn,
                guild_id=guild_id,
                winner_id=discord_id,
                winning_amount=total_pot,
                win_type="INSTANT WIN",
                announce_fn=announce_fn,
            )
        elif entry["status"] == "pending":
            db.confirm_entry(conn, entry_id)
            logger.info(f"Entry {entry_id} confirmed for discord_id={discord_id}")
            if announce_fn:
                pot = db.get_active_pot(conn, guild_id)
                total_pot = 0
                if pot:
                    participants = db.get_pot_participants(conn, pot["pot_id"])
                    total_pot = sum(p["amount"] for p in participants)
                await announce_fn(
                    f"<@{discord_id}> entered the pot! The pot is now at {total_pot} STK. Use `/enter-pot` to enter!"
                )
        else:
            logger.warning(
                f"Request accepted for entry {entry_id} in unexpected status: {entry['status']}"
            )
    finally:
        conn.close()


async def on_request_denied(event: dict, announce: RawAnnounceFn = None):
    """Handle a payment request being denied.

    ``announce`` is the raw announce function that takes ``(guild_id, message)``.
    """
    request_id = str(event.get("request_id", ""))
    if not request_id:
        logger.warning("on_request_denied called without request_id")
        return

    conn = db.get_connection()
    try:
        entry = db.get_entry_by_request_id(conn, request_id)
        if entry is None:
            logger.debug(
                f"Request {request_id} not associated with any pot entry (ignoring)"
            )
            return

        entry_id = entry["entry_id"]
        guild_id = entry["pot_guild_id"]
        discord_id = entry["discord_id"]
        announce_fn = partial(announce, guild_id) if announce else None

        db.deny_entry(conn, entry_id)
        logger.info(f"Entry {entry_id} denied for discord_id={discord_id}")
        if announce_fn:
            await announce_fn(
                f"<@{discord_id}>'s pot entry was cancelled (payment denied)."
            )
    finally:
        conn.close()
