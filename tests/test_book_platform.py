"""Order-book platform tests: reducer, raw event log, replay, ingestor wiring."""
import asyncio
from datetime import datetime

import pytest

from libs.db.book_log import BookEventLog
from libs.polymarket.book_state import (
    QUALITY_DEGRADED,
    QUALITY_NO_TIMESTAMP,
    QUALITY_OK,
    QUALITY_STALE,
    SEQUENCE_UNAVAILABLE,
    PolymarketBookReducer,
    parse_provider_timestamp,
)
from libs.polymarket.replay import replay_from_log
from libs.schemas import OrderbookTick
from modules.realtime_ingestor.service import RealtimeIngestorService

RECEIVE_TS = datetime(2026, 7, 21, 12, 0, 0)

SNAPSHOT = {
    "event_type": "book",
    "asset_id": "asset-1",
    "market": "market-1",
    "timestamp": "1753099200000",
    "hash": "abc123",
    "bids": [
        {"price": "0.40", "size": "100"},
        {"price": "0.45", "size": "50"},  # unsorted on purpose: best bid is 0.45
    ],
    "asks": [
        {"price": "0.60", "size": "80"},
        {"price": "0.55", "size": "30"},  # unsorted on purpose: best ask is 0.55
    ],
}


def make_reducer_with_snapshot() -> PolymarketBookReducer:
    reducer = PolymarketBookReducer()
    reducer.apply_snapshot(SNAPSHOT, receive_ts=RECEIVE_TS)
    return reducer


class TestReducer:
    def test_snapshot_sorted_bbo(self):
        reducer = make_reducer_with_snapshot()
        state = reducer.get_state("asset-1")
        assert state.bids == ((0.45, 50.0), (0.40, 100.0))  # descending
        assert state.asks == ((0.55, 30.0), (0.60, 80.0))  # ascending
        assert state.best_bid == (0.45, 50.0)
        assert state.best_ask == (0.55, 30.0)
        assert state.quality == QUALITY_OK
        assert state.market_id == "market-1"
        assert state.last_hash == "abc123"
        assert state.sequence_status == SEQUENCE_UNAVAILABLE

    def test_snapshot_merges_duplicate_levels(self):
        reducer = PolymarketBookReducer()
        state = reducer.apply_snapshot(
            {
                "asset_id": "a",
                "timestamp": "1753099200000",
                "bids": [{"price": "0.5", "size": "10"}, {"price": "0.5", "size": "5"}],
                "asks": [],
            },
            receive_ts=RECEIVE_TS,
        )
        assert state.bids == ((0.5, 15.0),)

    def test_price_change_updates_levels(self):
        reducer = make_reducer_with_snapshot()
        states = reducer.apply_price_change(
            {
                "event_type": "price_change",
                "asset_id": "asset-1",
                "market": "market-1",
                "timestamp": "1753099201000",
                "changes": [
                    {"price": "0.46", "side": "BUY", "size": "25"},  # new best bid
                    {"price": "0.55", "side": "SELL", "size": "40"},  # resize ask
                ],
            },
            receive_ts=RECEIVE_TS,
        )
        assert len(states) == 1
        state = states[0]
        assert state.best_bid == (0.46, 25.0)
        assert state.asks[0] == (0.55, 40.0)
        assert state.quality == QUALITY_OK
        assert state.has_snapshot is True

    def test_price_change_size_zero_removes_level(self):
        reducer = make_reducer_with_snapshot()
        (state,) = reducer.apply_price_change(
            {
                "asset_id": "asset-1",
                "timestamp": "1753099201000",
                "changes": [{"price": "0.45", "side": "BUY", "size": "0"}],
            },
            receive_ts=RECEIVE_TS,
        )
        assert all(price != 0.45 for price, _ in state.bids)
        assert state.best_bid == (0.40, 100.0)

    def test_crossed_book_marked_degraded(self):
        reducer = make_reducer_with_snapshot()
        (state,) = reducer.apply_price_change(
            {
                "asset_id": "asset-1",
                "timestamp": "1753099201000",
                "changes": [{"price": "0.55", "side": "BUY", "size": "10"}],
            },
            receive_ts=RECEIVE_TS,
        )
        assert state.is_crossed
        assert state.quality == QUALITY_DEGRADED

    def test_missing_timestamp_is_none_not_local_time(self):
        reducer = PolymarketBookReducer()
        snapshot = {k: v for k, v in SNAPSHOT.items() if k != "timestamp"}
        state = reducer.apply_snapshot(snapshot, receive_ts=RECEIVE_TS)
        assert state.source_ts is None  # never substituted with local time
        assert state.quality == QUALITY_NO_TIMESTAMP
        assert state.receive_ts == RECEIVE_TS

    def test_price_change_before_snapshot_marks_stale(self):
        reducer = PolymarketBookReducer()
        (state,) = reducer.apply_price_change(
            {
                "asset_id": "unknown-asset",
                "timestamp": "1753099201000",
                "changes": [{"price": "0.5", "side": "BUY", "size": "10"}],
            },
            receive_ts=RECEIVE_TS,
        )
        assert state.quality == QUALITY_STALE
        assert state.has_snapshot is False
        assert state.bids == ()  # never a guessed book

    def test_flat_and_multi_asset_price_change_shapes(self):
        reducer = make_reducer_with_snapshot()
        # flat single-change shape
        (state,) = reducer.apply_price_change(
            {"asset_id": "asset-1", "price": "0.44", "side": "BUY", "size": "7"},
            receive_ts=RECEIVE_TS,
        )
        assert (0.44, 7.0) in state.bids
        # price_changes list with per-entry asset ids
        states = reducer.apply_price_change(
            {
                "price_changes": [
                    {"asset_id": "asset-1", "price": "0.44", "side": "BUY", "size": "0"},
                    {"asset_id": "other", "price": "0.5", "side": "SELL", "size": "1"},
                ]
            },
            receive_ts=RECEIVE_TS,
        )
        by_asset = {s.asset_id: s for s in states}
        assert all(price != 0.44 for price, _ in by_asset["asset-1"].bids)
        assert by_asset["other"].quality == QUALITY_STALE  # no snapshot for it

    def test_parse_provider_timestamp_variants(self):
        assert parse_provider_timestamp(None) is None
        assert parse_provider_timestamp("") is None
        assert parse_provider_timestamp("not-a-time") is None
        assert parse_provider_timestamp("1753099200000") == datetime(2025, 7, 21, 12, 0, 0)
        assert parse_provider_timestamp("2026-07-21T12:00:00Z") == datetime(2026, 7, 21, 12, 0, 0)


