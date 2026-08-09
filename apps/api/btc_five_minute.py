"""The Polymarket BTC five-minute workbench: routes, providers and diagnostics.

Extracted from ``apps/api/main.py``, where it was the single largest block —
729 lines of provider fan-out, outlier classification and error diagnosis that
had nothing to do with the other 60 routes it shared a file with.

It stays one module rather than several because the pieces genuinely are one
thing: the workbench fetches the CLOB book, a reference price aggregated across
three exchanges, and the target price, then has to explain precisely which of
those failed and why. The health/diagnosis code is only meaningful next to the
fetchers it describes.

No order book is ever synthesised. When the real book cannot be read the
workbench says so and returns no trade — see ``build_btc_five_minute_unavailable_health``.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter

from apps.api.deps import cached_api_response, get_shared_http_client, logger
from libs.config import get_settings
from libs.polymarket.btc_five_minute import (
    BtcFiveMinuteConfig,
    build_btc_five_minute_slug,
    build_workbench_snapshot,
    map_outcome_tokens,
    normalize_book,
)

router = APIRouter()

@router.get("/api/polymarket/btc-5m/indicators")
async def get_btc_five_minute_indicators():
    """BTC 5m 涨跌预测可选指标目录（前端弹窗据此渲染勾选）。"""
    from libs.polymarket.btc_five_minute import BTC5M_INDICATORS, DEFAULT_ENABLED_INDICATORS

    return {"indicators": BTC5M_INDICATORS, "default_enabled": list(DEFAULT_ENABLED_INDICATORS)}


@router.get("/api/polymarket/btc-5m/calibration")
async def get_btc_five_minute_calibration():
    """门禁状态与研究校准数据 — independent of whether the book is readable.

    These numbers come from ``data/btc5m_mispricing.json``, not from the live
    CLOB, so they must survive a provider outage. The calibration panel is the
    one thing this page can still say when the order book is down — and an
    outage is exactly when a trading-shaped panel full of "不可用" is at its most
    misleading.
    """
    from libs.polymarket.btc_five_minute import _gate_status, _threshold_status
    from libs.polymarket.btc_five_minute import BtcFiveMinuteConfig

    return await cached_api_response(
        "btc5m_calibration", 300.0,
        lambda: asyncio.to_thread(
            lambda: {
                "gate_status": _gate_status(None),
                "thresholds": _threshold_status(BtcFiveMinuteConfig(), None),
            }
        ),
    )


@router.get("/api/polymarket/btc-5m/workbench")
async def get_btc_five_minute_workbench(slug: str | None = None, indicators: str | None = None):
    """BTC 5-minute Polymarket Up/Down 专用工作台。

    ``indicators`` 逗号分隔的指标 id（如 ``market_implied,digital_option``）。
    留空 = 默认指标；用于前端弹窗自定义预测。
    """
    requested_slug = slug or build_btc_five_minute_slug(datetime.now().astimezone())
    enabled = [s.strip() for s in indicators.split(",") if s.strip()] if indicators else None

    async def load() -> dict:
        return await collect_btc_five_minute_workbench(slug=requested_slug, enabled_indicators=enabled)

    try:
        return await cached_api_response(
            f"btc_five_minute_workbench:{requested_slug}:{','.join(enabled) if enabled else 'default'}",
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


async def collect_btc_five_minute_workbench(
    slug: str | None = None, enabled_indicators: list[str] | None = None
) -> dict:
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

    up_response, down_response, btc_reference, page_target, micro = await asyncio.gather(
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
        _fetch_btc_micro_features_safe(client),
    )
    up_response.raise_for_status()
    down_response.raise_for_status()

    # Attach real realized volatility + momentum so the workbench uses the
    # calibrated digital-option probability and optional momentum indicator
    # instead of the hand-tuned scale (fail-soft).
    if isinstance(btc_reference, dict) and isinstance(micro, dict):
        btc_reference = {**btc_reference, **micro}

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
        enabled_indicators=enabled_indicators,
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


async def _fetch_btc_micro_features_safe(client: httpx.AsyncClient) -> dict | None:
    """Recent 1-minute BTC micro features: realized vol + last-minute momentum.

    Feeds the calibrated digital-option probability and the optional momentum
    indicator in the BTC 5m workbench. Fail-soft: any error returns None so the
    model falls back to legacy behaviour.
    """
    async def load() -> dict | None:
        response = await client.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": "BTCUSDT", "interval": "1m", "limit": 30},
            timeout=httpx.Timeout(4.0, connect=2.0),
        )
        response.raise_for_status()
        closes = [float(row[4]) for row in response.json()]
        if len(closes) < 10:
            return None
        rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
        if len(rets) < 5:
            return None
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        vol = math.sqrt(var)
        out: dict = {"momentum_1m": rets[-1]}
        if vol > 0:
            out["return_volatility"] = vol
        return out

    try:
        return await cached_api_response("btc_micro_features_1m", 15.0, load)
    except Exception as exc:
        logger.info("btc_micro_features_unavailable", error=str(exc) or exc.__class__.__name__)
        return None


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
