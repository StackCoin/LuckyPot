# Payment Denial Ban System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ban users for 48 hours when they deny a payment request, closing the exploit where users can repeatedly deny payments to get free instant win rolls.

**Architecture:** New `user_bans` table in SQLite with `ban_user()`, `get_active_ban()` DB functions. `enter_pot()` checks for active bans before the instant win roll. `on_request_denied()` creates a ban after marking the entry denied. New UI component shows ban status with Discord relative timestamp.

**Tech Stack:** Python 3.13, SQLite (WAL), pydantic-settings, hikari, pytest + pytest-asyncio (e2e tests in `tmp/StackCoin/test/e2e/py/`)

---

### Task 1: Add `user_bans` table to DB schema

**Files:**
- Modify: `luckypot/db.py:14-52` (inside `init_database()`)

**Step 1: Add the table creation and index to `init_database()`**

In `luckypot/db.py`, inside the `conn.executescript("""...""")` block in `init_database()`, add after the existing `CREATE INDEX` statements:

```sql
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
```

**Step 2: Commit**

```bash
git add luckypot/db.py
git commit -m "feat(db): add user_bans table schema"
```

---

### Task 2: Add `ban_duration_hours` config setting

**Files:**
- Modify: `luckypot/config.py:20` (add new field after `debug_mode`)

**Step 1: Add the setting**

In `luckypot/config.py`, add this field to the `Settings` class after `debug_mode: bool = False`:

```python
ban_duration_hours: int = 48
```

This is configurable via `LUCKYPOT_BAN_DURATION_HOURS` env var.

**Step 2: Commit**

```bash
git add luckypot/config.py
git commit -m "feat(config): add ban_duration_hours setting (default 48h)"
```

---

### Task 3: Add `ban_user()` and `get_active_ban()` DB functions

**Files:**
- Modify: `luckypot/db.py` (add two new functions after `deny_entry()` around line 154)

**Step 1: Add `ban_user()` function**

Add after `deny_entry()`:

```python
def ban_user(conn, discord_id: str, guild_id: str, reason: str, duration_hours: int):
    """Ban a user from entering pots in a guild for a specified duration."""
    conn.execute(
        """INSERT INTO user_bans (discord_id, guild_id, reason, expires_at)
           VALUES (?, ?, ?, datetime('now', '+' || ? || ' hours'))""",
        (discord_id, guild_id, reason, duration_hours),
    )
    conn.commit()
```

**Step 2: Add `get_active_ban()` function**

Add after `ban_user()`:

```python
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
```

**Step 3: Commit**

```bash
git add luckypot/db.py
git commit -m "feat(db): add ban_user() and get_active_ban() functions"
```

---

### Task 4: Add ban check to `enter_pot()` in game.py

**Files:**
- Modify: `luckypot/game.py:29-66` (inside `enter_pot()`, after acquiring guild lock and before instant win roll)

**Step 1: Import config settings**

At the top of `luckypot/game.py`, add to the imports:

```python
from luckypot.config import settings
```

**Step 2: Add ban check inside the guild lock**

In `enter_pot()`, after `pot = db.ensure_active_pot(conn, guild_id)` (line 59) and before `if db.has_user_entered(...)` (line 62), add the ban check:

```python
            # Check for active ban before anything else
            active_ban = db.get_active_ban(conn, discord_id, guild_id)
            if active_ban:
                return {
                    "status": "banned",
                    "expires_at": active_ban["expires_at"],
                    "message": f"You are banned from entering pots until {active_ban['expires_at']} UTC.",
                }
```

**Step 3: Commit**

```bash
git add luckypot/game.py
git commit -m "feat(game): check for active ban before allowing pot entry"
```

---

### Task 5: Add ban creation to `on_request_denied()` in game.py

**Files:**
- Modify: `luckypot/game.py:431-471` (inside `on_request_denied()`)

**Step 1: Add ban creation after `db.deny_entry()`**

In `on_request_denied()`, after `db.deny_entry(conn, entry_id)` (line 464), add:

```python
            db.ban_user(
                conn,
                discord_id=discord_id,
                guild_id=guild_id,
                reason="payment_denied",
                duration_hours=settings.ban_duration_hours,
            )
            logger.info(
                f"User {discord_id} banned for {settings.ban_duration_hours}h in guild {guild_id} (payment denied)"
            )
```

**Step 2: Update the announcement message**

Change the announce message (currently at line 467-469) from:

```python
            if announce_fn:
                await announce_fn(
                    f"<@{discord_id}>'s pot entry was cancelled (payment denied)."
                )
```

to:

```python
            if announce_fn:
                await announce_fn(
                    f"<@{discord_id}>'s pot entry was cancelled (payment denied). They have been banned from entering pots for {settings.ban_duration_hours} hours."
                )
```

