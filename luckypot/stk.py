"""StackCoin API access for LuckyPot.

Thin wrapper around the stackcoin SDK that manages a shared Client instance
configured from LuckyPot's settings.
"""

import stackcoin
from loguru import logger

from luckypot.config import settings
from typing import cast

from luckypot.types import (
    StackCoinPreauth,
    StackCoinRequestResult,
    StackCoinSendResult,
    StackCoinUser,
)

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


async def get_user_by_discord_id(discord_id: str) -> StackCoinUser | None:
    """Look up a StackCoin user by their Discord ID."""
    try:
        users = await get_client().get_users(discord_id=discord_id)
        if not users:
            return None
        user = users[0]
        if user.id is None:
            logger.error(f"StackCoin user for discord_id={discord_id} had no id")
            return None
        return cast(
            StackCoinUser,
            {"id": user.id, "username": user.username, "balance": user.balance},
        )
    except stackcoin.StackCoinError as e:
        logger.error(f"Failed to look up user by discord_id={discord_id}: {e}")
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
    to_user_id: int,
    amount: int,
    label: str | None = None,
    idempotency_key: str | None = None,
) -> StackCoinSendResult | None:
    """Send STK to a user. Returns response dict or None on failure."""
    try:
        result = await get_client().send(
            to_user_id=to_user_id,
            amount=amount,
            label=label,
            idempotency_key=idempotency_key,
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


async def create_preauth(
    user_id: int,
    max_amount: int,
    window_hours: int,
) -> StackCoinPreauth | None:
    """Request a preauthorization from a user."""
    try:
        return cast(
            StackCoinPreauth,
            await get_client().create_preauth(
                user_id=user_id,
                max_amount=max_amount,
                window_hours=window_hours,
            ),
        )
    except stackcoin.StackCoinError as e:
        logger.error(f"Failed to create preauth for user {user_id}: {e}")
        return None


async def get_preauths(user_id: int | None = None) -> list[StackCoinPreauth]:
    """List preauths for this bot."""
    try:
        return cast(
            list[StackCoinPreauth], await get_client().get_preauths(user_id=user_id)
        )
    except stackcoin.StackCoinError as e:
        logger.error(f"Failed to get preauths: {e}")
        return []


async def create_request(
    to_user_id: int,
    amount: int,
    label: str | None = None,
    idempotency_key: str | None = None,
    use_preauth: bool = False,
) -> StackCoinRequestResult | None:
    """Create a payment request. Returns response dict or None on failure.

    Raises StackCoinError for preauth_limit_exceeded so callers can handle it.
    """
    try:
        result = await get_client().create_request(
            to_user_id=to_user_id,
            amount=amount,
            label=label,
            idempotency_key=idempotency_key,
            use_preauth=use_preauth,
        )
        return {
            "success": result.success,
            "request_id": result.request_id,
            "amount": result.amount,
            "status": result.status,
            "transaction_id": result.transaction_id,
        }
    except stackcoin.StackCoinError as e:
        error_str = str(e).lower()
        if "preauth_limit_exceeded" in error_str:
            raise
        logger.error(
            f"Failed to create request for {amount} STK from user {to_user_id}: {e}"
        )
        return None


async def deny_request(request_id: int) -> bool:
    """Deny a payment request. Returns True if the request was denied."""
    try:
        result = await get_client().deny_request(request_id=request_id)
        return result.success is True
    except stackcoin.StackCoinError as e:
        logger.error(f"Failed to deny request {request_id}: {e}")
        return False


async def get_guild_channel(guild_id: str) -> str | None:
    """Get the designated channel for a Discord guild."""
    try:
        guild = await get_client().get_discord_guild(snowflake=guild_id)
        return guild.designated_channel_snowflake
    except stackcoin.StackCoinError:
        return None
