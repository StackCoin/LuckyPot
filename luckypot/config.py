"""Configuration via pydantic-settings.

All environment variables are prefixed with ``LUCKYPOT_``.
Example: the ``discord_token`` field reads from ``LUCKYPOT_DISCORD_TOKEN``.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LUCKYPOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    discord_token: str = ""
    stackcoin_api_url: str = "http://localhost:4000"
    stackcoin_api_token: str = ""
    stackcoin_ws_url: str = "ws://localhost:4000/socket/websocket"
    db_path: str = "luckypot.db"

    # Discord bot settings
    testing_guild_id: str = ""
    debug_mode: bool = False

    # Daily draw schedule (UTC)
    daily_draw_hour: int = 0
    daily_draw_minute: int = 0


settings = Settings()
