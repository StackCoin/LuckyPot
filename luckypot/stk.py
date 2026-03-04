"""StackCoin API wrapper for LuckyPot bot."""
import httpx
from loguru import logger
from luckypot.config import settings


def _client() -> httpx.AsyncClient:
    """Create an authenticated HTTP client for the StackCoin API."""
    return httpx.AsyncClient(
        base_url=settings.stackcoin_api_url,
        headers={"Authorization": f"Bearer {settings.stackcoin_api_token}"},
        timeout=10.0,
    )


async def get_user_by_discord_id(discord_id: str) -> dict | None:
    """Look up a StackCoin user by their Discord ID."""
    async with _client() as client:
        resp = await client.get("/api/users", params={"discord_id": discord_id})
        if resp.status_code != 200:
            logger.error(f"Failed to look up user by discord_id={discord_id}: {resp.status_code}")
            return None
        data = resp.json()
        users = data.get("users", [])
        return users[0] if users else None


async def get_bot_user() -> dict | None:
    """Get the bot's own StackCoin user profile."""
    async with _client() as client:
        resp = await client.get("/api/user/me")
        if resp.status_code != 200:
            logger.error(f"Failed to get bot user: {resp.status_code}")
            return None
        return resp.json()


async def get_bot_balance() -> int | None:
    """Get the bot's current STK balance."""
    user = await get_bot_user()
    if user is None:
        return None
    return user.get("balance")


async def send_stk(to_user_id: int, amount: int, label: str | None = None, idempotency_key: str | None = None) -> dict | None:
    """Send STK from the bot to a user.

    Args:
        to_user_id: The StackCoin user ID of the recipient.
        amount: Amount of STK to send.
        label: Optional transaction label.
        idempotency_key: Optional idempotency key to prevent duplicate sends.

    Returns:
        Response dict on success, None on failure.
    """
    async with _client() as client:
        payload: dict = {"amount": amount}
        if label:
            payload["label"] = label
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        resp = await client.post(f"/api/user/{to_user_id}/send", json=payload, headers=headers)
        if resp.status_code != 200:
            logger.error(f"Failed to send {amount} STK to user {to_user_id}: {resp.status_code} {resp.text}")
            return None
        return resp.json()


async def create_request(to_user_id: int, amount: int, label: str | None = None, idempotency_key: str | None = None) -> dict | None:
    """Create a STK request (ask a user to pay the bot).

    The bot is the requester; to_user_id is the responder who must accept/deny.

    Args:
        to_user_id: The StackCoin user ID to request payment from.
        amount: Amount of STK to request.
        label: Optional request label.
        idempotency_key: Optional idempotency key to prevent duplicate requests.

    Returns:
        Response dict on success, None on failure.
    """
    async with _client() as client:
        payload: dict = {"amount": amount}
        if label:
            payload["label"] = label
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        resp = await client.post(f"/api/user/{to_user_id}/request", json=payload, headers=headers)
        if resp.status_code != 200:
            logger.error(f"Failed to create request for {amount} STK from user {to_user_id}: {resp.status_code} {resp.text}")
            return None
        return resp.json()


async def get_request(request_id: int) -> dict | None:
    """Get details of a specific request."""
    async with _client() as client:
        resp = await client.get(f"/api/request/{request_id}")
        if resp.status_code != 200:
            logger.error(f"Failed to get request {request_id}: {resp.status_code}")
            return None
        return resp.json()


async def get_guild_channel(guild_id: str) -> str | None:
    """Get the designated channel snowflake for a guild."""
    async with _client() as client:
        resp = await client.get(f"/api/discord/guild/{guild_id}")
        if resp.status_code != 200:
            logger.debug(f"No guild info for {guild_id}: {resp.status_code}")
            return None
        data = resp.json()
        return data.get("designated_channel_snowflake")
