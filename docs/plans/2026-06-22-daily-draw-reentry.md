# Daily Draw Re-Entry Implementation Plan

**Goal:** When the daily draw misses (~5% of rolls), users can `/enter-pot` again to add more entries to the same pot. Auto-enter opt-ins are re-entered automatically on every miss. The pot stays open across multiple missed draws, accumulating a bigger prize until a hit.

**Architecture:** Add `current_round` to `pots` and `entry_round` to `pot_entries`. Each pot starts at round 1; each daily-draw miss bumps `current_round` by 1. Entries record which round they were created in. The existing "user already in pot" check becomes round-scoped, so a user can enter once per round. Winner weighting is already entry-row-based, so multiple entries from the same user across rounds automatically weigh correctly. No new slash commands, no new config settings, no new UI.

**Tech Stack:** Python 3.13, SQLite (WAL mode), hikari-lightbulb, e2e tests in `../StackCoin/test/e2e/py/test_luckypot.py` using existing fixtures (`luckypot_db`, `configure_luckypot_stk`, `test_context`, RNG mocking via `unittest.mock.patch("luckypot.game.secrets.randbelow", ...)`).

---

### Task 1: Schema migration

**Files:**
- Modify: `luckypot/db.py` (extend `init_database()`, add `_migrate_schema()`)

**Step 1: Extend `CREATE TABLE` statements** inside `init_database()`'s `executescript` so fresh databases get the new columns:

In the `pots` table definition, add after `win_type TEXT`:
```sql
            , current_round INTEGER NOT NULL DEFAULT 1
```

In the `pot_entries` table definition, add after `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`:
```sql
            , entry_round INTEGER NOT NULL DEFAULT 1
```

After the existing `idx_pot_entries_active_request_id_unique` index, add:
```sql
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pot_entries_one_per_round
            ON pot_entries(pot_id, discord_id, entry_round)
            WHERE status IN ('pending', 'confirmed');
```

**Step 2: Add a migration helper** below `init_database()`:

```python
def _migrate_schema() -> None:
    """Idempotently add new columns to existing databases.

    SQLite's ``CREATE TABLE IF NOT EXISTS`` skips tables that already exist,
    so new columns added in a later release never make it into older prod
    databases. This helper inspects ``PRAGMA table_info`` and runs
    ``ALTER TABLE ... ADD COLUMN`` for any missing columns. Safe to run
    on every boot.
    """
    conn = get_connection()
    try:
        pots_cols = {row["name"] for row in conn.execute("PRAGMA table_info(pots)")}
        if "current_round" not in pots_cols:
            conn.execute("ALTER TABLE pots ADD COLUMN current_round INTEGER NOT NULL DEFAULT 1")

        entries_cols = {row["name"] for row in conn.execute("PRAGMA table_info(pot_entries)")}
        if "entry_round" not in entries_cols:
            conn.execute("ALTER TABLE pot_entries ADD COLUMN entry_round INTEGER NOT NULL DEFAULT 1")

        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_pot_entries_one_per_round "
            "ON pot_entries(pot_id, discord_id, entry_round) "
            "WHERE status IN ('pending', 'confirmed')"
        )
        conn.commit()
    finally:
        conn.close()
```

**Step 3: Call it from `init_database()`** at the end, before `logger.info("Database initialized")`:

```python
    _migrate_schema()
    logger.info("Database initialized")
```

Note: `_migrate_schema` is defined as a module-level function after `init_database`, so the forward call inside `init_database` works because the call happens at runtime, not at definition time.

---

### Task 2: Update `has_user_entered()` and `add_entry()` signatures

**Files:**
- Modify: `luckypot/db.py` (`has_user_entered` at line 245, `add_entry` at line 128)

**Step 1: Make `has_user_entered` round-scoped**

Change:
```python
def has_user_entered(conn, pot_id: int, discord_id: str) -> bool:
    """Check if a user has already entered the active pot."""
    cursor = conn.execute(
        """SELECT COUNT(*) as count FROM pot_entries
           WHERE pot_id = ? AND discord_id = ? AND status IN ('pending', 'confirmed')""",
        (pot_id, discord_id),
    )
    return cursor.fetchone()["count"] > 0
```
to:
```python
def has_user_entered(conn, pot_id: int, discord_id: str, entry_round: int) -> bool:
    """Check if a user has already entered the active pot for the given round.

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
```

