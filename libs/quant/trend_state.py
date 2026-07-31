"""趋势状态判定 — multi-timeframe returns fused with a moving-average system.

《炒股的智慧》 is unambiguous about direction: **"绝不要在跌势时入市"** (never enter
during a downtrend) and **"最好在升势或突破阻力线时买入"** (buy in an uptrend or on a
break of resistance). Until now nothing in this repo answered the prior question
those rules depend on — *which way is this instrument actually trending?* — so
:mod:`libs.quant.verdict` could reach ACT on a stock in free fall. This module
supplies that missing read.

The specification, and why each number is what it is
====================================================

Two independent lenses on the same latent quantity (the sign and strength of
drift), combined 50/50, each producing a score in ``[-1, +1]``.

**Block A — multi-timeframe returns (weight 0.50).** Horizons 1w / 1m / 2m / 3m
/ 6m / 1y, i.e. 5 / 21 / 42 / 63 / 126 / 252 trading days.

*Why these horizons carry different weight.* Moskowitz, Ooi & Pedersen (2012,
JFE 104(2) 228-250, "Time Series Momentum") document that an instrument's own
past 1-to-12-month return positively predicts its next-month return across all
58 futures they test, with the effect persisting about a year before partially
reversing. Jegadeesh (1990) documents the opposite at very short horizons —
weekly/monthly returns *reverse*. So the horizons are not interchangeable and a
flat average would be wrong.

*The weighting rule is derived, not chosen.* Under a drift-plus-noise model
(``r_t = mu + sigma * eps_t``), the cumulative return over ``h`` days has mean
``mu*h`` and standard deviation ``sigma*sqrt(h)``; its signal-to-noise ratio
therefore grows as ``sqrt(h)``. Weighting each horizon by ``sqrt(h)`` and
normalising is exactly "weight each observation by the information it carries".
That yields 1w 4.6%, 1m 9.5%, 2m 13.4%, 3m 16.4%, 6m 23.2%, 1y 32.8% — a
monotone profile that matches the TSMOM evidence (the 12-month read dominates)
and leaves the 1-week return with too little weight to flip a state on its own,
which is the correct treatment given short-horizon reversal. No number here was
fitted to any price series.

*Each horizon is volatility-normalised before it is scored.* The raw return is
divided by ``sigma_daily * sqrt(h)`` to give a t-like statistic, so a 10% move
in a 60%-vol altcoin is not read as the same evidence as a 10% move in a
utility. The statistic is squashed with ``tanh(t/2)``: at the conventional
two-sigma threshold ``t = 2`` the component reads 0.76, and it saturates
thereafter so one violent horizon cannot dominate the other five.

**Block B — the moving-average system (weight 0.50).** Returns alone describe
endpoints; moving averages describe the *path*, and the price-versus-long-MA
regime filter is the most heavily documented trend rule in the literature
(Faber 2007, "A Quantitative Approach to Tactical Asset Allocation", J. Wealth
Management — itself following Siegel's 200-day test on the Dow back to 1886).
Four components, weights inside the block:

- ``price`` vs ``MA200``       0.40 — the Faber/Siegel filter, the single
  most-tested regime read, so it carries the most weight.
- stacked ``price>MA20>MA50>MA200``  0.25 — the classic full alignment; +1 when
  fully bullish-stacked, -1 when fully bearish-stacked, 0 when tangled.
- ``MA50`` vs ``MA200``        0.20 — golden/death cross.
- ``MA200`` slope over 20 bars 0.15 — a rising long average distinguishes a
  genuine regime from a price that merely poked above a flat one.

The last three are functions of the same two averages as the first, so they get
progressively less weight: they add confirmation, not independent evidence.

*The comparisons are banded, not binary.* A price 0.05% above its MA200 is not
the same evidence as one 15% above it, and reading both as ``+1`` would let a
hairline crossing swing 20% of the total score. Siegel's own formulation of the
200-day rule used a 1% band (buy only 1% above the average, sell only 1% below),
so a band is the cited treatment rather than an invention. Here each gap is
divided by ``band = max(1%, sigma_daily * sqrt(20))`` — Siegel's 1% floor,
widened to "one month of ordinary noise" for volatile instruments — and clamped
to ``[-1, +1]``. The MA200 slope gets ``0.1 * band``, which is not a second
guess: ``SMA200(t) - SMA200(t-20)`` equals ``0.1 x`` the difference of two
20-day means, so its natural scale is exactly a tenth of the price-level band.
The stacked-alignment component stays a strict ordering, because three smoothed
averages do not change order on a hairline the way a raw price does.

**Block weighting is 50/50 on purpose.** There is no out-of-sample evidence in
this repo that either lens dominates the other, and equal weighting beats
estimated "optimal" weights out of sample often enough to be the default
(DeMiguel, Garlappi & Uppal, 2009, "Optimal Versus Naive Diversification").
Anything else would be a number invented to fit a story.

**Classification.** The combined raw score lives in ``[-1, +1]`` and is reported
to callers rescaled to ``[0, 1]`` (``score = (raw + 1) / 2``, so 0.5 is dead
neutral). Thresholds are stated as *fractions of evidence weight*, not as fitted
constants: a raw score of ``+0.15`` means roughly 57.5% of the evidence weight
points up (better than a coin flip); ``+0.50`` means a 75/25 supermajority.

- ``strong_uptrend``   raw >= +0.50 **and** fully bullish-stacked MAs
- ``uptrend``          raw >= +0.15 **and** price > MA200
- ``strong_downtrend`` raw <= -0.50 **and** fully bearish-stacked MAs
- ``downtrend``        raw <= -0.15, **or** (price < MA200 and raw < 0)
- ``neutral``          everything else

The asymmetry is deliberate and fail-closed: "strong" requires the MA system to
confirm the momentum, while a downtrend triggers on either lens alone. Stated
plainly, *below the 200-day average with any net-negative evidence is a
downtrend* — that is Faber's binary filter and the book's prohibition taken at
face value, and it is intentionally easier to trigger than an uptrend, because
the cost of missing a downtrend (entering one, which the book forbids outright)
is far larger than the cost of sitting out a chop.

**Insufficient history is not neutrality.** Below 200 bars there is no MA200 and
therefore no regime read, so the classification is ``unknown`` — never a silent
``neutral``. Horizons longer than the available history are reported as ``None``
and their weight is redistributed across the horizons that do exist.

**Causality.** ``classify_trend`` reads only ``closes[:len(bars)]``; every
statistic ends at the last supplied bar. It is proven causal in
``tests/test_trend_state.py`` with :func:`libs.quant.pit.assert_no_lookahead`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, Sequence, runtime_checkable


class TrendClass(str, Enum):
    STRONG_UPTREND = "strong_uptrend"
    UPTREND = "uptrend"
    NEUTRAL = "neutral"
    DOWNTREND = "downtrend"
    STRONG_DOWNTREND = "strong_downtrend"
    UNKNOWN = "unknown"          # not enough history — never a silent "neutral"


@runtime_checkable
class _BarsLike(Protocol):
    """The shape of :class:`libs.data.real_sources.DailyBars` we actually need."""

    closes: Sequence[float]
    dates: Sequence[str]


# Trading-day lookbacks. Calendar-week/month labels, trading-day arithmetic —
# the series we consume are trading days, not calendar days.
HORIZONS: dict[str, int] = {"1w": 5, "1m": 21, "2m": 42, "3m": 63, "6m": 126, "1y": 252}

# Without MA200 there is no regime read at all, so this is a hard floor.
MIN_BARS = 200

# Moving-average block weights — see the module docstring for the rationale.
_MA_WEIGHTS = {"price_vs_ma200": 0.40, "stacked": 0.25, "ma50_vs_ma200": 0.20,
               "ma200_slope": 0.15}
_MA_SLOPE_LOOKBACK = 20
# Siegel's 1% band around the 200-day average, widened to a month of noise.
_MIN_BAND = 0.01
_BAND_LOOKBACK = 20
# SMA200(t) - SMA200(t-20) is 0.1x the difference of two 20-day means.
_SLOPE_BAND_RATIO = _MA_SLOPE_LOOKBACK / 200.0

# Evidence-majority thresholds, in raw-score space.
_STRONG = 0.50                    # a 75/25 supermajority of the evidence weight
_LEAN = 0.15                      # a 57.5/42.5 majority — better than a coin flip


@dataclass(frozen=True)
class TrendState:
    """A trend classification plus every number that produced it."""

    classification: TrendClass
    score: float                                 # 0..1, 0.5 = neutral
    raw_score: float                             # -1..1, the pre-rescale value
    returns: dict[str, float | None]             # "1w".."1y" -> simple return
    ma: dict[str, float | None]                  # price / ma20 / ma50 / ma200 / slope
    aligned: bool                                # price > MA20 > MA50 > MA200
    alignment: int                               # +1 bullish, -1 bearish, 0 tangled
    bars: int
    as_of: str | None
    evidence_zh: str
    evidence_en: str
    momentum_score: float = 0.0                  # block A, -1..1
    ma_score: float = 0.0                        # block B, -1..1
    components: dict[str, float] = field(default_factory=dict)

    @property
    def blocks_act(self) -> bool:
        """True when the book's rule forbids entering here (跌势时不入市)."""
        return self.classification in (TrendClass.DOWNTREND, TrendClass.STRONG_DOWNTREND)

    @property
    def supports_act(self) -> bool:
        return self.classification in (TrendClass.UPTREND, TrendClass.STRONG_UPTREND)

    def to_dict(self) -> dict[str, Any]:
        """The wire contract consumed by ``/api/verdict`` and the dashboard."""
        return {
            "classification": self.classification.value,
            "score": round(self.score, 4),
            "returns": {k: (None if v is None else round(v, 6)) for k, v in self.returns.items()},
            "ma": {k: (None if v is None else round(v, 6)) for k, v in self.ma.items()},
            "aligned": self.aligned,
            "evidence_zh": self.evidence_zh,
            "evidence_en": self.evidence_en,
            "raw_score": round(self.raw_score, 4),
            "momentum_score": round(self.momentum_score, 4),
            "ma_score": round(self.ma_score, 4),
            "bars": self.bars,
            "as_of": self.as_of,
        }


