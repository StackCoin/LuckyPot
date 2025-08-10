import os
from loguru import logger
from stackcoin_python import AuthenticatedClient
from stackcoin_python.types import Unset
from stackcoin_python.models import (
    UsersResponse,
    CreateRequestParams,
    CreateRequestResponse,
    RequestsResponse,
    SendStkParams,
    SendStkResponse,
    DiscordGuildResponse,
    User,
    Request,
)
from stackcoin_python.api.default import (
    stackcoin_users,
    stackcoin_create_request,
    stackcoin_requests,
    stackcoin_deny_request,
    stackcoin_discord_guild,
    stackcoin_send_stk,
)

# Configuration
STACKCOIN_BOT_TOKEN = os.getenv("LUCKY_POT_STACKCOIN_BOT_TOKEN")
STACKCOIN_BASE_URL = (
    os.getenv("LUCKY_POT_STACKCOIN_BASE_URL") or "https://stackcoin.world"
)


def get_client():
    """Get authenticated StackCoin client"""
    if not STACKCOIN_BASE_URL or not STACKCOIN_BOT_TOKEN:
        raise ValueError("StackCoin credentials not configured")
    return AuthenticatedClient(base_url=STACKCOIN_BASE_URL, token=STACKCOIN_BOT_TOKEN)


async def get_user_by_discord_id(discord_id: str) -> User | None:
    """Get StackCoin user by Discord ID"""
    try:
        async with get_client() as client:
            response = await stackcoin_users.asyncio(
                client=client, discord_id=discord_id
            )

            if not isinstance(response, UsersResponse) or isinstance(
                response.users, Unset
            ):
                logger.error(f"Failed to get user info for Discord ID {discord_id}")
                return None

            if len(response.users) == 0:
                logger.warning(f"No StackCoin user found for Discord ID {discord_id}")
                return None

            return response.users[0]
    except Exception as e:
        logger.error(f"Error getting user by Discord ID {discord_id}: {e}")
        return None


async def create_payment_request(
    user_id: int, amount: int, label: str = "Lucky Pot Entry"
) -> str | None:
    """Create a payment request and return request ID"""
    try:
        async with get_client() as client:
            response = await stackcoin_create_request.asyncio(
                client=client,
                user_id=user_id,
                body=CreateRequestParams(amount=amount, label=label),
            )

            if isinstance(response, CreateRequestResponse):
                return str(response.request_id)
            else:
                logger.error(f"Failed to create payment request for user {user_id}")
                return None
    except Exception as e:
        logger.error(f"Error creating payment request for user {user_id}: {e}")
        return None


async def send_stk(discord_id: str, amount: int, label: str) -> bool:
    """Send STK to a user by Discord ID"""
    try:
        user = await get_user_by_discord_id(discord_id)
        if not user:
            return False

        async with get_client() as client:
            if not isinstance(user.id, int):
                raise Exception("User ID is not an integer")

            response = await stackcoin_send_stk.asyncio(
                client=client,
                user_id=user.id,
                body=SendStkParams(amount=amount, label=label),
            )

            if isinstance(response, SendStkResponse) and response.success:
                logger.info(f"Successfully sent {amount} STK to {user.username}")
                return True
            else:
                logger.error(f"Failed to send {amount} STK to {user.username}")
                return False
    except Exception as e:
        logger.error(f"Error sending {amount} STK to Discord ID {discord_id}: {e}")
        return False


async def get_accepted_requests() -> list[Request]:
    """Get all accepted payment requests from the last 2 hours with pagination"""
    try:
        all_requests = []
        page = 1

        async with get_client() as client:
            while True:
                response = await stackcoin_requests.asyncio(
                    client=client,
                    role="responder",
                    status="accepted",
                    since="2h",
                    page=page,
                )

                if not isinstance(response, RequestsResponse) or isinstance(
                    response.requests, Unset
                ):
                    break

                if not response.requests:
                    break

                all_requests.extend(response.requests)

                total_pages = (
                    response.pagination.total_pages
                    if not isinstance(response.pagination, Unset)
                    else None
                )

                if (
                    isinstance(response.pagination, Unset)
                    or total_pages is None
                    or isinstance(total_pages, Unset)
                    or page >= total_pages
                ):
                    break

                page += 1

        return all_requests
    except Exception as e:
        logger.error(f"Error getting accepted requests: {e}")
        return []


async def deny_request(request_id: str) -> bool:
    """Deny a payment request"""
    try:
        async with get_client() as client:
            await stackcoin_deny_request.asyncio(
                client=client, request_id=int(request_id)
            )
            return True  # If no exception, assume success
    except Exception as e:
        logger.error(f"Error denying request {request_id}: {e}")
        return False


async def get_guild_channel(guild_id: str) -> str | None:
    """Get designated channel for a guild"""
    try:
        async with get_client() as client:
            response = await stackcoin_discord_guild.asyncio(
                client=client, snowflake=guild_id
            )

            if isinstance(response, DiscordGuildResponse) and not isinstance(
                response.designated_channel_snowflake, Unset
            ):
                return response.designated_channel_snowflake
            return None
    except Exception as e:
        logger.error(f"Error getting guild channel for {guild_id}: {e}")
        return None