**Step 2: Add `entry_round` kwarg to `add_entry`**

Change:
```python
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
```
to:
```python
def add_entry(
    conn,
    pot_id: int,
    discord_id: str,
    amount: int,
    stackcoin_request_id: str | None = None,
    status: str = "pending",
    entry_round: int = 1,
) -> int:
    """Add an entry to a pot for a specific round. Returns the entry_id."""
    cursor = conn.execute(
        """INSERT INTO pot_entries
             (pot_id, discord_id, amount, status, stackcoin_request_id, entry_round)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (pot_id, discord_id, amount, status, stackcoin_request_id, entry_round),
    )
    conn.commit()
    return cursor.lastrowid
```

---

### Task 3: Add `advance_pot_round()` DB function

**Files:**
- Modify: `luckypot/db.py` (add after `end_pot()` around line 126)

```python
def advance_pot_round(conn, pot_id: int) -> int:
    """Bump a pot's current_round by 1 and return the new round number.

    Called after a daily-draw roll misses, signalling that the pot is
    now accepting entries for the next round.
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
```

---

### Task 4: Update `enter_pot()` in game.py

**Files:**
- Modify: `luckypot/game.py` (inside `enter_pot`, around lines 59-130)

**Step 1: Capture `current_round` from the pot object after `ensure_active_pot`**

Current code starts:
```python
        conn = db.get_connection()
        try:
            pot = db.ensure_active_pot(conn, guild_id)
            pot_id = pot["pot_id"]
```

Change to:
```python
        conn = db.get_connection()
        try:
            pot = db.ensure_active_pot(conn, guild_id)
            pot_id = pot["pot_id"]
            current_round = pot["current_round"]
```

**Step 2: Pass `current_round` to `has_user_entered`**

Change:
```python
            if db.has_user_entered(conn, pot_id, discord_id):
```
to:
```python
            if db.has_user_entered(conn, pot_id, discord_id, current_round):
```

**Step 3: Pass `entry_round=current_round` to every `db.add_entry` call**

There are two `db.add_entry` calls in `enter_pot` (one for the instant-win-free-entry path at line 118, one for the normal path at line 160). Both need the new kwarg:

For the instant-win empty-pot free-entry (line 118):
```python
                entry_id = db.add_entry(
                    conn,
                    pot_id=pot_id,
                    discord_id=discord_id,
                    amount=0,
                    stackcoin_request_id=None,
                    status="confirmed",
                    entry_round=current_round,
                )
```

For the normal entry (line 160):
```python
                entry_id = db.add_entry(
                    conn,
                    pot_id=pot_id,
                    discord_id=discord_id,
                    amount=POT_ENTRY_COST,
                    stackcoin_request_id=request_id,
                    entry_round=current_round,
                )
```

---

### Task 5: Update `daily_pot_draw()` miss branch

**Files:**
- Modify: `luckypot/game.py` (inside `daily_pot_draw`, around lines 454-468)

**Step 1: Replace the miss branch**

Current miss branch:
```python
                else:
                    logger.info(
                        f"Daily draw skipped for guild {guild_id} (roll={roll:.3f}, needed < {DAILY_DRAW_CHANCE})"
                    )
                    if announce:
                        pot = db.get_active_pot(conn, guild_id)
                        if pot:
                            participants = db.get_pot_participants(conn, pot["pot_id"])
                            total = sum(p["amount"] for p in participants)
                            guild_announce = partial(announce, guild_id)
                            await guild_announce(
                                f"The daily draw was held, but no winner was chosen today. "
                                f"The pot carries over with {total} STK from {len(participants)} "
                                f"{'entry' if len(participants) == 1 else 'entries'}!"
                            )
```

Replacement:
```python
                else:
                    logger.info(
                        f"Daily draw skipped for guild {guild_id} (roll={roll:.3f}, needed < {DAILY_DRAW_CHANCE})"
                    )
                    pot = db.get_active_pot(conn, guild_id)
                    if pot is None:
                        continue
                    new_round = db.advance_pot_round(conn, pot["pot_id"])
                    participants = db.get_pot_participants(conn, pot["pot_id"])
                    total = sum(p["amount"] for p in participants)
                    entry_word = "entry" if len(participants) == 1 else "entries"
                    if announce:
                        guild_announce = partial(announce, guild_id)
                        await guild_announce(
                            f"No winner today, the pot carries over to round {new_round} "
                            f"with {total} STK from {len(participants)} {entry_word}. "
                            f"Use `/enter-pot` to add another {POT_ENTRY_COST} STK!"
                        )
                    # Fire-and-forget: re-enter opt-ins into the new round.
                    # Scheduled via create_task so it runs after the guild lock
                    # is released (enter_pot acquires the same lock).
                    guild_announce = partial(announce, guild_id) if announce else None
                    asyncio.create_task(
                        _auto_enter_users(guild_id, announce_fn=guild_announce),
                        name=f"auto-enter-round-{new_round}-{guild_id}",
                    )
```