**Step 3: Commit**

```bash
git add luckypot/game.py
git commit -m "feat(game): ban user for 48h on payment denial"
```

---

### Task 6: Add `build_entry_banned()` UI component

**Files:**
- Modify: `luckypot/discord/ui.py` (add new function after `build_entry_error()`)

**Step 1: Add the banned response builder**

Add after `build_entry_error()`:

```python
def build_entry_banned(expires_at: str) -> ContainerComponentBuilder:
    """Build response when a user is banned from entering pots."""
    from datetime import datetime, timezone

    # Parse the SQLite timestamp and convert to Discord timestamp
    dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    unix_ts = int(dt.timestamp())

    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("🚫 Banned")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        f"You are banned from entering pots. Your ban expires <t:{unix_ts}:R>."
    )
    return container
```

**Step 2: Commit**

```bash
git add luckypot/discord/ui.py
git commit -m "feat(ui): add banned response component with relative timestamp"
```

---

### Task 7: Handle `banned` status in `/enter-pot` command

**Files:**
- Modify: `luckypot/discord/commands.py:36-63` (inside the `EnterPot` invoke method)

**Step 1: Add the banned status handler**

In the `EnterPot` invoke method, after the `elif status == "already_entered":` block (line 53-57), add:

```python
                elif status == "banned":
                    expires_at = result.get("expires_at", "")
                    container = ui.build_entry_banned(expires_at)
                    await ctx.respond(
                        components=[container], flags=hikari.MessageFlag.EPHEMERAL
                    )
```

**Step 2: Commit**

```bash
git add luckypot/discord/commands.py
git commit -m "feat(commands): handle banned status in /enter-pot response"
```

---

### Task 8: Write e2e tests for the ban system

**Files:**
- Modify: `tmp/StackCoin/test/e2e/py/test_luckypot.py` (add new test class at the end)

**Step 1: Add `TestLuckyPotPaymentDenialBan` test class**

Add at the end of `test_luckypot.py`:

```python
@pytest.mark.asyncio
class TestLuckyPotPaymentDenialBan:
    """Tests for the payment denial ban system."""

    @patch("luckypot.game.random.random", return_value=0.99)
    async def test_denial_creates_ban(self, _mock_random, luckypot_db, configure_luckypot_stk, test_context):
        """Denying a payment request should create a ban record."""
        result = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_ban",
        )
        assert result["status"] == "pending"

        event_data = RequestDeniedData(
            request_id=int(result["request_id"]), status="denied",
        )
        await game.on_request_denied(event_data)

        conn = db.get_connection()
        try:
            ban = db.get_active_ban(conn, test_context["user1_discord_id"], "test_guild_ban")
            assert ban is not None
            assert ban["reason"] == "payment_denied"
        finally:
            conn.close()

    @patch("luckypot.game.random.random", return_value=0.99)
    async def test_banned_user_cannot_enter_pot(self, _mock_random, luckypot_db, configure_luckypot_stk, test_context):
        """A banned user should be rejected from entering any pot."""
        # Enter and deny to get banned
        result = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_ban",
        )
        assert result["status"] == "pending"

        event_data = RequestDeniedData(
            request_id=int(result["request_id"]), status="denied",
        )
        await game.on_request_denied(event_data)

        # Try to enter again — should be banned
        result2 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_ban",
        )
        assert result2["status"] == "banned"
        assert "expires_at" in result2

    @patch("luckypot.game.random.random", return_value=0.001)
    async def test_banned_user_cannot_roll_instant_win(self, _mock_random, luckypot_db, configure_luckypot_stk, test_context):
        """A banned user should not get to roll for instant win — ban check comes first."""
        # Manually create a ban
        conn = db.get_connection()
        try:
            db.ban_user(conn, test_context["user1_discord_id"], "test_guild_ban", "payment_denied", 48)
        finally:
            conn.close()

        # Even with instant win rigged, should be blocked
        result = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_ban",
        )
        assert result["status"] == "banned"

    @patch("luckypot.game.random.random", return_value=0.99)
    async def test_ban_is_guild_scoped(self, _mock_random, luckypot_db, configure_luckypot_stk, test_context):
        """A ban in guild A should not block entry to guild B."""
        # Get banned in guild A
        result = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="guild_A_ban",
        )
        assert result["status"] == "pending"
        event_data = RequestDeniedData(
            request_id=int(result["request_id"]), status="denied",
        )
        await game.on_request_denied(event_data)

        # Should be banned in guild A
        result2 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="guild_A_ban",
        )
        assert result2["status"] == "banned"

        # Should be able to enter guild B
        result3 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="guild_B_ban",
        )
        assert result3["status"] == "pending"

    @patch("luckypot.game.random.random", return_value=0.99)
    async def test_expired_ban_allows_entry(self, _mock_random, luckypot_db, configure_luckypot_stk, test_context):
        """After a ban expires, the user should be able to enter again."""
        # Create an already-expired ban (duration 0 hours)
        conn = db.get_connection()
        try:
            conn.execute(
                """INSERT INTO user_bans (discord_id, guild_id, reason, expires_at)
                   VALUES (?, ?, ?, datetime('now', '-1 hours'))""",
                (test_context["user1_discord_id"], "test_guild_expired", "payment_denied"),
            )
            conn.commit()
        finally:
            conn.close()

        # Should be allowed to enter (ban is expired)
        result = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_expired",
        )
        assert result["status"] == "pending"

    @patch("luckypot.game.random.random", return_value=0.99)
    async def test_other_user_not_affected_by_ban(self, _mock_random, luckypot_db, configure_luckypot_stk, test_context):
        """Banning user1 should not affect user2 in the same guild."""
        # Ban user1
        result = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id="test_guild_other",
        )
        assert result["status"] == "pending"
        event_data = RequestDeniedData(
            request_id=int(result["request_id"]), status="denied",
        )
        await game.on_request_denied(event_data)

        # User2 should be able to enter the same guild
        result2 = await game.enter_pot(
            discord_id=test_context["user2_discord_id"],
            guild_id="test_guild_other",
        )
        assert result2["status"] == "pending"
```

