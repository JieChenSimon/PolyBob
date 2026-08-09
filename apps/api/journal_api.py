"""交易日志 API — the loop from "an edge fired" to "here is what it returned".

Every other surface in this workbench reports a *research* number. These routes
are the only place your own execution gets measured, which is what the north
star ("持续提高胜率与收益率") actually asks for: you cannot improve a win rate
you never record.

Manual fills are deliberate, not a stopgap. The real orders happen in a broker
or an exchange this process cannot see, so the journal has to accept what you
tell it. What it will not do is guess: an entry with no fill has no return, and
the performance aggregate skips it rather than assuming it filled at the plan.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from apps.api.deps import clear_api_response_cache, logger
from libs.db.trade_journal import get_journal
from libs.quant.promotion_registry import get_registry

router = APIRouter()


def _float_or_none(payload: dict, key: str) -> float | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{key} 必须是数字") from exc


@router.get("/api/journal/entries")
async def list_journal_entries(edge_id: str | None = None, status: str | None = None):
    """The ledger, newest first."""
    entries = await asyncio.to_thread(
        get_journal().list_entries, edge_id=edge_id, status=status, limit=200
    )
    return {
        "entries": [e.to_dict() for e in entries],
        "count": len(entries),
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.post("/api/journal/entries")
async def create_journal_entry(payload: dict | None = None):
    """Log that an edge fired and you intend to take it.

    The promotion gate applies here too: a journal row for an unvalidated
    strategy would put research-free trades into the same performance table the
    validated edges are judged by, and the comparison is the whole point.
    """
    payload = payload or {}
    edge_id = str(payload.get("edge_id") or "").strip()
    symbol = str(payload.get("symbol") or "").strip()
    direction = str(payload.get("direction") or "").strip().lower()
    if not edge_id or not symbol:
        raise HTTPException(status_code=422, detail="edge_id 与 symbol 必填")
    if direction not in ("long", "short"):
        raise HTTPException(status_code=422, detail="direction 必须是 long 或 short")

    registry = get_registry()
    if not registry.is_promoted(edge_id):
        raise HTTPException(
            status_code=403,
            detail=f"'{edge_id}' 未过晋级门禁，不能记入交易日志："
                   f"{registry.reason_blocked(edge_id)}",
        )

    record = next((r for r in registry.records() if r.strategy == edge_id), None)
    entry = await asyncio.to_thread(
        get_journal().open_entry,
        edge_id=edge_id,
        symbol=symbol,
        domain=str(payload.get("domain") or (record.domain if record else "")),
        direction=direction,
        planned_entry=_float_or_none(payload, "planned_entry"),
        planned_stop=_float_or_none(payload, "planned_stop"),
        hold_sessions=payload.get("hold_sessions"),
        qty=_float_or_none(payload, "qty"),
        intent_id=payload.get("intent_id"),
        evidence=str(payload.get("evidence") or ""),
        # The research figure is copied in at open time so a later re-run of the
        # experiment cannot retroactively change what this trade was compared to.
        research_pct=record.mean_excess_pct if record else None,
        meta=payload.get("meta") or {},
    )
    clear_api_response_cache()
    return entry.to_dict()


@router.post("/api/journal/entries/{entry_id}/fill")
async def fill_journal_entry(entry_id: str, payload: dict | None = None):
    """Record the actual entry fill — price, size, fees."""
    payload = payload or {}
    price = _float_or_none(payload, "price")
    if price is None:
        raise HTTPException(status_code=422, detail="price 必填，不接受默认值")
    try:
        entry = await asyncio.to_thread(
            get_journal().record_fill, entry_id, price=price,
            qty=_float_or_none(payload, "qty"),
            fees=_float_or_none(payload, "fees") or 0.0,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"没有这条日志：{entry_id}") from exc
    clear_api_response_cache()
    return entry.to_dict()


@router.post("/api/journal/entries/{entry_id}/close")
async def close_journal_entry(entry_id: str, payload: dict | None = None):
    """Close the position and compute what it actually returned."""
    payload = payload or {}
    price = _float_or_none(payload, "price")
    if price is None:
        raise HTTPException(status_code=422, detail="price 必填，不接受默认值")
    try:
        entry = await asyncio.to_thread(
            get_journal().close_entry, entry_id, price=price,
            reason=str(payload.get("reason") or "manual"),
            fees=_float_or_none(payload, "fees") or 0.0,
            funding=_float_or_none(payload, "funding") or 0.0,
            benchmark_pct=_float_or_none(payload, "benchmark_pct"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"没有这条日志：{entry_id}") from exc
    clear_api_response_cache()
    return entry.to_dict()


@router.post("/api/journal/entries/{entry_id}/abandon")
async def abandon_journal_entry(entry_id: str, payload: dict | None = None):
    """You saw the signal and chose not to take it. Recorded — a skip is data."""
    payload = payload or {}
    try:
        entry = await asyncio.to_thread(
            get_journal().abandon, entry_id, str(payload.get("note") or "")
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"没有这条日志：{entry_id}") from exc
    clear_api_response_cache()
    return entry.to_dict()


@router.get("/api/journal/due")
async def list_due_exits():
    """Open positions whose validated holding period has elapsed.

    The horizon is part of the edge: the insider study measured 20 sessions and
    the crowding study 5 days. Holding past it is a different trade from the one
    with the evidence, so this is the queue that keeps the two the same.
    """
    due = await asyncio.to_thread(get_journal().due_for_exit)
    return {
        "due": [e.to_dict() for e in due],
        "count": len(due),
        "as_of": date.today().isoformat(),
    }


@router.get("/api/journal/performance")
async def get_journal_performance(edge_id: str | None = None):
    """研究值 vs 实测值 per edge — the north star, made checkable.

    ``slippage_pct`` is the number that matters: research minus reality. It is
    the only evidence that an edge survives contact with your own execution,
    and until this endpoint existed there was no way to compute it.
    """
    measured = await asyncio.to_thread(get_journal().performance, edge_id)
    registry = get_registry()
    rows = []
    for record in registry.records():
        if not record.approved or record.role != "trade":
            continue
        stats = measured.get(record.strategy)
        rows.append({
            "edge_id": record.strategy,
            "domain": record.domain,
            "research_win_rate": record.win_rate,
            "research_mean_pct": record.mean_excess_pct,
            "research_n": record.n,
            # None, not zero: a win rate over no closed trades is unknown.
            "measured": stats,
        })
    return {"edges": rows, "timestamp": datetime.now(UTC).isoformat()}
