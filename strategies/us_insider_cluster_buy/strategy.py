"""US insider cluster buying — the desk's one gate-approved tradable edge.

This is the executable form of the hypothesis ``insider_cluster_buy``, measured
in ``scripts/insider_experiment.py`` on real SEC Form 345 filings. It exists
because the board and the desk had drifted apart: the board approved edges that
no code implemented, while every runnable strategy was unvalidated. A promotion
gate over two disjoint sets blocks everything and proves nothing.

So the rules below are deliberately *the same rules the study measured*, not a
refinement of them:

- **Entry on the filing date.** ``FILING_DATE`` is when the purchase becomes
  public. ``TRANS_DATE`` is when the insider traded, which was not public then —
  using it would be look-ahead, and the measured edge would not be the traded
  one.
- **Two insiders, $50k each.** The same clustering thresholds
  :func:`libs.data.sec_insider.cluster_buys` used in the experiment. A single
  insider was the control and did **not** clear the hurdle; loosening to one
  here would be trading something that was never validated.
- **A 20-session horizon**, the study's holding period.
- **Only fresh filings.** The study measured the return from the filing date
  forward. A cluster filed two months ago is a different trade — the drift it
  predicted has already happened — so stale events are dropped rather than
  entered late.

Any change to those constants invalidates the evidence behind this strategy, so
they are read from config but default to the validated values, and the strategy
refuses to emit intents unless the promotion registry still marks it tradable.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable, Iterable

import structlog

from libs.data.sec_insider import (
    InsiderTrade,
    SecDataUnavailable,
    cluster_buys,
    fetch_insider_trades,
)
from libs.quant.promotion_registry import get_registry

logger = structlog.get_logger()

STRATEGY_ID = "us_insider_cluster_buy"
INSTRUMENT = "US_ALL"

# The validated parameters. Changing one detaches the strategy from its evidence.
VALIDATED = {
    "min_insiders": 2,
    "min_value_usd": 50_000.0,
    "hold_sessions": 20,
}


@dataclass(frozen=True)
class ClusterCandidate:
    """One tradable cluster-buy event."""

    symbol: str
    filing_date: str
    insiders: int
    value_usd: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "filing_date": self.filing_date,
            "insiders": self.insiders,
            "value_usd": round(self.value_usd, 2),
        }


TradeSource = Callable[[int, int], list[InsiderTrade]]


def _quarters_covering(start: date, end: date) -> list[tuple[int, int]]:
    """Every SEC filing quarter touching ``[start, end]``, oldest first."""
    out: list[tuple[int, int]] = []
    year, quarter = start.year, (start.month - 1) // 3 + 1
    while (year, quarter) <= (end.year, (end.month - 1) // 3 + 1):
        out.append((year, quarter))
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
    return out


def find_clusters(
    trades: Iterable[InsiderTrade],
    *,
    as_of: date,
    max_age_days: int,
    min_insiders: int,
    min_value_usd: float,
) -> list[ClusterCandidate]:
    """Cluster buys fresh enough to still be the trade the study measured."""
    trade_list = list(trades)
    grouped = cluster_buys(
        trade_list, min_insiders=min_insiders, min_value_usd=min_value_usd
    )
    counts: dict[tuple[str, str], int] = {}
    for trade in trade_list:
        if trade.is_open_market_buy and trade.value_usd >= min_value_usd:
            key = (trade.symbol, trade.filing_date)
            counts[key] = counts.get(key, 0) + 1

    cutoff = as_of - timedelta(days=max_age_days)
    out: list[ClusterCandidate] = []
    for (symbol, filing_date), value in grouped.items():
        try:
            filed = date.fromisoformat(filing_date)
        except ValueError:
            continue
        if not (cutoff <= filed <= as_of):
            continue
        out.append(ClusterCandidate(symbol, filing_date, counts.get((symbol, filing_date), 0), value))
    out.sort(key=lambda c: (c.filing_date, -c.value_usd))
    return out


class UsInsiderClusterBuy:
    """Scans real SEC filings for cluster buys and raises long intents."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        intent_service: Any = None,
        trade_source: TradeSource | None = None,
    ) -> None:
        config = config or {}
        self.strategy_id = STRATEGY_ID
        self.intent_service = intent_service
        self._fetch_trades: TradeSource = trade_source or fetch_insider_trades

        self.min_insiders = int(config.get("min_insiders", VALIDATED["min_insiders"]))
        self.min_value_usd = float(config.get("min_value_usd", VALIDATED["min_value_usd"]))
        self.hold_sessions = int(config.get("hold_sessions", VALIDATED["hold_sessions"]))
        self.max_age_days = int(config.get("max_age_days", 5))
        self.max_positions_per_scan = int(config.get("max_positions_per_scan", 5))
        self.position_usd = float(config.get("position_usd", 1000.0))
        self.scan_interval_seconds = float(config.get("scan_interval_seconds", 6 * 3600))
        # The study's measured mean excess return over the horizon, in bps. It is
        # the expectation this strategy is entitled to claim — not a target.
        self.expected_edge_bps = float(config.get("expected_edge_bps", 511.0))
        self.confidence = float(config.get("confidence", 0.53))  # the measured win rate

        self._running = False
        self._seen: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------ status
    def parameters_match_evidence(self) -> bool:
        """False if the config has drifted from what was actually validated."""
        return (
            self.min_insiders == VALIDATED["min_insiders"]
            and self.min_value_usd == VALIDATED["min_value_usd"]
            and self.hold_sessions == VALIDATED["hold_sessions"]
        )

    def gate_status(self) -> dict[str, Any]:
        registry = get_registry()
        promoted = registry.is_promoted(self.strategy_id, INSTRUMENT)
        return {
            "strategy_id": self.strategy_id,
            "instrument": INSTRUMENT,
            "promoted": promoted,
            "reason": registry.reason_blocked(self.strategy_id, INSTRUMENT),
            "parameters_match_evidence": self.parameters_match_evidence(),
            "validated_parameters": dict(VALIDATED),
        }

    # ------------------------------------------------------------------- scan
    def scan(self, as_of: date | None = None) -> list[ClusterCandidate]:
        """Fresh cluster-buy events from real SEC data. Never fabricates."""
        as_of = as_of or datetime.now(UTC).date()
        start = as_of - timedelta(days=self.max_age_days)
        trades: list[InsiderTrade] = []
        for year, quarter in _quarters_covering(start, as_of):
            try:
                trades.extend(self._fetch_trades(year, quarter))
            except SecDataUnavailable as exc:
                logger.info("insider_quarter_unavailable", year=year, quarter=quarter, error=str(exc))
        return find_clusters(
            trades,
            as_of=as_of,
            max_age_days=self.max_age_days,
            min_insiders=self.min_insiders,
            min_value_usd=self.min_value_usd,
        )

    async def run_once(self, as_of: date | None = None) -> list[dict[str, Any]]:
        """One scan → intents, subject to the promotion gate. Returns intents."""
        status = self.gate_status()
        if not status["promoted"]:
            logger.info("insider_cluster_gate_blocked", reason=status["reason"])
            return []
        if not status["parameters_match_evidence"]:
            logger.warning(
                "insider_cluster_parameters_drifted",
                configured={"min_insiders": self.min_insiders,
                            "min_value_usd": self.min_value_usd,
                            "hold_sessions": self.hold_sessions},
                validated=VALIDATED,
            )
            return []
        if self.intent_service is None:
            return []

        created: list[dict[str, Any]] = []
        for candidate in self.scan(as_of)[: self.max_positions_per_scan]:
            key = (candidate.symbol, candidate.filing_date)
            if key in self._seen:
                continue
            self._seen.add(key)
            intent = await self.intent_service.create_intent(
                strategy_id=self.strategy_id,
                rationale=(
                    f"{candidate.insiders} 名内部人于 {candidate.filing_date} 同日申报公开市场买入 "
                    f"{candidate.symbol}(合计 ${candidate.value_usd:,.0f});"
                    f"按已验证规则持有 {self.hold_sessions} 个交易日"
                ),
                expected_edge_bps=self.expected_edge_bps,
                confidence=self.confidence,
                legs=[{
                    "venue": "paper",
                    "symbol": candidate.symbol,
                    "side": "buy",
                    "quantity": self.position_usd,
                    "role": "primary",
                }],
                metadata={
                    "edge": "us_insider_cluster_buy",
                    "filing_date": candidate.filing_date,
                    "insiders": str(candidate.insiders),
                    "hold_sessions": str(self.hold_sessions),
                    "source": "SEC Form 345",
                },
                idempotency_key=f"{self.strategy_id}:{candidate.symbol}:{candidate.filing_date}",
            )
            created.append(intent)
        return created

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        logger.info("starting_strategy", strategy_id=self.strategy_id,
                    gate=self.gate_status())
        self._running = True
        while self._running:
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001 - a bad scan must not kill the loop
                logger.error("insider_cluster_scan_failed", error=str(exc))
            for _ in range(int(self.scan_interval_seconds)):
                if not self._running:
                    break
                await asyncio.sleep(1)

    async def stop(self) -> None:
        logger.info("stopping_strategy", strategy_id=self.strategy_id)
        self._running = False


__all__ = [
    "INSTRUMENT",
    "STRATEGY_ID",
    "VALIDATED",
    "ClusterCandidate",
    "UsInsiderClusterBuy",
    "find_clusters",
]
