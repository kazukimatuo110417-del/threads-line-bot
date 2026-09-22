from functools import lru_cache
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()


@dataclass(frozen=True)
class Settings:
    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    line_user_id: str = ""

    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    threads_access_token: str = ""
    threads_api_base: str = "https://graph.threads.net/v1.0"

    database_path: str = "data/bot.sqlite3"
    app_timezone: str = "Asia/Tokyo"


@lru_cache
def get_settings() -> Settings:
    return Settings(
        line_channel_secret=os.getenv("LINE_CHANNEL_SECRET", ""),
        line_channel_access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""),
        line_user_id=os.getenv("LINE_USER_ID", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        threads_access_token=os.getenv("THREADS_ACCESS_TOKEN", ""),
        threads_api_base=os.getenv("THREADS_API_BASE", "https://graph.threads.net/v1.0"),
        database_path=os.getenv("DATABASE_PATH", "data/bot.sqlite3"),
        app_timezone=os.getenv("APP_TIMEZONE", "Asia/Tokyo"),
    )
