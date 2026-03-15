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
    stackcoin_ws_url: str = "ws://localhost:4000/ws"
    db_path: str = "luckypot.db"

    testing_guild_id: str = ""
    debug_mode: bool = False
    ban_duration_hours: int = 48

    daily_draw_hour: int = 0
    daily_draw_minute: int = 0
    draw_interval_minutes: int = (
        0  # When >0, overrides daily schedule with a repeating interval
    )


settings = Settings()
