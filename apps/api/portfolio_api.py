"""Account state and position sizing — the half of return that had no substrate.

``return = edge x size``. The edge half has a promotion gate, clustered standard
errors and a trial count; the size half printed ``100_000 / 10``. These endpoints
expose the real thing: an account you enter, and a size derived from the measured
edge, discounted by how little independent sample it rests on, and budgeted so two
edges cannot each take their "safe" tenth in the same direction.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from libs.config import get_settings
from libs.portfolio.account import (
    ASSUMED_CROSS_DOMAIN_CORRELATION,
    MAX_DOMAIN_FRACTION,
    MAX_POSITION_FRACTION,
    MAX_TOTAL_RISK_FRACTION,
    Account,
    Position,
)
from libs.portfolio.sizing import EdgeStatistics, size_position
from libs.quant.promotion_registry import get_registry

router = APIRouter()


def _account() -> Account:
    """The account as this process knows it.

    Equity comes from configuration and is ``None`` when unset — never a default.
    Open positions come from the trade journal, which is where a real fill is
    recorded; a position the journal does not know about cannot be budgeted for,
    and the snapshot says how many it saw rather than implying completeness.
    """
    equity = get_settings().polybob_account_equity
    positions: list[Position] = []
    try:
        from libs.db.trade_journal import get_journal

        for entry in get_journal().list_entries(status="open"):
            # A *planned* entry holds no risk: nothing is filled, so nothing can
            # move against you. Only a filled position consumes budget.
            if not entry.actual_entry or not entry.qty:
                continue
            positions.append(Position(
                symbol=entry.symbol, domain=entry.domain or "", edge_id=entry.edge_id,
                direction=entry.direction, quantity=float(entry.qty),
                entry_price=float(entry.actual_entry),
                stop_price=float(entry.planned_stop) if entry.planned_stop else None,
                opened_on=entry.entry_filled_at or entry.opened_at or "",
            ))
    except Exception:  # noqa: BLE001 — an unavailable journal means unknown positions
        pass
    return Account(equity=equity, cash=equity, positions=positions)


@router.get("/api/portfolio/account")
async def get_account():
    account = _account()
    return {
        **account.snapshot(),
        "limits": {
            "max_position_fraction": MAX_POSITION_FRACTION,
            "max_domain_fraction": MAX_DOMAIN_FRACTION,
            "max_total_risk_fraction": MAX_TOTAL_RISK_FRACTION,
            "assumed_cross_domain_correlation": ASSUMED_CROSS_DOMAIN_CORRELATION,
        },
        "hint_zh": (
            None if account.configured else
            "未配置账户权益。设置 POLYBOB_ACCOUNT_EQUITY 后这里才会出金额和股数;"
            "在那之前只给比例——本项目不替你猜本金。"
        ),
    }


@router.get("/api/portfolio/size/{strategy}")
async def get_size(
    strategy: str, entry_price: float | None = None, stop_price: float | None = None
):
    """How much of the account this edge may take, with the reasoning attached.

    Reads the edge's *own* measured statistics off the promotion board, so the size
    cannot be computed from numbers nobody verified. An unpromoted edge gets a
    sizing answer of zero and the gate's reason, rather than a hypothetical.
    """
    registry = get_registry()
    record = next((r for r in registry.records() if r.strategy == strategy), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"board 上没有 '{strategy}'")

    if not record.tradable:
        return {
            "strategy": strategy, "allowed": False, "fraction": 0.0,
            "amount": None, "shares": None,
            "reasons_zh": [f"未获开仓权限:{registry.reason_blocked(strategy)}"],
            "capital_known": _account().configured,
        }

    if record.win_rate is None or record.n_clusters is None:
        raise HTTPException(
            status_code=422,
            detail=f"'{strategy}' 缺少胜率或独立单元数,无法定仓位",
        )

    stats = EdgeStatistics(
        win_rate=float(record.win_rate),
        mean_excess=(record.mean_excess_pct or 0.0) / 100.0,
        n_clusters=int(record.n_clusters),
    )
    decision = size_position(
        stats, _account(), domain=record.domain or "",
        entry_price=entry_price, stop_price=stop_price,
    )
    return {"strategy": strategy, "domain": record.domain, **decision.to_dict()}
