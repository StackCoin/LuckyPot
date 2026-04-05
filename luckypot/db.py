import sqlite3
from loguru import logger
from luckypot.config import settings


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_database():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pots (
            pot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            winner_discord_id TEXT,
            winning_amount INTEGER,
            win_type TEXT
        );

        CREATE TABLE IF NOT EXISTS pot_entries (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pot_id INTEGER NOT NULL,
            discord_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            stackcoin_request_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pot_id) REFERENCES pots(pot_id)
        );

        CREATE TABLE IF NOT EXISTS gateway_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_pots_guild_active
            ON pots(guild_id, is_active);
        CREATE INDEX IF NOT EXISTS idx_pot_entries_pot_id
            ON pot_entries(pot_id);
        CREATE INDEX IF NOT EXISTS idx_pot_entries_request_id
            ON pot_entries(stackcoin_request_id);

        CREATE TABLE IF NOT EXISTS user_bans (
            ban_id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id TEXT NOT NULL,
            guild_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_user_bans_lookup
            ON user_bans(discord_id, guild_id, expires_at);

        CREATE TABLE IF NOT EXISTS auto_enter_users (
            discord_id TEXT NOT NULL,
            guild_id   TEXT NOT NULL,
            enabled_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (discord_id, guild_id)
        );
    """)
    conn.commit()
    conn.close()
    logger.info("Database initialized")


def get_active_pot(conn, guild_id: str) -> dict | None:
    """Get the active pot for a guild, or None if there isn't one."""
    cursor = conn.execute(
        "SELECT * FROM pots WHERE guild_id = ? AND is_active = TRUE",
        (guild_id,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def create_pot(conn, guild_id: str) -> dict:
    """Create a new active pot for a guild."""
    cursor = conn.execute(
        "INSERT INTO pots (guild_id) VALUES (?)",
        (guild_id,),
    )
    conn.commit()
    return {"pot_id": cursor.lastrowid, "guild_id": guild_id, "is_active": True}


def ensure_active_pot(conn, guild_id: str) -> dict:
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


def add_entry(
    conn,
    pot_id: int,
    discord_id: str,
    amount: int,
    stackcoin_request_id: str | None = None,
    status: str = "pending",
) -> int:
    """Add an entry to a pot. Returns the entry_id."""
    cursor = conn.execute(
        """INSERT INTO pot_entries (pot_id, discord_id, amount, status, stackcoin_request_id)
           VALUES (?, ?, ?, ?, ?)""",
        (pot_id, discord_id, amount, status, stackcoin_request_id),
    )
    conn.commit()
    return cursor.lastrowid


def get_entry_by_id(conn, entry_id: int) -> dict | None:
    """Get a pot entry by its ID."""
    cursor = conn.execute("SELECT * FROM pot_entries WHERE entry_id = ?", (entry_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_entry_by_request_id(conn, request_id: str) -> dict | None:
    """Get a pot entry by its StackCoin request ID, including pot guild_id."""
    cursor = conn.execute(
        """SELECT pe.*, p.guild_id AS pot_guild_id
           FROM pot_entries pe
           JOIN pots p ON pe.pot_id = p.pot_id
           WHERE pe.stackcoin_request_id = ?""",
        (request_id,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def confirm_entry(conn, entry_id: int):
    """Mark an entry as confirmed (payment received)."""
    conn.execute(
        "UPDATE pot_entries SET status = 'confirmed' WHERE entry_id = ?",
        (entry_id,),
    )
    conn.commit()


def deny_entry(conn, entry_id: int):
    """Mark an entry as denied (payment rejected)."""
    conn.execute(
        "UPDATE pot_entries SET status = 'denied' WHERE entry_id = ?",
        (entry_id,),
    )
    conn.commit()


def ban_user(conn, discord_id: str, guild_id: str, reason: str, duration_hours: int):
    """Ban a user from entering pots in a guild for a specified duration."""
    conn.execute(
        """INSERT INTO user_bans (discord_id, guild_id, reason, expires_at)
           VALUES (?, ?, ?, datetime('now', '+' || ? || ' hours'))""",
        (discord_id, guild_id, reason, duration_hours),
    )
    conn.commit()


def get_active_ban(conn, discord_id: str, guild_id: str) -> dict | None:
    """Get the active (non-expired) ban for a user in a guild, or None."""
    cursor = conn.execute(
        """SELECT * FROM user_bans
           WHERE discord_id = ? AND guild_id = ? AND expires_at > datetime('now')
           ORDER BY expires_at DESC LIMIT 1""",
        (discord_id, guild_id),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def get_confirmed_entries(conn, pot_id: int) -> list[dict]:
    """Get all confirmed entries for a pot."""
    cursor = conn.execute(
        "SELECT * FROM pot_entries WHERE pot_id = ? AND status = 'confirmed'",
        (pot_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_pot_participants(conn, pot_id: int) -> list[dict]:
    """Get all confirmed entries for a pot (active participants)."""
    cursor = conn.execute(
        "SELECT * FROM pot_entries WHERE pot_id = ? AND status = 'confirmed'",
        (pot_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_pot_status(conn, guild_id: str) -> dict:
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


def has_user_entered(conn, pot_id: int, discord_id: str) -> bool:
    """Check if a user has already entered the active pot."""
    cursor = conn.execute(
        """SELECT COUNT(*) as count FROM pot_entries
           WHERE pot_id = ? AND discord_id = ? AND status IN ('pending', 'confirmed')""",
        (pot_id, discord_id),
    )
    return cursor.fetchone()["count"] > 0


def get_all_active_guilds(conn) -> list[str]:
    """Get all guild_ids that have an active pot."""
    cursor = conn.execute("SELECT DISTINCT guild_id FROM pots WHERE is_active = TRUE")
    return [row["guild_id"] for row in cursor.fetchall()]


PAGE_SIZE = 5


def get_pot_history(conn, guild_id: str, page: int = 1) -> list[dict]:
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
    return [dict(row) for row in cursor.fetchall()]


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
