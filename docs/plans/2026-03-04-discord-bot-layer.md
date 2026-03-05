# Discord Bot Layer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Re-add the hikari/lightbulb Discord bot (slash commands, rich UI, channel announcements) on top of the framework-agnostic `luckypot/` core package, with an asyncio-based daily draw scheduler.

**Architecture:** A `luckypot/discord/` subpackage contains all Discord-specific code (bot lifecycle, slash commands, UI builders, channel announcements). The entry point `lucky_pot.py` wires the bot, StackCoin WebSocket gateway, and daily draw scheduler together. The core `luckypot/` package remains untouched — E2E tests continue importing `luckypot.game`, `luckypot.db`, `luckypot.stk` without triggering any hikari imports.

**Tech Stack:** Python 3.13, hikari, hikari-lightbulb, httpx, websockets, loguru, SQLite

---

### Task 1: Clean up dependencies and config

**Files:**
- Modify: `pyproject.toml`
- Modify: `luckypot/config.py`
- Modify: `.env.dist`
- Delete: `config.py` (root shim)
- Delete: `db.py` (root shim)
- Delete: `stk.py` (root shim)

**Step 1: Update pyproject.toml**

Remove `schedule` dependency. Keep everything else.

```toml
[project]
name = "luckypot"
version = "0.1.0"
description = "LuckyPot is a bot that implements a lottery system on top of StackCoin"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "hikari>=2.3.5",
    "hikari-lightbulb>=3.1.1",
    "httpx>=0.27.0",
    "loguru>=0.7.3",
    "python-dotenv>=1.1.1",
    "websockets>=13.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["luckypot"]
```

**Step 2: Add new config variables to `luckypot/config.py`**

```python
"""Configuration loading from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
STACKCOIN_API_URL = os.getenv("STACKCOIN_API_URL", "http://localhost:4000")
STACKCOIN_API_TOKEN = os.getenv("STACKCOIN_API_TOKEN", "")
STACKCOIN_WS_URL = os.getenv("STACKCOIN_WS_URL", "ws://localhost:4000/ws")
DB_PATH = os.getenv("LUCKYPOT_DB_PATH", "luckypot.db")

# Discord bot settings
TESTING_GUILD_ID = os.getenv("TESTING_GUILD_ID", "")
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# Daily draw schedule (UTC)
DAILY_DRAW_HOUR = int(os.getenv("DAILY_DRAW_HOUR", "0"))
DAILY_DRAW_MINUTE = int(os.getenv("DAILY_DRAW_MINUTE", "0"))
```

**Step 3: Update `.env.dist`**

```
DISCORD_TOKEN=
STACKCOIN_API_URL=http://localhost:4000
STACKCOIN_API_TOKEN=
STACKCOIN_WS_URL=ws://localhost:4000/ws
LUCKYPOT_DB_PATH=luckypot.db
TESTING_GUILD_ID=
DEBUG_MODE=false
DAILY_DRAW_HOUR=0
DAILY_DRAW_MINUTE=0
```

**Step 4: Delete root-level shim files**

```bash
rm config.py db.py stk.py
```

**Step 5: Run E2E tests from the StackCoin repo to confirm core package still works**

```bash
cd /path/to/StackCoin/test/e2e && python -m pytest test_luckypot.py -x -v
```

Expected: All luckypot tests pass (they only import from `luckypot.game`, `luckypot.db`, `luckypot.stk`).

**Step 6: Commit**

```bash
git add -A && git commit -m "chore: clean up deps, add config vars, remove root shims"
```

---

### Task 2: Create `luckypot/discord/ui.py` — rich container builders

This module has zero side effects — pure functions that build hikari container components. Easy to write and test in isolation.

**Files:**
- Create: `luckypot/discord/__init__.py`
- Create: `luckypot/discord/ui.py`

**Step 1: Create the `__init__.py`**

```python
"""Discord bot layer for LuckyPot."""
```

**Step 2: Create `ui.py`**

This module provides builder functions that return hikari `ContainerComponentBuilder` objects. Each function takes plain data dicts (the same dicts returned by `luckypot.db` and `luckypot.game`) and builds a rich container response.

