"""
PolyBob Main Application
"""
import asyncio
import json
import math
import re
from datetime import datetime, timezone
import logging
import sys
import time
import structlog
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import numpy as np
import yaml

from libs.config import get_settings
from libs.db import fact_store
from libs.db.repositories import BasketRepository, DecisionRepository, IntentRepository
from libs.polymarket.btc_five_minute import (
    BtcFiveMinuteConfig,
    build_btc_five_minute_slug,
    build_workbench_snapshot,
    map_outcome_tokens,
    normalize_book,
)
from services.risk_manager.risk_checker import RiskChecker
from services.market_discovery import MarketDiscoveryService
from services.realtime_ingestor import RealtimeIngestorService
from services.feature_engine import FeatureEngineService
from services.strategy_manager import StrategyManagerService
from services.execution_engine.basket_executor import BasketExecutor
from services.execution_engine.contract_executor import ContractExecutor
from services.execution_engine.intent_execution_service import IntentExecutionService
from services.onchain_monitor import OnchainMonitorService
from services.pair_feature_engine import PairDefinition, PairFeatureEngineService
from libs.crypto.binance_client import BinanceClient
from libs.crypto.discovery.providers.binance_alpha import BinanceAlphaProvider
from libs.crypto.discovery.providers.binance_futures import BinanceFuturesProvider
from libs.crypto.discovery.providers.http import build_provider_http_client
from libs.crypto.discovery.models import DiscoverySnapshot
from libs.crypto.discovery.service import AltcoinDiscoveryService
from libs.crypto.hyperliquid_client import HyperliquidClient
from libs.knowledge.impact import ASSET_CLASSES
from libs.knowledge.models import KnowledgeSearchResult, SourceRunStatus
from libs.knowledge.sources.finnhub_news import FinnhubNewsSource
from libs.knowledge.sources.statementdog import StatementDogSource
from libs.knowledge.store import KnowledgeStore
from libs.schemas import ExecutionVenue, InstrumentRef
from services.knowledge_ingestion import KnowledgeIngestionService
from services.simulation import (
    InvalidRunTransitionError,
    SimulationService,
    UnknownRunError,
    downsample_equity_curve,
)
from services.simulation.metrics import compute_run_metrics


def configure_logging():
    """配置 structlog 输出和级别过滤"""
    settings = get_settings()
    log_level_name = settings.log_level.upper()
    numeric_level = getattr(logging, log_level_name, logging.INFO)

    log_format = settings.log_format.lower()
    if log_format == "auto":
        log_format = "console" if sys.stderr.isatty() else "json"

    shared_processors = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


configure_logging()

logger = structlog.get_logger()


# 全局服务实例
market_discovery: MarketDiscoveryService | None = None
realtime_ingestor: RealtimeIngestorService | None = None
feature_engine: FeatureEngineService | None = None
strategy_manager: StrategyManagerService | None = None
basket_executor: BasketExecutor | None = None
intent_execution_service: IntentExecutionService | None = None
pair_feature_engine: PairFeatureEngineService | None = None
onchain_monitor: OnchainMonitorService | None = None
altcoin_discovery: AltcoinDiscoveryService | None = None
knowledge_ingestion: KnowledgeIngestionService | None = None
market_news_service: KnowledgeIngestionService | None = None
simulation_service: SimulationService | None = None
trading_engine = None
PAIR_UNIVERSE_PATH = Path(__file__).parent.parent.parent / "config" / "pair_universe.yaml"
ONCHAIN_WATCHLIST_PATH = Path(__file__).parent.parent.parent / "config" / "onchain_watchlists.yaml"
PORTFOLIO_LEDGER_NOT_CONFIGURED_NOTE = (
    "Portfolio ledger not configured; portfolio exposure, leverage, and PnL are unknown."
)
_api_response_cache: dict[str, dict[str, Any]] = {}
_api_response_locks: dict[str, asyncio.Lock] = {}
_API_RESPONSE_CACHE_MAX_ENTRIES = 256

_shared_http_client: httpx.AsyncClient | None = None


def get_shared_http_client() -> httpx.AsyncClient:
    """返回进程级共享的 AsyncClient；缺失时懒加载创建（便于无 lifespan 的测试）。"""
    global _shared_http_client
    if _shared_http_client is None or _shared_http_client.is_closed:
        _shared_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(4, connect=2),
            headers={"User-Agent": "PolyBob/0.1"},
        )
    return _shared_http_client


async def close_shared_http_client() -> None:
    global _shared_http_client
    client, _shared_http_client = _shared_http_client, None
    if client is not None and not client.is_closed:
        await client.aclose()


def _evict_expired_api_cache_entries(now: float, active_key: str) -> None:
    """插入新缓存前清理过期条目（及其锁），并对总量做硬上限。"""
    for key in [
        key
        for key, entry in _api_response_cache.items()
        if entry["expires_at"] <= now and key != active_key
    ]:
        _api_response_cache.pop(key, None)
        _api_response_locks.pop(key, None)

    overflow = len(_api_response_cache) - _API_RESPONSE_CACHE_MAX_ENTRIES
    if overflow > 0:
        for key in sorted(
            _api_response_cache,
            key=lambda cache_key: _api_response_cache[cache_key]["expires_at"],
        ):
            if overflow <= 0:
                break
            if key == active_key:
                continue
            _api_response_cache.pop(key, None)
            _api_response_locks.pop(key, None)
            overflow -= 1


