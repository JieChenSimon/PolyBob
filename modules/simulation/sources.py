"""Signal-source adapters for the simulation service.

Strategies in this repo emit signals through different channels (event-bus
publishes, intent-service calls, or ``generate_signal`` return values). The
simulation service needs one uniform, side-effect-free interface, so this
module defines a minimal :class:`SignalSource` protocol:

- ``topics``: which lossy event-bus topics the source consumes
  (``Topics.FEATURE_SNAPSHOT`` and/or ``Topics.PAIR_SNAPSHOT``).
- ``on_snapshot(topic, snapshot) -> list[SimSignal]``: pure transformation of
  one snapshot into zero or more :class:`SimSignal`.

Each :class:`SimSignal` carries its own quote context (bid/ask/mid/depth and
timestamp taken from the snapshot that produced it) so the fill model in
``service.py`` never has to guess where prices came from.

Implemented adapters:

- :class:`FusionSignalSource` — wraps :class:`strategies.signal_fusion.SignalFusion`
  (feature snapshots). Records the contributing sub-signal names in
  ``signal_meta['signals']`` so the feedback loop can attribute outcomes.
- :class:`SpreadReversionSignalSource` — replicates the entry logic of
  ``spread_reversion_v1`` (wide spread + balanced book) as a returned signal
  instead of an event-bus publish.
- :class:`PairSpreadSignalSource` — replicates the entry logic of
  ``spread_arbitrage_v1`` on pair snapshots, emitting one signal per leg
  (instrument ids are ``"venue:symbol"``).
- :class:`MomentumSignalSource` — self-contained dual moving-average momentum
  on feature snapshots. Keeps a per-instrument rolling window of the most
  recent mid prices and compares a fast vs slow simple moving average using
  only prices seen so far (strictly causal, no look-ahead). Deliberately does
  NOT import from ``strategies/`` so the simulation engine has a lightweight,
  dependency-free trend strategy of its own.
- :class:`KronosForecastLabSource` — converts a completed forecasting artifact
  into a simulation-only signal. It is deliberately not an event-bus or intent
  source and stamps every signal ``lab_only``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from libs.events import Topics


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class SimSignal:
    """One directional trading signal plus the quote context it was based on."""

    instrument_id: str
    side: str  # "buy" | "sell"
    confidence: float
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    bid_depth: float | None = None
    ask_depth: float | None = None
    timestamp: datetime | None = None
    signal_meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SignalSource(Protocol):
    """Minimal adapter every simulated strategy binding must implement."""

    topics: tuple[str, ...]

    async def on_snapshot(self, topic: str, snapshot: dict) -> list[SimSignal]:
        ...


class KronosForecastLabSource:
    """Translate forecast evidence into a signal for simulation only.

    This class has no live topics and cannot publish an intent.  Promotion is
    still checked by the execution boundary; the source exists so an unpromoted
    model can accumulate honest paper evidence before asking for permission.
    """

    topics: tuple[str, ...] = ()

    def __init__(self, minimum_abs_return: float = 0.005) -> None:
        self.minimum_abs_return = max(0.0, float(minimum_abs_return))

    async def on_snapshot(self, topic: str, snapshot: dict) -> list[SimSignal]:
        return []

    def signals_for_artifact(self, artifact: Any) -> list[SimSignal]:
        status = getattr(artifact, "status", None)
        if getattr(status, "value", status) != "ready":
            return []
        expected = float(getattr(artifact, "expected_return", 0.0))
        if abs(expected) < self.minimum_abs_return:
            return []
        last_close = float(getattr(artifact, "last_close", 0.0))
        if last_close <= 0:
            return []
        up_probability = float(getattr(artifact, "up_probability", 0.5))
        return [
            SimSignal(
                instrument_id=str(artifact.instrument_id),
                side="buy" if expected > 0 else "sell",
                confidence=min(1.0, abs(up_probability - 0.5) * 2),
                mid=last_close,
                timestamp=artifact.as_of,
                signal_meta={
                    "source": "kronos_daily_forecast",
                    "run_id": artifact.run_id,
                    "model_revision": artifact.model_revision,
                    "promotion_status": "lab_only",
                    "trade_permission": False,
                    "expected_return": expected,
                    "up_probability": up_probability,
                },
            )
        ]


class FusionSignalSource:
    """Adapts :class:`SignalFusion` (feature-snapshot driven) to SignalSource.

    The wrapped fusion strategy expects indicator features (``rsi``,
    ``ma_fast`` …). Live feature snapshots only carry book/trade features, so
    callers may layer indicators into the snapshot upstream; anything present
    is forwarded verbatim (plus ``price`` defaulting to ``mid_price``).
    """

    topics = (Topics.FEATURE_SNAPSHOT,)

    def __init__(self, fusion: Any):
        self.fusion = fusion

    async def on_snapshot(self, topic: str, snapshot: dict) -> list[SimSignal]:
        features = dict(snapshot)
        features.setdefault("price", snapshot.get("mid_price", 0.0))
        # Drive the strategy's own scoring + fusion (which already applies its
        # ``min_confidence`` gate and returns a plain ``direction``/``confidence``
        # tuple), rather than ``generate_signal``. ``generate_signal`` maps the
        # decision onto a ``libs.schemas.Side`` enum that has no plain BUY/SELL
        # members, so it raises for directional signals; the fusion internals do
        # not, and give us exactly the direction + confidence we need here.
        scores = self.fusion._calculate_signal_scores(features)
        direction, confidence, reason = self.fusion._fuse_signals(scores)
        if direction == 0:
            return []
        contributing = sorted(
            name for name, sub in scores.items() if sub.direction != 0
        )
        side = "buy" if direction > 0 else "sell"
        return [
            SimSignal(
                instrument_id=str(snapshot.get("market_id", "unknown")),
                side=side,
                confidence=float(confidence),
                bid=_positive(snapshot.get("bid_price")),
                ask=_positive(snapshot.get("ask_price")),
                mid=_positive(snapshot.get("mid_price")),
                bid_depth=_positive(snapshot.get("bid_size")),
                ask_depth=_positive(snapshot.get("ask_size")),
                timestamp=_parse_ts(snapshot.get("timestamp")),
                signal_meta={
                    "source": "signal_fusion",
                    "signals": contributing,
                    "reason": reason,
                },
            )
        ]


class SpreadReversionSignalSource:
    """Wide-spread mean-reversion entries from live feature snapshots."""

    topics = (Topics.FEATURE_SNAPSHOT,)

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.spread_threshold_bps = float(config.get("spread_threshold_bps", 150.0))
        self.min_depth_ratio = float(config.get("min_depth_ratio", 0.3))
        self.confidence = float(config.get("reversion_confidence", 0.7))
        self.min_size = float(config.get("min_size", 10.0))

    async def on_snapshot(self, topic: str, snapshot: dict) -> list[SimSignal]:
        spread_bps = float(snapshot.get("spread_bps") or 0.0)
        if spread_bps < self.spread_threshold_bps:
            return []
        if abs(float(snapshot.get("depth_imbalance") or 0.0)) > self.min_depth_ratio:
            return []
        bid_size = float(snapshot.get("bid_size") or 0.0)
        ask_size = float(snapshot.get("ask_size") or 0.0)
        if bid_size < self.min_size or ask_size < self.min_size:
            return []
        imbalance = float(snapshot.get("depth_imbalance") or 0.0)
        side = "buy" if imbalance >= 0 else "sell"
        return [
            SimSignal(
                instrument_id=str(snapshot.get("market_id", "unknown")),
                side=side,
                confidence=self.confidence,
                bid=_positive(snapshot.get("bid_price")),
                ask=_positive(snapshot.get("ask_price")),
                mid=_positive(snapshot.get("mid_price")),
                bid_depth=bid_size,
                ask_depth=ask_size,
                timestamp=_parse_ts(snapshot.get("timestamp")),
                signal_meta={
                    "source": "spread_reversion_v1",
                    "spread_bps": spread_bps,
                },
            )
        ]


class PairSpreadSignalSource:
    """Cross-venue spread signals from pair snapshots (one signal per leg)."""

    topics = (Topics.PAIR_SNAPSHOT,)

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.min_net_edge_bps = float(config.get("min_net_edge_bps", 12.0))
        self.min_abs_spread_bps = float(config.get("min_abs_spread_bps", 8.0))
        self.min_confidence = float(config.get("min_confidence", 0.55))

    @staticmethod
    def instrument_id(ref: dict) -> str:
        return f"{ref.get('venue')}:{ref.get('symbol')}"

    async def on_snapshot(self, topic: str, snapshot: dict) -> list[SimSignal]:
        net_edge_bps = float(snapshot.get("net_edge_bps") or 0.0)
        spread_bps = float(snapshot.get("spread_bps") or 0.0)
        z_score = abs(float(snapshot.get("z_score") or 0.0))
        confidence = min(1.0, 0.45 + z_score * 0.15 + max(net_edge_bps, 0.0) / 100)

        if net_edge_bps < self.min_net_edge_bps:
            return []
        if abs(spread_bps) < self.min_abs_spread_bps:
            return []
        if confidence < self.min_confidence:
            return []

        pair_id = str(snapshot.get("pair_id"))
        ts = _parse_ts(snapshot.get("timestamp"))
        left = snapshot.get("left") or {}
        right = snapshot.get("right") or {}
        meta = {
            "source": "spread_arbitrage_v1",
            "pair_id": pair_id,
            "net_edge_bps": net_edge_bps,
        }
        opportunity_side = snapshot.get("opportunity_side")
        if opportunity_side == "long_right_short_left":
            left_side, right_side = "sell", "buy"
        else:
            left_side, right_side = "buy", "sell"

        def leg(ref: dict, side: str, bid: Any, ask: Any) -> SimSignal:
            bid_f = _positive(bid)
            ask_f = _positive(ask)
            mid = (bid_f + ask_f) / 2 if bid_f and ask_f else None
            return SimSignal(
                instrument_id=self.instrument_id(ref),
                side=side,
                confidence=confidence,
                bid=bid_f,
                ask=ask_f,
                mid=mid,
                timestamp=ts,
                signal_meta=dict(meta),
            )

        return [
            leg(left, left_side, snapshot.get("left_bid"), snapshot.get("left_ask")),
            leg(right, right_side, snapshot.get("right_bid"), snapshot.get("right_ask")),
        ]


class MomentumSignalSource:
    """Self-contained dual moving-average momentum on feature snapshots.

    Strictly causal: on every snapshot the newest mid price is appended to a
    per-instrument rolling window (capped at ``slow_window``), and a signal is
    emitted only once the window is full. The fast SMA (last ``fast_window``
    prices) is compared to the slow SMA (whole window); a fast average above
    the slow one is an up-trend (buy), below is a down-trend (sell). Only past
    and current prices are ever used, so there is no look-ahead. A minimum
    separation gate (``min_separation_bps``) suppresses noise when the two
    averages are effectively equal.
    """

    topics = (Topics.FEATURE_SNAPSHOT,)

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.fast_window = max(1, int(config.get("fast_window", 3)))
        self.slow_window = max(self.fast_window + 1, int(config.get("slow_window", 8)))
        self.min_separation_bps = float(config.get("min_separation_bps", 5.0))
        self.confidence = float(config.get("momentum_confidence", 0.7))
        self.invert_signal = bool(config.get("invert_signal", False))
        self._prices: dict[str, list[float]] = {}

    @staticmethod
    def _reference_mid(snapshot: dict) -> float | None:
        mid = _positive(snapshot.get("mid_price"))
        if mid is not None:
            return mid
        bid = _positive(snapshot.get("bid_price"))
        ask = _positive(snapshot.get("ask_price"))
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        return None

    async def on_snapshot(self, topic: str, snapshot: dict) -> list[SimSignal]:
        instrument = str(snapshot.get("market_id", "unknown"))
        mid = self._reference_mid(snapshot)
        if mid is None:
            return []
        history = self._prices.setdefault(instrument, [])
        history.append(mid)
        if len(history) > self.slow_window:
            del history[: len(history) - self.slow_window]
        if len(history) < self.slow_window:
            return []

        fast = sum(history[-self.fast_window :]) / self.fast_window
        slow = sum(history) / len(history)
        if slow <= 0:
            return []
        separation_bps = (fast - slow) / slow * 10_000.0
        if abs(separation_bps) < self.min_separation_bps:
            return []

        bullish = separation_bps > 0
        if self.invert_signal:
            bullish = not bullish
        side = "buy" if bullish else "sell"
        confidence = min(1.0, self.confidence + min(abs(separation_bps) / 1_000.0, 0.29))
        return [
            SimSignal(
                instrument_id=instrument,
                side=side,
                confidence=confidence,
                bid=_positive(snapshot.get("bid_price")),
                ask=_positive(snapshot.get("ask_price")),
                mid=mid,
                bid_depth=_positive(snapshot.get("bid_size")),
                ask_depth=_positive(snapshot.get("ask_size")),
                timestamp=_parse_ts(snapshot.get("timestamp")),
                signal_meta={
                    "source": "momentum_dualma_v1",
                    "fast_ma": fast,
                    "slow_ma": slow,
                    "separation_bps": separation_bps,
                    "invert_signal": self.invert_signal,
                },
            )
        ]


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


__all__ = [
    "FusionSignalSource",
    "MomentumSignalSource",
    "PairSpreadSignalSource",
    "SignalSource",
    "SimSignal",
    "SpreadReversionSignalSource",
]