```python
"""Rich container UI builders for Discord responses."""
from datetime import datetime, timedelta, timezone

import hikari
from hikari.impl.special_endpoints import ContainerComponentBuilder

from luckypot import config


def build_entry_pending(request_id: int, amount: int) -> ContainerComponentBuilder:
    """Build response for a successful pot entry (pending payment)."""
    container = ContainerComponentBuilder(accent_color=hikari.Color(0xFFA500))
    container.add_text_display("🎲 Pot Entry Submitted!")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        f"Accept the **{amount} STK** payment request from StackCoin via DMs to confirm your spot."
    )
    return container


def build_entry_instant_win() -> ContainerComponentBuilder:
    """Build response for an instant win roll (still needs payment)."""
    container = ContainerComponentBuilder(accent_color=hikari.Color(0xFFD700))
    container.add_text_display("🎉 INSTANT WIN!")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        "You rolled an **instant win**! Accept the payment request to claim the entire pot!"
    )
    return container


def build_entry_already_entered() -> ContainerComponentBuilder:
    """Build response when user has already entered the pot."""
    container = ContainerComponentBuilder(accent_color=hikari.Color(0xFF0000))
    container.add_text_display("❌ Already Entered")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display("You have already entered this pot! You can only enter once per pot.")
    return container


def build_entry_error(message: str) -> ContainerComponentBuilder:
    """Build response for a pot entry error."""
    container = ContainerComponentBuilder(accent_color=hikari.Color(0xFF0000))
    container.add_text_display("❌ Error")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(message)
    return container


def build_pot_status(status: dict) -> ContainerComponentBuilder:
    """Build the pot status display.

    Args:
        status: Dict from ``db.get_pot_status()`` with keys:
            active, participants, total_amount, and optionally pot_id.
    """
    if not status.get("active"):
        container = ContainerComponentBuilder(accent_color=hikari.Color(0x808080))
        container.add_text_display("🎲 No Active Pot")
        container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
        container.add_text_display("Use `/enter-pot` to start one!")
        return container

    container = ContainerComponentBuilder(accent_color=hikari.Color(0x00FF00))
    container.add_text_display("🎰 Lucky Pot Status")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(f"💰 Total Pot: **{status['total_amount']} STK**")
    container.add_text_display(f"👥 Participants: **{status['participants']}**")

    # Next daily draw countdown
    now = datetime.now(timezone.utc)
    next_draw = now.replace(
        hour=config.DAILY_DRAW_HOUR,
        minute=config.DAILY_DRAW_MINUTE,
        second=0,
        microsecond=0,
    )
    if next_draw <= now:
        next_draw += timedelta(days=1)
    container.add_text_display(f"⏰ Next Draw: <t:{int(next_draw.timestamp())}:R>")

    if "pot_id" in status:
        container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
        container.add_text_display(f"Pot ID: {status['pot_id']}")

    return container


def build_pot_history(history: list[dict]) -> ContainerComponentBuilder:
    """Build the pot history display.

    Args:
        history: List of dicts from ``db.get_pot_history()``.
    """
    container = ContainerComponentBuilder(accent_color=hikari.Color(0x4169E1))
    container.add_text_display("📜 Pot History")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)

    if not history:
        container.add_text_display("No completed pots yet.")
        return container

    for pot in history:
        winner = pot.get("winner_discord_id")
        amount = pot.get("winning_amount", 0)
        win_type = pot.get("win_type", "DRAW")
        ended = pot.get("ended_at", "?")
        winner_text = f"<@{winner}>" if winner else "No winner"
        container.add_text_display(f"**{amount} STK** → {winner_text} ({win_type}) — {ended}")

    return container


def build_winner_announcement(
    winner_discord_id: str, winning_amount: int, win_type: str
) -> str:
    """Build a winner announcement message for the guild channel.

    Returns a plain string (not a container) since channel announcements
    should be simple text that renders well for everyone.
    """
    return (
        f"🎉 **{win_type} WINNER!** 🎉\n\n"
        f"<@{winner_discord_id}> has won the pot of **{winning_amount} STK**!\n"
        f"Congratulations! 🎊\n\n"
        f"A new pot has started — use `/enter-pot` to join!"
    )


def build_no_winner_announcement(pot_amount: int) -> str:
    """Build a daily draw 'no winner' announcement."""
    return (
        f"🎲 Daily draw occurred, but the pot continues! No winner this time.\n"
        f"Current pot: **{pot_amount} STK**\n"
        f"Use `/enter-pot` to increase your chances!"
    )
```

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: add Discord UI container builders"
```

---

### Task 3: Create `luckypot/discord/scheduler.py` — daily draw loop

**Files:**
- Create: `luckypot/discord/scheduler.py`

**Step 1: Create `scheduler.py`**

```python
"""Asyncio-based daily draw scheduler."""
import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from luckypot import config
from luckypot.game import daily_pot_draw, AnnounceFn