def _sma(closes: Sequence[float], window: int, offset: int = 0) -> float | None:
    """Simple moving average ending ``offset`` bars before the last bar."""
    end = len(closes) - offset
    if end - window < 0 or end <= 0:
        return None
    return sum(closes[end - window:end]) / window


def _daily_vol(closes: Sequence[float], window: int = 252) -> float:
    """Std-dev of daily log returns over the most recent ``window`` bars."""
    tail = list(closes[-(window + 1):])
    rets = [math.log(tail[i] / tail[i - 1]) for i in range(1, len(tail))
            if tail[i] > 0 and tail[i - 1] > 0]
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var)


def _ramp(gap: float, band: float) -> float:
    """A banded reading of a gap: 0 inside the noise, saturating at +/-1 outside."""
    if band <= 0:
        return 1.0 if gap > 0 else (-1.0 if gap < 0 else 0.0)
    return max(-1.0, min(1.0, gap / band))


def _unknown(bars_len: int, as_of: str | None) -> TrendState:
    return TrendState(
        classification=TrendClass.UNKNOWN, score=0.5, raw_score=0.0,
        returns={k: None for k in HORIZONS}, ma={"price": None, "ma20": None,
                                                 "ma50": None, "ma200": None,
                                                 "ma200_slope_20d": None},
        aligned=False, alignment=0, bars=bars_len, as_of=as_of,
        evidence_zh=f"历史仅 {bars_len} 根K线，不足 {MIN_BARS} 根，无法判断趋势——不猜",
        evidence_en=(f"Only {bars_len} bars of history, fewer than {MIN_BARS}; "
                     "the trend is unknown — this is not a guess"),
    )


