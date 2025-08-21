import sqlite3
from contextlib import contextmanager
from typing import Generator
from typing_extensions import TypedDict


class Pot(TypedDict):
    pot_id: int
    guild_id: str
    winner_id: str | None
    winning_amount: int
    created_at: str
    won_at: str | None
    is_active: bool


class PotEntry(TypedDict):
    entry_id: int
    pot_id: int
    discord_id: str
    guild_id: str
    amount: int
    status: str
    stackcoin_request_id: str
    created_at: str
    confirmed_at: str | None
    pot_guild_id: str


class Participant(TypedDict):
    discord_id: str


class ParticipantWithAmount(TypedDict):
    discord_id: str
    total_amount: int


class PotStatus(TypedDict):
    pot_id: int
    total_amount: int
    participant_count: int
    participants: list[ParticipantWithAmount]
    created_at: str


DB_PATH = "lucky_pot.db"


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Get a database connection with automatic cleanup"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_transaction() -> Generator[sqlite3.Connection, None, None]:
    """Get a database connection with transaction management"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    with get_connection() as conn:
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
                FOREIGN KEY (discord_id, guild_id) REFERENCES users(discord_id, guild_id),
                UNIQUE(pot_id, discord_id)
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


def get_or_create_user(
    conn: sqlite3.Connection, discord_id: str, guild_id: str
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO users (discord_id, guild_id)
        VALUES (?, ?)
    """,
        (discord_id, guild_id),
    )


def get_current_pot(conn: sqlite3.Connection, guild_id: str) -> Pot | None:
    cursor = conn.execute(
        """
        SELECT * FROM pots
        WHERE guild_id = ? AND is_active = TRUE AND winner_id IS NULL
        ORDER BY created_at DESC LIMIT 1
    """,
        (guild_id,),
    )
    row = cursor.fetchone()
    return Pot(**dict(row)) if row else None


def create_new_pot(conn: sqlite3.Connection, guild_id: str) -> int:
    cursor = conn.execute(
        """
        INSERT INTO pots (guild_id) VALUES (?)
    """,
        (guild_id,),
    )
    last_row_id = cursor.lastrowid
    if last_row_id is None:
        raise Exception("Failed to create new pot")
    return last_row_id


def can_user_enter_pot(
    conn: sqlite3.Connection, discord_id: str, guild_id: str, pot_id: int
) -> bool:
    cursor = conn.execute(
        """
        SELECT COUNT(*) FROM pot_entries
        WHERE discord_id = ? AND guild_id = ? AND pot_id = ?
          AND status IN ('confirmed', 'unconfirmed', 'instant_win')
    """,
        (discord_id, guild_id, pot_id),
    )
    count = cursor.fetchone()[0]
    return count == 0


def create_pot_entry(
    conn: sqlite3.Connection,
    pot_id: int,
    discord_id: str,
    guild_id: str,
    stackcoin_request_id: str,
    is_instant_win: bool = False,
) -> int:
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

    if is_instant_win:
        cursor.execute(
            """
            UPDATE pot_entries SET status = 'instant_win' WHERE entry_id = ?
        """,
            (entry_id,),
        )

    return entry_id


def get_pot_status(conn: sqlite3.Connection, guild_id: str) -> PotStatus | None:
    pot = get_current_pot(conn, guild_id)
    if not pot:
        return None

    cursor = conn.execute(
        """
        SELECT discord_id, amount as total_amount
        FROM pot_entries
        WHERE pot_id = ? AND status = 'confirmed'
        ORDER BY total_amount DESC
    """,
        (pot["pot_id"],),
    )

    participants = [ParticipantWithAmount(**dict(row)) for row in cursor.fetchall()]

    cursor = conn.execute(
        """
        SELECT SUM(amount) as total_pot FROM pot_entries
        WHERE pot_id = ? AND status = 'confirmed'
    """,
        (pot["pot_id"],),
    )

    total_pot = cursor.fetchone()[0] or 0

    return PotStatus(
        pot_id=pot["pot_id"],
        total_amount=total_pot,
        participant_count=len(participants),
        participants=participants,
        created_at=pot["created_at"],
    )


def confirm_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute(
        """
        UPDATE pot_entries
        SET status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP
        WHERE entry_id = ?
    """,
        (entry_id,),
    )


def deny_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute(
        """
        UPDATE pot_entries
        SET status = 'denied'
        WHERE entry_id = ?
    """,
        (entry_id,),
    )


def get_unconfirmed_entries(conn: sqlite3.Connection) -> list[PotEntry]:
    cursor = conn.execute("""
        SELECT pe.*, p.guild_id as pot_guild_id
        FROM pot_entries pe
        JOIN pots p ON pe.pot_id = p.pot_id
        WHERE pe.status = 'unconfirmed'
          AND pe.created_at > datetime('now', '-1 hour')
        ORDER BY pe.created_at ASC
    """)
    return [PotEntry(**dict(row)) for row in cursor.fetchall()]


def get_expired_entries(conn: sqlite3.Connection) -> list[PotEntry]:
    cursor = conn.execute("""
        SELECT pe.*, p.guild_id as pot_guild_id
        FROM pot_entries pe
        JOIN pots p ON pe.pot_id = p.pot_id
        WHERE pe.status = 'unconfirmed'
          AND pe.created_at <= datetime('now', '-1 hour')
        ORDER BY pe.created_at ASC
    """)
    return [PotEntry(**dict(row)) for row in cursor.fetchall()]


def get_active_pot_participants(
    conn: sqlite3.Connection, guild_id: str
) -> list[Participant]:
    pot = get_current_pot(conn, guild_id)
    if not pot:
        return []

    cursor = conn.execute(
        """
        SELECT discord_id
        FROM pot_entries
        WHERE pot_id = ? AND status = 'confirmed'
    """,
        (pot["pot_id"],),
    )
    return [Participant(**dict(row)) for row in cursor.fetchall()]


def win_pot(
    conn: sqlite3.Connection, guild_id: str, winner_id: str, winning_amount: int
) -> None:
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


def get_all_active_guilds(conn: sqlite3.Connection) -> list[str]:
    cursor = conn.execute("""
        SELECT DISTINCT guild_id FROM pots WHERE is_active = TRUE
    """)
    return [row[0] for row in cursor.fetchall()]


def get_entry_by_id(conn: sqlite3.Connection, entry_id: int) -> PotEntry | None:
    """Get a pot entry by ID"""
    cursor = conn.execute(
        """
        SELECT pe.*, p.guild_id as pot_guild_id
        FROM pot_entries pe
        JOIN pots p ON pe.pot_id = p.pot_id
        WHERE pe.entry_id = ?
    """,
        (entry_id,),
    )
    row = cursor.fetchone()
    return PotEntry(**dict(row)) if row else None
