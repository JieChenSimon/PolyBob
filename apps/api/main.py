"""
PolyBob Main Application
"""
import asyncio
import json
from datetime import datetime
import logging
import sys
import structlog
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import httpx
import numpy as np
import yaml

from libs.config import get_settings
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
from libs.crypto.hyperliquid_client import HyperliquidClient
from libs.schemas import ExecutionVenue, InstrumentRef


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
trading_engine = None
PAIR_UNIVERSE_PATH = Path(__file__).parent.parent.parent / "config" / "pair_universe.yaml"
ONCHAIN_WATCHLIST_PATH = Path(__file__).parent.parent.parent / "config" / "onchain_watchlists.yaml"


def get_trading_engine():
    """延迟初始化交易引擎，避免应用启动阶段额外阻塞。"""
    global trading_engine
    if trading_engine is None:
        from services.auto_trader.engine import TradingEngine

        trading_engine = TradingEngine(10000)
    return trading_engine


def lab_auto_trader_enabled() -> bool:
    return get_settings().enable_lab_auto_trader


def get_lab_trading_status() -> dict:
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
    current_price = engine.get_btc_price()
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


def build_quote_fetcher(left: InstrumentRef, right: InstrumentRef):
    async def fetch_quotes() -> dict:
        def build_client(instrument: InstrumentRef):
            if instrument.venue == ExecutionVenue.BINANCE:
                return BinanceClient(paper_trading=True)
            if instrument.venue == ExecutionVenue.HYPERLIQUID:
                return HyperliquidClient()
            raise ValueError(f"Unsupported venue: {instrument.venue}")

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

        left_client = build_client(left)
        right_client = build_client(right)
        left_orderbook = left_client.get_orderbook(left.symbol) or {}
        right_orderbook = right_client.get_orderbook(right.symbol) or {}
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
    global market_discovery, realtime_ingestor, feature_engine, strategy_manager, basket_executor, intent_execution_service, pair_feature_engine, onchain_monitor

    logger.info("starting_polybob")

    # 启动服务
    market_discovery = MarketDiscoveryService()
    await market_discovery.start()

    realtime_ingestor = RealtimeIngestorService()
    await realtime_ingestor.start()

    feature_engine = FeatureEngineService()
    await feature_engine.start()

    basket_executor = BasketExecutor(
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
    )
    pair_feature_engine = PairFeatureEngineService(
        pair_definitions=load_pair_definitions(),
        poll_interval_seconds=5.0,
    )
    await pair_feature_engine.start()
    onchain_monitor = OnchainMonitorService.from_yaml(ONCHAIN_WATCHLIST_PATH)
    await onchain_monitor.start()

    strategy_manager = StrategyManagerService(
        dependencies={"intent_execution_service": intent_execution_service},
    )
    await strategy_manager.start()
    try:
        await strategy_manager.start_instance("spread_arbitrage_v1:default")
    except Exception as exc:
        logger.warning("failed_to_start_default_spread_arbitrage", error=str(exc))

    logger.info("polybob_started")

    yield

    # 停止服务
    logger.info("stopping_polybob")

    if feature_engine:
        await feature_engine.stop()

    if strategy_manager:
        await strategy_manager.stop()

    if pair_feature_engine:
        await pair_feature_engine.stop()

    if onchain_monitor:
        await onchain_monitor.stop()

    if realtime_ingestor:
        await realtime_ingestor.stop()

    if market_discovery:
        await market_discovery.stop()

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
    items = await collect_dashboard_markets(limit=36)

    return {
        "markets": items,
        "count": len(items),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/overview")
async def get_overview():
    """统一返回 overview 页面所需摘要。"""
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

    lab_status = get_lab_trading_status()

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
            "total_value": lab_status["total_value"],
            "pnl": lab_status["pnl"],
            "pnl_pct": lab_status["pnl_pct"],
        },
        "risk": {
            "net_exposure": lab_status["position"],
            "estimated_leverage": 0.0,
            "alert_level": (
                "watch"
                if lab_status["running"] and abs(lab_status["position"]) > 0
                else "nominal"
            ),
            "onchain_alert_count": onchain_summary["alert_count"],
            "critical_onchain_alerts": onchain_summary["critical_alerts"],
        },
    }