def classify_trend(bars: Any) -> TrendState:
    """Classify the trend of ``bars`` using only data up to its last bar.

    ``bars`` may be a :class:`libs.data.real_sources.DailyBars` or anything with
    ``.closes`` (and optionally ``.dates``); ``highs``/``lows``/``volumes`` are
    accepted but unused — direction is a close-to-close question, and mixing in
    intraday extremes would add noise without adding an independent lens.
    """
    closes = [float(c) for c in getattr(bars, "closes", None) or []]
    dates = list(getattr(bars, "dates", None) or [])
    as_of = dates[-1] if dates else None
    n = len(closes)

    if n < MIN_BARS or closes[-1] <= 0:
        return _unknown(n, as_of)

    price = closes[-1]

    # --- Block A: multi-timeframe returns, volatility-normalised ------------
    returns: dict[str, float | None] = {}
    for label, h in HORIZONS.items():
        if n > h and closes[-1 - h] > 0:
            returns[label] = price / closes[-1 - h] - 1.0
        else:
            returns[label] = None

    vol = _daily_vol(closes)
    momentum = 0.0
    weight_used = 0.0
    for label, h in HORIZONS.items():
        r = returns[label]
        if r is None:
            continue                       # weight is redistributed, not defaulted
        w = math.sqrt(h)
        if vol > 0:
            t_stat = math.log1p(max(r, -0.999999)) / (vol * math.sqrt(h))
            component = math.tanh(t_stat / 2.0)
        else:
            # A noiseless path measures its own drift perfectly: t -> +/-inf.
            component = 1.0 if r > 0 else (-1.0 if r < 0 else 0.0)
        momentum += w * component
        weight_used += w
    momentum = momentum / weight_used if weight_used else 0.0

    # --- Block B: the moving-average system ---------------------------------
    ma20, ma50, ma200 = _sma(closes, 20), _sma(closes, 50), _sma(closes, 200)
    ma200_prev = _sma(closes, 200, offset=_MA_SLOPE_LOOKBACK)
    slope = None
    if ma200 is not None and ma200_prev not in (None, 0):
        slope = ma200 / ma200_prev - 1.0

    if ma20 is None or ma50 is None or ma200 is None:
        return _unknown(n, as_of)

    if price > ma20 > ma50 > ma200:
        alignment = 1
    elif price < ma20 < ma50 < ma200:
        alignment = -1
    else:
        alignment = 0

    band = max(_MIN_BAND, vol * math.sqrt(_BAND_LOOKBACK))
    components: dict[str, float] = {
        "price_vs_ma200": _ramp(price / ma200 - 1.0, band),
        "stacked": float(alignment),
        "ma50_vs_ma200": _ramp(ma50 / ma200 - 1.0, band),
        "ma200_slope": 0.0 if slope is None else _ramp(slope, band * _SLOPE_BAND_RATIO),
    }
    ma_score = sum(_MA_WEIGHTS[k] * v for k, v in components.items())

    # --- Fuse and classify ---------------------------------------------------
    raw = 0.5 * momentum + 0.5 * ma_score
    raw = max(-1.0, min(1.0, raw))

    if raw >= _STRONG and alignment == 1:
        cls = TrendClass.STRONG_UPTREND
    elif raw >= _LEAN and price > ma200:
        cls = TrendClass.UPTREND
    elif raw <= -_STRONG and alignment == -1:
        cls = TrendClass.STRONG_DOWNTREND
    elif raw <= -_LEAN or (price < ma200 and raw < 0):
        cls = TrendClass.DOWNTREND
    else:
        cls = TrendClass.NEUTRAL

    components["momentum"] = momentum
    zh, en = _evidence(cls, returns, price, ma20, ma50, ma200, slope, alignment, raw)

    return TrendState(
        classification=cls, score=(raw + 1.0) / 2.0, raw_score=raw,
        returns=returns,
        ma={"price": price, "ma20": ma20, "ma50": ma50, "ma200": ma200,
            "ma200_slope_20d": slope},
        aligned=alignment == 1, alignment=alignment, bars=n, as_of=as_of,
        evidence_zh=zh, evidence_en=en,
        momentum_score=momentum, ma_score=ma_score, components=components,
    )


