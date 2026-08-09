"""今日触发的边 — which instruments the validated edges are firing on right now.

The workbench was built the wrong way round. Every page asked you to name an
instrument and then told you whether an edge applied to it. But these edges are
*events*: ``us_insider_cluster_buy`` fires on roughly five tickers a day out of
several thousand, and ``altcoin_retail_crowding`` on a handful of eight coins.
Typing a symbol and being told "not this one" is not a workflow — you would have
to type the whole market to find the five that matter.

So this endpoint inverts it. It scans each tradable edge across the universe the
study actually validated it on, and returns the instruments where the triggering
event is live. The scoreboard says the edges exist; this says where they are.

Two rules it will not bend:

- **Only the validated universe.** ``altcoin_retail_crowding`` was measured on
  eight majors; scanning a hundred coins with it would be extrapolation dressed
  as coverage.
- **Coverage is reported, not assumed.** An edge whose data could not be read
  returns ``unknown`` for the whole scan rather than an empty "nothing today",
  because those two look identical on screen and mean opposite things.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from apps.api.deps import cached_api_response, logger
from libs.quant.edge_instance import Direction, EdgeStatus, detect
from libs.quant.promotion_registry import get_registry

router = APIRouter()

# The universe each edge was validated on. Scanning outside it is extrapolation:
# the numbers on the board do not describe instruments the study never saw.
EDGE_UNIVERSE: dict[str, dict[str, Any]] = {
    "altcoin_retail_crowding": {
        "domain": "altcoin",
        # strategies/altcoin_retail_crowding VALIDATED_UNIVERSE
        "symbols": ["SOL-USDT", "DOGE-USDT", "ADA-USDT", "AVAX-USDT",
                    "LINK-USDT", "LTC-USDT", "XRP-USDT", "BCH-USDT"],
        "scan": "per_symbol",
    },
    "us_insider_cluster_buy": {
        "domain": "us_equity",
        # No fixed list: the edge is defined over every US issuer that files, so
        # the scan reads the filings and reports whichever tickers appear.
        "symbols": None,
        "scan": "market_wide",
    },
    "a_share_billboard_reversal": {
        "domain": "a_share",
        "symbols": None,
        "scan": "market_wide",
    },
}


def _scan_market_wide(strategy: str) -> dict[str, Any]:
    """Edges defined over a whole market: read the event feed, list what fired."""
    if strategy == "us_insider_cluster_buy":
        from libs.data.sec_daily_insider import scan_window

        scan = scan_window(allow_fetch=False)
        return {
            "instruments": [
                {
                    "symbol": event.symbol,
                    "status": EdgeStatus.ACTIVE.value,
                    "direction": Direction.LONG.value,
                    "fired_on": event.filing_date,
                    "evidence_zh": (
                        f"{event.insiders} 名内部人于 {event.filing_date} 同日申报公开市场买入"
                        f"（合计 ${event.value_usd:,.0f}）"
                    ),
                    "evidence_en": (
                        f"{event.insiders} insiders filed open-market purchases on "
                        f"{event.filing_date} (${event.value_usd:,.0f})"
                    ),
                    "detail": event.to_dict(),
                }
                for event in sorted(scan.events, key=lambda e: (-e.value_usd, e.symbol))
            ],
            "coverage": {
                "complete": scan.complete,
                "days_covered": len(scan.days_covered),
                "days_missing": scan.days_missing,
                "hint_zh": (
                    None if scan.complete else
                    "EDGAR 每日申报缓存不完整，下面的清单可能有遗漏。"
                    "运行 scripts/warm_insider_cache.py 预热"
                ),
            },
        }

    if strategy == "a_share_billboard_reversal":
        from libs.data.a_share_flow import FlowDataUnavailable, fetch_billboard_events

        try:
            events = fetch_billboard_events(max_events=3000)
        except FlowDataUnavailable as exc:
            return {"instruments": [], "coverage": {
                "complete": False, "days_covered": 0, "days_missing": [],
                "hint_zh": f"龙虎榜数据不可用：{exc}",
            }}
        today = datetime.now(UTC).date()
        recent = [e for e in events
                  if (today - datetime.fromisoformat(e.trade_date).date()).days <= 5]
        seen: set[str] = set()
        rows = []
        for event in sorted(recent, key=lambda e: e.trade_date, reverse=True):
            if event.code in seen:
                continue
            seen.add(event.code)
            rows.append({
                "symbol": event.code,
                "name": event.name,
                "status": EdgeStatus.ACTIVE.value,
                "direction": Direction.AVOID.value,
                "fired_on": event.trade_date,
                "evidence_zh": f"{event.name}({event.code}) 于 {event.trade_date} 上榜龙虎榜",
                "evidence_en": f"{event.name} ({event.code}) listed on {event.trade_date}",
                "detail": {"trade_date": event.trade_date},
            })
        return {"instruments": rows, "coverage": {
            "complete": True, "days_covered": 5, "days_missing": [], "hint_zh": None,
        }}

    return {"instruments": [], "coverage": {
        "complete": False, "days_covered": 0, "days_missing": [],
        "hint_zh": "该边没有市场级扫描器",
    }}


def _scan_per_symbol(strategy: str, symbols: list[str]) -> dict[str, Any]:
    """Edges defined over a fixed universe: check each member."""
    instruments = []
    unknown = 0
    for symbol in symbols:
        try:
            result = detect(strategy, symbol)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not lose the scan
            logger.info("edge_scan_failed", strategy=strategy, symbol=symbol, error=str(exc))
            unknown += 1
            continue
        if result.status is EdgeStatus.UNKNOWN:
            unknown += 1
            continue
        if result.status is not EdgeStatus.ACTIVE:
            continue
        instruments.append({
            "symbol": symbol,
            "status": result.status.value,
            "direction": result.direction.value if result.direction else None,
            "fired_on": (result.detail or {}).get("date"),
            "evidence_zh": result.evidence_zh,
            "evidence_en": result.evidence_en,
            "detail": result.detail or {},
        })
    return {
        "instruments": instruments,
        "coverage": {
            "complete": unknown == 0,
            "days_covered": len(symbols) - unknown,
            "days_missing": [],
            "hint_zh": (None if unknown == 0 else
                        f"{unknown}/{len(symbols)} 个标的数据不可用，清单可能有遗漏"),
        },
    }


def _scan_all() -> dict[str, Any]:
    registry = get_registry()
    groups = []
    for record in registry.records():
        if not record.approved:
            continue
        spec = EDGE_UNIVERSE.get(record.strategy)
        if spec is None:
            continue
        if spec["scan"] == "market_wide":
            found = _scan_market_wide(record.strategy)
        else:
            found = _scan_per_symbol(record.strategy, spec["symbols"])
        groups.append({
            "strategy": record.strategy,
            "domain": record.domain or spec["domain"],
            "role": record.role,
            "implementation": record.implementation,
            # The measured numbers travel with the opportunity so the list can
            # never imply more (or less) than the evidence behind it.
            "win_rate": record.win_rate,
            "mean_excess_pct": record.mean_excess_pct,
            "n": record.n,
            "t_stat": record.t_stat,
            "n_clusters": record.n_clusters,
            "cluster_by": record.cluster_by,
            **found,
        })

    firing = sum(len(g["instruments"]) for g in groups if g["role"] == "trade")
    avoid = sum(len(g["instruments"]) for g in groups if g["role"] == "avoid")
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "groups": groups,
        # Why the tradable list is the length it is. An empty desk with no
        # explanation looks like an outage, and someone who thinks the screen is
        # broken will go trade on a hunch instead — which is the exact failure the
        # gate exists to prevent.
        "demoted": [_demoted_row(r) for r in get_registry().demoted_pairs()],
        "counts": {"tradable_firing": firing, "avoid_firing": avoid},
        "complete": all(g["coverage"]["complete"] for g in groups) if groups else False,
    }


_FAIL_REASON_ZH = {
    "wrong_sign_vs_preregistration": "结果方向与预注册相反,假设被否证",
    "no_result": "原始实验文件里没有这一行",
    "no_per_event_data_cannot_verify_t": "证据未保存逐事件收益,无法核验标准误",
    "sample_too_small": "样本太小,未做检验",
    "no_run_manifest_cannot_replay": (
        "证据没有运行清单,无法重放 —— 重跑该实验以生成 as_of 和代码状态"
    ),
    "run_not_reproducible_dirty_tree": (
        "跑这次实验时有源码未提交,记录的 commit 不描述实际运行的代码 —— "
        "先 commit,再重跑实验"
    ),
}


def _demoted_row(record) -> dict[str, Any]:
    """One rejected edge, with the reason stated in the language of the evidence."""
    reasons_zh: list[str] = []
    for code in record.failed:
        if code in _FAIL_REASON_ZH:
            reasons_zh.append(_FAIL_REASON_ZH[code])
        elif code.startswith("independent_clusters<"):
            floor = code.split("<", 1)[1]
            reasons_zh.append(
                f"独立单元只有 {record.n_clusters} 个(需要 ≥{floor})——"
                f"事件虽多但都挤在同一段行情里,{record.n} 这个数字不是有效样本量"
            )
        elif code.startswith("|t_clustered|<") or code.startswith("|t|<"):
            hurdle = code.split("<", 1)[1]
            gap = ""
            if record.t_stat is not None and record.t_stat_iid is not None:
                gap = (f"(按 i.i.d. 算是 {record.t_stat_iid:+.2f},"
                       f"计入持有期重叠后只有 {record.t_stat:+.2f})")
            reasons_zh.append(f"聚类 t 值未过多重检验门槛 {hurdle} {gap}".strip())
        elif code.startswith("n<"):
            reasons_zh.append(f"事件数不足 {code[2:]}")
        else:
            reasons_zh.append(code)

    return {
        "strategy": record.strategy,
        "domain": record.domain,
        "role": record.role,
        "n": record.n,
        "n_clusters": record.n_clusters,
        "cluster_by": record.cluster_by,
        "win_rate": record.win_rate,
        "mean_excess_pct": record.mean_excess_pct,
        "t_stat": record.t_stat,
        "t_stat_iid": record.t_stat_iid,
        "t_hurdle": record.t_hurdle,
        "failed": record.failed,
        "reasons_zh": reasons_zh,
        "evidence": record.evidence,
    }


@router.get("/api/edges/firing")
async def get_firing_edges():
    """今天哪些标的触发了已验证的边。

    Cached for five minutes: the underlying scans read disk caches, but the
    A-share billboard fetch can be slow and this is the landing page's first
    request.
    """
    return await cached_api_response(
        "edges_firing", 300.0, lambda: asyncio.to_thread(_scan_all)
    )