async def cached_api_response(
    key: str,
    ttl_seconds: float,
    loader: Callable[[], Awaitable[dict]],
) -> dict:
    now = time.monotonic()
    cached = _api_response_cache.get(key)
    if cached and cached["expires_at"] > now:
        return cached["value"]

    lock = _api_response_locks.setdefault(key, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        cached = _api_response_cache.get(key)
        if cached and cached["expires_at"] > now:
            return cached["value"]

        value = await loader()
        now = time.monotonic()
        _evict_expired_api_cache_entries(now, key)
        _api_response_cache[key] = {
            "expires_at": now + ttl_seconds,
            "value": value,
        }
        return value


def clear_api_response_cache() -> None:
    _api_response_cache.clear()
    _api_response_locks.clear()


def get_trading_engine():
    """延迟初始化交易引擎，避免应用启动阶段额外阻塞。"""
    global trading_engine
    if trading_engine is None:
        from services.auto_trader.engine import TradingEngine

        trading_engine = TradingEngine(10000)
    return trading_engine


def serialize_knowledge_result(result: KnowledgeSearchResult) -> dict[str, Any]:
    return {
        "source_id": result.source_id,
        "document_id": result.document_id,
        "url": result.url,
        "title": result.title,
        "document_type": result.document_type,
        "ticker": result.ticker,
        "company_name": result.company_name,
        "published_at": result.published_at.isoformat() if result.published_at else None,
        "updated_at": result.updated_at.isoformat() if result.updated_at else None,
        "captured_at": result.captured_at.isoformat(),
        "language": result.language,
        "summary": result.summary,
        "snippet": result.snippet,
        "tags": result.tags,
        "metadata": result.metadata,
    }


def serialize_source_status(status: SourceRunStatus) -> dict[str, Any]:
    return {
        "source_id": status.source_id,
        "status": status.status,
        "started_at": status.started_at.isoformat(),
        "finished_at": status.finished_at.isoformat() if status.finished_at else None,
        "discovered_count": status.discovered_count,
        "fetched_count": status.fetched_count,
        "inserted_count": status.inserted_count,
        "updated_count": status.updated_count,
        "failed_count": status.failed_count,
        "message": status.message,
    }


def require_altcoin_discovery() -> AltcoinDiscoveryService:
    if altcoin_discovery is None:
        raise HTTPException(status_code=503, detail="Altcoin discovery service not ready")
    return altcoin_discovery


def require_knowledge_ingestion() -> KnowledgeIngestionService:
    if knowledge_ingestion is None:
        raise HTTPException(status_code=503, detail="Knowledge ingestion service not ready")
    return knowledge_ingestion


def require_market_news() -> KnowledgeIngestionService:
    if market_news_service is None:
        raise HTTPException(status_code=503, detail="Market news service not ready")
    return market_news_service


def lab_auto_trader_enabled() -> bool:
    return get_settings().enable_lab_auto_trader


def lab_backtest_enabled() -> bool:
    return get_settings().enable_lab_backtest


async def get_lab_trading_status() -> dict:
    """返回 lab BTC demo 状态；默认不初始化 demo 引擎或拉取外部报价。"""
    if not lab_auto_trader_enabled():
        return {
            "running": False,
            "enabled": False,
            "mode": "lab_disabled",
            "capital": 0.0,
            "position": 0.0,
            "total_value": 0.0,
            "pnl": 0.0,
            "pnl_pct": 0.0,
        }

    engine = get_trading_engine()
    # 优先复用 run loop 缓存的最新价格，避免每次状态请求都发起阻塞 HTTP 调用。
    current_price = getattr(engine, "last_price", None)
    if current_price is None:
        current_price = await asyncio.to_thread(engine.get_btc_price)
    total_value = engine.capital + (engine.position * current_price if engine.position > 0 else 0)
    return {
        "running": engine.running,
        "enabled": True,
        "mode": "btc_demo_lab",
        "capital": engine.capital,
        "position": engine.position,
        "total_value": total_value,
        "pnl": total_value - engine.initial_capital,
        "pnl_pct": ((total_value - engine.initial_capital) / engine.initial_capital) * 100,
    }


def get_lab_trading_performance() -> dict:
    if not lab_auto_trader_enabled():
        return {
            "enabled": False,
            "mode": "lab_disabled",
            "total_trades": 0,
            "win_rate": 0,
            "trades": [],
        }

    engine = get_trading_engine()
    wins = sum(1 for trade in engine.trades if trade.get("pnl", 0) > 0)
    return {
        "enabled": True,
        "mode": "btc_demo_lab",
        "total_trades": len(engine.trades),
        "win_rate": wins / len(engine.trades) if engine.trades else 0,
        "trades": engine.trades[-20:],
    }


def get_portfolio_risk_snapshot() -> dict:
    """Return real portfolio risk state without substituting lab/demo balances."""
    return {
        "portfolio_status": "not_configured",
        "source": "portfolio_ledger",
        "net_exposure": None,
        "estimated_leverage": None,
        "total_value": None,
        "pnl": None,
        "pnl_pct": None,
        "notes": [PORTFOLIO_LEDGER_NOT_CONFIGURED_NOTE],
    }


def get_portfolio_alert_level(portfolio_risk: dict, critical_alerts: int, watch_condition: bool) -> str:
    if critical_alerts > 0:
        return "critical"
    if portfolio_risk["portfolio_status"] == "not_configured":
        return "not_configured"
    if watch_condition:
        return "watch"
    return "nominal"


def get_service_health() -> list[dict]:
    """返回当前 API 进程可见的服务健康状态。"""
    return [
        {
            "name": "market_discovery",
            "status": "running" if market_discovery is not None else "not_started",
        },
        {
            "name": "realtime_ingestor",
            "status": "running" if realtime_ingestor is not None else "not_started",
        },
        {
            "name": "feature_engine",
            "status": "running" if feature_engine is not None else "not_started",
        },
        {
            "name": "strategy_manager",
            "status": "running" if strategy_manager is not None else "not_started",
        },
        {
            "name": "basket_executor",
            "status": "running" if basket_executor is not None else "not_started",
        },
        {
            "name": "intent_execution_service",
            "status": "running" if intent_execution_service is not None else "not_started",
        },
        {
            "name": "pair_feature_engine",
            "status": "running" if pair_feature_engine is not None else "not_started",
        },
        {
            "name": "onchain_monitor",
            "status": "running" if onchain_monitor is not None else "not_started",
        },
        {
            "name": "simulation_service",
            "status": "running" if simulation_service is not None else "not_started",
        },
        {
            "name": "auto_trader_demo",
            "tier": "lab",
            "status": (
                "running"
                if lab_auto_trader_enabled() and trading_engine is not None and trading_engine.running
                else "disabled" if not lab_auto_trader_enabled() else "stopped"
            ),
        },
    ]


def require_strategy_manager() -> StrategyManagerService:
    if strategy_manager is None:
        raise RuntimeError("strategy manager not ready")
    return strategy_manager


def require_basket_executor() -> BasketExecutor:
    if basket_executor is None:
        raise RuntimeError("basket executor not ready")
    return basket_executor


def require_intent_execution_service() -> IntentExecutionService:
    if intent_execution_service is None:
        raise RuntimeError("intent execution service not ready")
    return intent_execution_service


def require_pair_feature_engine() -> PairFeatureEngineService:
    if pair_feature_engine is None:
        raise RuntimeError("pair feature engine not ready")
    return pair_feature_engine


def require_onchain_monitor() -> OnchainMonitorService:
    if onchain_monitor is None:
        raise RuntimeError("onchain monitor not ready")
    return onchain_monitor


def require_simulation_service() -> SimulationService:
    if simulation_service is None:
        raise HTTPException(status_code=503, detail="Simulation service not ready")
    return simulation_service


def build_quote_fetcher(left: InstrumentRef, right: InstrumentRef):
    def build_client(instrument: InstrumentRef):
        if instrument.venue == ExecutionVenue.BINANCE:
            return BinanceClient(paper_trading=True)
        if instrument.venue == ExecutionVenue.HYPERLIQUID:
            return HyperliquidClient()
        raise ValueError(f"Unsupported venue: {instrument.venue}")

    # 客户端只构建一次并复用（内部使用共享的模块级 AsyncClient 连接池）。
    left_client = build_client(left)
    right_client = build_client(right)

    async def fetch_quotes() -> dict:
        def first_price(level) -> float:
            if isinstance(level, dict):
                return float(level.get("px") or level.get("price") or 0.0)
            if isinstance(level, (list, tuple)) and level:
                return float(level[0])
            return 0.0

        def extract_quote(orderbook: dict, venue: ExecutionVenue) -> dict:
            if venue == ExecutionVenue.HYPERLIQUID:
                levels = orderbook.get("levels") or []
                bid_levels = levels[0] if len(levels) > 0 else []
                ask_levels = levels[1] if len(levels) > 1 else []
                return {
                    "bid": first_price(bid_levels[0]) if bid_levels else 0.0,
                    "ask": first_price(ask_levels[0]) if ask_levels else 0.0,
                }

            bids = orderbook.get("bids") or []
            asks = orderbook.get("asks") or []
            return {
                "bid": first_price(bids[0]) if bids else 0.0,
                "ask": first_price(asks[0]) if asks else 0.0,
            }

        # 两腿并发抓取，复用共享连接池，不阻塞事件循环。
        left_orderbook, right_orderbook = await asyncio.gather(
            left_client.get_orderbook_async(left.symbol),
            right_client.get_orderbook_async(right.symbol),
        )
        left_orderbook = left_orderbook or {}
        right_orderbook = right_orderbook or {}
        return {
            "left": extract_quote(left_orderbook, left.venue),
            "right": extract_quote(right_orderbook, right.venue),
        }

    return fetch_quotes


def load_pair_definitions() -> list[PairDefinition]:
    if not PAIR_UNIVERSE_PATH.exists():
        return []

    with open(PAIR_UNIVERSE_PATH, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    definitions: list[PairDefinition] = []
    for pair in raw.get("pairs", []):
        left = InstrumentRef(
            venue=ExecutionVenue(str(pair["left"]["venue"])),
            symbol=str(pair["left"]["symbol"]),
        )
        right = InstrumentRef(
            venue=ExecutionVenue(str(pair["right"]["venue"])),
            symbol=str(pair["right"]["symbol"]),
        )
        definitions.append(
            PairDefinition(
                pair_id=str(pair["pair_id"]),
                left=left,
                right=right,
                fetch_quotes=build_quote_fetcher(left, right),
            )
        )

    return definitions


async def collect_dashboard_markets(limit: int = 36) -> list[dict]:
    """统一聚合市场与特征。"""
    if not market_discovery or not feature_engine:
        return []

    markets = await market_discovery.get_markets(limit=limit)
    items: list[dict] = []

    for market in markets:
        features = feature_engine.get_features(market.market_id)
        item = market.model_dump(mode="json")
        item["features"] = features.to_dict() if features else None
        items.append(item)

    return items


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global market_discovery, realtime_ingestor, feature_engine, strategy_manager, basket_executor, intent_execution_service, pair_feature_engine, onchain_monitor, altcoin_discovery, knowledge_ingestion, market_news_service, simulation_service

    logger.info("starting_polybob")

    # 创建共享 HTTP 客户端
    get_shared_http_client()

    # 启动服务
    market_discovery = MarketDiscoveryService()
    await market_discovery.start()

    # Optional raw order-book event log (default OFF via POLYBOB_BOOK_LOG_ENABLED;
    # raw event capture grows disk usage steadily).
    book_log = None
    if get_settings().polybob_book_log_enabled:
        try:
            from libs.db.book_log import BookEventLog

            book_log = BookEventLog(db_path=get_settings().polybob_db_path)
            logger.info("book_log_enabled", db_path=get_settings().polybob_db_path)
        except Exception as exc:
            logger.warning("book_log_unavailable", error=str(exc) or exc.__class__.__name__)

    realtime_ingestor = RealtimeIngestorService(book_log=book_log)
    await realtime_ingestor.start()

    feature_engine = FeatureEngineService()
    await feature_engine.start()

    # Fact-store persistence: bootstrap schema, then hand repositories to the
    # execution services. Failures degrade to memory-only operation.
    settings = get_settings()
    intent_repository: IntentRepository | None = None
    basket_repository: BasketRepository | None = None
    decision_repository: DecisionRepository | None = None
    try:
        db_path = fact_store.bootstrap(settings.polybob_db_path)
        intent_repository = IntentRepository(db_path)
        basket_repository = BasketRepository(db_path)
        decision_repository = DecisionRepository(db_path)
        logger.info("fact_store_ready", db_path=str(db_path))
    except Exception as exc:
        logger.warning(
            "fact_store_unavailable_running_memory_only",
            db_path=settings.polybob_db_path,
            error=str(exc) or exc.__class__.__name__,
        )

    basket_executor = BasketExecutor(
        basket_repository=basket_repository,
        executors={
            ExecutionVenue.BINANCE: ContractExecutor(
                BinanceClient(paper_trading=True),
                paper_trading=True,
                venue=ExecutionVenue.BINANCE.value,
            ),
            ExecutionVenue.HYPERLIQUID: ContractExecutor(
                HyperliquidClient(),
                paper_trading=True,
                venue=ExecutionVenue.HYPERLIQUID.value,
            ),
        }
    )
    intent_execution_service = IntentExecutionService(
        basket_executor,
        risk_checker=RiskChecker(max_position=3, max_order_size=0.05),
        max_open_intents=3,
        dedupe_window_seconds=30.0,
        intent_repository=intent_repository,
        decision_repository=decision_repository,
    )
    # Restore persisted execution state so a restart does not lose
    # intents/baskets; memory remains the hot cache for reads.
    await basket_executor.restore_state()
    await intent_execution_service.restore_state()

    pair_feature_engine = PairFeatureEngineService(
        pair_definitions=load_pair_definitions(),
        poll_interval_seconds=5.0,
    )
    await pair_feature_engine.start()
    onchain_monitor = OnchainMonitorService.from_yaml(ONCHAIN_WATCHLIST_PATH)
    await onchain_monitor.start()

    settings = get_settings()
    discovery_client = build_provider_http_client(
        proxy=settings.polybob_outbound_proxy or None,
        timeout_seconds=settings.discovery_request_timeout_seconds,
    )
    altcoin_discovery = AltcoinDiscoveryService(
        alpha_provider=BinanceAlphaProvider(
            discovery_client,
            base_url=settings.binance_alpha_api_url,
            market_base_url=settings.binance_alpha_market_api_url,
        ),
        futures_provider=BinanceFuturesProvider(
            discovery_client,
            base_url=settings.binance_futures_api_url,
            websocket_url=settings.binance_futures_ws_api_url,
            proxy=settings.polybob_outbound_proxy or None,
        ),
        min_coverage=settings.discovery_min_coverage,
        max_cashout_risk=settings.discovery_max_cashout_risk,
        min_pump_potential=settings.discovery_min_pump_potential,
        min_liquidity_usd=settings.discovery_min_liquidity_usd,
        min_volume_24h_usd=settings.discovery_min_volume_24h_usd,
        http_client=discovery_client,
    )
    await altcoin_discovery.start()

    knowledge_ingestion = KnowledgeIngestionService(
        store=KnowledgeStore(settings.polybob_db_path),
        sources=[
            StatementDogSource(
                authorized=settings.statementdog_crawl_authorized,
                lookback_months=settings.statementdog_lookback_months,
                concurrency=settings.statementdog_crawl_concurrency,
            )
        ],
        enabled=settings.knowledge_ingestion_enabled and settings.statementdog_crawl_authorized,
        interval_seconds=settings.statementdog_crawl_interval_seconds,
    )
    await knowledge_ingestion.start()

    # Market-news terminal (市场观察 real-time feed). Runs on its own short
    # cadence, independent of the hourly research crawl, and shares the same
    # knowledge store so news documents are queryable via document_type="news".
    market_news_categories = tuple(
        part.strip() for part in settings.market_news_categories.split(",") if part.strip()
    )
    market_news_service = KnowledgeIngestionService(
        store=KnowledgeStore(settings.polybob_db_path),
        sources=[
            FinnhubNewsSource(
                api_key=settings.finnhub_api_key,
                categories=market_news_categories or ("general", "crypto", "forex"),
                max_items_per_category=settings.market_news_max_items_per_category,
            )
        ],
        enabled=settings.market_news_enabled and bool(settings.finnhub_api_key),
        interval_seconds=settings.market_news_interval_seconds,
    )
    await market_news_service.start()

    strategy_manager = StrategyManagerService(
        dependencies={"intent_execution_service": intent_execution_service},
    )
    await strategy_manager.start()
    try:
        await strategy_manager.start_instance("spread_arbitrage_v1:default")
    except Exception as exc:
        logger.warning("failed_to_start_default_spread_arbitrage", error=str(exc))

    # Paper-trading simulation service: persistent runs + restart recovery.
    try:
        simulation_service = SimulationService(settings.polybob_db_path)
        await simulation_service.start()
        await simulation_service.restore_state()
    except Exception as exc:
        simulation_service = None
        logger.warning(
            "simulation_service_unavailable",
            error=str(exc) or exc.__class__.__name__,
        )

    logger.info("polybob_started")

    yield

    # 停止服务
    logger.info("stopping_polybob")

    if simulation_service:
        await simulation_service.stop()

    if feature_engine:
        await feature_engine.stop()

    if strategy_manager:
        await strategy_manager.stop()

    if pair_feature_engine:
        await pair_feature_engine.stop()

    if onchain_monitor:
        await onchain_monitor.stop()

    if altcoin_discovery:
        await altcoin_discovery.stop()

    if knowledge_ingestion:
        await knowledge_ingestion.stop()
    if market_news_service:
        await market_news_service.stop()

    if realtime_ingestor:
        await realtime_ingestor.stop()

    if market_discovery:
        await market_discovery.stop()

    await close_shared_http_client()

    logger.info("polybob_stopped")


# 创建 FastAPI 应用
app = FastAPI(
    title="PolyBob",
    description="Polymarket 实时分析与交易自动化系统",
    version="0.1.0",
    lifespan=lifespan,
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """健康检查"""
    return {
        "status": "ok",
        "service": "polybob",
        "version": "0.1.0",
    }


@app.get("/markets/watchlist")
async def get_watchlist():
    """获取 watchlist"""
    if not market_discovery:
        return {"error": "service not ready"}

    watchlist = await market_discovery.get_watchlist()
    return {
        "watchlist": watchlist,
        "count": len(watchlist),
    }


@app.get("/markets/{market_id}/features")
async def get_market_features(market_id: str):
    """获取市场特征"""
    if not feature_engine:
        return {"error": "service not ready"}

    features = feature_engine.get_features(market_id)
    if not features:
        return {"error": "market not found"}

    return features.to_dict()


@app.get("/api/dashboard/markets")
async def get_dashboard_markets():
    """返回 dashboard 聚合数据"""
    async def load() -> dict:
        items = await collect_dashboard_markets(limit=36)
        return {
            "markets": items,
            "count": len(items),
            "timestamp": datetime.utcnow().isoformat(),
        }

    return await cached_api_response("dashboard_markets", 5.0, load)


@app.get("/api/overview")
async def get_overview():
    """统一返回 overview 页面所需摘要。"""
    async def load() -> dict:
        manager = require_strategy_manager()
        templates = manager.list_templates()
        instances = manager.list_instances()
        intents = require_intent_execution_service().list_intents()
        onchain_summary = require_onchain_monitor().get_summary()
        market_items = await collect_dashboard_markets(limit=36)
        ready_count = sum(1 for item in market_items if item.get("features"))

        widest_spread = None
        spreads = [
            item["features"]["spread_bps"]
            for item in market_items
            if item.get("features") and isinstance(item["features"].get("spread_bps"), (int, float))
        ]
        if spreads:
            widest_spread = max(spreads)

        lab_status = await get_lab_trading_status()
        portfolio_risk = get_portfolio_risk_snapshot()

        return {
            "system": {
                "api_connected": True,
                "timestamp": datetime.utcnow().isoformat(),
                "mode": get_settings().product_mode,
                "operating_model": "personal_market_workbench",
            },
            "markets": {
                "tracked": len(market_items),
                "feature_ready": ready_count,
                "widest_spread_bps": widest_spread,
            },
            "strategy_center": {
                "template_count": len(templates),
                "active_instances": sum(1 for instance in instances if instance["status"] == "running"),
                "families": sorted({template["family"] for template in templates}),
                "intent_count": len(intents),
            },
            "execution": {
                "running": lab_status["running"],
                "enabled": lab_status["enabled"],
                "mode": lab_status["mode"],
                "portfolio_status": portfolio_risk["portfolio_status"],
                "total_value": portfolio_risk["total_value"],
                "pnl": portfolio_risk["pnl"],
                "pnl_pct": portfolio_risk["pnl_pct"],
            },
            "risk": {
                "portfolio_status": portfolio_risk["portfolio_status"],
                "net_exposure": portfolio_risk["net_exposure"],
                "estimated_leverage": portfolio_risk["estimated_leverage"],
                "alert_level": get_portfolio_alert_level(
                    portfolio_risk,
                    onchain_summary["critical_alerts"],
                    lab_status["running"] and abs(lab_status["position"]) > 0,
                ),
                "onchain_alert_count": onchain_summary["alert_count"],
                "critical_onchain_alerts": onchain_summary["critical_alerts"],
                "notes": portfolio_risk["notes"],
            },
        }

    return await cached_api_response("overview", 5.0, load)


@app.get("/api/markets/summary")
async def get_markets_summary():
    """Markets 页面摘要。"""
    async def load() -> dict:
        market_items = await collect_dashboard_markets(limit=50)
        return {
            "markets": market_items,
            "pairs": require_pair_feature_engine().list_snapshots(),
            "count": len(market_items),
            "timestamp": datetime.utcnow().isoformat(),
        }

    return await cached_api_response("markets_summary", 5.0, load)


@app.get("/api/polymarket/btc-5m/workbench")
async def get_btc_five_minute_workbench(slug: str | None = None):
    """BTC 5-minute Polymarket Up/Down 专用工作台。"""
    requested_slug = slug or build_btc_five_minute_slug(datetime.now().astimezone())

    async def load() -> dict:
        return await collect_btc_five_minute_workbench(slug=requested_slug)

    try:
        return await cached_api_response(
            f"btc_five_minute_workbench:{requested_slug}",
            # TTL 略大于 dashboard 轮询间隔，避免稳定轮询每次都打冷缓存。
            float(getattr(get_settings(), "polybob_btc_5m_poll_seconds", 3)) + 1.0,
            load,
        )
    except Exception as exc:
        error = str(exc) or exc.__class__.__name__
        btc_reference = await fetch_btc_reference_for_unavailable_workbench()
        return {
            "source": "unavailable",
            "action": "no_trade",
            "recommended_outcome": None,
            "reason_codes": ["WORKBENCH_UNAVAILABLE"],
            "slug": requested_slug,
            "btc_reference": btc_reference,
            "data_health": build_btc_five_minute_unavailable_health(exc, btc_reference),
            "error": error,
            "error_diagnosis": diagnose_btc_five_minute_error(exc),
            "timestamp": datetime.utcnow().isoformat(),
        }


async def fetch_btc_reference_for_unavailable_workbench() -> dict | None:
    try:
        reference = await _fetch_btc_reference_aggregate_safe(get_shared_http_client())
        return reference if reference.get("price") is not None else None
    except Exception:
        return None


def build_btc_five_minute_unavailable_health(exc: Exception, btc_reference: dict | None) -> dict:
    diagnosis = diagnose_btc_five_minute_error(exc)
    btc_reference_ok = bool(btc_reference and isinstance(btc_reference.get("price"), (int, float)))
    return {
        "polymarket_market": {
            "status": "unavailable",
            "provider": diagnosis.get("provider") or "Polymarket Gamma",
            "message": str(exc) or exc.__class__.__name__,
            "action": diagnosis.get("user_action"),
            "endpoint": diagnosis.get("endpoint"),
        },
        "polymarket_orderbook": {
            "status": "unavailable",
            "provider": "Polymarket CLOB",
            "message": "Order book was not requested because the active BTC 5m market could not be resolved.",
            "action": "先恢复 Polymarket Gamma 市场元数据；没有真实 token id 时不请求 CLOB 盘口，也不生成假盘口。",
            "endpoint": None,
        },
        "btc_reference": {
            "status": "ok" if btc_reference_ok else "unavailable",
            "provider": str(btc_reference.get("source")) if btc_reference_ok else "Binance / OKX / Coinbase",
            "message": (
                f"BTC reference available from {btc_reference.get('source')}."
                if btc_reference_ok
                else "No BTC reference source returned a valid price."
            ),
            "action": None if btc_reference_ok else "检查本机到 Binance / OKX / Coinbase 的网络或代理链路。",
            "endpoint": None,
        },
        "target_price": {
            "status": "unavailable",
            "provider": "Polymarket event/page",
            "message": "Target price is unavailable because the active BTC 5m market could not be resolved.",
            "action": "等待 Polymarket Gamma 或页面目标价恢复。",
            "endpoint": None,
        },
    }


def build_btc_five_minute_success_health(snapshot: dict) -> dict:
    up = snapshot.get("outcomes", {}).get("UP", {}) if isinstance(snapshot.get("outcomes"), dict) else {}
    down = snapshot.get("outcomes", {}).get("DOWN", {}) if isinstance(snapshot.get("outcomes"), dict) else {}
    both_books = bool(up.get("is_real_orderbook") and down.get("is_real_orderbook"))
    complete_books = bool(
        both_books
        and isinstance(up.get("best_bid"), (int, float))
        and isinstance(up.get("best_ask"), (int, float))
        and isinstance(down.get("best_bid"), (int, float))
        and isinstance(down.get("best_ask"), (int, float))
    )
    btc_reference = snapshot.get("btc_reference") if isinstance(snapshot.get("btc_reference"), dict) else None
    btc_reference_ok = bool(btc_reference and isinstance(btc_reference.get("price"), (int, float)))
    target = snapshot.get("target_price") if isinstance(snapshot.get("target_price"), dict) else None
    target_ok = bool(target and isinstance(target.get("price"), (int, float)))
    orderbook_status = "ok" if complete_books else "degraded" if both_books else "unavailable"
    orderbook_message = (
        "UP and DOWN executable order books loaded."
        if complete_books
        else "CLOB returned real levels, but at least one side is missing bid or ask depth."
        if both_books
        else "One or both CLOB order books are unavailable."
    )
    return {
        "polymarket_market": {
            "status": "ok",
            "provider": "Polymarket Gamma",
            "message": "Active BTC 5m market resolved.",
            "action": None,
            "endpoint": None,
        },
        "polymarket_orderbook": {
            "status": orderbook_status,
            "provider": "Polymarket CLOB",
            "message": orderbook_message,
            "action": (
                None
                if complete_books
                else "保持 no-trade；等待双边 bid/ask 恢复后再计算入场价。"
                if both_books
                else "检查 CLOB /book 接口和 token id。"
            ),
            "endpoint": None,
        },
        "btc_reference": {
            "status": "ok" if btc_reference_ok else "unavailable",
            "provider": str(btc_reference.get("source")) if btc_reference_ok else "Binance / OKX / Coinbase",
            "message": "BTC reference available." if btc_reference_ok else "No BTC reference source returned a valid price.",
            "action": None if btc_reference_ok else "检查本机到 BTC 行情源的网络或代理链路。",
            "endpoint": None,
        },
        "target_price": {
            "status": "ok" if target_ok else "unavailable",
            "provider": str(target.get("source")) if target_ok else "Polymarket event/page",
            "message": "Target price available." if target_ok else "Target price unavailable.",
            "action": None if target_ok else "检查 Gamma eventMetadata 或 Polymarket 页面目标价解析。",
            "endpoint": None,
        },
    }


def diagnose_btc_five_minute_error(exc: Exception) -> dict[str, Any]:
    """Classify BTC 5m data failures so the UI can show where the problem likely is."""
    technical_detail = str(exc) or exc.__class__.__name__
    endpoint = _exception_endpoint(exc)
    provider = _provider_from_endpoint(endpoint)
    base = {
        "category": "unknown",
        "responsibility": "unknown",
        "provider": provider,
        "endpoint": endpoint,
        "retryable": True,
        "likely_cause": "暂时无法判断具体失败来源，可能是外部数据源、网络链路或本地服务内部错误。",
        "user_action": "稍后重试；如果持续出现，把这里的 technical_detail 发出来继续排查。",
        "technical_detail": technical_detail,
    }

    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return {
            **base,
            "category": "network_timeout",
            "responsibility": "local_network_or_provider_path",
            "likely_cause": "请求外部数据源超时。可能是你的本机网络、代理、DNS 到该服务的链路问题，也可能是对方服务响应过慢。",
            "user_action": "先检查本机网络/代理/VPN/DNS；同时可直接访问对应 endpoint 验证是否能连通。",
        }

    if "503 Service Unavailable" in technical_detail:
        return {
            **base,
            "category": "provider_status",
            "responsibility": "external_provider",
            "likely_cause": f"{provider or '外部数据源'} 返回 503，说明对方服务或边缘节点当前不可用，不是 PolyBob 前端计算错误。",
            "user_action": "等待外部服务恢复；可以用 curl 直接访问 endpoint 复核。系统会保持 no-trade，不使用假盘口。",
        }

    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 429:
            return {
                **base,
                "category": "provider_rate_limit",
                "responsibility": "external_provider",
                "likely_cause": f"{provider or '外部数据源'} 返回 429，说明免费接口或当前 IP 触发了限流。",
                "user_action": "降低刷新频率，等待限流窗口恢复；如果经常出现，需要做本地缓存或多数据源配额调度。",
            }
        if status_code >= 500:
            return {
                **base,
                "category": "provider_status",
                "responsibility": "external_provider",
                "likely_cause": f"{provider or '外部数据源'} 返回 {status_code}，更像是对方服务不可用或临时故障，不是前端 UI 算错。",
                "user_action": "等待外部服务恢复；可以用 curl 直接访问 endpoint 复核。系统会保持 no-trade，不使用假盘口。",
            }
        return {
            **base,
            "category": "provider_request_rejected",
            "responsibility": "request_or_provider_policy",
            "retryable": False,
            "likely_cause": f"{provider or '外部数据源'} 返回 {status_code}，请求被拒绝，可能是参数、权限、地区或接口策略问题。",
            "user_action": "检查 endpoint、请求参数、接口文档和地区/权限限制。",
        }

    if isinstance(exc, httpx.TransportError):
        return {
            **base,
            "category": "network_connection",
            "responsibility": "local_network_or_provider_path",
            "likely_cause": "连接外部数据源失败。常见原因是本机网络、代理/VPN、DNS、SSL 握手、公司/地区网络限制，或对方边缘节点不可达。",
            "user_action": "检查本机网络、代理/VPN、DNS 和系统时间；再用 curl 直接访问 endpoint 做链路验证。",
        }

    if isinstance(exc, ValueError):
        return {
            **base,
            "category": "data_contract",
            "responsibility": "external_provider_schema_or_parser",
            "retryable": False,
            "likely_cause": "外部数据返回结构与 PolyBob 预期不一致，可能是市场未开放、接口字段变化或解析规则需要更新。",
            "user_action": "保留 no-trade；需要查看原始 API 响应并更新解析规则。",
        }

    return base


def _exception_endpoint(exc: Exception) -> str | None:
    request = getattr(exc, "request", None)
    url = getattr(request, "url", None)
    return str(url) if url else None


def _provider_from_endpoint(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    host = urlparse(endpoint).netloc.lower()
    if "gamma-api.polymarket.com" in host:
        return "Polymarket Gamma"
    if "clob.polymarket.com" in host:
        return "Polymarket CLOB"
    if "binance.com" in host:
        return "Binance Futures"
    return host or None


async def collect_btc_five_minute_workbench(slug: str | None = None) -> dict:
    """从 Gamma + CLOB + BTC reference 构建 BTC 5m 工作台快照。"""
    settings = get_settings()
    now = datetime.now().astimezone()
    slug = slug or build_btc_five_minute_slug(now)

    client = get_shared_http_client()

    async def load_market() -> dict:
        return await fetch_btc_five_minute_gamma_market(
            client,
            gamma_base_url=settings.polymarket_gamma_api_url,
            slug=slug,
        )

    market = await cached_api_response(
        f"btc_five_minute_gamma_market:{slug}",
        60.0,
        load_market,
    )
    tokens = map_outcome_tokens(market)

    up_response, down_response, btc_reference, page_target = await asyncio.gather(
        client.get(
            f"{settings.polymarket_clob_rest_url}/book",
            params={"token_id": tokens["UP"]},
            timeout=httpx.Timeout(4.0, connect=2.0),
        ),
        client.get(
            f"{settings.polymarket_clob_rest_url}/book",
            params={"token_id": tokens["DOWN"]},
            timeout=httpx.Timeout(4.0, connect=2.0),
        ),
        _fetch_btc_reference_aggregate_safe(client),
        _fetch_btc_five_minute_page_target_price_safe(client, slug),
    )
    up_response.raise_for_status()
    down_response.raise_for_status()

    received_at = datetime.now().astimezone()
    snapshot_market = dict(market)
    if page_target:
        snapshot_market["polymarketPageTargetPrice"] = page_target
    snapshot = build_workbench_snapshot(
        market=snapshot_market,
        up_book=normalize_book(tokens["UP"], up_response.json(), received_at),
        down_book=normalize_book(tokens["DOWN"], down_response.json(), received_at),
        btc_reference=btc_reference,
        now=received_at,
        config=BtcFiveMinuteConfig(),
    )
    snapshot["data_health"] = build_btc_five_minute_success_health(snapshot)
    return snapshot


async def fetch_btc_five_minute_gamma_market(
    client: httpx.AsyncClient,
    *,
    gamma_base_url: str,
    slug: str,
) -> dict:
    """优先用 event slug，因为它包含 eventMetadata.priceToBeat。"""
    async def fetch_event() -> Any:
        response = await client.get(f"{gamma_base_url}/events/slug/{slug}")
        response.raise_for_status()
        return response.json()

    async def fetch_markets() -> Any:
        response = await client.get(f"{gamma_base_url}/markets", params={"slug": slug})
        response.raise_for_status()
        return response.json()

    event_result, markets_result = await asyncio.gather(
        fetch_event(),
        fetch_markets(),
        return_exceptions=True,
    )

    if not isinstance(event_result, Exception):
        try:
            return _select_btc_five_minute_market(event_result)
        except ValueError:
            pass

    if not isinstance(markets_result, Exception):
        if not isinstance(markets_result, list) or not markets_result:
            raise ValueError("BTC 5m Gamma market not found")
        return _select_btc_five_minute_market({"markets": markets_result})

    if isinstance(markets_result, Exception):
        raise markets_result
    if isinstance(event_result, Exception):
        raise event_result
    raise ValueError("BTC 5m Gamma market not found")


def _btc_five_minute_window_iso(slug: str) -> tuple[str, str]:
    window_start = _btc_five_minute_slug_timestamp(slug)
    start_iso = datetime.fromtimestamp(window_start, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = datetime.fromtimestamp(window_start + 300, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return start_iso, end_iso


async def fetch_btc_five_minute_api_target_price(
    client: httpx.AsyncClient,
    *,
    slug: str,
) -> dict:
    """Read the target price from Polymarket's crypto-price JSON API.

    This is the same endpoint the event page calls client-side and is far more
    reliable than scraping the dehydrated page state, which only intermittently
    embeds the live window. ``openPrice`` is the window's "price to beat".
    """
    start_iso, end_iso = _btc_five_minute_window_iso(slug)
    response = await client.get(
        "https://polymarket.com/api/crypto/crypto-price",
        params={
            "symbol": "BTC",
            "eventStartTime": start_iso,
            "variant": "fiveminute",
            "endDate": end_iso,
        },
        headers={"User-Agent": "Mozilla/5.0 PolyBob/0.1"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("openPrice") is None:
        raise ValueError("Polymarket crypto-price API returned no openPrice")
    return {
        "source": "polymarket_crypto_price_api",
        "price": float(payload["openPrice"]),
        "field": "crypto-price.openPrice",
    }


async def fetch_btc_five_minute_page_target_price(
    client: httpx.AsyncClient,
    *,
    slug: str,
) -> dict:
    """Fallback: read the Polymarket page's dehydrated crypto-prices openPrice."""
    start_iso, end_iso = _btc_five_minute_window_iso(slug)
    response = await client.get(
        f"https://polymarket.com/event/{slug}",
        headers={"User-Agent": "Mozilla/5.0 PolyBob/0.1"},
    )
    response.raise_for_status()
    price = _extract_btc_five_minute_page_target_price(response.text, start_iso, end_iso)
    return {
        "source": "polymarket_page_crypto_prices",
        "price": price,
        "field": "crypto-prices.openPrice",
    }


async def _fetch_btc_five_minute_page_target_price_safe(
    client: httpx.AsyncClient,
    slug: str,
) -> dict | None:
    async def load() -> dict:
        # Prefer the JSON API; fall back to the page scrape if it is unavailable.
        try:
            return await fetch_btc_five_minute_api_target_price(client, slug=slug)
        except Exception as api_exc:
            logger.info(
                "btc_five_minute_target_price_api_fallback",
                slug=slug,
                error=str(api_exc) or api_exc.__class__.__name__,
            )
            return await fetch_btc_five_minute_page_target_price(client, slug=slug)

    try:
        return await cached_api_response(f"btc_five_minute_page_target:{slug}", 20.0, load)
    except Exception as exc:
        logger.warning(
            "btc_five_minute_target_price_unavailable",
            slug=slug,
            error=str(exc) or exc.__class__.__name__,
        )
        return None


def _extract_btc_five_minute_page_target_price(html: str, start_iso: str, end_iso: str) -> float:
    # Polymarket dehydrates the React Query cache into the page as a JSON string,
    # so every quote may arrive backslash-escaped (\") rather than literal (").
    # ``q`` matches a quote in either form so the parser survives both encodings.
    q = r'\\?"'
    start = re.escape(start_iso)
    end = re.escape(end_iso)
    pattern = re.compile(
        rf'{q}state{q}:\{{{q}data{q}:\{{{q}openPrice{q}:(?P<open>[0-9]+(?:\.[0-9]+)?),'
        rf'{q}closePrice{q}:(?:null|[0-9]+(?:\.[0-9]+)?)\}}'
        rf'.{{0,1200}}?{q}queryKey{q}:\[{q}crypto-prices{q},{q}price{q},{q}BTC{q},'
        rf'{q}{start}{q},{q}fiveminute{q},{q}{end}{q}\]',
        re.DOTALL,
    )
    match = pattern.search(html)
    if not match:
        raise ValueError("Polymarket page crypto-prices target price not found")
    return float(match.group("open"))


def _btc_five_minute_slug_timestamp(slug: str) -> int:
    match = re.fullmatch(r"btc-updown-5m-(\d+)", slug)
    if not match:
        raise ValueError("Invalid BTC 5m Polymarket slug")
    return int(match.group(1))


def _select_btc_five_minute_market(event_payload: Any) -> dict:
    markets = event_payload.get("markets") if isinstance(event_payload, dict) else None
    event_metadata = event_payload.get("eventMetadata") if isinstance(event_payload, dict) else None
    if not isinstance(markets, list) or not markets:
        raise ValueError("BTC 5m Gamma event has no markets")
    for market in markets:
        if not isinstance(market, dict):
            continue
        if bool(market.get("active", False)) and not bool(market.get("closed", False)):
            selected = dict(market)
            if event_metadata is not None and "eventMetadata" not in selected:
                selected["eventMetadata"] = event_metadata
            return selected
    raise ValueError("BTC 5m Gamma event has no active market")


async def fetch_btc_reference_aggregate(client: httpx.AsyncClient, *, now: datetime | None = None) -> dict:
    received_at = now.astimezone(timezone.utc) if now else None
    source_results = await asyncio.gather(
        _fetch_btc_reference_source(
            client,
            source="binance_futures",
            symbol="BTCUSDT",
            url="https://fapi.binance.com/fapi/v1/ticker/price",
            params={"symbol": "BTCUSDT"},
            parser=_parse_binance_futures_ticker,
            received_at=received_at,
        ),
        _fetch_btc_reference_source(
            client,
            source="okx_swap",
            symbol="BTC-USDT-SWAP",
            url="https://www.okx.com/api/v5/market/ticker",
            params={"instId": "BTC-USDT-SWAP"},
            headers={"User-Agent": "PolyBob/0.1"},
            parser=_parse_okx_ticker,
            received_at=received_at,
        ),
        _fetch_btc_reference_source(
            client,
            source="coinbase_spot",
            symbol="BTC-USD",
            url="https://api.exchange.coinbase.com/products/BTC-USD/ticker",
            headers={"User-Agent": "PolyBob/0.1"},
            parser=_parse_coinbase_ticker,
            received_at=received_at,
        ),
    )
    sources = [_classify_btc_reference_outlier(source, source_results) for source in source_results]
    selected = _select_btc_reference_source(sources)
    aggregate_received_at = datetime.now(timezone.utc).isoformat()
    if selected is None:
        return {
            "source": "unavailable",
            "symbol": "BTCUSDT",
            "price": None,
            "timestamp": aggregate_received_at,
            "received_at": aggregate_received_at,
            "latency_quality": "unavailable",
            "sources": sources,
        }
    selected["selected"] = True
    return {
        "source": selected["source"],
        "symbol": selected["symbol"],
        "price": selected["price"],
        "timestamp": selected.get("provider_timestamp") or selected["received_at"],
        "received_at": selected["received_at"],
        "provider_timestamp": selected.get("provider_timestamp"),
        "round_trip_ms": selected["round_trip_ms"],
        "staleness_ms": selected.get("staleness_ms"),
        "latency_quality": selected["latency_quality"],
        "sources": sources,
    }


async def _fetch_btc_reference_aggregate_safe(client: httpx.AsyncClient) -> dict:
    async def load() -> dict:
        return await fetch_btc_reference_aggregate(client)

    try:
        return await cached_api_response("btc_reference_aggregate", 1.0, load)
    except Exception as exc:
        return {
            "source": "unavailable",
            "symbol": "BTCUSDT",
            "price": None,
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(exc) or exc.__class__.__name__,
            "latency_quality": "unavailable",
            "sources": [],
        }


async def _fetch_btc_reference_source(
    client: httpx.AsyncClient,
    *,
    source: str,
    symbol: str,
    url: str,
    parser: Callable[[Any], tuple[float, datetime | None]],
    received_at: datetime | None,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    started = time.perf_counter()
    try:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        round_trip_ms = max(0, int((time.perf_counter() - started) * 1000))
        completed_at = received_at or datetime.now(timezone.utc)
        price, provider_timestamp = parser(response.json())
        provider_timestamp = provider_timestamp.astimezone(timezone.utc) if provider_timestamp else None
        staleness_ms = (
            max(0, int((completed_at - provider_timestamp).total_seconds() * 1000))
            if provider_timestamp
            else None
        )
        return {
            "source": source,
            "symbol": symbol,
            "status": "ok",
            "selected": False,
            "price": price,
            "provider_timestamp": provider_timestamp.isoformat() if provider_timestamp else None,
            "received_at": completed_at.isoformat(),
            "round_trip_ms": round_trip_ms,
            "staleness_ms": staleness_ms,
            "latency_quality": "provider_timestamp" if provider_timestamp else "transport_only",
        }
    except Exception as exc:
        return {
            "source": source,
            "symbol": symbol,
            "status": "error",
            "selected": False,
            "price": None,
            "provider_timestamp": None,
            "received_at": (received_at or datetime.now(timezone.utc)).isoformat(),
            "round_trip_ms": max(0, int((time.perf_counter() - started) * 1000)),
            "staleness_ms": None,
            "latency_quality": "unavailable",
            "error": str(exc) or exc.__class__.__name__,
        }


def _parse_binance_futures_ticker(payload: Any) -> tuple[float, datetime | None]:
    price = float(payload["price"])
    timestamp = _timestamp_ms_to_datetime(payload.get("time"))
    return price, timestamp


def _parse_okx_ticker(payload: Any) -> tuple[float, datetime | None]:
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("OKX ticker payload missing data")
    item = data[0]
    return float(item["last"]), _timestamp_ms_to_datetime(item.get("ts"))


def _parse_coinbase_ticker(payload: Any) -> tuple[float, datetime | None]:
    provider_timestamp = None
    raw_time = payload.get("time")
    if raw_time:
        provider_timestamp = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
    return float(payload["price"]), provider_timestamp


def _timestamp_ms_to_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)


def _classify_btc_reference_outlier(source: dict, all_sources: list[dict]) -> dict:
    if source.get("status") != "ok" or not isinstance(source.get("price"), (int, float)):
        return source
    valid_prices = [
        item["price"]
        for item in all_sources
        if item.get("status") == "ok" and isinstance(item.get("price"), (int, float))
    ]
    if len(valid_prices) < 2:
        return source
    if len(valid_prices) == 2:
        low, high = sorted(valid_prices)
        if low > 0 and (high - low) / low > 0.01 and source["price"] == high:
            return {**source, "status": "outlier", "selected": False}
        return source
    sorted_prices = sorted(valid_prices)
    midpoint = len(sorted_prices) // 2
    median = (
        sorted_prices[midpoint]
        if len(sorted_prices) % 2 == 1
        else (sorted_prices[midpoint - 1] + sorted_prices[midpoint]) / 2
    )
    if median > 0 and abs(source["price"] - median) / median > 0.01:
        return {**source, "status": "outlier", "selected": False}
    return source


def _select_btc_reference_source(sources: list[dict]) -> dict | None:
    candidates = [
        source
        for source in sources
        if source.get("status") == "ok" and isinstance(source.get("price"), (int, float))
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda source: (
            0 if source.get("latency_quality") == "provider_timestamp" else 1,
            source.get("staleness_ms") if source.get("staleness_ms") is not None else 10**9,
            source.get("round_trip_ms") if source.get("round_trip_ms") is not None else 10**9,
        ),
    )


@app.get("/api/pairs/snapshots")
async def get_pair_snapshots():
    """Pair snapshots 列表。"""
    snapshots = require_pair_feature_engine().list_snapshots()
    return {
        "snapshots": snapshots,
        "count": len(snapshots),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/pairs/universe")
async def get_pair_universe():
    """Pair universe 配置。"""
    pairs = require_pair_feature_engine().list_pairs()
    return {
        "pairs": pairs,
        "count": len(pairs),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/onchain/watchlists")
async def get_onchain_watchlists():
    """链上重点地址 watchlist。"""
    async def load() -> dict:
        watches = require_onchain_monitor().list_watch_addresses()
        return {
            "watchlists": watches,
            "count": len(watches),
            "timestamp": datetime.utcnow().isoformat(),
        }

    return await cached_api_response("onchain_watchlists", 30.0, load)


@app.get("/api/crypto/altcoin-discovery")
async def get_altcoin_discovery():
    snapshot = await require_altcoin_discovery().get_snapshot()
    if snapshot.status == "unavailable":
        return JSONResponse(
            status_code=503,
            content=jsonable_encoder(snapshot.model_dump(mode="json")),
        )
    return _altcoin_discovery_list_payload(snapshot)


def _altcoin_discovery_list_payload(snapshot: DiscoverySnapshot) -> dict[str, Any]:
    payload = snapshot.model_dump(mode="json")
    for candidate in payload["candidates"]:
        candidate["evidence"] = []
        candidate["trade_plans"] = {}
        for score_group in ("pump_potential", "cashout_risk"):
            for score in candidate[score_group].values():
                score["contributions"] = _top_score_contributions(score.get("contributions"))
    return payload


def _top_score_contributions(contributions: Any, limit: int = 3) -> dict[str, float]:
    if not isinstance(contributions, dict):
        return {}
    ranked = sorted(
        (
            (str(name), float(value))
            for name, value in contributions.items()
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    return dict(ranked[:limit])


@app.get("/api/crypto/altcoin-discovery/status")
async def get_altcoin_discovery_status():
    return require_altcoin_discovery().get_status()


@app.get("/api/crypto/altcoin-discovery/{asset_id:path}")
async def get_altcoin_discovery_detail(asset_id: str):
    detail = await require_altcoin_discovery().get_detail(asset_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Altcoin discovery asset not found")
    return detail


@app.get("/api/knowledge/search")
async def search_knowledge(
    q: str = "",
    source: str | None = None,
    type: str | None = None,
    ticker: str | None = None,
    limit: int = 20,
):
    """检索本地研究知识库。"""
    service = require_knowledge_ingestion()
    results = service.search(
        query=q,
        source_id=source,
        document_type=type,
        ticker=ticker,
        limit=limit,
    )
    return {
        "count": len(results),
        "results": [serialize_knowledge_result(result) for result in results],
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/knowledge/recent")
async def get_recent_knowledge(source: str | None = None, limit: int = 20):
    """最近入库的知识文档。"""
    service = require_knowledge_ingestion()
    results = service.recent(source_id=source, limit=limit)
    return {
        "count": len(results),
        "results": [serialize_knowledge_result(result) for result in results],
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/knowledge/sources")
async def get_knowledge_sources():
    """各知识源最近一次抓取状态。"""
    service = require_knowledge_ingestion()
    statuses = service.source_statuses()
    return {
        "count": len(statuses),
        "sources": [serialize_source_status(status) for status in statuses],
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/api/knowledge/sources/{source_id}/refresh")
async def refresh_knowledge_source(source_id: str):
    """手动触发指定知识源刷新。"""
    service = require_knowledge_ingestion()
    try:
        return await service.refresh_source(source_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown knowledge source: {source_id}")


def _news_impacts(result: KnowledgeSearchResult) -> list[dict[str, Any]]:
    impacts = result.metadata.get("impacts")
    return impacts if isinstance(impacts, list) else []


def serialize_market_news(result: KnowledgeSearchResult) -> dict[str, Any]:
    """Flatten a stored news document into the terminal feed shape."""
    metadata = result.metadata or {}
    return {
        "document_id": result.document_id,
        "headline": result.title,
        "summary": result.summary,
        "url": result.url,
        "source": metadata.get("news_source") or result.source_id,
        "category": metadata.get("category"),
        "related": metadata.get("related") or [],
        "image": metadata.get("image") or "",
        "published_at": result.published_at.isoformat() if result.published_at else None,
        "captured_at": result.captured_at.isoformat(),
        "sentiment": metadata.get("sentiment", "neutral"),
        "analysis_engine": metadata.get("analysis_engine", "heuristic"),
        "impacts": _news_impacts(result),
    }


@app.get("/api/market-news")
async def get_market_news(asset_class: str | None = None, limit: int = 40):
    """实时市场新闻流 + 跨资产影响分析（股市 / 加密 / 黄金 / 外汇 / 利率 / 原油）。

    ``asset_class`` 可选，用于只看对某一资产类别有影响的新闻。
    """
    service = require_market_news()
    if asset_class and asset_class not in ASSET_CLASSES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown asset_class '{asset_class}'. Valid: {', '.join(ASSET_CLASSES)}",
        )

    def load() -> dict:
        # Over-fetch then filter by asset class in Python (impacts live in
        # metadata, not a queryable column).
        raw = service.search(document_type="news", limit=max(limit * 3, limit))
        items: list[dict[str, Any]] = []
        for result in raw:
            serialized = serialize_market_news(result)
            if asset_class:
                if not any(impact.get("asset_class") == asset_class for impact in serialized["impacts"]):
                    continue
            items.append(serialized)
            if len(items) >= limit:
                break
        return {
            "count": len(items),
            "asset_classes": list(ASSET_CLASSES),
            "filter": asset_class,
            "items": items,
            "timestamp": datetime.utcnow().isoformat(),
        }

    return await cached_api_response(
        f"market_news:{asset_class or 'all'}:{limit}", 15.0, lambda: asyncio.to_thread(load)
    )


@app.get("/api/onchain/alerts")
async def get_onchain_alerts(limit: int = 50):
    """链上出货告警列表。"""
    async def load() -> dict:
        alerts = require_onchain_monitor().list_alerts(limit=limit)
        return {
            "alerts": alerts,
            "count": len(alerts),
            "timestamp": datetime.utcnow().isoformat(),
        }

    return await cached_api_response(f"onchain_alerts:{limit}", 5.0, load)


@app.get("/api/onchain/events")
async def get_onchain_events(limit: int = 50):
    """最近链上事件列表。"""
    async def load() -> dict:
        events = require_onchain_monitor().list_events(limit=limit)
        return {
            "events": events,
            "count": len(events),
            "timestamp": datetime.utcnow().isoformat(),
        }

    return await cached_api_response(f"onchain_events:{limit}", 5.0, load)


@app.get("/api/onchain/summary")
async def get_onchain_summary():
    """链上监控摘要。"""
    async def load() -> dict:
        summary = require_onchain_monitor().get_summary()
        summary["timestamp"] = datetime.utcnow().isoformat()
        return summary

    return await cached_api_response("onchain_summary", 5.0, load)


@app.post("/api/onchain/events")
async def ingest_onchain_event(payload: dict):
    """注入一条标准化链上事件。"""
    result = await require_onchain_monitor().ingest_event(payload)
    clear_api_response_cache()
    return result


@app.get("/api/strategies/catalog")
async def get_strategy_catalog():
    """策略模板目录。"""
    templates = require_strategy_manager().list_templates()
    return {
        "strategies": templates,
        "count": len(templates),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/strategies/instances")
async def get_strategy_instances():
    """策略实例列表。"""
    instances = require_strategy_manager().list_instances()
    return {
        "instances": instances,
        "count": len(instances),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/api/strategies/instances")
async def create_strategy_instance(payload: dict | None = None):
    """创建策略实例。"""
    payload = payload or {}
    manager = require_strategy_manager()
    instance = await manager.create_instance(
        strategy_id=str(payload["strategy_id"]),
        name=payload.get("name"),
        config=payload.get("config"),
        environment=str(payload.get("environment", "paper")),
    )
    clear_api_response_cache()
    return instance


@app.post("/api/strategies/instances/{instance_id}/start")
async def start_strategy_instance(instance_id: str):
    """启动策略实例。"""
    result = await require_strategy_manager().start_instance(instance_id)
    clear_api_response_cache()
    return result


@app.post("/api/strategies/instances/{instance_id}/stop")
async def stop_strategy_instance(instance_id: str):
    """停止策略实例。"""
    result = await require_strategy_manager().stop_instance(instance_id)
    clear_api_response_cache()
    return result


@app.delete("/api/strategies/instances/{instance_id}")
async def delete_strategy_instance(instance_id: str):
    """删除策略实例。"""
    await require_strategy_manager().delete_instance(instance_id)
    clear_api_response_cache()
    return {"status": "deleted", "instance_id": instance_id}


@app.get("/api/strategies/intents")
async def list_strategy_intents():
    """列出交易意图。"""
    intents = require_intent_execution_service().list_intents()
    return {
        "intents": intents,
        "count": len(intents),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/api/strategies/intents")
async def create_strategy_intent(payload: dict | None = None):
    """创建一个手动交易意图。"""
    payload = payload or {}
    result = await require_intent_execution_service().create_intent(
        strategy_id=str(payload.get("strategy_id", "manual_spread_arbitrage")),
        rationale=str(payload.get("rationale", "manual arbitrage intent")),
        expected_edge_bps=float(payload.get("expected_edge_bps", 0.0)),
        confidence=float(payload.get("confidence", 0.5)),
        legs=payload.get("legs") or [],
        metadata=payload.get("metadata"),
    )
    clear_api_response_cache()
    return result


@app.post("/api/strategies/intents/{intent_id}/submit")
async def submit_strategy_intent(intent_id: str):
    """提交意图到执行层。"""
    result = await require_intent_execution_service().submit_intent(intent_id)
    clear_api_response_cache()
    return result


@app.get("/api/execution/status")
async def get_execution_status():
    """执行台统一状态。"""
    async def load() -> dict:
        status = await get_trading_status()
        performance = await get_trading_performance()
        baskets = require_basket_executor().list_baskets()
        intents = require_intent_execution_service().list_intents()
        pair_snapshots = require_pair_feature_engine().list_snapshots()
        onchain_summary = require_onchain_monitor().get_summary()
        return {
            "status": status,
            "performance": performance,
            "intents": intents,
            "baskets": baskets,
            "pair_snapshots": pair_snapshots,
            "onchain_summary": onchain_summary,
            "timestamp": datetime.utcnow().isoformat(),
        }

    return await cached_api_response("execution_status", 3.0, load)


@app.post("/api/execution/baskets")
async def create_execution_basket(payload: dict | None = None):
    """创建并提交一个多腿 basket。"""
    payload = payload or {}
    legs = payload.get("legs") or []
    parent_intent_id = str(payload.get("parent_intent_id", "manual"))
    result = await require_basket_executor().submit_basket(legs=legs, parent_intent_id=parent_intent_id)
    clear_api_response_cache()
    return result


@app.get("/api/execution/baskets")
async def list_execution_baskets():
    """列出 basket 执行记录。"""
    baskets = require_basket_executor().list_baskets()
    return {
        "baskets": baskets,
        "count": len(baskets),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/api/execution/baskets/{basket_id}/cancel")
async def cancel_execution_basket(basket_id: str):
    """取消一个 basket。"""
    result = await require_basket_executor().cancel_basket(basket_id)
    clear_api_response_cache()
    return result


# ---------------------------------------------------------------------------
# Simulation (paper trading) endpoints
# ---------------------------------------------------------------------------


_PLACEHOLDER_MARKET_ID_RE = re.compile(r"^MARKET_ID_\d+$")


async def _live_market_universe(count: int) -> list[str]:
    """Real, feature-ready Polymarket market ids to fill preset universes.

    Preference order: markets that already have live features (so a preset run
    will actually receive snapshots and trade), then any discovered market as a
    fallback. Returns fewer than ``count`` — possibly empty — if discovery is
    not ready, in which case callers keep the placeholder ids.
    """
    if not market_discovery or not feature_engine or count <= 0:
        return []
    try:
        markets = await market_discovery.get_markets(limit=max(count * 3, 12))
    except Exception as exc:  # discovery not ready / transient failure
        logger.info("simulation_preset_universe_unavailable", error=str(exc) or exc.__class__.__name__)
        return []
    feature_ready = [m.market_id for m in markets if feature_engine.get_features(m.market_id)]
    pool = feature_ready or [m.market_id for m in markets]
    return [str(market_id) for market_id in pool[:count]]


async def _resolve_preset_universe(preset: dict) -> dict:
    """Swap ``MARKET_ID_*`` placeholders for real market ids so presets run as-is.

    Non-placeholder entries (e.g. ``binance:BTCUSDT`` pair legs) are left
    untouched. If no real markets are available the preset is returned
    unchanged so the operator still sees a usable (if manual) template.
    """
    universe = preset.get("suggested_universe") or []
    placeholder_count = sum(1 for item in universe if _PLACEHOLDER_MARKET_ID_RE.match(str(item)))
    if placeholder_count == 0:
        preset = dict(preset)
        preset["universe_source"] = "placeholder"
        return preset
    real_ids = iter(await _live_market_universe(placeholder_count))
    resolved: list[str] = []
    for item in universe:
        if _PLACEHOLDER_MARKET_ID_RE.match(str(item)):
            replacement = next(real_ids, None)
            if replacement is not None:
                resolved.append(replacement)
            else:
                resolved.append(item)  # keep placeholder if we ran out of real ids
        else:
            resolved.append(item)
    preset = dict(preset)
    preset["suggested_universe"] = resolved
    preset["universe_source"] = (
        "live_market_discovery" if resolved != universe else "placeholder"
    )
    return preset


@app.get("/api/simulation/presets")
async def list_simulation_presets():
    """预设的集中模拟测试类型；前端创建表单据此一键填充。

    ``suggested_universe`` 中的 ``MARKET_ID_*`` 占位符会在此处替换为
    market_discovery 提供的真实、已就绪的市场 id，让预设开箱即跑，无需手改。
    """
    from services.simulation import presets as sim_presets

    presets = [await _resolve_preset_universe(preset) for preset in sim_presets.list_presets()]
    return {"presets": presets}


@app.post("/api/simulation/runs")
async def create_simulation_run(payload: dict | None = None):
    """创建一个模拟盘 run（初始为 paused，需显式 start）。

    可传 ``preset_id`` 采用预设测试类型：预设提供 strategy_id / config /
    建议标的作为基底，请求里显式给出的字段覆盖预设。
    """
    from services.simulation import presets as sim_presets

    service = require_simulation_service()
    payload = payload or {}

    preset_id = payload.get("preset_id")
    try:
        if preset_id:
            requested_universe = [str(item) for item in (payload.get("universe") or [])] or None
            # No explicit universe: resolve the preset's placeholder ids to real
            # markets so an API-created preset run is runnable without hand-editing.
            if requested_universe is None:
                base_preset = sim_presets.get_preset(str(preset_id))
                if base_preset is not None:
                    resolved_universe = (await _resolve_preset_universe(base_preset)).get(
                        "suggested_universe", []
                    )
                    candidate = [str(item) for item in resolved_universe]
                    if candidate and not any(
                        _PLACEHOLDER_MARKET_ID_RE.match(item) for item in candidate
                    ):
                        requested_universe = candidate
            try:
                params = sim_presets.resolve_run_params(
                    str(preset_id),
                    name=payload.get("name"),
                    universe=requested_universe,
                    initial_capital=payload.get("initial_capital"),
                    config_overrides=payload.get("config") or None,
                )
            except KeyError:
                raise HTTPException(status_code=404, detail=f"Unknown preset: {preset_id}")
            run = await service.create_run(
                name=str(params["name"]),
                strategy_id=str(params["strategy_id"]),
                universe=[str(item) for item in params["universe"]],
                initial_capital=float(params["initial_capital"]),
                config=params["config"],
            )
        else:
            run = await service.create_run(
                name=str(payload.get("name") or "simulation run"),
                strategy_id=str(payload.get("strategy_id") or ""),
                universe=[str(item) for item in (payload.get("universe") or [])],
                initial_capital=float(payload.get("initial_capital") or 0.0),
                config=payload.get("config") or {},
            )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"run": run}


@app.get("/api/simulation/runs")
async def list_simulation_runs():
    """列出全部模拟盘 run 及概要指标。"""
    service = require_simulation_service()

    def load() -> list[dict]:
        runs = []
        for record in service.store.list_runs():
            item = record.to_dict()
            item["metrics"] = compute_run_metrics(service.store, record.run_id)
            runs.append(item)
        return runs

    return {"runs": await asyncio.to_thread(load)}


@app.get("/api/simulation/runs/{run_id}")
async def get_simulation_run(run_id: str):
    """单个 run 详情：指标、持仓、最近成交、下采样后的资金曲线。"""
    service = require_simulation_service()

    def load() -> dict | None:
        record = service.store.get_run(run_id)
        if record is None:
            return None
        points = service.store.list_equity_points(run_id)
        return {
            "run": record.to_dict(),
            "metrics": compute_run_metrics(service.store, run_id),
            "equity_curve": downsample_equity_curve(points, max_points=500),
            "positions": [p.to_dict() for p in service.store.list_positions(run_id)],
            "trades": [t.to_dict() for t in service.store.list_trades(run_id, limit=50)],
        }

    detail = await asyncio.to_thread(load)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Unknown simulation run: {run_id}")
    return detail


async def _simulation_transition(run_id: str, action: str) -> dict:
    service = require_simulation_service()
    try:
        if action == "start":
            run = await service.start_run(run_id)
        elif action == "pause":
            run = await service.pause_run(run_id)
        else:
            run = await service.stop_run(run_id)
    except UnknownRunError:
        raise HTTPException(status_code=404, detail=f"Unknown simulation run: {run_id}")
    except InvalidRunTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"run": run}


@app.post("/api/simulation/runs/{run_id}/start")
async def start_simulation_run(run_id: str):
    """启动（恢复）一个模拟盘 run。"""
    return await _simulation_transition(run_id, "start")


@app.post("/api/simulation/runs/{run_id}/pause")
async def pause_simulation_run(run_id: str):
    """暂停一个模拟盘 run。"""
    return await _simulation_transition(run_id, "pause")


@app.post("/api/simulation/runs/{run_id}/stop")
async def stop_simulation_run(run_id: str):
    """终止一个模拟盘 run（终态）。"""
    return await _simulation_transition(run_id, "stop")


@app.post("/api/simulation/runs/{run_id}/feedback")
async def apply_simulation_feedback(run_id: str):
    """把已平仓交易的真实结果回灌到策略权重（带防过拟合护栏）。"""
    service = require_simulation_service()
    try:
        result = await service.apply_feedback(run_id)
    except UnknownRunError:
        raise HTTPException(status_code=404, detail=f"Unknown simulation run: {run_id}")
    return {"run_id": run_id, **result}


@app.get("/api/risk/summary")
async def get_risk_summary():
    """风险与运维页基础摘要。"""
    async def load() -> dict:
        lab_status = await get_lab_trading_status()
        baskets = require_basket_executor().list_baskets()
        intents = require_intent_execution_service().list_intents()
        onchain_summary = require_onchain_monitor().get_summary()
        portfolio_risk = get_portfolio_risk_snapshot()
        residual_legs = sum(basket["metrics"]["residual_legs"] for basket in baskets)
        rejected_intents = len([intent for intent in intents if intent["status"] in {"risk_rejected", "duplicate_blocked"}])

        return {
            "alert_level": get_portfolio_alert_level(
                portfolio_risk,
                onchain_summary["critical_alerts"],
                lab_status["running"] and (abs(lab_status["position"]) > 0 or residual_legs > 0),
            ),
            "portfolio_status": portfolio_risk["portfolio_status"],
            "net_exposure": portfolio_risk["net_exposure"],
            "estimated_leverage": portfolio_risk["estimated_leverage"],
            "pnl": portfolio_risk["pnl"],
            "pnl_pct": portfolio_risk["pnl_pct"],
            "open_baskets": len(baskets),
            "open_intents": len([intent for intent in intents if intent["status"] in {"created", "submitted"}]),
            "rejected_intents": rejected_intents,
            "residual_legs": residual_legs,
            "onchain_alerts": onchain_summary["alert_count"],
            "critical_onchain_alerts": onchain_summary["critical_alerts"],
            "recent_cex_flow_usd": onchain_summary["recent_cex_flow_usd"],
            "services": get_service_health(),
            "notes": [
                *portfolio_risk["notes"],
                "Core mode is a personal market workbench: market discovery, signals, intents, risk notes, and paper baskets.",
                "BTC auto trader is a lab module and is disabled unless ENABLE_LAB_AUTO_TRADER=true.",
                "Pair exposure, hedge mismatch, and kill switch flows are not implemented yet.",
                "Onchain monitor currently relies on normalized event ingestion rather than a built-in indexer.",
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }

    return await cached_api_response("risk_summary", 3.0, load)


@app.get("/api/market/realtime")
async def get_realtime_market():
    """获取实时 BTC 行情。"""
    try:
        reference = await _fetch_btc_reference_aggregate_safe(get_shared_http_client())
        if reference.get("price") is None:
            return {"error": reference.get("error") or "BTC reference unavailable", "sources": reference.get("sources", [])}
        return reference
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/predict")
async def predict():
    """生成简化版 BTC 方向预测。"""
    try:
        response = await get_shared_http_client().get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId": "BTC-USDT-SWAP", "bar": "5m", "limit": 100},
            timeout=httpx.Timeout(8, connect=3),
        )
        response.raise_for_status()
        payload = response.json()
        klines = payload.get("data") or []

        prices = np.array([float(kline[4]) for kline in reversed(klines)])
        if prices.size < 20:
            raise ValueError("OKX candle payload does not contain enough 5m bars")
        current = prices[-1]
        sma5 = np.mean(prices[-5:])
        sma20 = np.mean(prices[-20:])

        deltas = np.diff(prices[-15:])
        gains = np.maximum(deltas, 0)
        losses = np.maximum(-deltas, 0)
        rsi = 100 - (100 / (1 + np.mean(gains) / (np.mean(losses) + 1e-10)))

        score = 0
        score += 1 if sma5 > sma20 else -1
        if rsi < 30:
            score += 1
        elif rsi > 70:
            score -= 1

        direction = "long" if score > 0 else "short"
        confidence = min(abs(score) / 2.0, 1.0)

        return {
            "direction": direction,
            "confidence": confidence,
            "price": float(current),
            "rsi": float(rsi),
            "sma5": float(sma5),
            "sma20": float(sma20),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/prediction/btc")
async def predict_btc_alias():
    """前端兼容的 BTC 预测端点。"""
    return await predict()


@app.post("/api/backtest")
async def backtest():
    """生成 dashboard 所需的回测摘要和权益曲线。"""
    if not lab_backtest_enabled():
        raise HTTPException(
            status_code=403,
            detail="Sample backtest is a lab module. Set ENABLE_LAB_BACKTEST=true to enable it.",
        )

    try:
        from libs.backtest.analyzer import BacktestAnalyzer
        from libs.backtest.engine import BacktestConfig, BacktestEngine

        data_file = Path(__file__).parent.parent.parent / "data" / "sample_backtest_data.json"
        if not data_file.exists():
            return {"error": "数据文件不存在"}

        with open(data_file, encoding="utf-8") as handle:
            market_data = json.load(handle)

        config = BacktestConfig(initial_capital=10000, fee_rate=0.001, slippage_bps=5.0)
        engine = BacktestEngine(config)
        analyzer = BacktestAnalyzer()

        for tick in market_data[:100]:
            timestamp = datetime.fromisoformat(tick["timestamp"])
            price = (tick.get("bid_price", 0) + tick.get("ask_price", 0)) / 2
            engine.update_equity(timestamp, {"BTC-USDT": price})

        report = analyzer.analyze(engine)
        equity_curve = [
            {"timestamp": timestamp.isoformat(), "value": float(value)}
            for timestamp, value in report.equity_curve
        ]

        return {
            "total_return": report.performance.total_return,
            "sharpe_ratio": report.performance.sharpe_ratio,
            "max_drawdown": report.performance.max_drawdown,
            "win_rate": report.performance.win_rate,
            "num_trades": report.performance.num_trades,
            "equity_curve": equity_curve,
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/backtest/results")
async def backtest_results_alias():
    """前端兼容的回测结果端点。"""
    return await backtest()


@app.post("/api/trading/start")
async def start_trading():
    """启动模拟交易引擎。"""
    if not lab_auto_trader_enabled():
        raise HTTPException(
            status_code=403,
            detail="BTC demo auto trader is a lab module. Set ENABLE_LAB_AUTO_TRADER=true to enable it.",
        )

    engine = get_trading_engine()
    if not engine.running:
        asyncio.create_task(engine.run())

    return {"status": "started", "timestamp": datetime.now().isoformat()}


@app.post("/api/trading/stop")
async def stop_trading():
    """停止模拟交易引擎。"""
    if not lab_auto_trader_enabled():
        return {"status": "disabled", "timestamp": datetime.now().isoformat()}

    engine = get_trading_engine()
    engine.stop()
    return {"status": "stopped", "timestamp": datetime.now().isoformat()}


@app.get("/api/trading/status")
async def get_trading_status():
    """返回模拟交易当前状态。"""
    return await get_lab_trading_status()


@app.get("/api/trading/performance")
async def get_trading_performance():
    """返回模拟交易绩效。"""
    return get_lab_trading_performance()


@app.websocket("/ws/market")
async def websocket_market(websocket: WebSocket):
    """向 dashboard 推送 BTC 实时价格。"""
    await websocket.accept()
    try:
        client = get_shared_http_client()
        while True:
            reference = await _fetch_btc_reference_aggregate_safe(client)

            await websocket.send_json(
                {
                    "price": reference.get("price"),
                    "source": reference.get("source"),
                    "staleness_ms": reference.get("staleness_ms"),
                    "round_trip_ms": reference.get("round_trip_ms"),
                    "timestamp": reference.get("timestamp") or datetime.now().isoformat(),
                    "sources": reference.get("sources", []),
                }
            )
            await asyncio.sleep(2)
    except Exception:
        return


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        "apps.api.main:app",
        host="0.0.0.0",
        port=settings.polybob_api_port,
        reload=settings.api_reload,
        log_level=settings.log_level.lower(),
    )
