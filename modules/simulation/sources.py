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
import math
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
        feature_weights = {
            name: float(self.fusion.weights.get(name, self.fusion.injected_signal_weight))
            for name in scores
        }
        feature_scores = {
            name: {
                "direction": int(sub.direction),
                "strength": float(sub.strength),
            }
            for name, sub in scores.items()
        }
        # Keep the raw numerical inputs that were actually available at the
        # decision timestamp. This is a descriptive snapshot, not a claim that
        # the raw feature caused the eventual PnL.
        feature_values = {
            key: float(value)
            for key, value in features.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value))
            and key not in {"timestamp"}
        }
        weighted_contributions = {
            name: weight * feature_scores[name]["direction"] * feature_scores[name]["strength"]
            for name, weight in feature_weights.items()
        }
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
                    "feature_weights": feature_weights,
                    "feature_scores": feature_scores,
                    "feature_values": feature_values,
                    "weighted_contributions": weighted_contributions,
                    "attribution_method": "model_weighted_signal_contribution",
                    "causal_claim": False,
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


class DeepDrawdownSignalSource:
    """Causal staged rebound candidate for paper-kernel research only.

    The source observes only closes seen so far.  A new episode is created when
    the close first falls at least ``drawdown_fraction`` below the expanding
    prior peak.  It then emits target-fraction signals on the next bar and the
    configured tranche offsets, followed by a target-zero exit after the
    configured holding period.  It deliberately does not infer fundamentals,
    liquidity or historical executable quotes; callers must keep those gates
    explicit and fail closed.
    """

    topics = (Topics.FEATURE_SNAPSHOT,)

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.drawdown_fraction = max(0.0, min(1.0, float(config.get("drawdown_fraction", 0.50))))
        offsets = config.get("tranche_delays_days", (0, 5, 20))
        self.tranche_delays_days = tuple(max(0, int(value)) for value in offsets)
        self.hold_days = max(1, int(config.get("hold_days", 63)))
        self.max_nav_fraction = max(0.0, min(1.0, float(config.get("max_nav_fraction", 0.05))))
        self.confidence = float(config.get("rebound_confidence", 0.7))
        self.confirmation_bars = max(0, int(config.get("confirmation_bars", 0)))
        self.probe_fraction = max(0.0, min(1.0, float(config.get("probe_fraction", 0.0))))
        self._index: dict[str, int] = {}
        self._prior_peak: dict[str, float] = {}
        self._prior_mid: dict[str, float] = {}
        self._triggered: dict[str, bool] = {}
        self._confirmation_count: dict[str, int] = {}
        self._pending_event: dict[str, dict[str, Any]] = {}
        self._active_until: dict[str, int] = {}
        self._pending: dict[str, list[dict[str, Any]]] = {}

    async def on_snapshot(self, topic: str, snapshot: dict) -> list[SimSignal]:
        instrument = str(snapshot.get("market_id", "unknown"))
        mid = MomentumSignalSource._reference_mid(snapshot)
        timestamp = _parse_ts(snapshot.get("timestamp"))
        if mid is None or timestamp is None:
            return []
        index = self._index.get(instrument, -1) + 1
        self._index[instrument] = index
        pending = self._pending.setdefault(instrument, [])
        due = [item for item in pending if int(item["due_index"]) <= index]
        self._pending[instrument] = [item for item in pending if int(item["due_index"]) > index]
        signals: list[SimSignal] = []
        for item in sorted(due, key=lambda value: int(value["due_index"])):
            target = float(item["target_fraction"])
            side = "buy" if target > 0 else "sell"
            signals.append(SimSignal(
                instrument_id=instrument,
                side=side,
                confidence=self.confidence,
                bid=_positive(snapshot.get("bid_price")),
                ask=_positive(snapshot.get("ask_price")),
                mid=mid,
                bid_depth=_positive(snapshot.get("bid_size")),
                ask_depth=_positive(snapshot.get("ask_size")),
                timestamp=timestamp,
                signal_meta={
                    "source": "deep_drawdown_rebound_v1",
                    "event_id": item["event_id"],
                    "tranche": item.get("tranche"),
                    "target_fraction": target,
                    "position_fraction": target,
                    "event_index": item.get("event_index"),
                    "event_date": item.get("event_date"),
                    "trigger_date": item.get("trigger_date"),
                    "confirmation_bars": item.get("confirmation_bars", self.confirmation_bars),
                    "hold_days": self.hold_days,
                    "causal_claim": False,
                    "evidence_status": "UNKNOWN_NO_TRADE",
                },
            ))
        prior_peak = self._prior_peak.get(instrument)
        triggered = (
            prior_peak is not None
            and mid <= prior_peak * (1.0 - self.drawdown_fraction)
        )
        if triggered and not self._triggered.get(instrument, False) and index >= self._active_until.get(instrument, -1):
            self._triggered[instrument] = True
            self._pending_event[instrument] = {
                "event_id": f"{instrument}:{index}",
                "trigger_index": index,
                "trigger_date": timestamp.isoformat(),
                "trigger_close": mid,
            }
            self._confirmation_count[instrument] = 0
            if self.confirmation_bars > 0 and self.probe_fraction > 0:
                denominator = max(1, len(self.tranche_delays_days))
                probe_target = self.max_nav_fraction * min(
                    self.probe_fraction, 1.0 / denominator
                )
                probe_entry = index + 1
                probe_exit = probe_entry + self.hold_days
                self._pending[instrument].append({
                    "due_index": probe_entry,
                    "target_fraction": probe_target,
                    "event_id": self._pending_event[instrument]["event_id"],
                    "tranche": "probe",
                    "event_index": index,
                    "event_date": timestamp.isoformat(),
                    "trigger_date": timestamp.isoformat(),
                    "confirmation_bars": self.confirmation_bars,
                })
                self._pending[instrument].append({
                    "due_index": probe_exit,
                    "target_fraction": 0.0,
                    "event_id": self._pending_event[instrument]["event_id"],
                    "tranche": "exit_probe",
                    "event_index": index,
                    "event_date": timestamp.isoformat(),
                    "trigger_date": timestamp.isoformat(),
                    "confirmation_bars": self.confirmation_bars,
                })
                self._pending_event[instrument]["probe"] = True
        pending_event = self._pending_event.get(instrument)
        if pending_event is not None:
            prior_mid = self._prior_mid.get(instrument)
            if index > int(pending_event["trigger_index"]):
                if prior_mid is not None and mid > prior_mid:
                    self._confirmation_count[instrument] = self._confirmation_count.get(instrument, 0) + 1
                else:
                    self._confirmation_count[instrument] = 0
            confirmed = (
                self.confirmation_bars == 0
                or self._confirmation_count.get(instrument, 0) >= self.confirmation_bars
            )
            if confirmed and (
                self.confirmation_bars == 0
                or index > int(pending_event["trigger_index"])
            ):
                event_id = str(pending_event["event_id"])
                pending_event = {
                    **pending_event,
                    "event_index": index,
                    "event_date": timestamp.isoformat(),
                    "confirmation_bars": self.confirmation_bars,
                }
                self._pending_event.pop(instrument, None)
                last_exit = index
                denominator = max(1, len(self.tranche_delays_days))
                start_tranche = 2 if pending_event.get("probe") else 1
                remaining_offsets = self.tranche_delays_days[start_tranche - 1:]
                if remaining_offsets:
                    first_offset = remaining_offsets[0]
                    remaining_offsets = tuple(
                        offset - first_offset for offset in remaining_offsets
                    )
                for tranche, offset in enumerate(
                    remaining_offsets, start=start_tranche
                ):
                    entry_index = index + 1 + offset
                    exit_index = entry_index + self.hold_days
                    last_exit = max(last_exit, exit_index)
                    self._pending[instrument].append({
                        "due_index": entry_index,
                        "target_fraction": self.max_nav_fraction * tranche / denominator,
                        "event_id": event_id,
                        "tranche": tranche,
                        "event_index": index,
                        "event_date": timestamp.isoformat(),
                        "trigger_date": pending_event["trigger_date"],
                        "confirmation_bars": self.confirmation_bars,
                    })
                    self._pending[instrument].append({
                        "due_index": exit_index,
                        "target_fraction": 0.0,
                        "event_id": event_id,
                        "tranche": f"exit_{tranche}",
                        "event_index": index,
                        "event_date": timestamp.isoformat(),
                        "trigger_date": pending_event["trigger_date"],
                        "confirmation_bars": self.confirmation_bars,
                    })
                self._active_until[instrument] = last_exit
        elif not triggered:
            self._triggered[instrument] = False
            self._confirmation_count[instrument] = 0
        self._prior_mid[instrument] = mid
        self._prior_peak[instrument] = max(prior_peak or mid, mid)
        return signals


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


__all__ = [
    "DeepDrawdownSignalSource",
    "FusionSignalSource",
    "MomentumSignalSource",
    "PairSpreadSignalSource",
    "SignalSource",
    "SimSignal",
    "SpreadReversionSignalSource",
]
