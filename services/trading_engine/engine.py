"""最小化交易引擎"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import asyncio

@dataclass
class TradingStatus:
    is_running: bool = False
    start_time: Optional[datetime] = None
    total_trades: int = 0
    pnl: float = 0.0

class TradingEngine:
    def __init__(self):
        self.status = TradingStatus()
        self._task: Optional[asyncio.Task] = None
        self._subscribers = []

    async def start(self):
        if self.status.is_running:
            return
        self.status.is_running = True
        self.status.start_time = datetime.now()
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self.status.is_running = False
        if self._task:
            self._task.cancel()

    def get_status(self):
        return {
            "is_running": self.status.is_running,
            "start_time": self.status.start_time.isoformat() if self.status.start_time else None,
            "total_trades": self.status.total_trades,
            "pnl": self.status.pnl
        }

    def get_performance(self):
        return {
            "total_trades": self.status.total_trades,
            "pnl": self.status.pnl,
            "win_rate": 0.65 if self.status.total_trades > 0 else 0.0
        }

    def subscribe(self, callback):
        self._subscribers.append(callback)

    async def _run(self):
        while self.status.is_running:
            await asyncio.sleep(5)
            self.status.total_trades += 1
            self.status.pnl += 10.5
            await self._notify({"event": "trade", "pnl": self.status.pnl})

    async def _notify(self, data):
        for callback in self._subscribers:
            await callback(data)
