"""add rounds to pots and pot_entries

Introduces per-pot rounds so users can re-enter the same pot after a missed
daily draw. ``pots.current_round`` tracks the active round; each miss bumps
it by one. ``pot_entries.entry_round`` records which round an entry belongs
to. A partial unique index forbids two entries from the same user in the
same round of the same pot.

Revision ID: 0002_rounds
Revises: 0001_initial
Create Date: 2026-06-22 12:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_rounds"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("pots", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "current_round",
                sa.Integer,
                nullable=False,
                server_default=sa.text("1"),
            )
        )

    with op.batch_alter_table("pot_entries", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "entry_round",
                sa.Integer,
                nullable=False,
                server_default=sa.text("1"),
            )
        )

    op.create_index(
        "idx_pot_entries_one_per_round",
        "pot_entries",
        ["pot_id", "discord_id", "entry_round"],
        unique=True,
        sqlite_where=sa.text("status IN ('pending', 'confirmed')"),
    )


def downgrade() -> None:
    op.drop_index("idx_pot_entries_one_per_round", table_name="pot_entries")

    with op.batch_alter_table("pot_entries", schema=None) as batch_op:
        batch_op.drop_column("entry_round")

    with op.batch_alter_table("pots", schema=None) as batch_op:
        batch_op.drop_column("current_round")
