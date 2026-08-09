"""Portfolio-level pre-trade risk checks.

``PortfolioRiskChecker`` evaluates a proposed intent/basket against the
caller-supplied portfolio snapshot and returns a structured
:class:`RiskDecision` — never a bare bool. Per the project's unknown != safe
principle, missing position data yields ``allowed=False`` with the reason
``"position data unavailable"``.

The legacy unit-based :class:`RiskChecker` is kept as a deprecated alias so
existing imports (apps/api, scripts) keep working.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass(frozen=True)
class RiskLimits:
    """Configurable portfolio risk limits (all notionals in quote currency).

    Defaults are deliberately generous so default-wired services keep their
    existing behavior; production deployments should tighten them in config.
    """

    max_gross_notional: float = 10_000_000.0   # total |existing| + proposed exposure
    max_market_notional: float = 2_500_000.0   # per-market |existing| + proposed exposure
    max_basket_legs: int = 20                  # legs per intent/basket
    max_order_notional: float = 1_000_000.0    # single leg/order notional
    min_cash_buffer: float = 0.0               # cash that must remain after the trade


@dataclass(frozen=True)
class RiskDecision:
    """Structured outcome of one risk evaluation."""

    allowed: bool
    reasons: list[str] = field(default_factory=list)
    measurements: dict[str, float] = field(default_factory=dict)


def _leg_fields(leg: Any) -> tuple[str, float, float | None]:
    """Extract (market_key, quantity, price) from a dict or TradeIntentLeg-like object."""
    if isinstance(leg, Mapping):
        market = leg.get("market_id") or leg.get("symbol") or "unknown"
        quantity = float(leg.get("quantity", 0.0))
        price = leg.get("limit_price", leg.get("price"))
    else:
        instrument = getattr(leg, "instrument", None)
        if instrument is not None:
            market = getattr(instrument, "market_id", None) or getattr(instrument, "symbol", "unknown")
        else:
            market = getattr(leg, "market_id", None) or getattr(leg, "symbol", "unknown")
        quantity = float(getattr(leg, "quantity", 0.0))
        price = getattr(leg, "limit_price", None)
        if price is None:
            price = getattr(leg, "price", None)
    return str(market), quantity, (float(price) if price is not None else None)


class PortfolioRiskChecker:
    """Evaluates proposed trades against portfolio-level limits.

    Args:
        limits: risk limits; defaults are generous (see :class:`RiskLimits`).
        audit_db_path: when provided, every decision is persisted as an
            ``audit_events`` row via the fact-store audit API. ``None``
            disables persistence.
    """

    def __init__(
        self,
        limits: RiskLimits | None = None,
        *,
        audit_db_path: str | Path | None = None,
    ):
        self.limits = limits or RiskLimits()
        self.audit_db_path = audit_db_path

    def evaluate_intent(
        self,
        legs: Iterable[Any],
        positions: Mapping[str, float] | None,
        *,
        cash: float | None = None,
        subject_id: str | None = None,
    ) -> RiskDecision:
        """Evaluate a proposed intent/basket.

        Args:
            legs: proposed legs (dicts or TradeIntentLeg-like objects with
                quantity and limit_price).
            positions: current per-market absolute notional exposure
                ({market_key: notional}). ``None`` means position data is
                unavailable and the trade is rejected (unknown != safe).
                An empty mapping means a genuinely flat book.
            cash: available cash; only checked when ``min_cash_buffer > 0``.
            subject_id: optional id (e.g. intent_id) recorded in the audit event.
        """
        limits = self.limits
        reasons: list[str] = []
        measurements: dict[str, float] = {}

        legs = list(legs)

        if positions is None:
            decision = RiskDecision(False, ["position data unavailable"], {})
            self._audit(decision, subject_id)
            return decision

        leg_count = len(legs)
        measurements["leg_count"] = float(leg_count)
        if leg_count > limits.max_basket_legs:
            reasons.append(
                f"basket leg count {leg_count} exceeds limit {limits.max_basket_legs}"
            )

        proposed_by_market: dict[str, float] = {}
        proposed_total = 0.0
        for leg in legs:
            market, quantity, price = _leg_fields(leg)
            if price is None:
                reasons.append(f"leg notional unavailable for {market} (no price)")
                continue
            notional = abs(quantity) * abs(price)
            proposed_by_market[market] = proposed_by_market.get(market, 0.0) + notional
            proposed_total += notional
            if notional > limits.max_order_notional:
                reasons.append(
                    f"order notional {notional:.2f} for {market} exceeds limit "
                    f"{limits.max_order_notional:.2f}"
                )

        existing_gross = sum(abs(float(v)) for v in positions.values())
        gross = existing_gross + proposed_total
        measurements["proposed_notional"] = proposed_total
        measurements["existing_gross_notional"] = existing_gross
        measurements["gross_notional"] = gross
        if gross > limits.max_gross_notional:
            reasons.append(
                f"gross notional {gross:.2f} exceeds limit {limits.max_gross_notional:.2f}"
            )

        for market, proposed in proposed_by_market.items():
            market_total = abs(float(positions.get(market, 0.0))) + proposed
            measurements[f"market_notional:{market}"] = market_total
            if market_total > limits.max_market_notional:
                reasons.append(
                    f"market notional {market_total:.2f} for {market} exceeds limit "
                    f"{limits.max_market_notional:.2f}"
                )

        if limits.min_cash_buffer > 0:
            if cash is None:
                reasons.append("cash balance unavailable")
            else:
                remaining = float(cash) - proposed_total
                measurements["cash_after_trade"] = remaining
                if remaining < limits.min_cash_buffer:
                    reasons.append(
                        f"cash after trade {remaining:.2f} below min buffer "
                        f"{limits.min_cash_buffer:.2f}"
                    )

        decision = RiskDecision(allowed=not reasons, reasons=reasons, measurements=measurements)
        self._audit(decision, subject_id)
        return decision

    def _audit(self, decision: RiskDecision, subject_id: str | None) -> None:
        """Persist the decision as an audit event; never breaks the hot path."""
        if self.audit_db_path is None:
            return
        try:
            from libs.db import fact_store

            fact_store.append_audit_event(
                "risk.decision",
                actor="risk_manager",
                subject_type="intent",
                subject_id=subject_id,
                payload={
                    "allowed": decision.allowed,
                    "reasons": decision.reasons,
                    "measurements": decision.measurements,
                },
                db_path=self.audit_db_path,
            )
        except Exception as exc:
            logger.warning(
                "risk_audit_persist_failed",
                error=str(exc) or exc.__class__.__name__,
            )


class RiskChecker:
    """DEPRECATED: legacy unit-based checker kept as a compatibility alias.

    Prefer :class:`PortfolioRiskChecker`, which enforces notional-based
    portfolio limits and returns a structured :class:`RiskDecision`.
    """

    def __init__(self, max_position=1000, max_order_size=100):
        self.max_position = max_position
        self.max_order_size = max_order_size
        self.current_position = 0

    def check_order(self, size):
        """检查订单是否通过风控"""
        # 检查订单大小
        if size > self.max_order_size:
            return False, "订单超过最大限制"

        # 检查持仓限制
        if abs(self.current_position + size) > self.max_position:
            return False, "持仓超过限制"

        return True, "通过"

    def update_position(self, size):
        """更新持仓"""
        self.current_position += size


PositionProvider = Callable[[], Mapping[str, float] | None]

__all__ = [
    "PortfolioRiskChecker",
    "PositionProvider",
    "RiskChecker",
    "RiskDecision",
    "RiskLimits",
]
