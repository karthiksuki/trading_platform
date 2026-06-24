import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_title: str = "trading_platform_backend"
    app_version: str = "0.1.0"
    db_path: str = os.getenv("TRADING_DB_PATH", "trading.db")
    market_data_source: str = os.getenv("MARKET_DATA_SOURCE", "polymarket").lower()
    polymarket_gamma_url: str = os.getenv("POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com")
    trading_encryption_key: str = os.getenv("TRADING_ENCRYPTION_KEY", "dev-only-change-this-key")
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)


settings = Settings()