**Step 2: Commit**

```bash
git add tmp/StackCoin/test/e2e/py/test_luckypot.py
git commit -m "test: add e2e tests for payment denial ban system"
```

---

### Task 9: Update existing denial test to expect ban

**Files:**
- Modify: `tmp/StackCoin/test/e2e/py/test_luckypot.py` (update `TestLuckyPotEventHandlers.test_on_request_denied_denies_entry`)

**Step 1: Update the existing test**

The existing `test_on_request_denied_denies_entry` test (line 423-442) should also verify a ban is created. Add after the existing `assert entry["status"] == "denied"`:

```python
            # Ban should also have been created
            ban = db.get_active_ban(conn, "user1", "guild1")
            assert ban is not None
            assert ban["reason"] == "payment_denied"
```

**Step 2: Commit**

```bash
git add tmp/StackCoin/test/e2e/py/test_luckypot.py
git commit -m "test: update existing denial test to verify ban creation"
```

---

### Task 10: Add `TestLuckyPotBanDb` unit tests

**Files:**
- Modify: `tmp/StackCoin/test/e2e/py/test_luckypot.py` (add new test class after `TestLuckyPotDb`)

**Step 1: Add DB-level ban tests**

Add after the `TestLuckyPotDb` class:

```python
class TestLuckyPotBanDb:
    """Test LuckyPot's ban-related DB operations."""

    def test_ban_user_creates_record(self, luckypot_db):
        conn = db.get_connection()
        try:
            db.ban_user(conn, "user1", "guild1", "payment_denied", 48)
            ban = db.get_active_ban(conn, "user1", "guild1")
            assert ban is not None
            assert ban["discord_id"] == "user1"
            assert ban["guild_id"] == "guild1"
            assert ban["reason"] == "payment_denied"
        finally:
            conn.close()

    def test_get_active_ban_returns_none_when_no_ban(self, luckypot_db):
        conn = db.get_connection()
        try:
            ban = db.get_active_ban(conn, "user1", "guild1")
            assert ban is None
        finally:
            conn.close()

    def test_expired_ban_not_returned(self, luckypot_db):
        conn = db.get_connection()
        try:
            # Insert an already-expired ban
            conn.execute(
                """INSERT INTO user_bans (discord_id, guild_id, reason, expires_at)
                   VALUES (?, ?, ?, datetime('now', '-1 hours'))""",
                ("user1", "guild1", "payment_denied"),
            )
            conn.commit()
            ban = db.get_active_ban(conn, "user1", "guild1")
            assert ban is None
        finally:
            conn.close()

    def test_ban_is_guild_scoped(self, luckypot_db):
        conn = db.get_connection()
        try:
            db.ban_user(conn, "user1", "guild_A", "payment_denied", 48)
            assert db.get_active_ban(conn, "user1", "guild_A") is not None
            assert db.get_active_ban(conn, "user1", "guild_B") is None
        finally:
            conn.close()
```

**Step 2: Commit**

```bash
git add tmp/StackCoin/test/e2e/py/test_luckypot.py
git commit -m "test: add DB-level ban unit tests"
```

---

### Task 11: Run all tests and verify

**Step 1: Run the e2e test suite**

```bash
cd tmp/StackCoin/test/e2e/py
uv run pytest test_luckypot.py -v
```

Expected: All tests pass, including the new ban tests.

**Step 2: Final commit if any adjustments needed**

```bash
git add -A
git commit -m "fix: address any test failures from ban implementation"
```
