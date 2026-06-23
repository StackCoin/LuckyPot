import sqlite3
from pathlib import Path
from typing import cast

from loguru import logger
from luckypot.config import settings
from luckypot.types import (
    PotEntryRow,
    PotEntryWithPotRow,
    PotRow,
    PotStatus,
    UserBanRow,
)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_database():
    """Initialize or migrate the database to the latest schema via alembic.

    On a fresh database, all migrations run from the baseline.

    On a legacy pre-alembic database (one that has the user tables but no
    ``alembic_version`` table), the DB is stamped to the initial baseline
    migration so migrations don't try to recreate tables; then any newer
    migrations are applied normally.
    """
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if _is_legacy_db(db_path):
        _stamp_legacy_db(db_path)

    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option(
        "script_location", str(Path(__file__).parent.parent / "alembic")
    )
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")

    logger.info("Database initialized")


def _is_legacy_db(db_path: Path) -> bool:
    """Return True if the DB has user tables but no alembic_version table.

    Such a database predates alembic and must be stamped before upgrade head
    is called, otherwise alembic would try to recreate tables that already
    exist (and fail).
    """
    if not db_path.exists():
        return False
    conn = sqlite3.connect(str(db_path))
    try:
        has_alembic = (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()
            is not None
        )
        if has_alembic:
            return False
        has_pots = (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='pots'"
            ).fetchone()
            is not None
        )
        return has_pots
    finally:
        conn.close()


def _stamp_legacy_db(db_path: Path) -> None:
    """Stamp a legacy pre-alembic database to the initial baseline migration."""
    from alembic import command
    from alembic.config import Config

    logger.info(
        f"Legacy pre-alembic database detected at {db_path}; stamping to 0001_initial"
    )
    cfg = Config()
    cfg.set_main_option(
        "script_location", str(Path(__file__).parent.parent / "alembic")
    )
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.stamp(cfg, "0001_initial")


def get_active_pot(conn, guild_id: str) -> PotRow | None:
    """Get the active pot for a guild, or None if there isn't one."""
    cursor = conn.execute(
        "SELECT * FROM pots WHERE guild_id = ? AND is_active = TRUE",
        (guild_id,),
    )
    row = cursor.fetchone()
    return cast(PotRow, dict(row)) if row else None


def create_pot(conn, guild_id: str) -> PotRow:
    """Create a new active pot for a guild."""
    cursor = conn.execute(
        "INSERT INTO pots (guild_id) VALUES (?)",
        (guild_id,),
    )
    conn.commit()
    return {
        "pot_id": cursor.lastrowid,
        "guild_id": guild_id,
        "is_active": True,
        "current_round": 1,
    }


def ensure_active_pot(conn, guild_id: str) -> PotRow:
    """Return the active pot for a guild, creating one if necessary."""
    pot = get_active_pot(conn, guild_id)
    if pot is None:
        pot = create_pot(conn, guild_id)
    return pot


def end_pot(
    conn, pot_id: int, winner_discord_id: str | None, winning_amount: int, win_type: str
):
    """Mark a pot as ended with a winner."""
    conn.execute(
        """UPDATE pots
           SET is_active = FALSE,
               ended_at = CURRENT_TIMESTAMP,
               winner_discord_id = ?,
               winning_amount = ?,
               win_type = ?
           WHERE pot_id = ?""",
        (winner_discord_id, winning_amount, win_type, pot_id),
    )
    conn.commit()


def claim_pot_for_payout(conn, pot_id: int) -> bool:
    """Atomically mark an active pot inactive before attempting payout."""
    cursor = conn.execute(
        "UPDATE pots SET is_active = FALSE WHERE pot_id = ? AND is_active = TRUE",
        (pot_id,),
    )
    conn.commit()
    return cursor.rowcount == 1


def reopen_pot_after_failed_payout(conn, pot_id: int) -> None:
    """Reactivate a claimed pot when no payout was sent."""
    conn.execute(
        """UPDATE pots
           SET is_active = TRUE
           WHERE pot_id = ?
             AND winner_discord_id IS NULL
             AND ended_at IS NULL""",
        (pot_id,),
    )
    conn.commit()


def advance_pot_round(conn, pot_id: int) -> int:
    """Bump a pot's current_round by 1 and return the new round number.

    Called after a daily-draw roll misses, signalling that the pot is now
    accepting entries for the next round.
    """
    conn.execute(
        "UPDATE pots SET current_round = current_round + 1 WHERE pot_id = ?",
        (pot_id,),
    )
    conn.commit()
    row = conn.execute(
        "SELECT current_round FROM pots WHERE pot_id = ?", (pot_id,)
    ).fetchone()
    return row["current_round"]


