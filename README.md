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
| `STACKCOIN_WS_URL` | No | `ws://localhost:4000/socket/websocket` | StackCoin WebSocket URL |
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
