"""《炒股的智慧》(陈江挺) — critical-point signals as a reusable module.

The book's core claim is that price movement is a record of crowd psychology,
and that the moments worth trading are 临界点 ("critical points") — the points at
which the public re-evaluates a stock. That framing matches what this project
found empirically: generic chart patterns produced nothing across 184 tested
configurations, while every edge that survived (dragon-tiger attention reversal,
insider clusters, retail crowding) was a crowd-psychology signal.

Implemented here, each with the book's own stop-loss rule attached:

- **Uptrend continuation** — buy the break above the prior swing high; the trend
  is invalidated if price then breaks the prior swing low.
- **Resistance breakout** — buy the break of resistance, but only on expanding
  volume; the book is explicit that a breakout without volume "has no meaning".
- **False breakdown reversal** — price breaks support on heavy volume then snaps
  back above it. The author calls this his highest-conviction setup ("nine times
  out of ten I make money"), reading it as a large operator manufacturing panic
  to accumulate.
- **Parabolic exhaustion (exit)** — after a near-vertical run, the first down
  close is the exit; "don't expect good things to go on forever".
- **Distribution (exit)** — volume surges while price stalls: someone is selling
  into strength.
- **Trailing stop** — ratchet the stop up to each successive swing low, which is
  how the book proposes to "抓中间70%" of a move without guessing the top.

Position sizing follows the book too: capital in ten parts, one part per idea,
a minimum 1:3 risk/reward, and a stop no wider than 10% (20% absolute maximum).

Important caveat, in the author's own words: "股票买卖的思维方式不是机械式的" —
these mechanical rules are an entry point, not a system. Signals from this module
are candidate observations for review, and like anything else here they must
clear the promotion gate on real data before they may drive live intents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

import numpy as np


class SignalKind(str, Enum):
    UPTREND_BREAKOUT = "uptrend_breakout"
    RESISTANCE_BREAKOUT = "resistance_breakout"
    FALSE_BREAKDOWN = "false_breakdown"
    PARABOLIC_EXHAUSTION = "parabolic_exhaustion"
    DISTRIBUTION = "distribution"


class Direction(str, Enum):
    BUY = "buy"
    EXIT = "exit"


# What this project measured when it tested the book's boldest claim.
#
# 《炒股的智慧》 calls the false breakdown its highest-conviction setup and says it
# wins "十次有九次" — nine times in ten. Measured on real data across all three
# instrument domains (scripts/false_breakdown_experiment.py, results in
# data/false_breakdown_results.json), it does not:
#
#   假突破反转(全部)      n=2557  平均超额 -0.26%  胜率 45.8%  t=-2.19 (门槛 3.68)
#   └ 放量确认子集        n=1007  平均超额 -0.47%  胜率 45.9%
#   对照:破位未收回       n=2254  平均超额 -0.31%  胜率 45.7%
#   对照:无条件基准率    n=23720  平均超额 -0.23%  胜率 45.2%
#
# The signal group is indistinguishable from both controls, so the pattern
# carries no information — the "recovery" that supposedly makes it special
# performs the same as a breakdown that never recovered. The volume-confirmed
# subset, which the book singles out as the strongest, is the *worst* of the
# three. And the unconditional base rate is negative by roughly one round trip's
# cost, which is the sanity check that the machinery itself is unbiased.
#
# The signal is kept, surfaced, and labelled with this measurement rather than
# deleted: seeing a pattern fire and knowing it has been tested and failed is
# more useful than not seeing it at all. 「知错却不肯认错就更加不可救药。」
FALSE_BREAKDOWN_EVIDENCE = {
    "n": 2557,
    "win_rate": 0.458,
    "mean_excess": -0.0026,
    "t_clustered": -2.19,
    "t_hurdle": 3.68,
    "confirmed": False,
    "source": "scripts/false_breakdown_experiment.py",
}

# The book's stop-loss discipline: 10% preferred, 20% is the hard ceiling.
DEFAULT_STOP_PCT = 0.10
MAX_STOP_PCT = 0.20
MIN_RISK_REWARD = 3.0        # "至少 1:3 的风险报酬比"
CAPITAL_PARTS = 10           # "把手头的资本分成 10 份"


@dataclass(frozen=True)
class WisdomSignal:
    kind: SignalKind
    direction: Direction
    index: int                    # bar the signal fires on
    price: float
    stop_price: float | None
    confidence: float             # 0..1, from how many book conditions are met
    rationale_zh: str
    rationale_en: str
    volume_confirmed: bool = False

    @property
    def stop_pct(self) -> float | None:
        if self.stop_price is None or self.price <= 0:
            return None
        return abs(self.price - self.stop_price) / self.price

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value, "direction": self.direction.value,
            "index": self.index, "price": round(self.price, 6),
            "stop_price": round(self.stop_price, 6) if self.stop_price else None,
            "stop_pct": round(self.stop_pct, 4) if self.stop_pct else None,
            "confidence": round(self.confidence, 3),
            "volume_confirmed": self.volume_confirmed,
            "rationale_zh": self.rationale_zh, "rationale_en": self.rationale_en,
        }


@dataclass
class Bars:
    """Minimal OHLCV container so any instrument can feed this module."""

    closes: Sequence[float]
    highs: Sequence[float] | None = None
    lows: Sequence[float] | None = None
    opens: Sequence[float] | None = None
    volumes: Sequence[float] | None = None
    dates: Sequence[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.closes)

    def as_arrays(self):
        close = np.asarray(self.closes, dtype=float)
        high = np.asarray(self.highs, dtype=float) if self.highs is not None else close
        low = np.asarray(self.lows, dtype=float) if self.lows is not None else close
        open_ = np.asarray(self.opens, dtype=float) if self.opens is not None else close
        volume = (np.asarray(self.volumes, dtype=float)
                  if self.volumes is not None else np.zeros_like(close))
        return close, high, low, open_, volume


# ------------------------------------------------------------------ helpers
def swing_points(values: np.ndarray, window: int = 5) -> tuple[list[int], list[int]]:
    """Indices of swing highs and lows — the 波峰/波谷 the book reasons about."""
    highs: list[int] = []
    lows: list[int] = []
    for i in range(window, len(values) - window):
        segment = values[i - window : i + window + 1]
        if values[i] == segment.max() and (values[i] > values[i - 1] or values[i] > values[i + 1]):
            highs.append(i)
        if values[i] == segment.min() and (values[i] < values[i - 1] or values[i] < values[i + 1]):
            lows.append(i)
    return highs, lows


def _volume_ratio(volume: np.ndarray, i: int, window: int = 20) -> float:
    if i < window or volume[max(0, i - window):i].sum() <= 0:
        return 1.0
    baseline = float(volume[i - window : i].mean())
    return float(volume[i] / baseline) if baseline > 0 else 1.0


def _clamped_stop(entry: float, raw_stop: float) -> float:
    """Never risk more than the book's ceiling, however far the structure sits."""
    if entry <= 0:
        return raw_stop
    floor = entry * (1.0 - MAX_STOP_PCT)
    return max(raw_stop, floor)


