"""
配置管理
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/polybob"
    timescale_url: str = "postgresql+asyncpg://user:password@localhost:5432/polybob_timeseries"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Polymarket API
    polymarket_api_key: str = ""
    polymarket_gamma_api_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    polymarket_clob_rest_url: str = "https://clob.polymarket.com"

    # Risk Management
    max_position_size: float = 1000.0
    max_daily_loss: float = 500.0
    max_slippage_bps: float = 40.0

    # Monitoring
    prometheus_port: int = 9090
    log_level: str = "INFO"
    log_format: str = "auto"
    api_reload: bool = False

    # AI
    anthropic_api_key: str = ""


# 全局配置实例
_settings: Settings | None = None


def get_settings() -> Settings:
    """获取全局配置"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
