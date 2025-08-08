import os

import hikari
import lightbulb
from dotenv import load_dotenv
from stackcoin_python import AuthenticatedClient
from stackcoin_python.models import (
    BalanceResponse,
)
from stackcoin_python.api.default import (
    stackcoin_self_balance,
)

load_dotenv()

token = os.getenv("LUCKY_POT_DISCORD_TOKEN")
stackcoin_bot_token = os.getenv("LUCKY_POT_STACKCOIN_BOT_TOKEN")
stackcoin_base_url = os.getenv("LUCKY_POT_STACKCOIN_BASE_URL")
if not token:
    raise ValueError("LUCKY_POT_DISCORD_TOKEN is not set")

if not stackcoin_bot_token:
    raise ValueError("LUCKY_POT_STACKCOIN_BOT_TOKEN is not set")

if not stackcoin_base_url:
    raise ValueError("LUCKY_POT_STACKCOIN_BASE_URL is not set")


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


@lightbulb_client.register()
class Ping(
    lightbulb.SlashCommand,
    name="ping",
    description="checks the bot is alive",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        async with get_client() as client:
            my_balance = await stackcoin_self_balance.asyncio(client=client)

            if not isinstance(my_balance, BalanceResponse):
                raise Exception("Failed to get balance")

            await ctx.respond(
                f"Logged in as {my_balance.username} with balance {my_balance.balance}"
            )


if __name__ == "__main__":
    bot.run()
