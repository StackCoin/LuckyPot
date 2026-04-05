# Auto-Enter Design

**Date:** 2026-04-04  
**Issue:** https://github.com/StackCoin/LuckyPot/issues/3

## Summary

Add an `/auto-enter` command that lets users opt in (per-guild) to be automatically entered into every new pot. After a pot ends and the winner is announced, the bot waits 30 seconds then calls the existing `enter_pot()` flow for each opted-in user in that guild — sending them a StackCoin payment request DM as usual. Users opt out by running `/auto-enter enabled:False`.

## Data Model

New table added in `db.py` alongside existing tables in `init_database()`:

```sql
CREATE TABLE IF NOT EXISTS auto_enter_users (
    discord_id TEXT NOT NULL,
    guild_id   TEXT NOT NULL,
    enabled_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (discord_id, guild_id)
)
```

Three new functions in `db.py`:

- `set_auto_enter(conn, discord_id, guild_id, enabled: bool)` — inserts row on opt-in, deletes on opt-out
- `get_auto_enter_users(conn, guild_id) -> list[str]` — returns all opted-in `discord_id`s for a guild
- `get_auto_enter_status(conn, discord_id, guild_id) -> bool` — returns whether the user is currently opted in

## Command

`/auto-enter` slash command added to `commands.py`:

- Single optional boolean parameter `enabled`, defaults to `True`
- Primary use: `/auto-enter` to opt in, `/auto-enter enabled:False` to opt out
- Response is always ephemeral
- If the user is already in the requested state, responds with a message saying so (no-op)
- Otherwise calls `set_auto_enter()` and confirms the change

## Trigger Logic

After `process_pot_win()` completes (win announced) in `game.py`:

1. Fire-and-forget `asyncio.create_task()` for an async function `_auto_enter_users()`
2. `_auto_enter_users()` sleeps 30 seconds
3. Queries `get_auto_enter_users(conn, guild_id)`
4. For each `discord_id`, calls `enter_pot(discord_id, guild_id, announce_fn=announce_fn)`
5. The existing `enter_pot()` handles all edge cases: bans, already-entered, STK account missing, etc.
6. No additional announcement — users receive the standard StackCoin payment request DM

## What Is Not Changing

- The payment acceptance step is unchanged — users still must accept the StackCoin DM
- Deny-bans still apply — a banned auto-enter user will be silently skipped (returned `status: "banned"`)
- The pot creation lifecycle is unchanged — a new pot is created lazily on the first `ensure_active_pot()` call inside `enter_pot()`
- All existing commands are unchanged