async def run_daily_draw_loop(announce_fn: AnnounceFn = None):
    """Run the daily pot draw at the configured UTC time.

    Runs forever, sleeping until the next draw time, then calling
    ``game.daily_pot_draw()``. If the draw time has already passed
    today, waits until tomorrow.
    """
    while True:
        now = datetime.now(timezone.utc)
        next_draw = now.replace(
            hour=config.DAILY_DRAW_HOUR,
            minute=config.DAILY_DRAW_MINUTE,
            second=0,
            microsecond=0,
        )
        if next_draw <= now:
            next_draw += timedelta(days=1)

        sleep_seconds = (next_draw - now).total_seconds()
        logger.info(f"Next daily draw at {next_draw.isoformat()} (in {sleep_seconds:.0f}s)")
        await asyncio.sleep(sleep_seconds)

        logger.info("Running daily pot draw...")
        try:
            await daily_pot_draw(announce_fn=announce_fn)
        except Exception as e:
            logger.error(f"Daily draw failed: {e}")
```

**Step 2: Commit**

```bash
git add -A && git commit -m "feat: add asyncio daily draw scheduler"
```

---

### Task 4: Create `luckypot/discord/bot.py` — bot lifecycle and announcements

**Files:**
- Create: `luckypot/discord/bot.py`

**Step 1: Create `bot.py`**

This module creates the hikari bot, lightbulb client, and provides the `announce_fn` factory that posts to guild channels via the StackCoin API's designated channel lookup.

```python
"""Hikari bot lifecycle, lightbulb client setup, and channel announcements."""
import asyncio
from typing import Callable, Awaitable

import hikari
import lightbulb
from loguru import logger

from luckypot import config, stk


def create_bot() -> hikari.GatewayBot:
    """Create and return a configured hikari GatewayBot."""
    if not config.DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN is not set")
    return hikari.GatewayBot(token=config.DISCORD_TOKEN)


def create_lightbulb_client(bot: hikari.GatewayBot) -> lightbulb.Client:
    """Create a lightbulb client from the bot."""
    return lightbulb.client_from_app(bot)


def get_guild_ids() -> list[int]:
    """Get the guild IDs to register slash commands to.

    If TESTING_GUILD_ID is set, commands are guild-scoped (instant registration).
    Otherwise, commands are global (may take up to an hour to propagate).
    """
    if config.TESTING_GUILD_ID:
        return [int(config.TESTING_GUILD_ID)]
    return []


def make_announce_fn(bot: hikari.GatewayBot) -> Callable[[str, str], Awaitable[None]]:
    """Create an announce function that posts to a guild's designated channel.

    Returns an async function with signature:
        async def announce(guild_id: str, message: str) -> None

    Note: game.py's AnnounceFn expects (message: str) -> None, so the caller
    must partial-apply the guild_id. See commands.py for usage.
    """
    async def announce(guild_id: str, message: str) -> None:
        try:
            # Look up the guild's designated channel via StackCoin API
            users_resp = await stk.get_guild_channel(guild_id)
            if users_resp is None:
                logger.warning(f"No designated channel for guild {guild_id}")
                return

            channel_id = int(users_resp)
            channel = bot.cache.get_guild_channel(channel_id)

            if channel and isinstance(channel, hikari.TextableGuildChannel):
                await channel.send(message)
                logger.info(f"Announced to guild {guild_id} channel {channel_id}")
            else:
                logger.warning(f"Could not find textable channel {channel_id} for guild {guild_id}")
        except Exception as e:
            logger.error(f"Failed to announce to guild {guild_id}: {e}")

    return announce
