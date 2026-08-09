"""Short an altcoin perp when retail accounts are crowded long.

The executable form of the hypothesis ``altcoin_retail_crowding``, measured in
``scripts/us_crypto_experiment.py`` on real OKX data. It is here for the same
reason as the insider strategy: an approved edge with no implementation is a
gate protecting a desk that cannot act, and the promotion board's own test now
refuses to approve a tradable row without one.

What was measured, and why the short leg specifically:

- Spot exposure after crowding: 351 events, **-2.03%** over five days, 39.0%
  win rate. That is a reason not to buy.
- The same events traded as a **perp short with funding**: 234 events, **+3.20%**,
  68.4% win rate, t=6.45 against a 3.77 hurdle.

The earlier board approved this edge citing the first number while describing an
implementation based on the second — evidence and action pointing at different
legs. They are the same leg here: the strategy shorts, and the study that backs
it measured shorting, funding included. Crowded longs pay funding to shorts, so
leaving it out would have biased the very leg being traded.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

import structlog

from libs.quant.edge_instance import EdgeStatus, detect_retail_crowding
from libs.quant.promotion_registry import get_registry

logger = structlog.get_logger()

STRATEGY_ID = "altcoin_retail_crowding"
INSTRUMENT = "ALTCOIN_x8"

# The universe the experiment covered. Trading a coin outside it would be
# extrapolation, not the validated edge.
VALIDATED_UNIVERSE = ("SOL", "DOGE", "ADA", "AVAX", "LINK", "LTC", "XRP", "BCH")

# The rule as measured. Changing any of these detaches the strategy from its
# evidence, which the gate check below refuses to do silently.
VALIDATED = {
    "lookback": 30,
    "percentile": 80.0,
    "hold_days": 5,
}


@dataclass(frozen=True)
class CrowdingCandidate:
    symbol: str
    ratio: float
    threshold: float
    date: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ratio": round(self.ratio, 4),
            "threshold": round(self.threshold, 4),
            "date": self.date,
        }


class AltcoinRetailCrowding:
    """Scans the validated universe for crowded-long coins and shorts them."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        intent_service: Any = None,
        positioning_source: Callable[[str], list] | None = None,
    ) -> None:
        config = config or {}
        self.strategy_id = STRATEGY_ID
        self.intent_service = intent_service
        self._positioning_source = positioning_source

        self.lookback = int(config.get("lookback", VALIDATED["lookback"]))
        self.percentile = float(config.get("percentile", VALIDATED["percentile"]))
        self.hold_days = int(config.get("hold_days", VALIDATED["hold_days"]))
        self.universe = tuple(config.get("universe") or VALIDATED_UNIVERSE)
        self.position_usd = float(config.get("position_usd", 500.0))
        self.max_positions_per_scan = int(config.get("max_positions_per_scan", 3))
        self.scan_interval_seconds = float(config.get("scan_interval_seconds", 6 * 3600))
        # The measured five-day mean and win rate, not a target.
        self.expected_edge_bps = float(config.get("expected_edge_bps", 320.0))
        self.confidence = float(config.get("confidence", 0.68))

        self._running = False
        self._seen: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------ status
    def parameters_match_evidence(self) -> bool:
        return (
            self.lookback == VALIDATED["lookback"]
            and self.percentile == VALIDATED["percentile"]
            and self.hold_days == VALIDATED["hold_days"]
            and set(self.universe) <= set(VALIDATED_UNIVERSE)
        )

    def gate_status(self) -> dict[str, Any]:
        registry = get_registry()
        return {
            "strategy_id": self.strategy_id,
            "instrument": INSTRUMENT,
            "promoted": registry.is_promoted(self.strategy_id, INSTRUMENT),
            "reason": registry.reason_blocked(self.strategy_id, INSTRUMENT),
            "parameters_match_evidence": self.parameters_match_evidence(),
            "validated_parameters": dict(VALIDATED),
            "validated_universe": list(VALIDATED_UNIVERSE),
        }

    # ------------------------------------------------------------------- scan
    def scan(self) -> list[CrowdingCandidate]:
        """Coins currently crowded long, by the study's own trailing rule."""
        out: list[CrowdingCandidate] = []
        for ccy in self.universe:
            result = detect_retail_crowding(
                f"{ccy}-USDT",
                lookback=self.lookback,
                percentile=self.percentile,
                positioning_source=self._positioning_source,
            )
            if result.status is not EdgeStatus.ACTIVE:
                continue
            detail = result.detail or {}
            out.append(CrowdingCandidate(
                symbol=f"{ccy}-USDT-SWAP",
                ratio=float(detail.get("ratio", 0.0)),
                threshold=float(detail.get("threshold", 0.0)),
                date=str(detail.get("date", "")),
            ))
        # Most crowded first: the effect is monotone in how extreme the ratio is.
        out.sort(key=lambda c: c.ratio - c.threshold, reverse=True)
        return out

    async def run_once(self) -> list[dict[str, Any]]:
        status = self.gate_status()
        if not status["promoted"]:
            logger.info("altcoin_crowding_gate_blocked", reason=status["reason"])
            return []
        if not status["parameters_match_evidence"]:
            logger.warning("altcoin_crowding_parameters_drifted",
                           configured={"lookback": self.lookback,
                                       "percentile": self.percentile,
                                       "hold_days": self.hold_days,
                                       "universe": list(self.universe)},
                           validated=VALIDATED)
            return []
        if self.intent_service is None:
            return []

        created: list[dict[str, Any]] = []
        for candidate in self.scan()[: self.max_positions_per_scan]:
            key = (candidate.symbol, candidate.date)
            if key in self._seen:
                continue
            self._seen.add(key)
            intent = await self.intent_service.create_intent(
                strategy_id=self.strategy_id,
                rationale=(
                    f"{candidate.symbol} 散户多空比 {candidate.ratio:.2f} 高于近 "
                    f"{self.lookback} 日 {self.percentile:.0f} 分位（{candidate.threshold:.2f}）；"
                    f"按已验证规则做空并持有 {self.hold_days} 日（含资金费）"
                ),
                expected_edge_bps=self.expected_edge_bps,
                confidence=self.confidence,
                legs=[{
                    "venue": "paper",
                    "symbol": candidate.symbol,
                    "side": "sell",
                    "quantity": self.position_usd,
                    "role": "primary",
                }],
                metadata={
                    "edge": STRATEGY_ID,
                    "ratio": f"{candidate.ratio:.4f}",
                    "threshold": f"{candidate.threshold:.4f}",
                    "hold_days": str(self.hold_days),
                    "source": "OKX long/short account ratio",
                },
                idempotency_key=f"{self.strategy_id}:{candidate.symbol}:{candidate.date}",
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
                logger.error("altcoin_crowding_scan_failed", error=str(exc))
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
    "VALIDATED_UNIVERSE",
    "AltcoinRetailCrowding",
    "CrowdingCandidate",
]
