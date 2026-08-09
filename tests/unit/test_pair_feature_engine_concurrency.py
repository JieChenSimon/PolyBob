import asyncio
import threading
import time

from libs.schemas import ExecutionVenue, InstrumentRef
from modules.pair_feature_engine import PairDefinition, PairFeatureEngineService


def build_pair(left_fetch, right_fetch) -> PairDefinition:
    return PairDefinition(
        pair_id="btc_concurrency_test",
        left=InstrumentRef(venue=ExecutionVenue.BINANCE, symbol="BTCUSDT"),
        right=InstrumentRef(venue=ExecutionVenue.HYPERLIQUID, symbol="BTC"),
        fetch_left_quote=left_fetch,
        fetch_right_quote=right_fetch,
    )


def test_sync_quote_legs_start_concurrently():
    left_started = threading.Event()
    right_started = threading.Event()

    def fetch_left():
        left_started.set()
        assert right_started.wait(0.5)
        return {"bid": 65010.0, "ask": 65020.0}

    def fetch_right():
        right_started.set()
        assert left_started.wait(0.5)
        return {"bid": 64980.0, "ask": 64990.0}

    pair = build_pair(fetch_left, fetch_right)
    service = PairFeatureEngineService([pair])

    snapshot = asyncio.run(service._build_snapshot(pair))

    assert snapshot is not None
    assert left_started.is_set()
    assert right_started.is_set()


def test_slow_sync_quote_does_not_block_independent_async_task():
    slow_started = threading.Event()
    release_slow = threading.Event()

    def fetch_left():
        slow_started.set()
        assert release_slow.wait(1.0)
        return {"bid": 65010.0, "ask": 65020.0}

    def fetch_right():
        return {"bid": 64980.0, "ask": 64990.0}

    async def exercise():
        pair = build_pair(fetch_left, fetch_right)
        service = PairFeatureEngineService([pair])
        snapshot_task = asyncio.create_task(service._build_snapshot(pair))

        assert await asyncio.to_thread(slow_started.wait, 0.5)
        independent_task_ran = False

        async def independent_task():
            nonlocal independent_task_ran
            await asyncio.sleep(0)
            independent_task_ran = True

        await asyncio.wait_for(independent_task(), timeout=0.1)
        assert independent_task_ran
        release_slow.set()
        return await snapshot_task

    snapshot = asyncio.run(exercise())
    assert snapshot is not None


def test_async_fetcher_awaited_on_current_loop_without_nested_run():
    """异步 fetcher 直接在当前事件循环 await（不再嵌套 asyncio.run）。

    fetcher 内部的阻塞工作由 fetcher 自身通过 asyncio.to_thread 卸载。
    """
    loop_ids = []

    async def fetch_quotes():
        loop_ids.append(id(asyncio.get_running_loop()))
        await asyncio.to_thread(time.sleep, 0.15)
        return {
            "left": {"bid": 65010.0, "ask": 65020.0},
            "right": {"bid": 64980.0, "ask": 64990.0},
        }

    async def exercise():
        pair = PairDefinition(
            pair_id="btc_legacy_callback_test",
            left=InstrumentRef(venue=ExecutionVenue.BINANCE, symbol="BTCUSDT"),
            right=InstrumentRef(venue=ExecutionVenue.HYPERLIQUID, symbol="BTC"),
            fetch_quotes=fetch_quotes,
        )
        service = PairFeatureEngineService([pair])
        started_at = time.monotonic()
        snapshot_task = asyncio.create_task(service._build_snapshot(pair))
        await asyncio.sleep(0)
        independent_elapsed = time.monotonic() - started_at
        snapshot = await snapshot_task
        return independent_elapsed, snapshot, id(asyncio.get_running_loop())

    independent_elapsed, snapshot, outer_loop_id = asyncio.run(exercise())

    assert independent_elapsed < 0.05
    assert snapshot is not None
    # fetcher 必须运行在服务所在的同一个事件循环上（无嵌套新循环）。
    assert loop_ids == [outer_loop_id]


def test_poll_loop_processes_pairs_concurrently():
    """poll loop 并发处理多个 pair（受信号量限制），而非串行。"""
    barrier_started = []
    all_started = asyncio.Event()

    def make_fetcher(pair_index: int):
        async def fetch_quotes():
            barrier_started.append(pair_index)
            if len(barrier_started) >= 3:
                all_started.set()
            # 只有当三个 pair 同时在途时才会放行；串行实现会超时。
            await asyncio.wait_for(all_started.wait(), timeout=1.0)
            return {
                "left": {"bid": 65010.0, "ask": 65020.0},
                "right": {"bid": 64980.0, "ask": 64990.0},
            }

        return fetch_quotes

    pairs = [
        PairDefinition(
            pair_id=f"pair_{index}",
            left=InstrumentRef(venue=ExecutionVenue.BINANCE, symbol="BTCUSDT"),
            right=InstrumentRef(venue=ExecutionVenue.HYPERLIQUID, symbol="BTC"),
            fetch_quotes=make_fetcher(index),
        )
        for index in range(3)
    ]

    async def exercise():
        service = PairFeatureEngineService(pairs, poll_interval_seconds=60.0)
        await service.start()
        try:
            for _ in range(200):
                if len(service.snapshots) >= 3:
                    break
                await asyncio.sleep(0.01)
        finally:
            await service.stop()
        return dict(service.snapshots)

    snapshots = asyncio.run(exercise())
    assert set(snapshots) == {"pair_0", "pair_1", "pair_2"}