```

**Step 2: Add `get_guild_channel` to `luckypot/stk.py`**

This function was in the old `stk.py` (used `stackcoin_discord_guild`) but wasn't ported to the new httpx-based version. Add it:

Append to `luckypot/stk.py`:

```python
async def get_guild_channel(guild_id: str) -> str | None:
    """Get the designated channel snowflake for a guild."""
    async with _client() as client:
        resp = await client.get(f"/api/discord/guild/{guild_id}")
        if resp.status_code != 200:
            logger.debug(f"No guild info for {guild_id}: {resp.status_code}")
            return None
        data = resp.json()
        return data.get("designated_channel_snowflake")
```

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: add bot lifecycle, announce_fn, and guild channel lookup"
```

---

### Task 5: Create `luckypot/discord/commands.py` — slash commands

**Files:**
- Create: `luckypot/discord/commands.py`

**Step 1: Create `commands.py`**

```python
"""Slash commands for the LuckyPot Discord bot."""
from functools import partial

import hikari
import lightbulb
from loguru import logger

from luckypot import config, db
from luckypot.game import enter_pot, end_pot_with_winner, POT_ENTRY_COST
from luckypot.discord import ui
from luckypot.discord.bot import get_guild_ids, make_announce_fn


def register_commands(client: lightbulb.Client, bot: hikari.GatewayBot) -> None:
    """Register all slash commands on the lightbulb client."""
    guilds = get_guild_ids()
    announce = make_announce_fn(bot)

    @client.register(guilds=guilds)
    class EnterPot(
        lightbulb.SlashCommand,
        name="enter-pot",
        description=f"Enter the daily lucky pot (costs {POT_ENTRY_COST} STK)",
    ):
        @lightbulb.invoke
        async def invoke(self, ctx: lightbulb.Context) -> None:
            guild_id = str(ctx.guild_id)
            discord_id = str(ctx.user.id)

            try:
                guild_announce = partial(announce, guild_id)
                result = await enter_pot(discord_id, guild_id, announce_fn=guild_announce)
                status = result.get("status", "error")

                if status == "pending":
                    container = ui.build_entry_pending(
                        request_id=result.get("request_id", 0),
                        amount=POT_ENTRY_COST,
                    )
                    await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)
                elif status == "instant_win":
                    container = ui.build_entry_instant_win()
                    await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)
                elif status == "already_entered":
                    container = ui.build_entry_already_entered()
                    await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)
                else:
                    message = result.get("message", "Something went wrong.")
                    container = ui.build_entry_error(message)
                    await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)

            except Exception as e:
                logger.error(f"Error in /enter-pot for user {ctx.user.id}: {e}")
                container = ui.build_entry_error(f"An unexpected error occurred: {e}")
                await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)

    @client.register(guilds=guilds)
    class PotStatus(
        lightbulb.SlashCommand,
        name="pot-status",
        description="Check the current pot status and participants",
    ):
        @lightbulb.invoke
        async def invoke(self, ctx: lightbulb.Context) -> None:
            guild_id = str(ctx.guild_id)

            try:
                conn = db.get_connection()
                try:
                    status = db.get_pot_status(conn, guild_id)
                finally:
                    conn.close()

                container = ui.build_pot_status(status)
                await ctx.respond(components=[container])

            except Exception as e:
                logger.error(f"Error in /pot-status for guild {ctx.guild_id}: {e}")
                container = ui.build_entry_error("Error retrieving pot status. Please try again later.")
                await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)

    @client.register(guilds=guilds)
    class PotHistory(
        lightbulb.SlashCommand,
        name="pot-history",
        description="View recent pot winners",
    ):
        limit: int = lightbulb.integer("limit", "Number of recent pots to show", default=5, min_value=1, max_value=20)

        @lightbulb.invoke
        async def invoke(self, ctx: lightbulb.Context) -> None:
            guild_id = str(ctx.guild_id)

            try:
                conn = db.get_connection()
                try:
                    history = db.get_pot_history(conn, guild_id, limit=self.limit)
                finally:
                    conn.close()

                container = ui.build_pot_history(history)
                await ctx.respond(components=[container])

            except Exception as e:
                logger.error(f"Error in /pot-history for guild {ctx.guild_id}: {e}")
                container = ui.build_entry_error("Error retrieving pot history.")
                await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)

    if config.DEBUG_MODE:
        @client.register(guilds=guilds)
        class ForceEndPot(
            lightbulb.SlashCommand,
            name="force-end-pot",
            description="[DEBUG] Force end the current pot with a draw",
        ):
            @lightbulb.invoke
            async def invoke(self, ctx: lightbulb.Context) -> None:
                guild_id = str(ctx.guild_id)

                try:
                    conn = db.get_connection()
                    try:
                        status = db.get_pot_status(conn, guild_id)
                    finally:
                        conn.close()

                    if not status.get("active"):
                        container = ui.build_entry_error("No active pot to end!")
                        await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)
                        return

                    if status["participants"] == 0:
                        container = ui.build_entry_error("Cannot end pot with no confirmed participants!")
                        await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)
                        return

                    guild_announce = partial(announce, guild_id)
                    won = await end_pot_with_winner(guild_id, win_type="DEBUG FORCE END", announce_fn=guild_announce)

                    if won:
                        container = ui.build_entry_pending(0, 0)  # placeholder
                        await ctx.respond("✅ Pot ended! Check the channel for the winner announcement.", flags=hikari.MessageFlag.EPHEMERAL)
                    else:
                        container = ui.build_entry_error("No confirmed participants found!")
                        await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)

                except Exception as e:
                    logger.error(f"Error in /force-end-pot for guild {ctx.guild_id}: {e}")
                    container = ui.build_entry_error(f"Error ending pot: {e}")
                    await ctx.respond(components=[container], flags=hikari.MessageFlag.EPHEMERAL)
```

