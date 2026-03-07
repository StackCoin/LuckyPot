"""StackCoin API access for LuckyPot.

Thin wrapper around the stackcoin SDK that manages a shared Client instance
configured from LuckyPot's settings.
"""

import stackcoin
from loguru import logger

from luckypot.config import settings

_client: stackcoin.Client | None = None
_stackcoin_discord_id: str | None = None


def get_client() -> stackcoin.Client:
    """Get or create the shared StackCoin client."""
    global _client
    if _client is None:
        _client = stackcoin.Client(
            base_url=settings.stackcoin_api_url,
            token=settings.stackcoin_api_token,
        )
    return _client


def reset_client() -> None:
    """Reset the client (for testing or config changes)."""
    global _client
    _client = None


async def fetch_stackcoin_discord_id() -> str | None:
    """Fetch and cache the StackCoin Discord bot's user ID."""
    global _stackcoin_discord_id
    try:
        _stackcoin_discord_id = await get_client().get_discord_bot_id()
        logger.info(f"StackCoin Discord bot ID: {_stackcoin_discord_id}")
        return _stackcoin_discord_id
    except stackcoin.StackCoinError as e:
        logger.error(f"Failed to fetch StackCoin Discord bot ID: {e}")
        return None


def get_stackcoin_discord_id() -> str | None:
    """Return the cached StackCoin Discord bot user ID, or None if not fetched."""
    return _stackcoin_discord_id


async def close_client() -> None:
    """Close the shared client, releasing its connection pool."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def get_user_by_discord_id(discord_id: str) -> dict | None:
    """Look up a StackCoin user by their Discord ID."""
    try:
        users = await get_client().get_users(discord_id=discord_id)
        if not users:
            return None
        user = users[0]
        return {"id": user.id, "username": user.username, "balance": user.balance}
    except stackcoin.StackCoinError as e:
        logger.error(f"Failed to look up user by discord_id={discord_id}: {e}")
        return None


async def get_bot_user() -> dict | None:
    """Get the bot's own StackCoin user profile."""
    try:
        user = await get_client().get_me()
        return {"id": user.id, "username": user.username, "balance": user.balance}
    except stackcoin.StackCoinError as e:
        logger.error(f"Failed to get bot user: {e}")
        return None


async def get_bot_balance() -> int | None:
    """Get the bot's current STK balance."""
    try:
        user = await get_client().get_me()
        return user.balance
    except stackcoin.StackCoinError as e:
        logger.error(f"Failed to get bot balance: {e}")
        return None


async def send_stk(
    to_user_id: int, amount: int, label: str | None = None, idempotency_key: str | None = None
) -> dict | None:
    """Send STK to a user. Returns response dict or None on failure."""
    try:
        result = await get_client().send(
            to_user_id=to_user_id, amount=amount, label=label, idempotency_key=idempotency_key
        )
        return {
            "success": result.success,
            "transaction_id": result.transaction_id,
            "amount": result.amount,
            "from_new_balance": result.from_new_balance,
            "to_new_balance": result.to_new_balance,
        }
    except stackcoin.StackCoinError as e:
        logger.error(f"Failed to send {amount} STK to user {to_user_id}: {e}")
        return None


async def create_request(
    to_user_id: int, amount: int, label: str | None = None, idempotency_key: str | None = None
) -> dict | None:
    """Create a payment request. Returns response dict or None on failure."""
    try:
        result = await get_client().create_request(
            to_user_id=to_user_id, amount=amount, label=label, idempotency_key=idempotency_key
        )
        return {
            "success": result.success,
            "request_id": result.request_id,
            "amount": result.amount,
            "status": result.status,
        }
    except stackcoin.StackCoinError as e:
        logger.error(f"Failed to create request for {amount} STK from user {to_user_id}: {e}")
        return None


async def get_request(request_id: int) -> dict | None:
    """Get a request by ID."""
    try:
        req = await get_client().get_request(request_id=request_id)
        return {
            "id": req.id,
            "amount": req.amount,
            "status": req.status,
        }
    except stackcoin.StackCoinError as e:
        logger.error(f"Failed to get request {request_id}: {e}")
        return None


async def get_guild_channel(guild_id: str) -> str | None:
    """Get the designated channel for a Discord guild."""
    try:
        guild = await get_client().get_discord_guild(snowflake=guild_id)
        return guild.designated_channel_snowflake
    except stackcoin.StackCoinError:
        return None
