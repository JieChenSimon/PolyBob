"""投资准则判定 and the wisdom signals it reads — routes and their helpers.

Extracted from ``apps/api/main.py``. Kept together because the verdict is a
function of the signals: ``/api/verdict`` calls ``/api/wisdom/signals`` for the
buy/sell levels, then adds the parts the signal layer deliberately does not
know about — whether a *validated* edge is firing on this instrument, whether
the market's measured trap is present, and how the stop compares with this
instrument's own volatility.

The one rule that shapes everything here: a check that could not be run reports
UNKNOWN. Every helper below returns "I could not tell" as a distinct outcome
from "I checked and it is fine", because collapsing the two is what let the
A-share page report a clean dragon-tiger check it had never performed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException

from apps.api.deps import cached_api_response, logger
from libs.config import get_settings
from libs.quant.promotion_registry import get_registry as get_promotion_registry
from libs.quant.verdict import judge

router = APIRouter()

@router.get("/api/verdict")
async def get_investment_verdict(symbol: str, domain: str = "auto"):
    """投资准则判定——一个标的当前该不该动手,以及依据是什么。

    汇总:真实数据可信度、该市场是否有通过门禁的优势、风险是否已定义、
    是否正在犯本项目实测过的错误、以及当前是顺势还是逆势。默认结论是"等待"。
    """
    signals_payload = await get_wisdom_signals(symbol=symbol, domain=domain)
    resolved_domain = signals_payload.get("domain", domain)

    resolved_symbol = signals_payload.get("symbol", symbol)

    registry = get_promotion_registry()
    registry.reload()

    # Only edges promoted for THIS market, and each one checked against this
    # instrument rather than assumed from its asset class. See
    # libs/quant/edge_instance.py for why the distinction is the whole point.
    edges = await _detect_edge_instances(registry, resolved_symbol, resolved_domain)

    # The market's measured trap, actually evaluated on this symbol. ``None``
    # means it could not be run, which the engine reports as UNKNOWN — never as
    # a clean pass.
    trap = await _detect_trap(resolved_symbol, resolved_domain)

    bars = await _fetch_verdict_bars(resolved_symbol, resolved_domain)
    trend = _classify_trend_or_unknown(bars)
    volume = _classify_volume_or_unknown(bars, resolved_domain)

    report = judge(
        symbol=resolved_symbol,
        domain=resolved_domain,
        data_source=signals_payload.get("source"),
        as_of=signals_payload.get("as_of"),
        bars=int(signals_payload.get("bars", 0)),
        edges=edges,
        signals=signals_payload.get("signals", []),
        trap=trap,
        trend=trend,
        volume=volume,
        daily_vol=_daily_volatility(bars),
    )
    payload = report.to_dict()
    payload["edges"] = [e.to_dict() for e in edges]
    payload["trap"] = trap.to_dict() if trap is not None else None
    payload["trend"] = trend.to_dict()
    # ``null`` when the instrument has no volume concept at all. Polymarket
    # BTC-5m publishes an order book, not traded-volume bars, and no volume
    # number is fabricated from depth — see libs/quant/volume_state.py.
    payload["volume"] = volume.to_dict() if volume is not None else None
    return payload


# Markets whose daily bars this endpoint can fetch. Anything else has no daily
# volume concept here, and gets an honest ``null`` rather than an invented one.
_VERDICT_VOLUME_DOMAINS = frozenset({"a_share", "altcoin", "us_equity"})


async def _fetch_verdict_bars(symbol: str, domain: str):
    """Real daily bars for the verdict checks, or ``None`` on any absence.

    Shared by the trend and volume classifiers so one provider call serves both;
    the cache key is unchanged so existing warm entries still hit.
    """
    from libs.data.real_sources import (
        fetch_a_share_daily, fetch_altcoin_daily, fetch_us_equity_daily,
    )

    fetchers = {"a_share": fetch_a_share_daily, "altcoin": fetch_altcoin_daily,
                "us_equity": fetch_us_equity_daily}
    fetcher = fetchers.get(domain)
    if fetcher is None:
        return None
    try:
        return await cached_api_response(
            f"trend_bars:{domain}:{symbol}", 300.0,
            lambda: asyncio.to_thread(fetcher, symbol),
        )
    except Exception as exc:  # noqa: BLE001 - DataUnavailable et al; absence is not a signal
        logger.info("verdict_bars_unavailable", symbol=symbol, error=str(exc))
        return None


def _classify_trend_or_unknown(bars):
    """Bars -> trend classification, or an honest ``unknown``.

    A provider outage must not silently become "no trend concern": the classifier
    returns an ``unknown`` state, which the verdict engine treats as *not*
    supporting ACT.
    """
    from libs.quant.trend_state import classify_trend

    return classify_trend(bars)


def _classify_volume_or_unknown(bars, domain: str):
    """Bars -> volume-price classification, ``None`` where volume does not exist.

    ``None`` means "this instrument has no volume concept" (the frontend renders
    nothing); an ``unavailable`` state means "it should have one but we could not
    read it". Both map to ``UNKNOWN`` in the verdict, never to a silent pass.
    """
    from libs.quant.volume_state import classify_volume

    if domain not in _VERDICT_VOLUME_DOMAINS:
        return None
    return classify_volume(bars)


async def _detect_edge_instances(registry, symbol: str, domain: str):
    """Approved edges for this market, each checked against THIS instrument.

    Both tradable edges and avoidance filters are evaluated: the filters do not
    grant permission, but whether one is firing on this symbol is exactly what
    the trap check needs to know.
    """
    from libs.quant.edge_instance import detect

    out = []
    for record in registry.records():
        if not record.approved or _promotion_domain(record) != domain:
            continue
        try:
            out.append(await asyncio.to_thread(detect, record.strategy, symbol))
        except Exception as exc:  # noqa: BLE001 - a detector outage is UNKNOWN, not "clear"
            logger.info("verdict_edge_detect_failed",
                        strategy=record.strategy, symbol=symbol, error=str(exc))
    return out


async def _detect_trap(symbol: str, domain: str):
    """The market's measured trap, evaluated on this symbol, or ``None``.

    ``None`` is returned only when the check could not be run at all, so the
    verdict engine can say "not checked" instead of printing a pass nobody
    earned — the A-share dragon-tiger check used to do exactly that.
    """
    from libs.quant.edge_instance import EdgeStatus, detect
    from libs.quant.verdict import KNOWN_TRAPS

    trap = KNOWN_TRAPS.get(domain)
    if not trap:
        return None
    strategy = {"a_share": "a_share_billboard_reversal",
                "altcoin": "altcoin_retail_crowding"}.get(domain)
    if strategy is None:
        return None
    try:
        result = await asyncio.to_thread(detect, strategy, symbol)
    except Exception as exc:  # noqa: BLE001
        logger.info("verdict_trap_check_unavailable", symbol=symbol, error=str(exc))
        return None
    return result if result.status is not EdgeStatus.UNKNOWN else result


def _daily_volatility(bars) -> float | None:
    """Daily return standard deviation, so a stop can be judged against noise."""
    if bars is None or not getattr(bars, "closes", None) or len(bars.closes) < 30:
        return None
    closes = bars.closes[-120:]
    rets = [closes[i] / closes[i - 1] - 1.0
            for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(rets) < 20:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return var ** 0.5 or None


def _promotion_domain(record) -> str:
    """Map a promoted record to its market, for verdict filtering.

    Prefers the board's own ``domain`` field; the substring fallback only covers
    boards written before that field existed.
    """
    if getattr(record, "domain", ""):
        return record.domain
    strategy = record.strategy
    if "a_share" in strategy or "billboard" in strategy:
        return "a_share"
    if "altcoin" in strategy or "crowding" in strategy:
        return "altcoin"
    if "insider" in strategy or "us_" in strategy:
        return "us_equity"
    return "unknown"


@router.get("/api/wisdom/signals")
async def get_wisdom_signals(symbol: str, domain: str = "auto"):
    """《炒股的智慧》临界点信号——同一套方法接入任一标的。

    ``domain`` 为 ``auto`` 时按代码推断:6位数字=A股,``X-USDT``=山寨币,
    其余=美股。返回买卖信号、止损位与书中的仓位规则。
    """
    from libs.data.real_sources import (
        DataUnavailable, fetch_a_share_daily, fetch_altcoin_daily, fetch_us_equity_daily,
    )
    from strategies import trading_wisdom as wisdom

    clean = symbol.strip().upper()
    if domain == "auto":
        code = clean.split(".")[0]
        if code.isdigit() and len(code) == 6:
            domain = "a_share"
        elif clean.endswith("-USDT") or clean.endswith("-USD"):
            domain = "altcoin"
        else:
            domain = "us_equity"

    fetchers = {"a_share": fetch_a_share_daily, "altcoin": fetch_altcoin_daily,
                "us_equity": fetch_us_equity_daily}
    if domain not in fetchers:
        raise HTTPException(status_code=400, detail=f"unknown domain '{domain}'")

    def load() -> dict:
        try:
            bars = fetchers[domain](clean)
        except DataUnavailable as exc:
            # Real data or nothing — never synthesise a price series to draw on.
            raise HTTPException(status_code=502, detail=f"真实行情不可用: {exc}") from exc

        series = wisdom.Bars(
            closes=bars.closes, highs=bars.highs, lows=bars.lows,
            opens=bars.opens, volumes=bars.volumes, dates=bars.dates,
        )
        signals = wisdom.detect_signals(series)
        last_close = float(bars.closes[-1]) if bars.closes else 0.0
        buys = [s for s in signals if s.direction is wisdom.Direction.BUY]
        sizing = None
        if buys and buys[0].stop_price:
            # The account size comes from configuration, and is ``None`` when
            # unset. It used to be hardcoded at 100,000, which meant this endpoint
            # returned an exact allocation and share count derived from an account
            # nobody owns — a fabricated figure in the one field that tells you how
            # much to buy.
            sizing = wisdom.position_size(
                capital=get_settings().polybob_account_equity,
                entry=buys[0].price, stop=buys[0].stop_price,
            )
        return {
            "symbol": bars.symbol, "domain": domain, "source": bars.source,
            "as_of": bars.dates[-1] if bars.dates else None,
            "last_close": last_close, "bars": len(bars),
            "signals": [s.to_dict() for s in signals],
            "position_sizing": sizing,
            "rules": {
                "stop_loss_max_pct": wisdom.MAX_STOP_PCT,
                "capital_parts": wisdom.CAPITAL_PARTS,
                "min_risk_reward": wisdom.MIN_RISK_REWARD,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    return await cached_api_response(
        f"wisdom:{domain}:{clean}", 300.0, lambda: asyncio.to_thread(load)
    )