**Step 2: Commit**

```bash
git add -A && git commit -m "feat: add slash commands — enter-pot, pot-status, pot-history, force-end-pot"
```

---

### Task 6: Rewrite `lucky_pot.py` — wire everything together

**Files:**
- Modify: `lucky_pot.py`

**Step 1: Rewrite the entry point**

```python
"""
LuckyPot Discord bot runner.

Wires together three concurrent systems:
1. Hikari Discord bot (slash commands)
2. StackCoin WebSocket gateway (real-time event delivery)
3. Daily draw scheduler (asyncio sleep loop)
"""
import asyncio
from functools import partial

import hikari
from loguru import logger

from luckypot import config, db
from luckypot.gateway import StackCoinGateway
from luckypot.game import on_request_accepted, on_request_denied
from luckypot.discord.bot import create_bot, create_lightbulb_client, make_announce_fn
from luckypot.discord.commands import register_commands
from luckypot.discord.scheduler import run_daily_draw_loop


logger.add("lucky_pot.log", rotation="1 day", retention="7 days", level="INFO")


def main():
    """Initialize and run the LuckyPot bot."""
    logger.info("LuckyPot starting up...")
    db.init_database()

    bot = create_bot()
    client = create_lightbulb_client(bot)
    register_commands(client, bot)

    # Subscribe lightbulb to handle its startup
    bot.subscribe(hikari.StartingEvent, client.start)

    # Background tasks started once the bot is ready
    background_tasks: list[asyncio.Task] = []

    @bot.listen()
    async def on_started(event: hikari.StartedEvent) -> None:
        announce = make_announce_fn(bot)

        # --- StackCoin WebSocket gateway ---
        gateway = StackCoinGateway(config.STACKCOIN_API_URL, config.STACKCOIN_API_TOKEN)

        async def handle_accepted(payload):
            # Determine guild_id from the event data for announcements
            guild_id = payload.get("data", {}).get("guild_id")
            ann_fn = partial(announce, guild_id) if guild_id else None
            await on_request_accepted(payload.get("data", {}), announce_fn=ann_fn)

        async def handle_denied(payload):
            guild_id = payload.get("data", {}).get("guild_id")
            ann_fn = partial(announce, guild_id) if guild_id else None
            await on_request_denied(payload.get("data", {}), announce_fn=ann_fn)

        gateway.register_handler("request.accepted", handle_accepted)
        gateway.register_handler("request.denied", handle_denied)

        gateway_task = asyncio.create_task(gateway.connect())
        background_tasks.append(gateway_task)
        logger.info("StackCoin gateway started")

        # --- Daily draw scheduler ---
        # For the daily draw, we don't have a single guild_id — the draw
        # iterates over all active guilds internally. Pass None for now;
        # game.daily_pot_draw handles multi-guild draws. Announcements for
        # specific guilds happen inside process_pot_win which gets an announce_fn
        # from end_pot_with_winner. We need to pass a guild-aware announce_fn.
        # The simplest approach: pass None here and let the draw use the
        # announce_fn pattern from game.py. We can enhance this later.
        draw_task = asyncio.create_task(run_daily_draw_loop(announce_fn=None))
        background_tasks.append(draw_task)
        logger.info("Daily draw scheduler started")

    @bot.listen()
    async def on_stopping(event: hikari.StoppingEvent) -> None:
        for task in background_tasks:
            task.cancel()
        logger.info("Background tasks cancelled")

    if config.DEBUG_MODE:
        logger.info("DEBUG MODE ENABLED — /force-end-pot command available")

    bot.run()


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add -A && git commit -m "feat: rewrite entry point to wire bot, gateway, and scheduler"
```

