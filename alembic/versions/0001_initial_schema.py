"""initial schema baseline matching production as of 2026-06-22

Captures the exact schema state of the running production luckypot SQLite
database (dumped via PRAGMA table_info + sqlite_master on mug). Future
migrations build on this baseline.

Existing prod databases that pre-date alembic are stamped to this revision by
``db.init_database`` so they don't try to recreate tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the baseline schema that matches prod as of 2026-06-22.

    Order matters for foreign keys: ``pots`` before ``pot_entries``.
    """

    op.create_table(
        "pots",
        sa.Column("pot_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("ended_at", sa.TIMESTAMP, nullable=True),
        sa.Column("winner_discord_id", sa.Text, nullable=True),
        sa.Column("winning_amount", sa.Integer, nullable=True),
        sa.Column("win_type", sa.Text, nullable=True),
    )

    op.create_table(
        "pot_entries",
        sa.Column("entry_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("pot_id", sa.Integer, nullable=False),
        sa.Column("discord_id", sa.Text, nullable=False),
        sa.Column("amount", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("stackcoin_request_id", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["pot_id"], ["pots.pot_id"]),
    )

    op.create_table(
        "gateway_state",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )

    op.create_table(
        "user_bans",
        sa.Column("ban_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("discord_id", sa.Text, nullable=False),
        sa.Column("guild_id", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("banned_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.TIMESTAMP, nullable=False),
    )

    op.create_table(
        "auto_enter_users",
        sa.Column("discord_id", sa.Text, nullable=False),
        sa.Column("guild_id", sa.Text, nullable=False),
        sa.Column("enabled_at", sa.Text, nullable=False, server_default=sa.text("datetime('now')")),
        sa.PrimaryKeyConstraint("discord_id", "guild_id"),
    )

    # Indexes (matching prod by name so a re-run is a no-op)
    op.create_index("idx_pots_guild_active", "pots", ["guild_id", "is_active"])
    op.create_index(
        "idx_pots_one_active_per_guild",
        "pots",
        ["guild_id"],
        unique=True,
        sqlite_where=sa.text("is_active = TRUE"),
    )
    op.create_index("idx_pot_entries_pot_id", "pot_entries", ["pot_id"])
    op.create_index("idx_pot_entries_request_id", "pot_entries", ["stackcoin_request_id"])
    op.create_index(
        "idx_pot_entries_active_request_id_unique",
        "pot_entries",
        ["stackcoin_request_id"],
        unique=True,
        sqlite_where=sa.text(
            "stackcoin_request_id IS NOT NULL AND status IN ('pending', 'confirmed')"
        ),
    )
    op.create_index("idx_user_bans_lookup", "user_bans", ["discord_id", "guild_id", "expires_at"])
    op.create_index("idx_auto_enter_guild", "auto_enter_users", ["guild_id"])


def downgrade() -> None:
    op.drop_index("idx_auto_enter_guild", table_name="auto_enter_users")
    op.drop_index("idx_user_bans_lookup", table_name="user_bans")
    op.drop_index(
        "idx_pot_entries_active_request_id_unique", table_name="pot_entries"
    )
    op.drop_index("idx_pot_entries_request_id", table_name="pot_entries")
    op.drop_index("idx_pot_entries_pot_id", table_name="pot_entries")
    op.drop_index("idx_pots_one_active_per_guild", table_name="pots")
    op.drop_index("idx_pots_guild_active", table_name="pots")

    op.drop_table("auto_enter_users")
    op.drop_table("user_bans")
    op.drop_table("gateway_state")
    op.drop_table("pot_entries")
    op.drop_table("pots")