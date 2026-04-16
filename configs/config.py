import os
from loguru import logger


def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(f"Required environment variable '{key}' is not set or empty.")
    return value


class Config:
    TELEGRAM_TOKEN: str = _require("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID: str = _require("TELEGRAM_CHAT_ID")
    DATABASE_URL: str = _require("DATABASE_URL")
    TIMEZONE: str = os.environ.get("TIMEZONE", "America/Toronto")
    PORT: int = int(os.environ.get("PORT", 5000))


logger.debug(
    "Config loaded: DATABASE_URL={db}, TIMEZONE={tz}, PORT={port}",
    db=Config.DATABASE_URL,
    tz=Config.TIMEZONE,
    port=Config.PORT,
)
