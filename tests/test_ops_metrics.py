"""
P15 — Prometheus 指标与中间件测试。

覆盖:
- 一个请求会递增该路由的时延直方图 `_count`，`/metrics` 返回该 series；
- provider 调用计数、缓存命中/未命中计数出现在 `/metrics`；
- 事件循环滞后 gauge 存在；
- 事件总线队列深度 gauge 在抓取时被刷新。
"""
import asyncio

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from libs import metrics as ops_metrics


def _sample(name: str, labels: dict) -> float | None:
    return REGISTRY.get_sample_value(name, labels)


@pytest.mark.asyncio
async def test_request_increments_histogram_and_metrics_endpoint_returns_series():
    import apps.api.main as main

    with TestClient(main.app) as client:
        before = _sample(
            "polybob_http_request_duration_seconds_count",
            {"method": "GET", "route": "/", "status": "200"},
        ) or 0.0

        resp = client.get("/")
        assert resp.status_code == 200

        after = _sample(
            "polybob_http_request_duration_seconds_count",
            {"method": "GET", "route": "/", "status": "200"},
        )
        assert after is not None
        assert after == before + 1.0

        # /metrics 返回 prometheus 文本格式，且包含该路由的 series。
        metrics_resp = client.get("/metrics")
        assert metrics_resp.status_code == 200
        assert "text/plain" in metrics_resp.headers["content-type"]
        body = metrics_resp.text
        assert "polybob_http_request_duration_seconds_bucket" in body
        assert 'route="/"' in body
        # 本地计算段也被记录。
        assert "polybob_http_request_local_compute_seconds_count" in body


@pytest.mark.asyncio
async def test_provider_and_cache_counters_exposed():
    import apps.api.main as main

    ops_metrics.record_provider_call("polymarket", "ok")
    with ops_metrics.track_provider_wait("binance"):
        pass
    ops_metrics.record_cache_hit("orderbook")
    ops_metrics.record_cache_miss("orderbook")

    assert _sample(
        "polybob_provider_calls_total", {"provider": "polymarket", "outcome": "ok"}
    ) >= 1.0
    assert _sample(
        "polybob_provider_calls_total", {"provider": "binance", "outcome": "ok"}
    ) >= 1.0
    assert _sample(
        "polybob_cache_events_total", {"cache": "orderbook", "result": "hit"}
    ) >= 1.0
    assert _sample(
        "polybob_cache_events_total", {"cache": "orderbook", "result": "miss"}
    ) >= 1.0

    with TestClient(main.app) as client:
        body = client.get("/metrics").text
    assert "polybob_provider_calls_total" in body
    assert "polybob_cache_events_total" in body


@pytest.mark.asyncio
async def test_track_provider_wait_records_error_outcome():
    with pytest.raises(ValueError):
        with ops_metrics.track_provider_wait("flaky"):
            raise ValueError("boom")
    assert _sample(
        "polybob_provider_calls_total", {"provider": "flaky", "outcome": "error"}
    ) == 1.0


@pytest.mark.asyncio
async def test_event_loop_lag_monitor_updates_gauge():
    ops_metrics.stop_loop_lag_monitor()
    ops_metrics.ensure_loop_lag_monitor(interval=0.01)
    # 二次调用应幂等，不新建任务。
    ops_metrics.ensure_loop_lag_monitor(interval=0.01)
    await asyncio.sleep(0.05)
    value = _sample("polybob_event_loop_lag_seconds", {})
    assert value is not None
    assert value >= 0.0
    ops_metrics.stop_loop_lag_monitor()


@pytest.mark.asyncio
async def test_metrics_endpoint_reflects_event_bus_queue_depth():
    from libs.events import EventBus, Topics

    bus = EventBus(default_queue_maxsize=8)
    release = asyncio.Event()

    async def slow(_data):
        await release.wait()

    await bus.subscribe(Topics.ORDER_UPDATE, slow)
    for seq in range(3):
        await bus.publish(Topics.ORDER_UPDATE, {"order_id": "o", "seq": seq})

    # 抓取前主动刷新（避免依赖全局总线）。
    ops_metrics.collect_event_bus_metrics(bus)
    depth = _sample(
        "polybob_event_bus_queue_depth", {"topic": Topics.ORDER_UPDATE}
    )
    assert depth is not None
    assert depth >= 1.0

    release.set()
    await bus.close()