---

### Task 7: Update README and .gitignore

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`

**Step 1: Update README.md**

```markdown
# LuckyPot

A lottery bot for [StackCoin](https://github.com/StackCoin/StackCoin). Players enter a pot by paying STK, and a daily draw selects a winner who takes the entire pot. There's also a 5% chance of an instant win on entry.

## Architecture

- `luckypot/` — Framework-agnostic core (game logic, database, StackCoin API client, WebSocket gateway)
- `luckypot/discord/` — Discord bot layer (hikari + lightbulb slash commands, rich UI, announcements)
- `lucky_pot.py` — Entry point that wires everything together

## Setup

```bash
# Install dependencies
uv sync

# Copy and fill in environment variables
cp .env.dist .env

# Run the bot
python lucky_pot.py
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DISCORD_TOKEN` | Yes | | Discord bot token |
| `STACKCOIN_API_URL` | Yes | `http://localhost:4000` | StackCoin API base URL |
| `STACKCOIN_API_TOKEN` | Yes | | Bot API token from StackCoin |
| `STACKCOIN_WS_URL` | No | `ws://localhost:4000/ws` | StackCoin WebSocket URL |
| `LUCKYPOT_DB_PATH` | No | `luckypot.db` | SQLite database path |
| `TESTING_GUILD_ID` | No | | Restrict slash commands to one guild |
| `DEBUG_MODE` | No | `false` | Enable `/force-end-pot` command |
| `DAILY_DRAW_HOUR` | No | `0` | Daily draw hour (UTC) |
| `DAILY_DRAW_MINUTE` | No | `0` | Daily draw minute (UTC) |

## Slash Commands

- `/enter-pot` — Enter the daily lucky pot (costs 5 STK)
- `/pot-status` — Check the current pot status and participants
- `/pot-history` — View recent pot winners
- `/force-end-pot` — [DEBUG] Force end the current pot with a draw
```

**Step 2: Add `__pycache__/` to `.gitignore` if not already present**

Check and append if needed:

```
__pycache__/
*.pyc
```

**Step 3: Commit**

```bash
git add -A && git commit -m "docs: update README and gitignore"
```

---

### Task 8: Smoke test — verify E2E tests still pass

**Files:** None (verification only)

**Step 1: Run the StackCoin E2E LuckyPot tests**

```bash
cd /path/to/StackCoin/test/e2e
source .venv/bin/activate
python -m pytest test_luckypot.py -x -v --tb=short
```

Expected: All 16 luckypot tests pass. These tests import `from luckypot import db, game, stk` and never touch the `luckypot.discord` subpackage.

**Step 2: Verify the package builds**

```bash
cd /path/to/LuckyPot
uv sync
python -c "from luckypot.discord.bot import create_bot; print('discord layer imports OK')"
python -c "from luckypot.game import enter_pot; print('core imports OK')"
```

Both should print OK without errors.

**Step 3: Verify the bot starts (if Discord token is available)**

```bash
python lucky_pot.py
```

If `DISCORD_TOKEN` is set, the bot should connect to Discord and log "LuckyPot starting up..." followed by gateway connection messages. Ctrl+C to stop.

If `DISCORD_TOKEN` is not set, it should raise `ValueError: DISCORD_TOKEN is not set`.
