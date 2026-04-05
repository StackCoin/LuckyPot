# Auto-Enter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/auto-enter` so users can opt in per-guild to be automatically entered into every new pot via the existing `enter_pot()` flow, triggered 30 seconds after a pot ends.

**Architecture:** New `auto_enter_users` table in SQLite; three new db functions; one new slash command; a fire-and-forget async task launched from `process_pot_win()` after the win is announced.

**Tech Stack:** Python 3.13, SQLite (via existing `db.py` pattern), hikari-lightbulb, pytest (e2e tests in `tmp/StackCoin/test/e2e/py/`)

---

### Task 1: Add `auto_enter_users` table and db functions

**Files:**
- Modify: `luckypot/db.py`

- [ ] **Step 1: Add the table to `init_database()`**

In `luckypot/db.py`, extend the `executescript` string inside `init_database()` (after the `idx_user_bans_lookup` index, before the closing `"""`):

```python
        CREATE TABLE IF NOT EXISTS auto_enter_users (
            discord_id TEXT NOT NULL,
            guild_id   TEXT NOT NULL,
            enabled_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (discord_id, guild_id)
        );
```

- [ ] **Step 2: Add `set_auto_enter()`**

Add after `set_last_event_id()` at the bottom of `luckypot/db.py`:

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add luckypot/db.py
git commit -m "feat: add auto_enter_users table and db functions"
```

---

### Task 2: E2E tests for the db functions

**Files:**
- Modify: `tmp/StackCoin/test/e2e/py/test_luckypot.py`

- [ ] **Step 1: Add `TestAutoEnterDb` class**

Append to `tmp/StackCoin/test/e2e/py/test_luckypot.py`:

```python
class TestAutoEnterDb:
    """Test auto_enter_users DB operations."""

    def test_opt_in_creates_record(self, luckypot_db):
        conn = db.get_connection()
        try:
            db.set_auto_enter(conn, "user1", "guild1", True)
            assert db.get_auto_enter_status(conn, "user1", "guild1") is True
        finally:
            conn.close()

    def test_opt_out_removes_record(self, luckypot_db):
        conn = db.get_connection()
        try:
            db.set_auto_enter(conn, "user1", "guild1", True)
            db.set_auto_enter(conn, "user1", "guild1", False)
            assert db.get_auto_enter_status(conn, "user1", "guild1") is False
        finally:
            conn.close()

    def test_opt_out_when_not_opted_in_is_safe(self, luckypot_db):
        conn = db.get_connection()
        try:
            db.set_auto_enter(conn, "user1", "guild1", False)
            assert db.get_auto_enter_status(conn, "user1", "guild1") is False
        finally:
            conn.close()

    def test_opt_in_twice_is_idempotent(self, luckypot_db):
        conn = db.get_connection()
        try:
            db.set_auto_enter(conn, "user1", "guild1", True)
            db.set_auto_enter(conn, "user1", "guild1", True)
            users = db.get_auto_enter_users(conn, "guild1")
            assert users.count("user1") == 1
        finally:
            conn.close()

    def test_get_auto_enter_users_returns_all_opted_in(self, luckypot_db):
        conn = db.get_connection()
        try:
            db.set_auto_enter(conn, "user1", "guild1", True)
            db.set_auto_enter(conn, "user2", "guild1", True)
            db.set_auto_enter(conn, "user3", "guild1", False)
            users = db.get_auto_enter_users(conn, "guild1")
            assert set(users) == {"user1", "user2"}
        finally:
            conn.close()

    def test_auto_enter_is_guild_scoped(self, luckypot_db):
        conn = db.get_connection()
        try:
            db.set_auto_enter(conn, "user1", "guild_A", True)
            assert db.get_auto_enter_status(conn, "user1", "guild_A") is True
            assert db.get_auto_enter_status(conn, "user1", "guild_B") is False
        finally:
            conn.close()
