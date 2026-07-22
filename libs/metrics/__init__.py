"""
Metrics - Prometheus 可观测性层

集中定义所有应用指标，避免重复注册（模块级定义 + import 缓存）。

导出内容:

- ``PrometheusMiddleware``: 记录每条路由的请求时延直方图（总时延 / 上游等待 /
  本地计算三段），并统计在途请求数。
- ``track_provider_wait`` / ``record_provider_call``: 记录外部 provider 调用次数与
  时延，同时把“上游等待”累加进当前请求的上下文，供中间件从总时延中扣除，得到本地
  计算耗时。
- ``record_cache_hit`` / ``record_cache_miss``: 缓存命中/未命中计数。
- 事件循环滞后 gauge（后台采样任务，惰性启动，无需改动 lifespan）。
- ``collect_event_bus_metrics``: 抓取时把事件总线的队列深度/丢弃/合并计数刷入 gauge。
- ``render_latest`` / ``CONTENT_TYPE``: 生成 prometheus 文本格式供 ``GET /metrics``。

参考: FastAPI + prometheus-client 中间件模式（按路由模板打标签控制基数、用
perf_counter、在 finally 中记录）；asyncio 事件循环滞后用 sleep-drift 采样。
"""
from __future__ import annotations

import asyncio
import contextvars
import time
from contextlib import contextmanager
from typing import Optional

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

CONTENT_TYPE = CONTENT_TYPE_LATEST

# SLO 感知的时延桶（秒）。
_LATENCY_BUCKETS = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)

# --------------------------------------------------------------------- 指标定义

HTTP_REQUEST_DURATION = Histogram(
    "polybob_http_request_duration_seconds",
    "HTTP request total latency by route template.",
    ("method", "route", "status"),
    buckets=_LATENCY_BUCKETS,
)

HTTP_REQUEST_UPSTREAM_WAIT = Histogram(
    "polybob_http_request_upstream_wait_seconds",
    "Time a request spent awaiting upstream/provider calls.",
    ("method", "route"),
    buckets=_LATENCY_BUCKETS,
)

HTTP_REQUEST_LOCAL_COMPUTE = Histogram(
    "polybob_http_request_local_compute_seconds",
    "Request time spent in local compute (total minus upstream wait).",
    ("method", "route"),
    buckets=_LATENCY_BUCKETS,
)

HTTP_REQUESTS_INFLIGHT = Gauge(
    "polybob_http_requests_inflight",
    "In-flight HTTP requests.",
)

PROVIDER_CALLS = Counter(
    "polybob_provider_calls",
    "External provider calls by provider and outcome.",
    ("provider", "outcome"),
)

PROVIDER_CALL_DURATION = Histogram(
    "polybob_provider_call_duration_seconds",
    "External provider call latency.",
    ("provider",),
    buckets=_LATENCY_BUCKETS,
)

CACHE_EVENTS = Counter(
    "polybob_cache_events",
    "Cache hit/miss events by cache name.",
    ("cache", "result"),
)

EVENT_LOOP_LAG = Gauge(
    "polybob_event_loop_lag_seconds",
    "Asyncio event-loop scheduling lag (sleep drift).",
)

EVENT_BUS_QUEUE_DEPTH = Gauge(
    "polybob_event_bus_queue_depth",
    "Current per-topic max subscriber queue depth on the event bus.",
    ("topic",),
)

EVENT_BUS_DROPPED = Gauge(
    "polybob_event_bus_dropped_total",
    "Per-topic dropped events on the event bus (lossy topics only).",
    ("topic",),
)

EVENT_BUS_COALESCED = Gauge(
    "polybob_event_bus_coalesced_total",
    "Per-topic coalesced events on the event bus (lossy topics only).",
    ("topic",),
)

# ---------------------------------------------------- 上游等待累加（每请求上下文）

# 当前请求内累计的上游等待时间（秒），由 provider 包装器累加、中间件读取后清零。
_upstream_wait_var: contextvars.ContextVar[float] = contextvars.ContextVar(
    "polybob_upstream_wait", default=0.0
)


def _add_upstream_wait(seconds: float) -> None:
    try:
        _upstream_wait_var.set(_upstream_wait_var.get() + seconds)
    except LookupError:  # pragma: no cover - default always present
        _upstream_wait_var.set(seconds)


@contextmanager
def track_provider_wait(provider: str):
    """记录一次 provider 调用的时延/结果，并把耗时累加进当前请求的上游等待。"""
    start = time.perf_counter()
    outcome = "ok"
    try:
        yield
    except Exception:
        outcome = "error"
        raise
    finally:
        elapsed = time.perf_counter() - start
        PROVIDER_CALL_DURATION.labels(provider).observe(elapsed)
        PROVIDER_CALLS.labels(provider, outcome).inc()
        _add_upstream_wait(elapsed)