_LABEL_ZH = {
    TrendClass.STRONG_UPTREND: "强升势", TrendClass.UPTREND: "升势",
    TrendClass.NEUTRAL: "无明确趋势", TrendClass.DOWNTREND: "跌势",
    TrendClass.STRONG_DOWNTREND: "强跌势", TrendClass.UNKNOWN: "未知",
}
_LABEL_EN = {
    TrendClass.STRONG_UPTREND: "strong uptrend", TrendClass.UPTREND: "uptrend",
    TrendClass.NEUTRAL: "no clear trend", TrendClass.DOWNTREND: "downtrend",
    TrendClass.STRONG_DOWNTREND: "strong downtrend", TrendClass.UNKNOWN: "unknown",
}
_STACK_ZH = {1: "均线多头排列(价>MA20>MA50>MA200)", -1: "均线空头排列(价<MA20<MA50<MA200)",
             0: "均线未形成排列"}
_STACK_EN = {1: "MAs stacked bullish (price>MA20>MA50>MA200)",
             -1: "MAs stacked bearish (price<MA20<MA50<MA200)",
             0: "MAs not aligned"}


def _evidence(cls, returns, price, ma20, ma50, ma200, slope, alignment, raw):
    """Human-readable evidence — the numbers, not an adjective."""
    def pct(label: str) -> str:
        r = returns.get(label)
        return "n/a" if r is None else f"{r:+.1%}"

    spans = f"1w {pct('1w')} / 1m {pct('1m')} / 3m {pct('3m')} / 6m {pct('6m')} / 1y {pct('1y')}"
    above = "上方" if price > ma200 else "下方"
    above_en = "above" if price > ma200 else "below"
    slope_zh = "走平" if slope is None else ("上行" if slope > 0 else "下行")
    slope_en = "flat" if slope is None else ("rising" if slope > 0 else "falling")
    zh = (f"{_LABEL_ZH[cls]}(评分 {(raw + 1) / 2:.2f})：{spans}；"
          f"价格在 MA200({ma200:.2f}) {above}，MA200 近 20 日{slope_zh}；{_STACK_ZH[alignment]}")
    en = (f"{_LABEL_EN[cls]} (score {(raw + 1) / 2:.2f}): {spans}; "
          f"price {above_en} MA200 ({ma200:.2f}), MA200 {slope_en} over 20 bars; "
          f"{_STACK_EN[alignment]}")
    return zh, en


__all__ = ["HORIZONS", "MIN_BARS", "TrendClass", "TrendState", "classify_trend"]