```

- [ ] **Step 2: Run the new tests to verify they pass**

```bash
cd tmp/StackCoin/test/e2e/py
uv run pytest test_luckypot.py::TestAutoEnterDb -v
```

Expected: all 6 pass.

- [ ] **Step 3: Commit**

```bash
git add tmp/StackCoin/test/e2e/py/test_luckypot.py
git commit -m "test: add e2e tests for auto_enter_users db functions"
```

---

### Task 3: Add `_auto_enter_users()` trigger in `game.py`

**Files:**
- Modify: `luckypot/game.py`

- [ ] **Step 1: Add `AUTO_ENTER_DELAY_SECONDS` constant**

At the top of `luckypot/game.py`, after the existing constants (`POT_ENTRY_COST`, `DAILY_DRAW_CHANCE`, `RANDOM_WIN_CHANCE`):

```python
AUTO_ENTER_DELAY_SECONDS = 30
```

- [ ] **Step 2: Add `_auto_enter_users()` function**

Add after `_dramatic_draw_reveal()` (after line 279) in `luckypot/game.py`:

```python
async def _auto_enter_users(guild_id: str, announce_fn: AnnounceFn = None) -> None:
    """Wait briefly then auto-enter all opted-in users for a guild.

    Called as a fire-and-forget task after a pot win is announced.
    Uses the existing enter_pot() which handles all edge cases (bans,
    already-entered, STK account missing, etc.).
    """
    await asyncio.sleep(AUTO_ENTER_DELAY_SECONDS)

    conn = db.get_connection()
    try:
        discord_ids = db.get_auto_enter_users(conn, guild_id)
    finally:
        conn.close()

    if not discord_ids:
        return

    logger.info(
        f"Auto-entering {len(discord_ids)} user(s) into new pot for guild {guild_id}"
    )
    for discord_id in discord_ids:
        result = await enter_pot(discord_id, guild_id, announce_fn=announce_fn)
        logger.info(
            f"Auto-enter for discord_id={discord_id} guild={guild_id}: status={result['status']}"
        )
```

- [ ] **Step 3: Fire the task from `process_pot_win()` after a successful win**

In `process_pot_win()`, after `db.end_pot(...)` is called and the announcement is done (after the `if announce_fn and edit_announce_fn:` / `elif announce_fn:` block, before `return sent`), add:

```python
        asyncio.create_task(_auto_enter_users(guild_id, announce_fn=announce_fn))
```

The modified section of `process_pot_win()` should look like this:

```python
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
            suffix = f" ({win_type})" if win_type != "DAILY DRAW" else ""
            await announce_fn(f"<@{winner_id}> won {winning_amount} STK!{suffix}")
        asyncio.create_task(_auto_enter_users(guild_id, announce_fn=announce_fn))
    else:
