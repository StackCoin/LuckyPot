import hikari
from hikari.impl.special_endpoints import ContainerComponentBuilder

from luckypot.discord.scheduler import next_draw_time

BRAND_COLOR = hikari.Color(0x7C3AED)


def build_entry_pending(request_id: int, amount: int) -> ContainerComponentBuilder:
    """Build response for a successful pot entry (pending payment)."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("🎲 Pot Entry Submitted!")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        f"Accept the **{amount} STK** payment request from StackCoin via DMs to confirm your spot."
    )
    return container


def build_entry_instant_win() -> ContainerComponentBuilder:
    """Build response for an instant win roll (still needs payment)."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("🎉 INSTANT WIN!")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        "You rolled an **instant win**! Accept the payment request to claim the entire pot!"
    )
    return container


def build_entry_already_entered() -> ContainerComponentBuilder:
    """Build response when user has already entered the pot."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("❌ Already Entered")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        "You have already entered this pot! You can only enter once per pot."
    )
    return container


def build_entry_error(message: str) -> ContainerComponentBuilder:
    """Build response for a pot entry error."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("❌ Error")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(message)
    return container


def build_pot_status(status: dict) -> ContainerComponentBuilder:
    """Build the pot status display."""
    if not status.get("active"):
        container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
        container.add_text_display("🎲 No Active Pot")
        container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
        container.add_text_display("Use `/enter-pot` to start one!")
        return container

    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("🎰 Lucky Pot Status")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(f"💰 Total Pot: **{status['total_amount']} STK**")
    container.add_text_display(f"👥 Participants: **{status['participants']}**")

    next_draw = next_draw_time()
    container.add_text_display(f"⏰ Next Draw: <t:{int(next_draw.timestamp())}:R>")

    if "pot_id" in status:
        container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
        container.add_text_display(f"Pot ID: {status['pot_id']}")

    return container


def build_pot_history(history: list[dict]) -> ContainerComponentBuilder:
    """Build the pot history display."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
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
        container.add_text_display(
            f"**{amount} STK** → {winner_text} ({win_type}) — {ended}"
        )

    return container


def build_winner_announcement(
    winner_discord_id: str, winning_amount: int, win_type: str
) -> str:
    """Build a winner announcement message for the guild channel."""
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
