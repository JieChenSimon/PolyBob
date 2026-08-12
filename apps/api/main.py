"""
PolyBob Main Application
"""
import asyncio
import json
import math
import re
from datetime import datetime
import logging
import sys
import structlog
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import numpy as np
import yaml

from libs.config import get_settings
from libs import metrics as ops_metrics
from libs.db import fact_store
from libs.db.repositories import BasketRepository, DecisionRepository, IntentRepository
from modules.risk_manager.risk_checker import PortfolioRiskChecker, RiskLimits
from modules.market_discovery import MarketDiscoveryService
from modules.realtime_ingestor import RealtimeIngestorService
from modules.feature_engine import FeatureEngineService
from modules.strategy_manager import StrategyManagerService
from modules.execution_engine.basket_executor import BasketExecutor
from modules.execution_engine.contract_executor import ContractExecutor
from modules.execution_engine.intent_execution_service import (
    IntentExecutionService,
    StrategyNotPromoted,
)
from modules.onchain_monitor import OnchainMonitorService
from modules.pair_feature_engine import PairDefinition, PairFeatureEngineService
from libs.crypto.binance_client import BinanceClient
from libs.crypto.discovery.providers.binance_alpha import BinanceAlphaProvider
from libs.crypto.discovery.providers.binance_futures import BinanceFuturesProvider
from libs.crypto.discovery.providers.http import build_provider_http_client
from libs.crypto.discovery.models import DiscoverySnapshot
from libs.crypto.discovery.service import AltcoinDiscoveryService
from libs.crypto.hyperliquid_client import HyperliquidClient
from libs.knowledge.impact import ASSET_CLASSES
from libs.quant.promotion import PromotionGate
from dataclasses import asdict
from libs.quant.promotion_registry import get_registry as get_promotion_registry
from libs.knowledge.models import KnowledgeSearchResult, SourceRunStatus
from libs.knowledge.sources.finnhub_news import FinnhubNewsSource
from libs.knowledge.sources.statementdog import StatementDogSource
from libs.knowledge.store import KnowledgeStore
from libs.schemas import ExecutionVenue, InstrumentRef
from modules.knowledge_ingestion import KnowledgeIngestionService
from modules.simulation import (
    InvalidRunTransitionError,
    SimulationService,
    UnknownRunError,
    downsample_equity_curve,
)
from modules.simulation.metrics import compute_run_metrics


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
# Shared plumbing lives in apps/api/deps.py so route modules can import it
# without importing the application. Re-exported here because callers and
# tests still reach for apps.api.main.<name>.
from apps.api import btc_five_minute as btc_workbench  # noqa: E402
from apps.api.btc_five_minute import router as btc_five_minute_router  # noqa: E402
from apps.api.edges_api import router as edges_router  # noqa: E402
from apps.api.journal_api import router as journal_router  # noqa: E402
from apps.api.portfolio_api import router as portfolio_router  # noqa: E402
from apps.api.dev_control_api import router as dev_control_router  # noqa: E402
from apps.api.forecasting_api import router as forecasting_router  # noqa: E402
from apps.api.verdict_api import router as verdict_router  # noqa: E402
from apps.api.deps import (  # noqa: E402
    cached_api_response,
    clear_api_response_cache,
    close_shared_http_client,
    get_shared_http_client,
    logger,
)


def get_trading_engine():
    """延迟初始化交易引擎，避免应用启动阶段额外阻塞。"""
    global trading_engine
    if trading_engine is None:
        from modules.auto_trader.engine import TradingEngine

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


# Live risk limits (quote-currency notional). Deliberately tighter than the
# generous PortfolioRiskChecker defaults so the live path enforces real caps.
LIVE_RISK_LIMITS = RiskLimits(
    max_gross_notional=250_000.0,
    max_market_notional=100_000.0,
    max_order_notional=50_000.0,
    max_basket_legs=8,
)