```

- [ ] **Step 4: Commit**

```bash
git add luckypot/game.py
git commit -m "feat: add _auto_enter_users trigger after pot win"
```

---

### Task 4: E2E tests for auto-enter trigger

**Files:**
- Modify: `tmp/StackCoin/test/e2e/py/test_luckypot.py`

- [ ] **Step 1: Add `TestAutoEnterTrigger` class**

Append to `tmp/StackCoin/test/e2e/py/test_luckypot.py`:

```python
@pytest.mark.asyncio
class TestAutoEnterTrigger:
    """Test that auto-enter fires correctly after a pot win."""

    @patch("luckypot.game.AUTO_ENTER_DELAY_SECONDS", 0)
    @patch("luckypot.game.random.random", return_value=0.99)
    async def test_opted_in_user_is_entered_after_win(
        self, _mock_random, luckypot_db, configure_luckypot_stk, test_context
    ):
        """After a pot ends, opted-in users are automatically entered into the new pot."""
        guild_id = "test_guild_ae"

        # Opt user2 in to auto-enter
        conn = db.get_connection()
        try:
            db.set_auto_enter(conn, test_context["user2_discord_id"], guild_id, True)
        finally:
            conn.close()

        # User1 enters and confirms
        result1 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id=guild_id,
        )
        assert result1["status"] == "pending"
        await game.on_request_accepted(
            RequestAcceptedData(
                request_id=int(result1["request_id"]),
                status="accepted",
                transaction_id=0,
                amount=0,
            )
        )

        # Force draw — pot ends, user1 wins
        with patch("luckypot.game.random.random", return_value=0.01):
            task = asyncio.create_task(
                game.end_pot_with_winner(guild_id, win_type="DAILY DRAW")
            )
            await task

        # Give the auto-enter task a moment to run (delay is patched to 0)
        await asyncio.sleep(0.1)

        # User2 should now have a pending entry in the NEW pot
        conn = db.get_connection()
        try:
            new_pot = db.get_active_pot(conn, guild_id)
            assert new_pot is not None
            assert db.has_user_entered(conn, new_pot["pot_id"], test_context["user2_discord_id"]) is True
        finally:
            conn.close()

    @patch("luckypot.game.AUTO_ENTER_DELAY_SECONDS", 0)
    @patch("luckypot.game.random.random", return_value=0.99)
    async def test_not_opted_in_user_is_not_entered(
        self, _mock_random, luckypot_db, configure_luckypot_stk, test_context
    ):
        """Users not opted in are not auto-entered after a pot ends."""
        guild_id = "test_guild_ae_no"

        # User1 enters and confirms, no one opts in to auto-enter
        result1 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id=guild_id,
        )
        assert result1["status"] == "pending"
        await game.on_request_accepted(
            RequestAcceptedData(
                request_id=int(result1["request_id"]),
                status="accepted",
                transaction_id=0,
                amount=0,
            )
        )

        with patch("luckypot.game.random.random", return_value=0.01):
            await game.end_pot_with_winner(guild_id, win_type="DAILY DRAW")

        await asyncio.sleep(0.1)

        # No new pot should exist yet (nobody entered to trigger ensure_active_pot)
        conn = db.get_connection()
        try:
            assert db.get_active_pot(conn, guild_id) is None
        finally:
            conn.close()

    @patch("luckypot.game.AUTO_ENTER_DELAY_SECONDS", 0)
    @patch("luckypot.game.random.random", return_value=0.99)
    async def test_banned_user_skipped_by_auto_enter(
        self, _mock_random, luckypot_db, configure_luckypot_stk, test_context
    ):
        """Auto-enter silently skips banned users."""
        guild_id = "test_guild_ae_ban"

        # Opt user2 in but also ban them
        conn = db.get_connection()
        try:
            db.set_auto_enter(conn, test_context["user2_discord_id"], guild_id, True)
            db.ban_user(conn, test_context["user2_discord_id"], guild_id, "payment_denied", 48)
        finally:
            conn.close()

        # User1 enters and confirms
        result1 = await game.enter_pot(
            discord_id=test_context["user1_discord_id"],
            guild_id=guild_id,
        )
        assert result1["status"] == "pending"
        await game.on_request_accepted(
            RequestAcceptedData(
                request_id=int(result1["request_id"]),
                status="accepted",
                transaction_id=0,
                amount=0,
            )
        )

        with patch("luckypot.game.random.random", return_value=0.01):
            await game.end_pot_with_winner(guild_id, win_type="DAILY DRAW")

        await asyncio.sleep(0.1)

        # Banned user2 should not be in the new pot
        conn = db.get_connection()
        try:
            new_pot = db.get_active_pot(conn, guild_id)
            if new_pot:
                assert db.has_user_entered(conn, new_pot["pot_id"], test_context["user2_discord_id"]) is False
        finally:
            conn.close()
