import os

import hikari
import lightbulb
from dotenv import load_dotenv
from stackcoin_python import AuthenticatedClient
from stackcoin_python.types import Unset
from stackcoin_python.models import (
    UsersResponse,
)
from stackcoin_python.api.default import (
    stackcoin_users,
)

load_dotenv()

token = os.getenv("LUCKY_POT_DISCORD_TOKEN")
stackcoin_bot_token = os.getenv("LUCKY_POT_STACKCOIN_BOT_TOKEN")
stackcoin_base_url = (
    os.getenv("LUCKY_POT_STACKCOIN_BASE_URL") or "https://stackcoin.world"
)

testing_guild_id = os.getenv("LUCKY_POT_TESTING_GUILD_ID")

if not token:
    raise ValueError("LUCKY_POT_DISCORD_TOKEN is not set")

if not stackcoin_bot_token:
    raise ValueError("LUCKY_POT_STACKCOIN_BOT_TOKEN is not set")


def get_client():
    global stackcoin_base_url, stackcoin_bot_token

    if not stackcoin_base_url or not stackcoin_bot_token:
        raise ValueError(
            "LUCKY_POT_STACKCOIN_BASE_URL or LUCKY_POT_STACKCOIN_BOT_TOKEN is not set"
        )

    return AuthenticatedClient(base_url=stackcoin_base_url, token=stackcoin_bot_token)


bot = hikari.GatewayBot(token=token)
lightbulb_client = lightbulb.client_from_app(bot)

bot.subscribe(hikari.StartingEvent, lightbulb_client.start)

guilds = [int(testing_guild_id)] if testing_guild_id else []


@lightbulb_client.register(guilds=guilds)
class EnterPot(
    lightbulb.SlashCommand,
    name="enter-pot",
    description="Enter the daily lucky pot!",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        async with get_client() as client:
            users = await stackcoin_users.asyncio(
                client=client, discord_id=str(ctx.user.id)
            )

            if not isinstance(users, UsersResponse) or isinstance(users.users, Unset):
                raise Exception("Failed to get users")

            if len(users.users) == 0:
                await ctx.respond(
                    "You are not registered with StackCoin!, please run /dole first."
                )

            user = users.users[0]

            await ctx.respond(f"Hello {user.username}, welcome to the lucky pot!")


if __name__ == "__main__":
    bot.run()
