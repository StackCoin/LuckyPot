# LuckyPot

A lottery bot for [StackCoin](https://github.com/StackCoin/StackCoin). Players
enter a pot by paying STK, and a daily draw selects a winner who takes the
entire pot. There's also a small chance of an instant win on entry.

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

All environment variables are prefixed with `LUCKYPOT_`.

| Variable                    | Required | Default                                | Description                          |
| --------------------------- | -------- | -------------------------------------- | ------------------------------------ |
| `LUCKYPOT_DISCORD_TOKEN`    | Yes      |                                        | Discord bot token                    |
| `LUCKYPOT_STACKCOIN_API_URL`| Yes      | `http://localhost:4000`                | StackCoin API base URL               |
| `LUCKYPOT_STACKCOIN_API_TOKEN`| Yes    |                                        | Bot API token from StackCoin         |
| `LUCKYPOT_STACKCOIN_WS_URL` | No      | `ws://localhost:4000/ws`               | StackCoin WebSocket URL              |
| `LUCKYPOT_DB_PATH`          | No       | `luckypot.db`                          | SQLite database path                 |
| `LUCKYPOT_TESTING_GUILD_ID` | No       |                                        | Restrict slash commands to one guild |
| `LUCKYPOT_DEBUG_MODE`       | No       | `false`                                | Enable `/force-end-pot` command      |
| `LUCKYPOT_DAILY_DRAW_HOUR`  | No       | `0`                                    | Daily draw hour (UTC)                |
| `LUCKYPOT_DAILY_DRAW_MINUTE`| No       | `0`                                    | Daily draw minute (UTC)              |
| `LUCKYPOT_DRAW_INTERVAL_MINUTES`| No   | `0`                                    | When >0, overrides daily schedule with a repeating interval (for testing) |

## Slash Commands

- `/enter-pot` — Enter the daily lucky pot (costs 5 STK)
- `/pot-status` — Check the current pot status and participants
- `/pot-history` — View recent pot winners
- `/force-end-pot` — [DEBUG] Force end the current pot with a draw