def add_entry(
    conn,
    pot_id: int,
    discord_id: str,
    amount: int,
    stackcoin_request_id: str | None = None,
    status: str = "pending",
    entry_round: int = 1,
) -> int:
    """Add an entry to a pot for a specific round. Returns the entry_id.

    The ``(pot_id, discord_id, entry_round)`` triple is constrained unique by
    ``idx_pot_entries_one_per_round`` for pending/confirmed entries.
    """
    cursor = conn.execute(
        """INSERT INTO pot_entries
             (pot_id, discord_id, amount, status, stackcoin_request_id, entry_round)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (pot_id, discord_id, amount, status, stackcoin_request_id, entry_round),
    )
    conn.commit()
    return cursor.lastrowid


def get_entry_by_id(conn, entry_id: int) -> PotEntryRow | None:
    """Get a pot entry by its ID."""
    cursor = conn.execute("SELECT * FROM pot_entries WHERE entry_id = ?", (entry_id,))
    row = cursor.fetchone()
    return cast(PotEntryRow, dict(row)) if row else None


def get_entry_by_request_id(conn, request_id: str) -> PotEntryWithPotRow | None:
    """Get a pot entry by its StackCoin request ID, including pot guild_id."""
    cursor = conn.execute(
        """SELECT pe.*, p.guild_id AS pot_guild_id, p.is_active AS pot_is_active
           FROM pot_entries pe
           JOIN pots p ON pe.pot_id = p.pot_id
           WHERE pe.stackcoin_request_id = ?""",
        (request_id,),
    )
    row = cursor.fetchone()
    return cast(PotEntryWithPotRow, dict(row)) if row else None


def confirm_entry(conn, entry_id: int):
    """Mark an entry as confirmed (payment received)."""
    cursor = conn.execute(
        "UPDATE pot_entries SET status = 'confirmed' WHERE entry_id = ?",
        (entry_id,),
    )
    conn.commit()
    return cursor.rowcount == 1


def confirm_pending_entry(conn, entry_id: int) -> bool:
    """Mark a pending entry as confirmed. Returns True if changed."""
    cursor = conn.execute(
        "UPDATE pot_entries SET status = 'confirmed' WHERE entry_id = ? AND status = 'pending'",
        (entry_id,),
    )
    conn.commit()
    return cursor.rowcount == 1


def deny_entry(conn, entry_id: int):
    """Mark an entry as denied (payment rejected)."""
    cursor = conn.execute(
        "UPDATE pot_entries SET status = 'denied' WHERE entry_id = ?",
        (entry_id,),
    )
    conn.commit()
    return cursor.rowcount == 1


def deny_pending_entry(conn, entry_id: int) -> bool:
    """Mark a pending entry as denied. Returns True if changed."""
    cursor = conn.execute(
        "UPDATE pot_entries SET status = 'denied' WHERE entry_id = ? AND status = 'pending'",
        (entry_id,),
    )
    conn.commit()
    return cursor.rowcount == 1


def ban_user(conn, discord_id: str, guild_id: str, reason: str, duration_hours: int):
    """Ban a user from entering pots in a guild for a specified duration."""
    conn.execute(
        """INSERT INTO user_bans (discord_id, guild_id, reason, expires_at)
           VALUES (?, ?, ?, datetime('now', '+' || ? || ' hours'))""",
        (discord_id, guild_id, reason, duration_hours),
    )
    conn.commit()


def get_active_ban(conn, discord_id: str, guild_id: str) -> UserBanRow | None:
    """Get the active (non-expired) ban for a user in a guild, or None."""
    cursor = conn.execute(
        """SELECT * FROM user_bans
           WHERE discord_id = ? AND guild_id = ? AND expires_at > datetime('now')
           ORDER BY expires_at DESC LIMIT 1""",
        (discord_id, guild_id),
    )
    row = cursor.fetchone()
    return cast(UserBanRow, dict(row)) if row else None


def get_confirmed_entries(conn, pot_id: int) -> list[PotEntryRow]:
    """Get all confirmed entries for a pot."""
    cursor = conn.execute(
        "SELECT * FROM pot_entries WHERE pot_id = ? AND status = 'confirmed'",
        (pot_id,),
    )
    return [cast(PotEntryRow, dict(row)) for row in cursor.fetchall()]


def get_pot_participants(conn, pot_id: int) -> list[PotEntryRow]:
    """Get all confirmed entries for a pot (active participants)."""
    cursor = conn.execute(
        "SELECT * FROM pot_entries WHERE pot_id = ? AND status = 'confirmed'",
        (pot_id,),
    )
    return [cast(PotEntryRow, dict(row)) for row in cursor.fetchall()]


def get_pot_status(conn, guild_id: str) -> PotStatus:
    """Get the current pot status for a guild."""
    pot = get_active_pot(conn, guild_id)
    if pot is None:
        return {"active": False, "participants": 0, "total_amount": 0}

    cursor = conn.execute(
        """SELECT COUNT(*) as count, COALESCE(SUM(amount), 0) as total
           FROM pot_entries
           WHERE pot_id = ? AND status = 'confirmed'""",
        (pot["pot_id"],),
    )
    row = cursor.fetchone()
    return {
        "active": True,
        "pot_id": pot["pot_id"],
        "participants": row["count"],
        "total_amount": row["total"],
    }


def has_user_entered(conn, pot_id: int, discord_id: str, entry_round: int) -> bool:
    """Check if a user has already entered the given round of the pot.

    The ``(pot_id, discord_id, entry_round)`` triple is constrained unique by
    ``idx_pot_entries_one_per_round`` for pending/confirmed entries, so this
    query returns at most one row.
    """
    cursor = conn.execute(
        """SELECT COUNT(*) as count FROM pot_entries
           WHERE pot_id = ? AND discord_id = ? AND entry_round = ?
           AND status IN ('pending', 'confirmed')""",
        (pot_id, discord_id, entry_round),
    )
    return cursor.fetchone()["count"] > 0


def get_all_active_guilds(conn) -> list[str]:
    """Get all guild_ids that have an active pot."""
    cursor = conn.execute("SELECT DISTINCT guild_id FROM pots WHERE is_active = TRUE")
    return [row["guild_id"] for row in cursor.fetchall()]


PAGE_SIZE = 5


def get_pot_history(conn, guild_id: str, page: int = 1) -> list[PotRow]:
    """Get paginated pot history for a guild.

    Returns up to PAGE_SIZE completed pots, ordered most-recent first.
    ``page`` is 1-indexed.
    """
    offset = (page - 1) * PAGE_SIZE
    cursor = conn.execute(
        """SELECT * FROM pots
           WHERE guild_id = ? AND is_active = FALSE
           ORDER BY ended_at DESC LIMIT ? OFFSET ?""",
        (guild_id, PAGE_SIZE, offset),
    )
    return [cast(PotRow, dict(row)) for row in cursor.fetchall()]


def get_last_event_id(conn) -> int:
    """Get the last processed gateway event ID, or 0 if none."""
    cursor = conn.execute("SELECT value FROM gateway_state WHERE key = 'last_event_id'")
    row = cursor.fetchone()
    return int(row["value"]) if row else 0


def set_last_event_id(conn, event_id: int) -> None:
    """Persist the last processed gateway event ID."""
    conn.execute(
        "INSERT INTO gateway_state (key, value) VALUES ('last_event_id', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(event_id),),
    )
    conn.commit()


def set_auto_enter(conn, discord_id: str, guild_id: str, enabled: bool) -> None:
    """Opt a user in or out of auto-enter for a guild."""
    if enabled:
        conn.execute(
            """INSERT INTO auto_enter_users (discord_id, guild_id)
               VALUES (?, ?)
               ON CONFLICT(discord_id, guild_id) DO NOTHING""",
            (discord_id, guild_id),
        )
    else:
        conn.execute(
            "DELETE FROM auto_enter_users WHERE discord_id = ? AND guild_id = ?",
            (discord_id, guild_id),
        )
    conn.commit()


def get_auto_enter_users(conn, guild_id: str) -> list[str]:
    """Return discord_ids of all opted-in users for a guild."""
    cursor = conn.execute(
        "SELECT discord_id FROM auto_enter_users WHERE guild_id = ?",
        (guild_id,),
    )
    return [row["discord_id"] for row in cursor.fetchall()]


def get_auto_enter_status(conn, discord_id: str, guild_id: str) -> bool:
    """Return True if the user is opted in to auto-enter for this guild."""
    cursor = conn.execute(
        "SELECT 1 FROM auto_enter_users WHERE discord_id = ? AND guild_id = ?",
        (discord_id, guild_id),
    )
    return cursor.fetchone() is not None