@app.get("/api/markets/summary")
async def get_markets_summary():
    """Markets 页面摘要。"""
    market_items = await collect_dashboard_markets(limit=50)
    return {
        "markets": market_items,
        "pairs": require_pair_feature_engine().list_snapshots(),
        "count": len(market_items),
        "timestamp": datetime.utcnow().isoformat(),
    }


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
    watches = require_onchain_monitor().list_watch_addresses()
    return {
        "watchlists": watches,
        "count": len(watches),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/onchain/alerts")
async def get_onchain_alerts(limit: int = 50):
    """链上出货告警列表。"""
    alerts = require_onchain_monitor().list_alerts(limit=limit)
    return {
        "alerts": alerts,
        "count": len(alerts),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/onchain/events")
async def get_onchain_events(limit: int = 50):
    """最近链上事件列表。"""
    events = require_onchain_monitor().list_events(limit=limit)
    return {
        "events": events,
        "count": len(events),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/onchain/summary")
async def get_onchain_summary():
    """链上监控摘要。"""
    summary = require_onchain_monitor().get_summary()
    summary["timestamp"] = datetime.utcnow().isoformat()
    return summary


@app.post("/api/onchain/events")
async def ingest_onchain_event(payload: dict):
    """注入一条标准化链上事件。"""
    return await require_onchain_monitor().ingest_event(payload)


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
    return instance


@app.post("/api/strategies/instances/{instance_id}/start")
async def start_strategy_instance(instance_id: str):
    """启动策略实例。"""
    return await require_strategy_manager().start_instance(instance_id)


@app.post("/api/strategies/instances/{instance_id}/stop")
async def stop_strategy_instance(instance_id: str):
    """停止策略实例。"""
    return await require_strategy_manager().stop_instance(instance_id)


@app.delete("/api/strategies/instances/{instance_id}")
async def delete_strategy_instance(instance_id: str):
    """删除策略实例。"""
    await require_strategy_manager().delete_instance(instance_id)
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
    return await require_intent_execution_service().create_intent(
        strategy_id=str(payload.get("strategy_id", "manual_spread_arbitrage")),
        rationale=str(payload.get("rationale", "manual arbitrage intent")),
        expected_edge_bps=float(payload.get("expected_edge_bps", 0.0)),
        confidence=float(payload.get("confidence", 0.5)),
        legs=payload.get("legs") or [],
        metadata=payload.get("metadata"),
    )


@app.post("/api/strategies/intents/{intent_id}/submit")
async def submit_strategy_intent(intent_id: str):
    """提交意图到执行层。"""
    return await require_intent_execution_service().submit_intent(intent_id)


@app.get("/api/execution/status")
async def get_execution_status():
    """执行台统一状态。"""
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


@app.post("/api/execution/baskets")
async def create_execution_basket(payload: dict | None = None):
    """创建并提交一个多腿 basket。"""
    payload = payload or {}
    legs = payload.get("legs") or []
    parent_intent_id = str(payload.get("parent_intent_id", "manual"))
    return await require_basket_executor().submit_basket(legs=legs, parent_intent_id=parent_intent_id)


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
    return await require_basket_executor().cancel_basket(basket_id)


@app.get("/api/risk/summary")
async def get_risk_summary():
    """风险与运维页基础摘要。"""
    lab_status = get_lab_trading_status()
    baskets = require_basket_executor().list_baskets()
    intents = require_intent_execution_service().list_intents()
    onchain_summary = require_onchain_monitor().get_summary()
    leverage = 0.0
    residual_legs = sum(basket["metrics"]["residual_legs"] for basket in baskets)
    rejected_intents = len([intent for intent in intents if intent["status"] in {"risk_rejected", "duplicate_blocked"}])

    return {
        "alert_level": (
            "critical"
            if onchain_summary["critical_alerts"] > 0
            else (
                "watch"
                if lab_status["running"] and (abs(lab_status["position"]) > 0 or residual_legs > 0)
                else "nominal"
            )
        ),
        "net_exposure": lab_status["position"],
        "estimated_leverage": leverage,
        "open_baskets": len(baskets),
        "open_intents": len([intent for intent in intents if intent["status"] in {"created", "submitted"}]),
        "rejected_intents": rejected_intents,
        "residual_legs": residual_legs,
        "onchain_alerts": onchain_summary["alert_count"],
        "critical_onchain_alerts": onchain_summary["critical_alerts"],
        "recent_cex_flow_usd": onchain_summary["recent_cex_flow_usd"],
        "services": get_service_health(),
        "notes": [
            "Core mode is a personal market workbench: market discovery, signals, intents, risk notes, and paper baskets.",
            "BTC auto trader is a lab module and is disabled unless ENABLE_LAB_AUTO_TRADER=true.",
            "Pair exposure, hedge mismatch, and kill switch flows are not implemented yet.",
            "Onchain monitor currently relies on normalized event ingestion rather than a built-in indexer.",
        ],
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/market/realtime")
async def get_realtime_market():
    """获取实时 BTC 行情。"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://fapi.binance.com/fapi/v1/ticker/24hr",
                params={"symbol": "BTCUSDT"},
                timeout=10,
            )
            data = response.json()

        return {
            "symbol": "BTCUSDT",
            "price": float(data["lastPrice"]),
            "change_24h": float(data["priceChangePercent"]),
            "volume_24h": float(data["volume"]),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/predict")
async def predict():
    """生成简化版 BTC 方向预测。"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://fapi.binance.com/fapi/v1/klines",
                params={"symbol": "BTCUSDT", "interval": "5m", "limit": 100},
                timeout=10,
            )
            klines = response.json()

        prices = np.array([float(kline[4]) for kline in klines])
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
    return get_lab_trading_status()


@app.get("/api/trading/performance")
async def get_trading_performance():
    """返回模拟交易绩效。"""
    return get_lab_trading_performance()


@app.websocket("/ws/market")
async def websocket_market(websocket: WebSocket):
    """向 dashboard 推送 BTC 实时价格。"""
    await websocket.accept()
    try:
        while True:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://fapi.binance.com/fapi/v1/ticker/24hr",
                    params={"symbol": "BTCUSDT"},
                    timeout=10,
                )
                data = response.json()

            await websocket.send_json(
                {
                    "price": float(data["lastPrice"]),
                    "change_24h": float(data["priceChangePercent"]),
                    "timestamp": datetime.now().isoformat(),
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
        port=8000,
        reload=settings.api_reload,
        log_level=settings.log_level.lower(),
    )