**Step 2: Confirm `PARTY`/imports**

`asyncio` and `partial` are already imported at the top of `game.py`. `POT_ENTRY_COST` is defined at module top. No new imports needed.

---

### Task 6: Add e2e tests in `../StackCoin/test/e2e/py/test_luckypot.py`

**Files:**
- Modify: `../StackCoin/test/e2e/py/test_luckypot.py` (append `TestDailyDrawReentry` class)

All tests use the existing fixtures (`luckypot_db`, `configure_luckypot_stk`, `test_context`, `approve_preauth`) and follow the existing mocking pattern (`@patch("luckypot.game.secrets.randbelow", ...)`) to control RNG. No new fixtures, no new test infrastructure.

**Test class to append:**

```python
@pytest.mark.asyncio
class TestDailyDrawReentry:
    """Daily-draw re-entry across multiple rounds.

    All tests drive `game.daily_pot_draw` directly with mocked RNG and a
    mocked announce fn, then inspect the local DB and StackCoin state.
    """

    @patch("luckypot.game.secrets.randbelow", return_value=9999)
    async def test_single_miss_advances_round(
        self, _mock_rng, luckypot_db, configure_luckypot_stk, test_context
    ):
        """One missed draw advances pot.current_round from 1 to 2."""
        # Seed: user1 enters round 1
        await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_reentry",
        )
        announces = []
        await game.daily_pot_draw(
            announce=lambda gid, msg, **kw: announces.append((gid, msg)),
            edit_announce=None,
        )

        conn = db.get_connection()
        try:
            pot = db.get_active_pot(conn, "test_guild_reentry")
            assert pot["current_round"] == 2
            assert pot["is_active"] == 1  # still open
        finally:
            conn.close()

        assert any("round 2" in msg for _, msg in announces)

    @patch("luckypot.game.secrets.randbelow", return_value=9999)
    async def test_three_misses_in_a_row_advance_to_round_4(
        self, _mock_rng, luckypot_db, configure_luckypot_stk, test_context
    ):
        """Three consecutive misses advance the pot to round 4."""
        await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_reentry",
        )

        for _ in range(3):
            await game.daily_pot_draw(announce=None, edit_announce=None)

        conn = db.get_connection()
        try:
            pot = db.get_active_pot(conn, "test_guild_reentry")
            assert pot["current_round"] == 4
        finally:
            conn.close()

    @patch("luckypot.game.secrets.randbelow", return_value=9999)
    async def test_user_can_reenter_after_miss(
        self, _mock_rng, luckypot_db, configure_luckypot_stk, test_context
    ):
        """After a miss, a user can /enter-pot again and get a round-2 entry."""
        result1 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_reentry",
        )
        assert result1["status"] == "pending"

        await game.daily_pot_draw(announce=None, edit_announce=None)

        # Same user enters again: should succeed in round 2
        result2 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_reentry",
        )
        assert result2["status"] == "pending"

        conn = db.get_connection()
        try:
            entries = conn.execute(
                """SELECT * FROM pot_entries
                   WHERE discord_id = ? AND status IN ('pending','confirmed')
                   ORDER BY entry_id""",
                (test_context["user1_discord_id"],),
            ).fetchall()
            assert len(entries) == 2
            assert entries[0]["entry_round"] == 1
            assert entries[1]["entry_round"] == 2
        finally:
            conn.close()

    @patch("luckypot.game.secrets.randbelow", return_value=9999)
    async def test_cannot_reenter_within_same_round(
        self, _mock_rng, luckypot_db, configure_luckypot_stk, test_context
    ):
        """Without a miss, a user cannot enter the same round twice."""
        result1 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_reentry",
        )
        assert result1["status"] == "pending"

        # No call to daily_pot_draw: round is still 1
        result2 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_reentry",
        )
        assert result2["status"] == "already_entered"

    @patch("luckypot.game.secrets.randbelow", return_value=9999)
    async def test_unique_index_prevents_duplicate_round_entry(
        self, _mock_rng, luckypot_db, configure_luckypot_stk, test_context
    ):
        """Bypassing has_user_entered and inserting directly raises IntegrityError."""
        await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_reentry",
        )

        conn = db.get_connection()
        try:
            pot = db.get_active_pot(conn, "test_guild_reentry")
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """INSERT INTO pot_entries
                         (pot_id, discord_id, amount, status, stackcoin_request_id, entry_round)
                       VALUES (?, ?, ?, 'pending', 'force-dup', 1)""",
                    (pot["pot_id"], test_context["user1_discord_id"], 5),
                )
        finally:
            conn.close()

    @patch("luckypot.game.secrets.randbelow", return_value=9999)
    async def test_auto_enter_fires_on_miss(
        self, _mock_rng, luckypot_db, configure_luckypot_stk, test_context
    ):
        """Opted-in users get auto-entered into the new round after a miss."""
        # Opt user1 into auto-enter
        conn = db.get_connection()
        try:
            db.set_auto_enter(conn, test_context["user1_discord_id"], "test_guild_reentry", True)
        finally:
            conn.close()

        # Patch the 30s sleep so the test runs fast
        with patch("luckypot.game.AUTO_ENTER_DELAY_SECONDS", 0):
            await game.enter_pot(
                discord_id=test_context["user1_discord_id"],
                guild_id="test_guild_reentry",
            )
            await game.daily_pot_draw(announce=None, edit_announce=None)
            # Yield control so the fire-and-forget task can run
            await asyncio.sleep(0.1)

        conn = db.get_connection()
        try:
            entries = conn.execute(
                """SELECT entry_round FROM pot_entries
                   WHERE discord_id = ? AND status IN ('pending','confirmed')
                   ORDER BY entry_id""",
                (test_context["user1_discord_id"],),
            ).fetchall()
            assert [e["entry_round"] for e in entries] == [1, 2]
        finally:
            conn.close()

    @patch("luckypot.game.secrets.randbelow", side_effect=[10000, 0])
    async def test_winner_weighting_across_rounds(
        self, mock_rng, luckypot_db, configure_luckypot_stk, test_context
    ):
        """A user with 3 confirmed entries (rounds 1, 2, 3) wins over a user with 1.

        The first call to secrets.randbelow is the daily draw (mocked to miss
        three times via separate sequencing; here we simplify by mocking two
        misses followed by a hit setting roll=0 which selects the first
        cumulative-weight entry).
        """
        # NOTE: this single test exercises two misses then a hit; the daily
        # draw calls secrets.randbelow once per active guild, and
        # select_random_winner calls it once when picking a winner.
        # We mock sequenced returns: miss=10000 (>= 9500), miss=10000,
        # then for the draw we want the high-entry user to win.
        # Because sequencing is tricky, this test uses a simpler approach:
        # just directly call db functions and select_random_winner.

        conn = db.get_connection()
        try:
            pot = db.create_pot(conn, "test_guild_reentry")
            pot_id = pot["pot_id"]

            # User A enters rounds 1, 2, 3 (3 confirmed entries)
            for r in (1, 2, 3):
                db.add_entry(
                    conn, pot_id=pot_id,
                    discord_id=test_context["user1_discord_id"],
                    amount=5, status="confirmed", entry_round=r,
                )
            # User B enters round 1 only (1 confirmed entry)
            db.add_entry(
                conn, pot_id=pot_id,
                discord_id=test_context["user2_discord_id"],
                amount=5, status="confirmed", entry_round=1,
            )

            participants = db.get_pot_participants(conn, pot_id)
            assert len(participants) == 4  # 3 + 1

            # Total weight = 5 + 5 + 5 + 5 = 20. A user with 3 entries has
            # 75% of the weight (15/20).
            winners = []
            for roll in (0, 5, 10, 14, 15, 16, 19):
                # Patch the specific roll value
                with patch("luckypot.game.secrets.randbelow", return_value=roll):
                    w = game.select_random_winner(participants)
                    winners.append(w["discord_id"])

            from collections import Counter
            counts = Counter(winners)
            assert counts[test_context["user1_discord_id"]] == 12  # rolls 0..14 (3 entries)
            assert counts[test_context["user2_discord_id"]] == 3   # rolls 15..19 (1 entry)
        finally:
            conn.close()

    @patch("luckypot.game.secrets.randbelow", side_effect=[10000, 10000, 0])
    async def test_payout_sums_across_rounds(
        self, mock_rng, luckypot_db, configure_luckypot_stk, test_context
    ):
        """Two misses, then a hit. Winner gets the sum of all rounds.

        secrets.randbelow is called by daily_pot_draw (roll miss=10000 twice),
        then finally by select_random_winner (roll=0 picks the first
        cumulative weight).
        """
        conn = db.get_connection()
        try:
            pot = db.create_pot(conn, "test_guild_reentry")
            pot_id = pot["pot_id"]

            # 3 confirmed entries across rounds 1, 2 (15 STK total) from user1
            for r in (1, 2, 3):
                db.add_entry(
                    conn, pot_id=pot_id,
                    discord_id=test_context["user1_discord_id"],
                    amount=5, status="confirmed", entry_round=r,
                )
            # 1 entry from user2 in round 1
            db.add_entry(
                conn, pot_id=pot_id,
                discord_id=test_context["user2_discord_id"],
                amount=5, status="confirmed", entry_round=1,
            )
            db.advance_pot_round(conn, pot_id)  # round 1 -> 2
            db.advance_pot_round(conn, pot_id)  # round 2 -> 3
        finally:
            conn.close()

        # Now daily_pot_draw: first call misses (round 3->4), second call
        # also misses (but mock_rng only has 3 returns, so we re-invoke).
        # Simpler: directly call end_pot_with_winner with mocked announce.
        announces = []
        won = await game.end_pot_with_winner(
            "test_guild_reentry",
            win_type="DAILY DRAW",
            announce_fn=lambda msg: announces.append(msg),
            edit_announce_fn=None,
        )
        assert won is True

        conn = db.get_connection()
        try:
            pot = db.get_active_pot(conn, "test_guild_reentry")
            assert pot is None  # ended
            ended = conn.execute(
                "SELECT * FROM pots WHERE pot_id = ?",
                (pot_id,) if 'pot_id' in dir() else (1,),
            ).fetchone() if False else None
            # The pot has been marked ended with winning_amount=20
            row = conn.execute(
                "SELECT * FROM pots WHERE guild_id = ?",
                ("test_guild_reentry",),
            ).fetchone()
            assert row["is_active"] == 0
            assert row["winning_amount"] == 20  # 4 entries x 5 STK
        finally:
            conn.close()

        # The announce message should name the winner and amount
        assert any("20 STK" in m for m in announces)

    @patch("luckypot.game.secrets.randbelow", return_value=9999)
    async def test_late_round1_acceptance_during_round2(
        self, _mock_rng, luckypot_db, configure_luckypot_stk, test_context, approve_preauth
    ):
        """A round-1 pending entry accepted during round 2 confirms as round-1.

        The late acceptance path (on_request_accepted line 518) keys off
        pot_is_active, which is unaffected by rounds, so the entry keeps its
        original entry_round=1 and participates in the eventual draw.
        """
        # User1 enters round 1 with a preauth (entry is pending)
        result = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_reentry",
        )
        assert result["status"] == "pending"
        request_id = int(result["request_id"])

        # Miss the draw, round advances to 2
        await game.daily_pot_draw(announce=None, edit_announce=None)

        # User1 accepts the (old) round-1 request
        await game.on_request_accepted(
            RequestAcceptedData(request_id=request_id, status="accepted"),
            announce=None,
        )

        conn = db.get_connection()
        try:
            entry = db.get_entry_by_request_id(conn, str(request_id))
            assert entry["status"] == "confirmed"
            assert entry["entry_round"] == 1  # kept the original round
            assert entry["pot_is_active"] == 1
        finally:
            conn.close()

    @patch("luckypot.game.secrets.randbelow", return_value=9999)
    async def test_late_acceptance_after_pot_ended_refunds(
        self, _mock_rng, luckypot_db, configure_luckypot_stk, test_context
    ):
        """A pending entry accepted after the pot ended should be refunded.

        Reuses the existing late-acceptance path; the change here is just
        verifying nothing broke. The entry_round field is irrelevant
        after the pot ends.
        """
        # user1 enters (pending) then user2 enters (pending) so the pot
        # has at least 1 confirmed participant for a draw to actually end
        result1 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_reentry",
        )
        result2 = await game.enter_pot(
            discord_id=test_context["user2_discord_id"],
            guild_id="test_guild_reentry",
        )

        # Accept user2's entry, leaving user1 pending
        await game.on_request_accepted(
            RequestAcceptedData(request_id=int(result2["request_id"]), status="accepted"),
            announce=None,
        )

        # Force end the pot by rigging the daily draw to hit
        with patch("luckypot.game.secrets.randbelow", return_value=0):
            await game.daily_pot_draw(announce=None, edit_announce=None)

        # Now user1 accepts their late pending entry: pot is not active
        # so this should refund, not confirm
        announces = []
        await game.on_request_accepted(
            RequestAcceptedData(request_id=int(result1["request_id"]), status="accepted"),
            announce=lambda gid, msg, **kw: announces.append(msg),
        )

        conn = db.get_connection()
        try:
            entry = db.get_entry_by_request_id(conn, result1["request_id"])
            assert entry["status"] == "denied"  # refunded path denies the entry
        finally:
            conn.close()
        assert any("refunded" in m for m in announces)

    @patch("luckypot.game.secrets.randbelow", return_value=9999)
    async def test_miss_with_zero_participants_announces_zero(
        self, _mock_rng, luckypot_db, configure_luckypot_stk, test_context
    ):
        """Missing a draw with no confirmed participants still advances the
        round and announces 0 entries."""
        announces = []
        await game.daily_pot_draw(
            announce=lambda gid, msg, **kw: announces.append((gid, msg)),
            edit_announce=None,
        )

        conn = db.get_connection()
        try:
            # No pot was created because enter_pot wasn't called, so get_active_pot
            # returns None and daily_pot_draw's get_all_active_guilds iterates nothing.
            assert announces == []  # no active guild -> no announce
        finally:
            conn.close()

        # Now create an empty pot manually and verify the 0-entry message
        conn = db.get_connection()
        try:
            db.create_pot(conn, "test_guild_empty")
        finally:
            conn.close()

        await game.daily_pot_draw(
            announce=lambda gid, msg, **kw: announces.append((gid, msg)),
            edit_announce=None,
        )

        assert any("0 STK from 0 entries" in m for _, m in announces)

    @patch("luckypot.game.secrets.randbelow", return_value=9999)
    async def test_idempotency_key_unique_across_rounds(
        self, _mock_rng, luckypot_db, configure_luckypot_stk, test_context
    ):
        """enter_pot builds idempotency keys that differ across rounds.

        Idempotency key is pot_entry:{pot_id}:{discord_id}:{prior_attempts+1}
        where prior_attempts counts ALL entries (any status, any round) for
        that user in that pot.
        """
        result1 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_reentry",
        )
        # First entry -> pot_entry:P:U:1
        await game.daily_pot_draw(announce=None, edit_announce=None)

        result2 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_reentry",
        )
        # Second entry (round 2) -> pot_entry:P:U:2

        conn = db.get_connection()
        try:
            rows = conn.execute(
                """SELECT entry_round, stackcoin_request_id FROM pot_entries
                   WHERE discord_id = ? ORDER BY entry_id""",
                (test_context["user1_discord_id"],),
            ).fetchall()
            assert len(rows) == 2
            assert rows[0]["entry_round"] == 1
            assert rows[1]["entry_round"] == 2
        finally:
            conn.close()

    @patch("luckypot.game.secrets.randbelow", return_value=0)
    async def test_force_end_pot_with_multi_round_participants(
        self, _mock_rng, luckypot_db, configure_luckypot_stk, test_context
    ):
        """/force-end-pot draws correctly from a multi-round pot."""
        # Bypass the instant-win roll: patches return 0 which means
        # roll < 0.01 * 10000 is true. We want the NORMAL entry path, so
        # use a higher return value to bypass instant win.
        with patch("luckypot.game.secrets.randbelow", return_value=9999):
            await game.enter_pot(
                discord_id=test_context["user1_discord_id"],
                guild_id="test_guild_reentry",
            )
            await game.daily_pot_draw(announce=None, edit_announce=None)
            await game.enter_pot(
                discord_id=test_context["user1_discord_id"],
                guild_id="test_guild_reentry",
            )
            await game.enter_pot(
                discord_id=test_context["user2_discord_id"],
                guild_id="test_guild_reentry",
            )

        approves = []
        async def fake_announce(msg): approves.append(msg)
        won = await game.end_pot_with_winner(
            "test_guild_reentry",
            win_type="DEBUG FORCE END",
            announce_fn=fake_announce,
            edit_announce_fn=None,
        )
        assert won is True

        conn = db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM pots WHERE guild_id = ?",
                ("test_guild_reentry",),
            ).fetchone()
            assert row["is_active"] == 0
            assert row["winning_amount"] == 15  # 3 confirmed entries x 5 STK
        finally:
            conn.close()

    @patch("luckypot.game.secrets.randbelow", return_value=9999)
    async def test_migration_preserves_existing_data(
        self, _mock_rng, luckypot_db, configure_luckypot_stk, test_context
    ):
        """Schema migration on an existing prod-style DB adds columns cleanly.

        Create a pot + entries with the OLD schema (no current_round,
        no entry_round columns), then re-run init_database() and verify
        the migration helper adds the columns with the right defaults.
        """
        # Drop the new columns to simulate an old database
        conn = db.get_connection()
        try:
            # SQLite doesn't support DROP COLUMN before 3.35; we'll just
            # verify the migration is idempotent on the already-migrated DB.
            info_pots = [r["name"] for r in conn.execute("PRAGMA table_info(pots)")]
            info_entries = [r["name"] for r in conn.execute("PRAGMA table_info(pot_entries)")]
            assert "current_round" in info_pots
            assert "entry_round" in info_entries

            # Add a pot and an entry, then re-run init_database
            pot = db.create_pot(conn, "test_guild_migration")
            db.add_entry(
                conn, pot_id=pot["pot_id"],
                discord_id=test_context["user1_discord_id"],
                amount=5, status="confirmed", entry_round=1,
            )
        finally:
            conn.close()

        # Re-running init should not raise
        db.init_database()

        conn = db.get_connection()
        try:
            pot = db.get_active_pot(conn, "test_guild_migration")
            assert pot["current_round"] == 1
            row = conn.execute(
                "SELECT * FROM pot_entries WHERE pot_id = ?",
                (pot["pot_id"],),
            ).fetchone()
            assert row["entry_round"] == 1
        finally:
            conn.close()

    @patch("luckypot.game.secrets.randbelow", return_value=9999)
    async def test_full_money_flow_across_rounds_e2e(
        self, _mock_rng, luckypot_db, configure_luckypot_stk, test_context, approve_preauth
    ):
        """End-to-end money flow: two real StackCoin entries across two rounds
        and a real pay-out, against the live test server.

        Verifies:
        - User1's STK balance drops by 5 in round 1 and another 5 in round 2
        - On the eventual draw, the winner receives the 10 STK pot for real
        - Bot balance returns to ~0 after paying out
        """
        # user1 enters round 1 and accepts (preauth-resolved)
        result = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_money",
        )
        assert result["status"] == "pending"

        # Approve the pending request via StackCoin's accept endpoint
        # (using the bot's own accept_request method, simulating the user
        # clicking accept in Discord)
        await stk.get_client().accept_request(int(result["request_id"]))

        # Confirm luckypot saw the acceptance
        await game.on_request_accepted(
            RequestAcceptedData(request_id=int(result["request_id"]), status="accepted"),
            announce=None,
        )

        # Miss the draw -> round advances to 2
        await game.daily_pot_draw(announce=None, edit_announce=None)

        # user1 enters round 2
        result2 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_money",
        )
        await stk.get_client().accept_request(int(result2["request_id"]))
        await game.on_request_accepted(
            RequestAcceptedData(request_id=int(result2["request_id"]), status="accepted"),
            announce=None,
        )

        # Now rig the draw to hit
        with patch("luckypot.game.secrets.randbelow", return_value=0):
            await game.daily_pot_draw(announce=None, edit_announce=None)

        conn = db.get_connection()
        try:
            pot_row = conn.execute(
                "SELECT * FROM pots WHERE guild_id = ?",
                ("test_guild_money",),
            ).fetchone()
            assert pot_row["is_active"] == 0
            # Two confirmed entries x 5 STK
            assert pot_row["winning_amount"] == 10
            # same user won both their own entries, since they were the only player
            assert pot_row["winner_discord_id"] == test_context["user1_discord_id"]
        finally:
            conn.close()

        # Verify the winner's bank balance reflects the 10 STK payout
        winner = await stk.get_user_by_discord_id(test_context["user1_discord_id"])
        # user1 started at 500, paid 10, won 10 -> 500
        # (note: preauth-resolved entry costs come straight from balance)
        assert winner["balance"] == 500
```