# ------------------------------------------------------------------ signals
def detect_signals(bars: Bars, window: int = 5, lookback: int = 60) -> list[WisdomSignal]:
    """All critical-point signals on the most recent bar of ``bars``.

    Only the final bar is evaluated, so the result is exactly what a trader could
    have acted on at that moment — the function is causal by construction.
    """
    close, high, low, open_, volume = bars.as_arrays()
    n = len(close)
    if n < max(window * 3, 25):
        return []

    i = n - 1
    signals: list[WisdomSignal] = []
    peaks, troughs = swing_points(close[:i], window=window)
    vol_ratio = _volume_ratio(volume, i)
    volume_ok = vol_ratio >= 1.2      # "只有在交易量增加的前提下"

    # 1) Uptrend continuation: break the prior swing high, stop under prior low.
    if len(peaks) >= 1 and len(troughs) >= 1:
        prior_high = close[peaks[-1]]
        prior_low = close[troughs[-1]]
        rising = len(peaks) >= 2 and close[peaks[-1]] > close[peaks[-2]]
        if close[i] > prior_high and prior_low < prior_high:
            confidence = 0.5 + (0.2 if rising else 0.0) + (0.2 if volume_ok else 0.0)
            signals.append(WisdomSignal(
                kind=SignalKind.UPTREND_BREAKOUT, direction=Direction.BUY, index=i,
                price=float(close[i]), stop_price=_clamped_stop(close[i], float(prior_low)),
                confidence=min(confidence, 1.0), volume_confirmed=volume_ok,
                rationale_zh=f"升势突破前高 {prior_high:.4g}，止损设在前低 {prior_low:.4g} 之下",
                rationale_en=f"Broke prior swing high {prior_high:.4g}; stop below prior low {prior_low:.4g}",
            ))

    # 2) Resistance breakout — resistance = recent congestion high.
    resistance = float(np.max(high[max(0, i - lookback) : i]))
    if close[i] > resistance > 0 and close[i - 1] <= resistance:
        signals.append(WisdomSignal(
            kind=SignalKind.RESISTANCE_BREAKOUT, direction=Direction.BUY, index=i,
            price=float(close[i]),
            stop_price=_clamped_stop(close[i], resistance * 0.97),
            confidence=0.75 if volume_ok else 0.35, volume_confirmed=volume_ok,
            rationale_zh=(f"突破阻力线 {resistance:.4g}"
                          + ("，成交量放大确认" if volume_ok else "，但成交量未放大（书中：无意义）")),
            rationale_en=(f"Broke resistance {resistance:.4g}"
                          + (" on expanding volume" if volume_ok
                             else " WITHOUT volume — the book calls this meaningless")),
        ))

    # 3) False breakdown — the author's highest-conviction setup, and the one
    #    claim in this book that this project has measured and *falsified*.
    #    See FALSE_BREAKDOWN_EVIDENCE below and scripts/false_breakdown_experiment.py.
    support = float(np.min(low[max(0, i - lookback) : i - 2])) if i > 5 else 0.0
    if support > 0:
        broke = np.any(low[max(0, i - 3) : i + 1] < support)
        recovered = close[i] > support
        if broke and recovered:
            # Confidence reflects the measurement, not the claim. Volume
            # confirmation *lowers* it: the volume-confirmed subset was the
            # worst-performing of all (-0.47%, 45.9% win rate).
            confidence = 0.15 if volume_ok else 0.2
            signals.append(WisdomSignal(
                kind=SignalKind.FALSE_BREAKDOWN, direction=Direction.BUY, index=i,
                price=float(close[i]), stop_price=_clamped_stop(close[i], support * 0.97),
                confidence=confidence, volume_confirmed=volume_ok,
                rationale_zh=(f"跌穿支撑 {support:.4g} 后收回"
                              + ("（放量）" if volume_ok else "（未放量）")
                              + f"。⚠️ 书中称「十次有九次赚钱」，"
                                f"但本项目在 {FALSE_BREAKDOWN_EVIDENCE['n']} 个真实事件上实测"
                                f"胜率仅 {FALSE_BREAKDOWN_EVIDENCE['win_rate']*100:.1f}%，"
                                f"与「破位未收回」对照组无区别——该形态未被证实"),
                rationale_en=(f"Broke support {support:.4g} then reclaimed it"
                              + (" on volume" if volume_ok else " without volume")
                              + f". ⚠️ The book claims 9-in-10; measured on "
                                f"{FALSE_BREAKDOWN_EVIDENCE['n']} real events the win rate is "
                                f"{FALSE_BREAKDOWN_EVIDENCE['win_rate']*100:.1f}% and "
                                f"indistinguishable from the control — unconfirmed"),
            ))

    # 4) Parabolic exhaustion (exit): steep run, then the first down close.
    if i >= 10:
        run = close[i] / close[i - 10] - 1.0 if close[i - 10] > 0 else 0.0
        first_down = close[i] < open_[i]
        if run > 0.5 and first_down:
            signals.append(WisdomSignal(
                kind=SignalKind.PARABOLIC_EXHAUSTION, direction=Direction.EXIT, index=i,
                price=float(close[i]), stop_price=None, confidence=0.8,
                volume_confirmed=volume_ok,
                rationale_zh=f"十日暴涨 {run*100:.0f}% 后首根阴线——书中「遇到暴利，拿了再说」",
                rationale_en=f"Up {run*100:.0f}% in 10 bars then first down close — take the windfall",
            ))

    # 5) Distribution (exit): volume surges while price stalls.
    if i >= 25:
        recent_gain = close[i] / close[i - 20] - 1.0 if close[i - 20] > 0 else 0.0
        stalled = abs(close[i] / close[i - 3] - 1.0) < 0.02 if close[i - 3] > 0 else False
        if recent_gain > 0.1 and vol_ratio > 1.8 and stalled:
            signals.append(WisdomSignal(
                kind=SignalKind.DISTRIBUTION, direction=Direction.EXIT, index=i,
                price=float(close[i]), stop_price=None, confidence=0.7,
                volume_confirmed=True,
                rationale_zh=f"成交量放大 {vol_ratio:.1f} 倍但价格滞涨——有人出货",
                rationale_en=f"Volume {vol_ratio:.1f}x but price stalled — distribution",
            ))

    return signals


