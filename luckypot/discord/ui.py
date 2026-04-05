import hikari
from hikari.impl.special_endpoints import ContainerComponentBuilder

from luckypot import stk
from luckypot.discord.scheduler import next_draw_time

BRAND_COLOR = hikari.Color(0x7C3AED)


def build_entry_pending(amount: int) -> ContainerComponentBuilder:
    """Build response for a successful pot entry (pending payment)."""
    bot_id = stk.get_stackcoin_discord_id()
    bot_ref = f"<@{bot_id}>" if bot_id else "StackCoin"

    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("🎲 Pot Entry Submitted!")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        f"Accept the **{amount} STK** payment request from {bot_ref} via DMs to confirm your spot."
    )
    return container


def build_entry_instant_win(winning_amount: int) -> ContainerComponentBuilder:
    """Build response for an instant win — the user won the pot immediately."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("🎉 INSTANT WIN!")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        f"You won **{winning_amount} STK**! The winnings have been sent to your account."
    )
    return container


def build_entry_instant_win_free() -> ContainerComponentBuilder:
    """Build response for an instant win on an empty pot — free entry."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("🎉 INSTANT WIN... on an empty pot!")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        "You rolled an instant win, but the pot was empty. You got a **free entry** instead!"
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


def build_entry_banned(expires_at: str) -> ContainerComponentBuilder:
    """Build response when a user is banned from entering pots."""
    from datetime import datetime, timezone

    # Parse the SQLite timestamp and convert to Discord timestamp
    dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    unix_ts = int(dt.timestamp())

    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("🚫 Banned")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        f"You are banned from entering pots. Your ban expires <t:{unix_ts}:R>."
    )
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
    container.add_text_display(f"Total Pot: **{status['total_amount']} STK**")
    container.add_text_display(f"Participants: **{status['participants']}**")

    next_draw = next_draw_time()
    container.add_text_display(f"Next Draw: <t:{int(next_draw.timestamp())}:R>")

    return container


def build_pot_history(history: list[dict], page: int = 1) -> ContainerComponentBuilder:
    """Build the pot history display."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    header = "📜 Pot History" if page == 1 else f"📜 Pot History - Page {page}"
    container.add_text_display(header)
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)

    if not history:
        empty_msg = "No completed pots yet." if page == 1 else "Page has no pots."
        container.add_text_display(empty_msg)
        return container

    for pot in history:
        winner = pot.get("winner_discord_id")
        amount = pot.get("winning_amount", 0)
        win_type = pot.get("win_type", "DAILY DRAW")
        ended = pot.get("ended_at", "?")
        winner_text = f"<@{winner}>" if winner else "No winner"
        # Only annotate non-default win types (instant win, debug, etc.)
        suffix = f" ({win_type})" if win_type != "DAILY DRAW" else ""
        container.add_text_display(
            f"**{amount} STK** → {winner_text}{suffix} — {ended}"
        )

    return container


def build_auto_enter_opted_in() -> ContainerComponentBuilder:
    """Build response when user successfully opts in to auto-enter."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("✅ Auto-Enter Enabled")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        "You will automatically be entered into each new pot. "
        "Use `/auto-enter enabled:False` to opt out."
    )
    return container


def build_auto_enter_opted_out() -> ContainerComponentBuilder:
    """Build response when user successfully opts out of auto-enter."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    container.add_text_display("✅ Auto-Enter Disabled")
    container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
    container.add_text_display(
        "You will no longer be automatically entered into pots. "
        "Use `/auto-enter` to opt back in."
    )
    return container


def build_auto_enter_already_in_state(enabled: bool) -> ContainerComponentBuilder:
    """Build response when user is already in the requested state."""
    container = ContainerComponentBuilder(accent_color=BRAND_COLOR)
    if enabled:
        container.add_text_display("ℹ️ Already Opted In")
        container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
        container.add_text_display("You are already opted in to auto-enter.")
    else:
        container.add_text_display("ℹ️ Already Opted Out")
        container.add_separator(divider=True, spacing=hikari.SpacingType.SMALL)
        container.add_text_display("You are already opted out of auto-enter.")
    return container