def live_position_notionals() -> dict[str, float] | None:
    """Per-market notional exposure from live (submitted/filled) basket legs.

    This is the only in-process record of what the live path has actually
    routed, so it is used as the position snapshot for pre-trade risk. It is
    fail-closed: if the executor state cannot be read, or a live leg carries no
    price to value it, this returns ``None`` and the PortfolioRiskChecker
    rejects the intent (unknown != safe). An empty dict means a flat book.
    """
    executor = basket_executor
    if executor is None:
        return None
    try:
        notionals: dict[str, float] = {}
        for basket in executor.baskets.values():
            for leg in basket.legs:
                status = str(getattr(leg.status, "value", leg.status)).lower()
                if "submit" not in status and "fill" not in status:
                    continue
                price = leg.limit_price
                if price is None:
                    # A live leg we can't value → exposure is unknown → fail closed.
                    return None
                notionals[leg.symbol] = (
                    notionals.get(leg.symbol, 0.0) + abs(leg.quantity) * abs(price)
                )
        return notionals
    except Exception as exc:
        logger.warning(
            "live_position_provider_failed",
            error=str(exc) or exc.__class__.__name__,
        )
        return None


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
    db_path = None
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
            # Hyperliquid execution is an unsigned stub (no real order path).
            # Marked unavailable so legs are never falsely reported as fills.
            ExecutionVenue.HYPERLIQUID: ContractExecutor(
                HyperliquidClient(),
                paper_trading=True,
                venue=ExecutionVenue.HYPERLIQUID.value,
                available=False,
            ),
        }
    )
    # Live pre-trade risk: the rigorous, fail-closed, notional-based portfolio
    # checker (same class the simulation service uses), with a real position
    # provider and audit logging. Missing/unvaluable positions -> reject.
    live_risk_checker = PortfolioRiskChecker(
        limits=LIVE_RISK_LIMITS,
        audit_db_path=db_path,
    )
    intent_execution_service = IntentExecutionService(
        basket_executor,
        risk_checker=live_risk_checker,
        position_provider=live_position_notionals,
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
        # 不自启任何策略。原来这里无条件拉起 spread_arbitrage_v1——它根本不在看板
        # 上,于是每次进程启动都有一个未验证的策略在无人值守地下单意图。
        #
        # 改成"只自启已晋级的"也不对:那会在 API 一启动就跑起真实的扫描循环(打 SEC /
        # OKX、按小时轮询)。开一个研究工作台不该等于开始交易。启动策略是一个显式动作,
        # 走 POST /api/strategies/instances/{id}/start。
        logger.info("strategy_autostart_disabled",
                    hint="start instances explicitly via the API")
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

# Prometheus 可观测性中间件（每路由时延直方图 + 在途请求 + 事件循环滞后）。
if ops_metrics.PrometheusMiddleware is not None:
    app.add_middleware(ops_metrics.PrometheusMiddleware)

# Route groups extracted from this file live in their own modules. Each owns its
# helpers, so the group can be read — and tested — without the other 60 routes.
app.include_router(btc_five_minute_router)
app.include_router(verdict_router)
app.include_router(edges_router)
app.include_router(journal_router)
app.include_router(portfolio_router)
app.include_router(dev_control_router)
app.include_router(forecasting_router)


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus 文本格式指标（路由时延、provider 调用、缓存命中、事件循环滞后、
    事件总线队列深度/丢弃/合并计数）。"""
    from fastapi.responses import Response

    return Response(
        content=ops_metrics.render_latest(),
        media_type=ops_metrics.CONTENT_TYPE,
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


@app.get("/api/market-sentiment")
async def get_market_sentiment():
    """全球指数 + A股风险偏好(涨停数)——市场情绪面板数据。

    实证说明:涨停数分层对龙虎榜反转策略的效果差异**不显著**(p=0.30),
    所以这里只作为环境展示,不作为策略开关——不夸大它的作用。
    """
    from libs.data import sentiment_indices as indices
    from libs.data import sentiment_sources as sentiment

    def load() -> dict:
        payload: dict[str, Any] = {"timestamp": datetime.utcnow().isoformat()}
        # Crowd-emotion gauges — the ones that pair with the confirmed
        # crowd-behaviour edges. Each degrades independently.
        gauges: list[dict[str, Any]] = []
        for fetch in (indices.fetch_crypto_fear_greed, indices.fetch_vix,
                      indices.fetch_gold_oil_ratio):
            try:
                gauges.append(fetch().to_dict())
            except indices.SentimentIndexUnavailable as exc:
                logger.info("sentiment_gauge_unavailable", error=str(exc))
        payload["gauges"] = gauges
        try:
            payload["global_indices"] = [
                {"key": q.key, "name": q.name, "price": q.price,
                 "change": q.change, "change_pct": q.change_pct}
                for q in sentiment.fetch_global_indices()
            ]
        except sentiment.SentimentUnavailable as exc:
            payload["global_indices"] = []
            payload["global_error"] = str(exc)
        try:
            appetite = sentiment.fetch_limit_up_count()
            payload["a_share_risk_appetite"] = {
                "date": appetite.date, "limit_up_count": appetite.limit_up_count,
                "regime": appetite.regime,
            }
        except sentiment.SentimentUnavailable as exc:
            payload["a_share_risk_appetite"] = None
            payload["a_share_error"] = str(exc)
        return payload

    return await cached_api_response("market_sentiment", 60.0, lambda: asyncio.to_thread(load))


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


@app.get("/api/strategies/promotion-board")
async def get_promotion_board():
    """策略晋级红绿榜：哪些策略在真实历史上过了 PromotionGate，才准上执行台。"""
    registry = get_promotion_registry()
    registry.reload()
    return {
        "require_strategy_promotion": get_settings().require_strategy_promotion,
        **registry.to_dict(),
        # 整条记录透出。原来只发 6 个字段,而前端要的 win_rate / mean_excess_pct /
        # t_stat / n / role 一个都不在里面——于是首页把胜率渲染成 NaN%、把收益渲染成
        # 一个编造的红色 0.00%,还把 role=avoid 的回避过滤器算进"已通过门禁"。
        # r.to_dict(), not asdict(r): the evidence age and expiry verdict are
        # computed properties (they depend on today), and asdict would drop them.
        "records": [r.to_dict() for r in registry.records()],
    }


@app.post("/api/strategies/intents")
async def create_strategy_intent(payload: dict | None = None):
    """创建一个手动交易意图。

    若开启 ``require_strategy_promotion``，只有过了 PromotionGate 的策略才能
    创建实盘意图（fail-closed）；未达标的一律拒绝，留在 lab。
    """
    payload = payload or {}
    strategy_id = str(payload.get("strategy_id") or "").strip()
    if not strategy_id:
        raise HTTPException(status_code=422, detail="strategy_id 必填")

    # expected_edge_bps 和 confidence 必须由调用方给出。原来它们默认 0.0 / 0.5,
    # 于是"没人告诉我这笔的预期收益"被写成"预期收益是 0",再原样落进 intent 和
    # decision 审计表,看起来像一个算出来的数字。
    for field in ("expected_edge_bps", "confidence"):
        if payload.get(field) is None:
            raise HTTPException(status_code=422, detail=f"{field} 必填，不接受默认值")

    # 门禁已下沉到 IntentExecutionService.create_intent(唯一收口点),
    # 这里只负责把它的异常翻成 HTTP 403。
    try:
        result = await require_intent_execution_service().create_intent(
            strategy_id=strategy_id,
            rationale=str(payload.get("rationale", "manual intent")),
            expected_edge_bps=float(payload["expected_edge_bps"]),
            confidence=float(payload["confidence"]),
            legs=payload.get("legs") or [],
            metadata=payload.get("metadata"),
        )
    except StrategyNotPromoted as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
    from modules.simulation import presets as sim_presets

    presets = [await _resolve_preset_universe(preset) for preset in sim_presets.list_presets()]
    return {"presets": presets}


@app.post("/api/simulation/runs")
async def create_simulation_run(payload: dict | None = None):
    """创建一个模拟盘 run（初始为 paused，需显式 start）。

    可传 ``preset_id`` 采用预设测试类型：预设提供 strategy_id / config /
    建议标的作为基底，请求里显式给出的字段覆盖预设。
    """
    from modules.simulation import presets as sim_presets

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


@app.get("/api/simulation/runs/{run_id}/promotion")
async def get_simulation_run_promotion(
    run_id: str,
    n_trials: int = 1,
    min_observations: int = 30,
    min_dsr: float = 0.95,
):
    """能否把这个模拟盘 run 提升为可信策略？

    用 Deflated Sharpe Ratio（多重检验校正）+ 最小样本量对 run 的资金曲线
    做门禁判定。``n_trials`` 应填此前尝试过的策略配置数量——试得越多，
    通过门槛越高。样本不足或 DSR 不达标都会明确拒绝（fail-closed）。
    """
    service = require_simulation_service()

    def load() -> dict | None:
        record = service.store.get_run(run_id)
        if record is None:
            return None
        points = service.store.list_equity_points(run_id)
        returns: list[float] = []
        for previous, current in zip(points, points[1:]):
            if previous.equity > 0:
                returns.append(current.equity / previous.equity - 1.0)
        gate = PromotionGate(
            n_trials=max(1, n_trials),
            min_dsr=min_dsr,
            min_observations=max(1, min_observations),
        )
        decision = gate.evaluate(returns)
        return {
            "run_id": run_id,
            "n_returns": len(returns),
            "n_trials": max(1, n_trials),
            "decision": decision.to_dict(),
            "timestamp": datetime.utcnow().isoformat(),
        }

    result = await asyncio.to_thread(load)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown simulation run: {run_id}")
    return result


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


@app.get("/api/research/experiments")
async def list_research_experiments(experiment: str | None = None, limit: int = 50):
    """列出实验注册表中的最近 run（可复现研究记录：参数 + 指标 + 版本）。

    每条记录携带 data/model/code 版本，使任一结论都能追溯到产生它的确切输入
    (P8b, satisfies the roadmap's "Traceable output" gate)。
    """
    service = require_simulation_service()

    def load() -> list[dict]:
        records = service.registry.list_runs(experiment, limit=max(1, min(limit, 500)))
        return [record.to_dict() for record in records]

    return {"experiments": await asyncio.to_thread(load)}


@app.get("/api/monitoring/drift")
async def get_drift_status():
    """概念漂移熔断器状态 (P8c)。

    比较各市场近端 mid 分布与其固定参考窗 (PSI + KS)；任一市场显著漂移
    (PSI >= 0.25) 时 ``halted`` 置真，下游可据此暂停或降险。样本不足的市场
    不参与判定 (fail-safe: 不因缺数据误熔断)。
    """
    if feature_engine is None:
        return {"available": False, "halted": False, "reason": "feature_engine not started"}
    monitor = feature_engine.drift_monitor
    status = monitor.status()
    return {"available": True, "should_halt": monitor.should_halt(), **status}


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
        reference = await btc_workbench._fetch_btc_reference_aggregate_safe(
            get_shared_http_client()
        )
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