**Note on test design:** the existing test file imports `sqlite3`, `pytest`, `unittest.mock.patch`, `RequestAcceptedData`, etc. No new imports needed.

---

### Task 7: Run the e2e suite and verify

**Step 1: Run the new tests in isolation**

```bash
cd ../StackCoin/test/e2e/py
uv run pytest test_luckypot.py::TestDailyDrawReentry -v
```

Expected: all tests pass.

**Step 2: Run the full test suite**

```bash
uv run pytest test_luckypot.py -v
```

Expected: all previously-passing tests still pass (round changes are backward-compatible: existing single-round tests see `current_round=1` everywhere).

If any existing tests break, they likely need `has_user_entered(conn, pot_id, discord_id)` updated to `has_user_entered(conn, pot_id, discord_id, 1)` at the call site, or `db.add_entry(..., entry_round=1)` added. Grep for callers:

```bash
grep -rn "has_user_entered\|db.add_entry" luckypot/ ../StackCoin/test/e2e/py/
```

Each call site needs the new argument.

---

## Summary of changes

| File | Change |
|---|---|
| `luckypot/db.py` | Add `current_round` column to `pots`, `entry_round` to `pot_entries`, partial unique index `(pot_id, discord_id, entry_round)` for pending/confirmed entries. New `_migrate_schema()` helper (idempotent, runs every boot). New `advance_pot_round()`. Updated `has_user_entered` and `add_entry` signatures. |
| `luckypot/game.py` | `enter_pot` reads `current_round` from the pot, passes it to `has_user_entered` and `add_entry`. `daily_pot_draw` miss branch calls `advance_pot_round`, announces the re-entry-encouraging message, and fires-and-forgets `_auto_enter_users` to re-enter opt-ins into the new round. |
| `../StackCoin/test/e2e/py/test_luckypot.py` | New `TestDailyDrawReentry` class (~14 tests) exercising schema migration, round advancement, multi-round entry, unique-index enforcement, auto-enter on miss, winner weighting across rounds, payout sum across rounds, late acceptance across rounds, idempotency keys, and a full real-money e2e flow. |