class TestOrderbookTickCompat:
    def test_legacy_constructor_still_works(self):
        tick = OrderbookTick(
            market_id="m",
            timestamp=RECEIVE_TS,
            bid_price=0.4,
            ask_price=0.6,
            bid_size=1.0,
            ask_size=2.0,
        )
        assert tick.source_ts is None
        assert tick.receive_ts is None
        assert tick.quality == "ok"
        assert tick.sequence_status == "no_sequence_available"


class TestBookEventLog:
    def test_write_read_round_trip(self, tmp_path):
        log = BookEventLog(db_path=tmp_path / "book.sqlite3")
        log.log_event(
            asset_id="asset-1",
            event_type="book",
            payload=SNAPSHOT,
            receive_ts=RECEIVE_TS,
            source_ts=datetime(2026, 7, 21, 11, 59, 59),
            quality="ok",
        )
        log.log_event(
            asset_id="asset-1",
            event_type="price_change",
            payload={"asset_id": "asset-1", "changes": []},
            receive_ts=datetime(2026, 7, 21, 12, 0, 1),
            source_ts=None,
        )
        log.log_event(
            asset_id="other",
            event_type="book",
            payload={},
            receive_ts=RECEIVE_TS,
        )

        records = list(log.read_events("asset-1"))
        assert [r.event_type for r in records] == ["book", "price_change"]
        assert records[0].payload == SNAPSHOT
        assert records[0].source_ts == datetime(2026, 7, 21, 11, 59, 59)
        assert records[0].quality == "ok"
        assert records[1].source_ts is None
        assert records[1].receive_ts == datetime(2026, 7, 21, 12, 0, 1)

        # time-window filtering on receive_ts
        windowed = list(
            log.read_events(
                "asset-1",
                start=datetime(2026, 7, 21, 12, 0, 1),
                end=datetime(2026, 7, 21, 12, 0, 2),
            )
        )
        assert [r.event_type for r in windowed] == ["price_change"]

    def test_buffer_overflow_drops_oldest_and_counts(self, tmp_path):
        log = BookEventLog(db_path=tmp_path / "book.sqlite3", max_buffer_events=2)
        for i in range(5):
            log.log_event(
                asset_id="a",
                event_type="book",
                payload={"seq": i},
                receive_ts=RECEIVE_TS,
            )
        assert log.dropped_events == 3
        records = list(log.read_events("a"))
        assert [r.payload["seq"] for r in records] == [3, 4]

    async def test_background_flush_task(self, tmp_path):
        log = BookEventLog(
            db_path=tmp_path / "book.sqlite3",
            flush_max_events=1,
            flush_interval_seconds=0.05,
        )
        await log.start()
        log.log_event(
            asset_id="a", event_type="book", payload={}, receive_ts=RECEIVE_TS
        )
        await asyncio.sleep(0.2)
        await log.stop()
        assert len(list(log.read_events("a"))) == 1