```

Also add `import asyncio` at the top of the test file if it isn't already there.

- [ ] **Step 2: Run the new tests**

```bash
cd tmp/StackCoin/test/e2e/py
uv run pytest test_luckypot.py::TestAutoEnterTrigger -v
```

Expected: all 3 pass.

- [ ] **Step 3: Commit**

```bash
git add tmp/StackCoin/test/e2e/py/test_luckypot.py
git commit -m "test: add e2e tests for auto-enter trigger after pot win"
```

---

### Task 5: Add `/auto-enter` slash command

**Files:**
- Modify: `luckypot/discord/commands.py`
- Modify: `luckypot/discord/ui.py`

- [ ] **Step 1: Add UI builders to `ui.py`**

Add to `luckypot/discord/ui.py` (before the final line):

```python
def build_auto_enter_opted_in() -> ContainerComponentBuilder:
    """Build response when user successfully opts in to auto-enter."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("✅ Auto-Enter Enabled")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        "You will automatically be entered into each new pot. "
        "Use `/auto-enter enabled:False` to opt out."
    )
    return container


def build_auto_enter_opted_out() -> ContainerComponentBuilder:
    """Build response when user successfully opts out of auto-enter."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("✅ Auto-Enter Disabled")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        "You will no longer be automatically entered into pots. "
        "Use `/auto-enter` to opt back in."
    )
    return container


def build_auto_enter_already_in_state(enabled: bool) -> ContainerComponentBuilder:
    """Build response when user is already in the requested state."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    if enabled:
        container.add_text_display("ℹ️ Already Opted In")
        container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
        container.add_text_display("You are already opted in to auto-enter.")
    else:
        container.add_text_display("ℹ️ Already Opted Out")
        container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
        container.add_text_display("You are already opted out of auto-enter.")
    return container
```

- [ ] **Step 2: Add the `AutoEnter` command to `commands.py`**

In `luckypot/discord/commands.py`, update the import at the top to include the new db functions and ui builders:

```python
from luckypot import db
# (already imported — just ensure set_auto_enter, get_auto_enter_status are available via db.*)
```

```python
from luckypot.discord import ui
# (already imported — new builders are automatically available as ui.build_auto_enter_*)
```

Then add the new command inside `register_commands()`, after the `PotHistory` block and before the `if settings.debug_mode` block:

```python
    @client.register(guilds=guilds)
    class AutoEnter(
        lightbulb.SlashCommand,
        name="auto-enter",
        description="Automatically enter each new pot when one starts",
    ):
        enabled: bool = lightbulb.boolean(
            "enabled",
            "Whether to enable auto-enter (default: True)",
            default=True,
        )

        @lightbulb.invoke
        async def invoke(self, ctx: lightbulb.Context) -> None:
            guild_id = str(ctx.guild_id)
            discord_id = str(ctx.user.id)

            try:
                conn = db.get_connection()
                try:
                    current = db.get_auto_enter_status(conn, discord_id, guild_id)
                    if current == self.enabled:
                        container = ui.build_auto_enter_already_in_state(self.enabled)
                        await ctx.respond(
                            components=[container], flags=hikari.MessageFlag.EPHEMERAL
                        )
                        return
                    db.set_auto_enter(conn, discord_id, guild_id, self.enabled)
                finally:
                    conn.close()

                if self.enabled:
                    container = ui.build_auto_enter_opted_in()
                else:
                    container = ui.build_auto_enter_opted_out()
                await ctx.respond(
                    components=[container], flags=hikari.MessageFlag.EPHEMERAL
                )

            except Exception as e:
                logger.error(f"Error in /auto-enter for user {ctx.user.id}: {e}")
                container = ui.build_entry_error(f"An unexpected error occurred: {e}")
                await ctx.respond(
                    components=[container], flags=hikari.MessageFlag.EPHEMERAL
                )
```

- [ ] **Step 3: Commit**

```bash
git add luckypot/discord/commands.py luckypot/discord/ui.py
git commit -m "feat: add /auto-enter slash command"
```

---

### Task 6: Run the full e2e test suite

- [ ] **Step 1: Run all LuckyPot e2e tests**

```bash
cd tmp/StackCoin/test/e2e/py
uv run pytest test_luckypot.py -v
```

Expected: all tests pass (no regressions).

- [ ] **Step 2: If any failures, fix and re-run before proceeding**

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: address e2e test failures"
```