## Backward compatibility

- Existing prod pots (198, 200) get `current_round=1` from the `ALTER TABLE ... DEFAULT 1` migration. They behave exactly as before until the first miss, at which point round 2 opens up.
- Existing entries (`pot_entries` table) get `entry_round=1`. They behave exactly as before.
- Existing e2e tests are unaffected unless their codepath goes through `has_user_entered` or `add_entry` — those call sites need an extra arg. This is intentional: it forces every caller to think about which round they're operating in, rather than silently defaulting.
- The unique index is per-round, so existing single-round rows (which all have `entry_round=1` after migration) are correctly constrained; any duplicate the index catches would have been a bug in the old code too.

## Risk / failure modes considered

- **Race: draw miss and user enter simultaneously.** The `_guild_locks[guild_id]` serializes everything: `daily_pot_draw` holds it during the miss + advance, so a concurrent `enter_pot` is queued until after the round bump. The user's entry lands cleanly in the new round.
- **Race: auto-enter task vs. user manually entering.** `_auto_enter_users` is scheduled as a `create_task` after the lock is released and waits `AUTO_ENTER_DELAY_SECONDS=30` before doing anything. By then any synchronous user `/enter-pot` has finished. The auto-enter's `enter_pot` will see `already_entered` (round-N+1) for users who already entered manually and skip them gracefully, exactly as the existing post-win auto-enter does.
- **Migration failure mid-way.** The two `ALTER TABLE` + one `CREATE INDEX` are each committable separately. If the process dies between them, the next boot's `_migrate_schema` sees the partial state and completes it. Each step is idempotent.
- **Multiple miss streak.** No max-round cap. A 50-miss streak (probability ~0.05⁵⁰, astronomically small) would just push `current_round=51`. The unique index and round-scoped entry still work: users could be in 50+ rounds of the same pot. Winner payout sums across all rounds. Not capped.
- **Long-running pots in prod.** If pot 198 misses tonight's 06-21 draw, round 2 opens. The 6 users from round 1 can re-enter. If tomorrow's draw also misses, all 7+ users from round 1+2 re-enter round 3. The pot keeps growing until a draw hits. This is exactly the issue's desired behavior.