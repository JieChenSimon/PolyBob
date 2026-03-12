"""
PolyBob Main Application
"""
import asyncio
from datetime import datetime
import logging
import signal
import sys
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from libs.config import get_settings
from services.market_discovery import MarketDiscoveryService
from services.realtime_ingestor import RealtimeIngestorService
from services.feature_engine import FeatureEngineService


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global market_discovery, realtime_ingestor, feature_engine

    logger.info("starting_polybob")

    # 启动服务
    market_discovery = MarketDiscoveryService()
    await market_discovery.start()

    realtime_ingestor = RealtimeIngestorService()
    await realtime_ingestor.start()

    feature_engine = FeatureEngineService()
    await feature_engine.start()

    logger.info("polybob_started")

    yield

    # 停止服务
    logger.info("stopping_polybob")

    if feature_engine:
        await feature_engine.stop()

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
    if not market_discovery or not feature_engine:
        return {"error": "service not ready"}

    markets = await market_discovery.get_markets(limit=36)
    items = []
    for market in markets:
        features = feature_engine.get_features(market.market_id)
        item = market.model_dump(mode="json")
        item["features"] = features.to_dict() if features else None
        items.append(item)

    return {
        "markets": items,
        "count": len(items),
        "timestamp": datetime.utcnow().isoformat(),
    }


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