def trailing_stop(bars: Bars, entry_index: int, window: int = 5) -> float | None:
    """Ratchet the stop up to the latest swing low after entry (移动止损).

    This is the book's method for holding a trend without predicting its top —
    the stop only ever moves up, never down.
    """
    close, _high, _low, _open, _volume = bars.as_arrays()
    if entry_index >= len(close) - 1:
        return None
    _peaks, troughs = swing_points(close, window=window)
    after = [close[t] for t in troughs if t > entry_index]
    if not after:
        return _clamped_stop(float(close[entry_index]),
                             float(close[entry_index]) * (1 - DEFAULT_STOP_PCT))
    return float(max(after))          # highest swing low so far = current stop


def position_size(
    capital: float | None, entry: float, stop: float, target: float | None = None
) -> dict:
    """The book's sizing rule: one of ten parts, and only at 1:3 or better.

    ``capital`` may be ``None``, meaning nobody has told this process how large
    the account is. In that case the rule is still reported — one tenth of equity,
    with the risk as a percentage — but no allocation, share count or dollar risk
    is produced. Those are the fields that look like measurements, and a caller
    that supplies an invented equity gets an exact share count for an account that
    does not exist. Missing must stay missing, here as everywhere else.
    """
    if entry <= 0 or stop <= 0 or stop >= entry:
        return {"allowed": False, "reason": "invalid entry/stop"}
    risk_pct = (entry - stop) / entry
    if risk_pct > MAX_STOP_PCT:
        return {"allowed": False, "reason": f"stop {risk_pct:.1%} exceeds the {MAX_STOP_PCT:.0%} ceiling"}
    reward_ratio = ((target - entry) / (entry - stop)) if target else None
    if reward_ratio is not None and reward_ratio < MIN_RISK_REWARD:
        return {"allowed": False, "reason": f"risk/reward {reward_ratio:.1f} below 1:{MIN_RISK_REWARD:.0f}"}

    known = capital is not None and capital > 0
    allocation = (capital / CAPITAL_PARTS) if known else None
    return {
        "allowed": True,
        # The rule, which is always knowable.
        "capital_fraction": round(1.0 / CAPITAL_PARTS, 4),
        "risk_pct": round(risk_pct, 4),
        "risk_fraction_of_equity": round(risk_pct / CAPITAL_PARTS, 5),
        "reward_ratio": round(reward_ratio, 2) if reward_ratio else None,
        # The amounts, which are only knowable with a real account size.
        "capital": round(float(capital), 2) if known else None,
        "allocation": round(allocation, 2) if allocation is not None else None,
        "shares": int(allocation // entry) if allocation is not None else None,
        "risk_amount": round(allocation * risk_pct, 2) if allocation is not None else None,
        "capital_known": known,
        "note": (
            "one of ten parts, per 分散风险"
            if known
            else "one of ten parts, per 分散风险 — 未配置账户权益,只给比例不给股数"
        ),
    }


__all__ = [
    "Bars", "Direction", "SignalKind", "WisdomSignal",
    "detect_signals", "position_size", "swing_points", "trailing_stop",
]