def record_provider_call(provider: str, outcome: str = "ok", duration: Optional[float] = None) -> None:
    """直接记录一次 provider 调用（用于无法用上下文管理器包裹的场景）。"""
    PROVIDER_CALLS.labels(provider, outcome).inc()
    if duration is not None:
        PROVIDER_CALL_DURATION.labels(provider).observe(duration)
        _add_upstream_wait(duration)


def record_cache_hit(cache: str = "default") -> None:
    CACHE_EVENTS.labels(cache, "hit").inc()


def record_cache_miss(cache: str = "default") -> None:
    CACHE_EVENTS.labels(cache, "miss").inc()


# --------------------------------------------------------- 事件循环滞后采样任务

_loop_lag_task: Optional["asyncio.Task"] = None
_loop_lag_loop: Optional[asyncio.AbstractEventLoop] = None


async def _sample_loop_lag(interval: float = 0.25) -> None:
    """周期性 sleep，用实际耗时减去期望间隔得到调度滞后。"""
    while True:
        start = time.perf_counter()
        await asyncio.sleep(interval)
        drift = (time.perf_counter() - start) - interval
        EVENT_LOOP_LAG.set(max(0.0, drift))


def ensure_loop_lag_monitor(interval: float = 0.25) -> None:
    """在当前运行的事件循环上惰性启动滞后采样任务（幂等，随循环切换自愈）。"""
    global _loop_lag_task, _loop_lag_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - no running loop
        return
    if (
        _loop_lag_task is not None
        and not _loop_lag_task.done()
        and _loop_lag_loop is loop
    ):
        return
    _loop_lag_loop = loop
    _loop_lag_task = loop.create_task(_sample_loop_lag(interval))


def stop_loop_lag_monitor() -> None:
    """停止滞后采样任务（测试清理用）。"""
    global _loop_lag_task
    if _loop_lag_task is not None and not _loop_lag_task.done():
        _loop_lag_task.cancel()
    _loop_lag_task = None


# ----------------------------------------------------------- 事件总线指标采集

def collect_event_bus_metrics(bus=None) -> None:
    """把事件总线 stats() 快照刷入 gauge（在 /metrics 抓取时调用）。"""
    try:
        if bus is None:
            from libs.events import get_event_bus

            bus = get_event_bus()
        stats = bus.stats()
    except Exception:  # pragma: no cover - never let scrape fail
        return

    for topic, depths in stats.get("queue_depths", {}).items():
        EVENT_BUS_QUEUE_DEPTH.labels(topic).set(max(depths) if depths else 0)
    for topic, count in stats.get("dropped", {}).items():
        EVENT_BUS_DROPPED.labels(topic).set(count)
    for topic, count in stats.get("coalesced", {}).items():
        EVENT_BUS_COALESCED.labels(topic).set(count)


# --------------------------------------------------------------- 渲染 / 中间件

def render_latest() -> bytes:
    """生成 prometheus 文本格式（先刷新事件总线 gauge）。"""
    collect_event_bus_metrics()
    return generate_latest(REGISTRY)


def _route_template(request) -> str:
    """用路由模板而非原始路径打标签，控制基数。"""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path
    return "unmatched"


try:  # Starlette 是 FastAPI 的依赖，一般都在。
    from starlette.middleware.base import BaseHTTPMiddleware

    class PrometheusMiddleware(BaseHTTPMiddleware):
        """记录请求时延（总/上游/本地）与在途请求数。"""

        async def dispatch(self, request, call_next):
            ensure_loop_lag_monitor()
            token = _upstream_wait_var.set(0.0)
            HTTP_REQUESTS_INFLIGHT.inc()
            start = time.perf_counter()
            status = "500"
            try:
                response = await call_next(request)
                status = str(response.status_code)
                return response
            finally:
                total = time.perf_counter() - start
                upstream = _upstream_wait_var.get()
                _upstream_wait_var.reset(token)
                HTTP_REQUESTS_INFLIGHT.dec()
                route = _route_template(request)
                method = request.method
                HTTP_REQUEST_DURATION.labels(method, route, status).observe(total)
                if upstream > 0.0:
                    HTTP_REQUEST_UPSTREAM_WAIT.labels(method, route).observe(upstream)
                HTTP_REQUEST_LOCAL_COMPUTE.labels(method, route).observe(
                    max(0.0, total - upstream)
                )

except Exception:  # pragma: no cover - starlette missing
    PrometheusMiddleware = None  # type: ignore