class TestReplay:
    def _populate(self, tmp_path):
        log = BookEventLog(db_path=tmp_path / "book.sqlite3")
        log.log_event(
            asset_id="asset-1",
            event_type="book",
            payload=SNAPSHOT,
            receive_ts=RECEIVE_TS,
        )
        log.log_event(
            asset_id="asset-1",
            event_type="price_change",
            payload={
                "asset_id": "asset-1",
                "timestamp": "1753099201000",
                "changes": [
                    {"price": "0.46", "side": "BUY", "size": "25"},
                    {"price": "0.55", "side": "SELL", "size": "0"},
                ],
            },
            receive_ts=datetime(2026, 7, 21, 12, 0, 1),
        )
        log.log_event(  # trades are skipped by replay
            asset_id="asset-1",
            event_type="last_trade_price",
            payload={"price": "0.5", "size": "1"},
            receive_ts=datetime(2026, 7, 21, 12, 0, 2),
        )
        return log

    def test_replay_produces_expected_states(self, tmp_path):
        log = self._populate(tmp_path)
        states = replay_from_log(log, "asset-1")
        assert len(states) == 2  # snapshot + price_change (trade skipped)
        assert states[0].best_bid == (0.45, 50.0)
        assert states[1].best_bid == (0.46, 25.0)
        assert states[1].best_ask == (0.60, 80.0)  # 0.55 removed by size 0

    def test_replay_is_deterministic(self, tmp_path):
        log = self._populate(tmp_path)
        first = [s.book_hash() for s in replay_from_log(log, "asset-1")]
        second = [s.book_hash() for s in replay_from_log(log, "asset-1")]
        assert first == second
        assert len(first) == 2


class RecordingBus:
    def __init__(self):
        self.published = []

    async def publish(self, topic, payload):
        self.published.append((topic, payload))

    async def subscribe(self, topic, handler):
        return None


class TestIngestorIntegration:
    def _make_service(self, tmp_path=None):
        book_log = (
            BookEventLog(db_path=tmp_path / "book.sqlite3") if tmp_path is not None else None
        )
        service = RealtimeIngestorService(book_log=book_log)
        service.event_bus = RecordingBus()
        return service

    async def test_ingestor_logs_raw_events_when_configured(self, tmp_path):
        service = self._make_service(tmp_path)
        try:
            await service._handle_message(dict(SNAPSHOT))
            await service._handle_message(
                {
                    "event_type": "price_change",
                    "asset_id": "asset-1",
                    "market": "market-1",
                    "timestamp": "1753099201000",
                    "changes": [{"price": "0.46", "side": "BUY", "size": "25"}],
                }
            )
            records = list(service.book_log.read_events("asset-1"))
            assert [r.event_type for r in records] == ["book", "price_change"]
            assert records[0].payload["bids"] == SNAPSHOT["bids"]  # raw, pre-processing
        finally:
            await service.rest_client.close()

    async def test_ingestor_publishes_reduced_book_and_bbo(self, tmp_path):
        service = self._make_service(tmp_path)
        try:
            await service._handle_message(dict(SNAPSHOT))
            await service._handle_message(
                {
                    "event_type": "price_change",
                    "asset_id": "asset-1",
                    "market": "market-1",
                    "timestamp": "1753099201000",
                    "changes": [{"price": "0.46", "side": "BUY", "size": "25"}],
                }
            )
            ticks = [p for t, p in service.event_bus.published if isinstance(p, OrderbookTick)]
            assert len(ticks) == 2  # snapshot + incremental update
            assert ticks[0].bid_price == 0.45  # sorted best bid, not first level
            assert ticks[1].bid_price == 0.46
            assert ticks[1].quality == "ok"
            assert ticks[1].receive_ts is not None
            assert ticks[1].sequence_status == "no_sequence_available"
        finally:
            await service.rest_client.close()

    async def test_price_change_before_snapshot_requests_resync_not_publish(self):
        service = self._make_service()
        try:
            await service._handle_message(
                {
                    "event_type": "price_change",
                    "asset_id": "cold-asset",
                    "market": "market-x",
                    "changes": [{"price": "0.5", "side": "BUY", "size": "10"}],
                }
            )
            assert service.event_bus.published == []  # no garbage published
            assert "cold-asset" in service._resync_pending
            assert service._snapshot_queue.qsize() == 1
        finally:
            await service.rest_client.close()

    async def test_missing_timestamp_published_with_flag(self):
        service = self._make_service()
        try:
            snapshot = {k: v for k, v in SNAPSHOT.items() if k != "timestamp"}
            await service._handle_message(snapshot)
            (tick,) = [
                p for t, p in service.event_bus.published if isinstance(p, OrderbookTick)
            ]
            assert tick.source_ts is None
            assert tick.quality == "no_timestamp"
            assert tick.receive_ts is not None
            assert tick.timestamp == tick.receive_ts  # legacy field falls back explicitly
        finally:
            await service.rest_client.close()
