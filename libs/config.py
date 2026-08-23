"""
配置管理
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Local service ports
    polybob_api_port: int = 18000
    polybob_dashboard_port: int = 13001
    polybob_postgres_port: int = 15432
    polybob_redis_port: int = 16379
    polybob_prometheus_port: int = 19090
    polybob_grafana_port: int = 13000

    # The API is a single-operator local workbench. Keep the default listener
    # loopback-only; container deployment overrides this inside the container
    # while docker-compose keeps the host port loopback-only.
    polybob_api_host: str = "127.0.0.1"
    polybob_cors_origins: str = (
        "http://127.0.0.1:13001,http://localhost:13001"
    )

    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost:15432/polybob"
    timescale_url: str = "postgresql+asyncpg://user:password@localhost:15432/polybob_timeseries"
    polybob_db_path: str = "./.polybob/polybob.sqlite3"

    # Redis
    redis_url: str = "redis://localhost:16379/0"

    # Polymarket API
    polymarket_api_key: str = ""
    polymarket_gamma_api_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    polymarket_clob_rest_url: str = "https://clob.polymarket.com"

    # BTC 5-minute workbench refresh cadence (seconds). Backend cache TTL is
    # this + 1s; keep it aligned with the dashboard poll interval so the live
    # window stays near-real-time without hammering upstream every request.
    polybob_btc_5m_poll_seconds: float = 1.5

    # Raw order-book event log (append-only, for deterministic replay).
    # Off by default: raw event capture grows disk usage steadily.
    polybob_book_log_enabled: bool = False
    polybob_book_log_retention_days: int = 7
    polybob_book_log_max_rows: int = 500_000

    # Risk Management
    max_position_size: float = 1000.0
    max_daily_loss: float = 500.0
    max_slippage_bps: float = 40.0

    # Account equity, for turning a sizing *rule* into concrete share counts.
    # Deliberately has no default. The verdict API used to pass a hardcoded
    # 100,000 into the book's "one of ten parts" rule, which produced an exact
    # allocation and share count for an account that does not exist — a fabricated
    # number in the one place the product tells you how much to buy. Unset means
    # the API reports the rule as a *fraction* of capital and says the equity is
    # unknown, which is true. Set POLYBOB_ACCOUNT_EQUITY to get share counts.
    polybob_account_equity: float | None = None

    # Monitoring
    prometheus_port: int = 19090
    log_level: str = "INFO"
    log_format: str = "auto"
    api_reload: bool = False

    # Product operating mode
    product_mode: str = "personal_workbench"
    enable_lab_auto_trader: bool = False
    enable_lab_backtest: bool = False
    enable_lab_paper_execution: bool = False
    enable_lab_kronos_forecasting: bool = False
    polybob_kronos_model_root: str = "data/models/kronos"
    polybob_kronos_device: str = ""
    polybob_kronos_paths: int = 3

    # Compute backend
    polybob_compute_backend: str = "python"
    polybob_rust_fallback_enabled: bool = True

    # Crypto discovery providers
    polybob_outbound_proxy: str = ""
    binance_alpha_api_url: str = "https://web3.binance.com"
    binance_futures_api_url: str = "https://fapi.binance.com"
    binance_futures_ws_api_url: str = "wss://ws-fapi.binance.com/ws-fapi/v1"
    binance_alpha_market_api_url: str = "https://www.binance.com"
    dex_screener_api_url: str = "https://api.dexscreener.com"
    discovery_request_timeout_seconds: float = 10.0
    discovery_min_coverage: float = 0.70
    discovery_max_cashout_risk: float = 45.0
    discovery_min_pump_potential: float = 70.0
    discovery_min_liquidity_usd: float = 500_000.0
    discovery_min_volume_24h_usd: float = 1_000_000.0

    # Research knowledge ingestion
    knowledge_ingestion_enabled: bool = False
    statementdog_crawl_authorized: bool = False
    statementdog_crawl_interval_seconds: float = 3600.0
    statementdog_crawl_concurrency: int = 3
    statementdog_lookback_months: int = 6

    # Market news terminal (市场观察 real-time feed)
    finnhub_api_key: str = ""
    market_news_enabled: bool = True
    market_news_interval_seconds: float = 90.0
    market_news_categories: str = "general,crypto,forex"
    market_news_max_items_per_category: int = 60

    # Strategy promotion gate: only strategies that cleared PromotionGate on
    # real history (data/promotion_board.json) may create intents; everything
    # else stays in lab. Fail-closed, and on by default — an unvalidated
    # strategy reaching the execution desk is the failure mode this project
    # exists to prevent, so the safe state is the default state. Set
    # REQUIRE_STRATEGY_PROMOTION=false to deliberately open the gate.
    require_strategy_promotion: bool = True

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
