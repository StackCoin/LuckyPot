from typing import Literal, NotRequired, TypedDict


EntryStatus = Literal["pending", "confirmed", "denied"]


class PotRow(TypedDict):
    pot_id: int
    guild_id: str
    is_active: int | bool
    current_round: int
    created_at: NotRequired[str]
    ended_at: NotRequired[str | None]
    winner_discord_id: NotRequired[str | None]
    winning_amount: NotRequired[int | None]
    win_type: NotRequired[str | None]


class PotEntryRow(TypedDict):
    entry_id: int
    pot_id: int
    discord_id: str
    amount: int
    status: EntryStatus
    stackcoin_request_id: str | None
    entry_round: int
    created_at: NotRequired[str]


class PotEntryWithPotRow(PotEntryRow):
    pot_guild_id: str
    pot_is_active: int | bool


class UserBanRow(TypedDict):
    ban_id: int
    discord_id: str
    guild_id: str
    reason: str
    expires_at: str
    created_at: NotRequired[str]


class PotStatus(TypedDict, total=False):
    active: bool
    pot_id: int
    participants: int
    total_amount: int


class StackCoinUser(TypedDict):
    id: int
    username: str
    balance: int


class StackCoinSendResult(TypedDict):
    success: bool
    transaction_id: int | None
    amount: int
    from_new_balance: int
    to_new_balance: int


class StackCoinRequestResult(TypedDict):
    success: bool
    request_id: int
    amount: int
    status: str
    transaction_id: int | None


class StackCoinPreauth(TypedDict, total=False):
    id: int
    user_id: int
    status: str
    max_amount: int
    window_hours: int


class EnterPotResult(TypedDict, total=False):
    status: str
    message: str
    entry_id: int
    request_id: str
    winning_amount: int
    expires_at: str


class InstantWinResult(TypedDict):
    won: bool
    winning_amount: int
