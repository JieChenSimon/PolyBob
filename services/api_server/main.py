"""FastAPI应用入口"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import httpx
import numpy as np
from datetime import datetime
import json
app = FastAPI(title="PolyBob API")

# 延迟导入交易引擎
trading_engine = None

def get_trading_engine():
    global trading_engine
    if trading_engine is None:
        from services.auto_trader.engine import TradingEngine
        trading_engine = TradingEngine(10000)
    return trading_engine

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "service": "PolyBob API"}

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/api/market/realtime")
async def get_realtime_market():
    """获取实时BTC数据"""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://fapi.binance.com/fapi/v1/ticker/24hr",
                params={"symbol": "BTCUSDT"},
                timeout=10
            )
            data = r.json()
            return {
                "symbol": "BTCUSDT",
                "price": float(data["lastPrice"]),
                "change_24h": float(data["priceChangePercent"]),
                "volume_24h": float(data["volume"]),
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/predict")
async def predict():
    """调用预测逻辑"""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://fapi.binance.com/fapi/v1/klines",
                params={"symbol": "BTCUSDT", "interval": "5m", "limit": 100},
                timeout=10
            )
            klines = r.json()
            prices = np.array([float(k[4]) for k in klines])

        current = prices[-1]
        sma5 = np.mean(prices[-5:])
        sma20 = np.mean(prices[-20:])

        deltas = np.diff(prices[-15:])
        gains = np.maximum(deltas, 0)
        losses = np.maximum(-deltas, 0)
        rsi = 100 - (100 / (1 + np.mean(gains) / (np.mean(losses) + 1e-10)))

        score = 0
        if sma5 > sma20:
            score += 1
        else:
            score -= 1
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
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/backtest")
async def backtest():
    """调用回测逻辑"""
    try:
        from libs.backtest.engine import BacktestEngine, BacktestConfig
        from libs.backtest.analyzer import BacktestAnalyzer

        data_file = Path(__file__).parent.parent.parent / "data" / "sample_backtest_data.json"
        if not data_file.exists():
            return {"error": "数据文件不存在"}

        with open(data_file) as f:
            market_data = json.load(f)

        config = BacktestConfig(initial_capital=10000, fee_rate=0.001, slippage_bps=5.0)
        engine = BacktestEngine(config)
        analyzer = BacktestAnalyzer()

        for tick in market_data[:100]:
            timestamp = datetime.fromisoformat(tick['timestamp'])
            price = (tick.get('bid_price', 0) + tick.get('ask_price', 0)) / 2
            engine.update_equity(timestamp, {'BTC-USDT': price})

        report = analyzer.analyze(engine)

        return {
            "total_return": report.performance.total_return,
            "sharpe_ratio": report.performance.sharpe_ratio,
            "max_drawdown": report.performance.max_drawdown,
            "win_rate": report.performance.win_rate,
            "num_trades": report.performance.num_trades
        }
    except Exception as e:
        return {"error": str(e)}


@app.websocket("/ws/market")
async def websocket_market(websocket: WebSocket):
    """WebSocket推送实时价格"""
    await websocket.accept()
    try:
        while True:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://fapi.binance.com/fapi/v1/ticker/24hr",
                    params={"symbol": "BTCUSDT"},
                    timeout=10
                )
                data = r.json()
                await websocket.send_json({
                    "price": float(data["lastPrice"]),
                    "change_24h": float(data["priceChangePercent"]),
                    "timestamp": datetime.now().isoformat()
                })
            await asyncio.sleep(2)
    except Exception:
        pass

# 前端兼容端点
@app.post("/api/prediction/btc")
async def predict_btc_alias():
    """前端兼容的预测端点"""
    return await predict()

@app.get("/api/backtest/results")
async def backtest_results_alias():
    """前端兼容的回测端点"""
    return await backtest()

@app.post("/api/trading/start")
async def start_trading():
    """启动交易"""
    engine = get_trading_engine()
    asyncio.create_task(engine.run())
    return {"status": "started", "timestamp": datetime.now().isoformat()}

@app.post("/api/trading/stop")
async def stop_trading():
    """停止交易"""
    engine = get_trading_engine()
    engine.stop()
    return {"status": "stopped", "timestamp": datetime.now().isoformat()}

@app.get("/api/trading/status")
async def get_trading_status():
    """获取交易状态"""
    engine = get_trading_engine()
    total_value = engine.capital + (engine.position * engine.get_btc_price() if engine.position > 0 else 0)
    return {
        "running": engine.running,
        "capital": engine.capital,
        "position": engine.position,
        "total_value": total_value,
        "pnl": total_value - engine.initial_capital,
        "pnl_pct": ((total_value - engine.initial_capital) / engine.initial_capital) * 100
    }

@app.get("/api/trading/performance")
async def get_trading_performance():
    """获取交易绩效"""
    engine = get_trading_engine()
    wins = sum(1 for t in engine.trades if t.get('pnl', 0) > 0)
    return {
        "total_trades": len(engine.trades),
        "win_rate": wins / len(engine.trades) if engine.trades else 0,
        "trades": engine.trades[-20:]
    }
