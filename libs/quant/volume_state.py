"""量价配合判定 — volume read as a ratio to its own baseline, then matched to price.

《炒股的智慧》 treats volume as the confirmation layer that price alone cannot
provide: a breakout on thin volume "并没有很大意义", while 量增价滞 (volume
surging while price refuses to advance) is the classic distribution warning that
precedes a top. Until now :mod:`libs.quant.verdict` judged direction with
:mod:`libs.quant.trend_state` and nothing else — a price-only verdict, which can
bless a rally that nobody is actually participating in. This module supplies the
missing half.

The specification, and why each number is what it is
====================================================

**Everything is a ratio, never an absolute.** The three instruments this project
covers report volume in three incomparable units: ``fetch_a_share_daily``
(Tencent) returns A-share 手/股 counts in the hundreds of thousands,
``fetch_us_equity_daily`` (Yahoo) returns US share counts in the tens of
millions, ``fetch_altcoin_daily`` (OKX) returns base-currency coin counts that
can be fractional. No threshold stated in any of those units could mean the same
thing twice. So every reading here is ``volume / baseline`` — a dimensionless
number an A-share, a US equity and an altcoin can all be scored against.

**The baseline is a median, not a mean.** Volume distributions are violently
right-skewed: one earnings day or one liquidation cascade can lift a 250-day
*mean* by 20% and quietly re-scale every ratio that follows. The median of the
trailing ``BASELINE_WINDOW`` (250 bars ≈ one trading year) bars is the robust
statistic for exactly this shape, and a full year is used so that seasonal
quiet periods do not read as structural dry-ups.

**Three windows, because dry-up is a structural fact, not a daily one.**

- ``5d``  — this week versus the year. Catches the event, the spike, the gap.
- ``20d`` — this month versus the year. The headline (``ratio_20d``), because a
  month is long enough to be a participation regime rather than one news cycle,
  and short enough to still be current.
- ``60d`` — this quarter versus the year. A quarter of volume 40% below normal
  is a market losing interest in the instrument; that is invisible at 20d if the
  decay is gradual.

**Volume–price agreement is the core logic, and it is directional.** Volume has
no sign of its own — it is only meaningful against what price did over the same
window. The 20-day price change is volatility-normalised (``t = ln(1+r) /
(sigma_daily * sqrt(20))``) for the same reason the trend module normalises its
horizons: +8% in a 90%-vol altcoin is not the evidence +8% is in a utility.

- ``confirm`` — price up (> +2%) **and** ``ratio_20d >= 1.05``. Advancing on
  participation. This is the only state that can produce a ``PASS``.
- ``diverge`` — price up (> +2%) **and** ``ratio_20d <= 0.90`` (无量上涨: the
  rally nobody is buying), **or** price flat-to-down **and** ``ratio_20d >=
  1.30`` (量增价滞 / 价跌量增: supply is being distributed into the bid).
- ``neutral`` — everything else, *including a falling price on falling volume*.
  An orderly low-volume pullback is not distribution, but it is also not a
  confirmation of anything worth buying, and calling it ``confirm`` would let a
  declining instrument earn a volume ``PASS``. Fail-closed: no evidence is
  ``neutral``, not agreement.

**Classification**, evaluated in this order (first match wins), thresholds
stated as multiples of the year's normal volume rather than fitted constants:

- ``unavailable`` — no volume series, a degenerate one (over half the bars zero,
  which is how Yahoo represents *missing*, not *no trading*), a non-positive
  baseline, or fewer than ``MIN_BARS`` bars. Never a silent "fine".
- ``climax``      — ``latest / baseline >= 3.0`` together with a sharp 5-day move
  in *either* direction. 3x the year's median in a single session is not
  ordinary participation; paired with a vertical move it is exhaustion — a
  buying climax on the way up, capitulation on the way down. Both are ``FAIL``
  for a *new entry*, which is the only question this engine answers.
- ``distribution`` — ``ratio_20d >= 1.30`` while price failed to advance. The
  book's 量增价滞. Heavy volume that produces no progress means someone large is
  selling into every bid.
- ``drying_up``   — ``ratio_20d <= 0.70`` (structural disinterest), or price up
  more than 5% on ``ratio_20d <= 0.85`` (a rally on no participation).
- ``expanding``   — ``ratio_20d >= 1.30`` with price advancing. Participation is
  arriving with the move; the book's healthy breakout.
- ``confirming``  — the residual: volume in line with price, no conflict found.

Note the deliberate gap between ``confirming`` and ``PASS``. ``confirming`` means
"nothing is wrong here"; the verdict check requires *both* a ``confirming`` /
``expanding`` classification **and** ``agreement == "confirm"`` before it passes.
An unremarkable, drifting volume picture is not a confirmation, and grading it as
one would reintroduce exactly the silent pass this check exists to remove.

**The 0–1 score.** A raw score in ``[-1, +1]``, rescaled ``(raw + 1) / 2`` so 0.5
is dead neutral — the same convention as :mod:`libs.quant.trend_state`, so the
two scores are readable side by side. Three components:

- 0.50 ``agreement`` — ``p * r``, where ``p = tanh(t20 / 2)`` is the normalised
  price move and ``r = clamp(ln(ratio_20d) / ln(1.5), -1, 1)`` is the volume
  ratio on a log scale (1.5x normal saturates). The *product* is the point:
  same sign on both = positive, opposite signs = negative. That single term is
  the whole volume-price doctrine written as arithmetic.
- 0.30 ``up_volume_share`` — of the last 20 bars' volume, the fraction that
  traded on up days, mapped ``2 * (share - 0.5)``. Granville's on-balance-volume
  logic: accumulation concentrates volume on advances, distribution on declines.
  It is an independent lens on the same question as the first term, so it earns
  real weight but less than the direct measurement.
- 0.20 ``structure`` — the 60-day ratio on the same log scale, signed by the
  direction of price. Expansion into a rise is healthy; expansion into a decline
  is not. Least weight: it is the slowest and most confounded of the three.

Classification then *caps* the score — ``climax`` at 0.25, ``distribution`` at
0.35, ``drying_up`` at 0.50 — so a high component score can never talk its way
past a state the book calls a warning. The cap is one-directional by design.

**Polymarket BTC-5m has no volume, and none is invented.** Polymarket's CLOB
publishes an order book, not traded-volume bars; there is no honest daily volume
figure for a 5-minute binary market. Fabricating one — from depth, from trade
counts, from anything — would violate this project's hard real-data rule, and a
number that looks like volume but is not is worse than no number. The liquidity
read for that instrument already exists in the correct units and is already
parsed: ``bid_depth_top3`` / ``ask_depth_top3`` / ``spread`` in
:mod:`libs.polymarket.btc_five_minute`. Depth is a *stock*, volume is a *flow*;
they are not interchangeable and are not mixed here. Accordingly ``/api/verdict``
emits ``"volume": null`` for instruments with no volume concept, and this module
returns an explicit ``unavailable`` state (which the verdict engine maps to
``UNKNOWN``, never ``PASS``) when a daily-bar instrument arrives without one.

**Causality.** ``classify_volume`` reads only ``volumes[:len(bars)]`` and
``closes[:len(bars)]``; every statistic ends at the last supplied bar. It is
proven causal in ``tests/test_volume_state.py`` with
:func:`libs.quant.pit.assert_no_lookahead`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, Sequence, runtime_checkable


class VolumeClass(str, Enum):
    CONFIRMING = "confirming"      # volume in line with price — no conflict
    EXPANDING = "expanding"        # heavy volume arriving with an advance
    DRYING_UP = "drying_up"        # structural disinterest, or a rally on no volume
    DISTRIBUTION = "distribution"  # 量增价滞 — heavy volume, no price progress
    CLIMAX = "climax"              # 3x+ volume on a vertical move — exhaustion
    UNAVAILABLE = "unavailable"    # no usable volume series — never a silent pass


class VolumePriceAgreement(str, Enum):
    CONFIRM = "confirm"
    DIVERGE = "diverge"
    NEUTRAL = "neutral"


@runtime_checkable
class _BarsLike(Protocol):
    """The shape of :class:`libs.data.real_sources.DailyBars` we actually need."""

    closes: Sequence[float]
    volumes: Sequence[float] | None
    dates: Sequence[str]


# Ratio windows, in trading days. See the module docstring for why three.
WINDOWS: dict[str, int] = {"5d": 5, "20d": 20, "60d": 60}

# One trading year of history for the median baseline; a quarter is the floor
# below which "normal volume" is not a meaningful phrase.
BASELINE_WINDOW = 250
MIN_BARS = 60

# Fraction of zero-volume bars above which the series is treated as missing
# rather than as genuinely untraded. Yahoo writes 0.0 for absent data.
_MAX_ZERO_FRACTION = 0.5

_PRICE_WINDOW = 20               # the window the headline ratio is matched to
_CLIMAX_WINDOW = 5

# Thresholds, as multiples of the year's median volume.
_SURGE = 1.30                    # "heavy" — a third above the year's normal
_MILD = 1.05                     # the floor for calling an advance confirmed
_THIN = 0.90                     # rising price below this is 无量上涨
_DRY = 0.70                      # a structural dry-up
_RALLY_THIN = 0.85               # thin, judged against a >5% advance
_CLIMAX_RATIO = 3.0              # single-bar exhaustion volume

_ADVANCE = 0.02                  # +2% over 20 bars — the "price actually rose" bar
_STRONG_ADVANCE = 0.05
_CLIMAX_MOVE = 0.5               # normalised 5-day move (tanh scale) for a climax

_RATIO_SCALE = math.log(1.5)     # 1.5x normal volume saturates the log term

_WEIGHTS = {"agreement": 0.50, "up_volume_share": 0.30, "structure": 0.20}

# One-directional score caps — a warning state cannot be scored away.
_SCORE_CAP = {
    VolumeClass.CLIMAX: 0.25,
    VolumeClass.DISTRIBUTION: 0.35,
    VolumeClass.DRYING_UP: 0.50,
}


@dataclass(frozen=True)
class VolumeState:
    """A volume-price classification plus every number that produced it."""

    classification: VolumeClass
    score: float                                  # 0..1, 0.5 = neutral
    raw_score: float                              # -1..1, the pre-rescale value
    ratios: dict[str, float | None]               # "5d"/"20d"/"60d" -> vol / baseline
    agreement: VolumePriceAgreement
    latest_volume: float | None
    baseline_volume: float | None                 # the 250-bar median
    latest_ratio: float | None
    up_volume_share: float | None                 # of 20 bars' volume, share on up days
    price_change_20d: float | None
    bars: int
    as_of: str | None
    evidence_zh: str
    evidence_en: str
    components: dict[str, float] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.classification is not VolumeClass.UNAVAILABLE

    @property
    def confirms(self) -> bool:
        """True only when volume actively confirms an advance — the PASS gate."""
        return (self.classification in (VolumeClass.CONFIRMING, VolumeClass.EXPANDING)
                and self.agreement is VolumePriceAgreement.CONFIRM)

    @property
    def warns(self) -> bool:
        """Divergence, dry-up, or simply no confirmation — not a reason to buy."""
        return self.available and not self.confirms and not self.blocks_act

    @property
    def blocks_act(self) -> bool:
        """Distribution and climax — the two states the book calls a top."""
        return self.classification in (VolumeClass.DISTRIBUTION, VolumeClass.CLIMAX)

    def to_dict(self) -> dict[str, Any]:
        """The wire contract consumed by ``/api/verdict`` and the dashboard."""
        def r(v: float | None, digits: int = 4) -> float | None:
            return None if v is None else round(v, digits)

        return {
            "classification": self.classification.value,
            "score": round(self.score, 4),
            "ratio_20d": r(self.ratios.get("20d")),
            "ratios": {k: r(v) for k, v in self.ratios.items()},
            "price_volume_agreement": self.agreement.value,
            "latest_volume": r(self.latest_volume, 2),
            "evidence_zh": self.evidence_zh,
            "evidence_en": self.evidence_en,
            # Supporting detail — additive, never a replacement for the keys above.
            "baseline_volume": r(self.baseline_volume, 2),
            "latest_ratio": r(self.latest_ratio),
            "up_volume_share": r(self.up_volume_share),
            "price_change_20d": r(self.price_change_20d, 6),
            "raw_score": round(self.raw_score, 4),
            "bars": self.bars,
            "as_of": self.as_of,
        }


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def _daily_vol(closes: Sequence[float], window: int = 252) -> float:
    """Std-dev of daily log returns — the yardstick a price move is measured in."""
    tail = list(closes[-(window + 1):])
    rets = [math.log(tail[i] / tail[i - 1]) for i in range(1, len(tail))
            if tail[i] > 0 and tail[i - 1] > 0]
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var)


def _normalised_move(closes: Sequence[float], window: int, vol: float) -> tuple[float | None, float]:
    """Return ``(simple_return, tanh-squashed t-statistic)`` over ``window`` bars."""
    if len(closes) <= window or closes[-1 - window] <= 0 or closes[-1] <= 0:
        return None, 0.0
    ret = closes[-1] / closes[-1 - window] - 1.0
    if vol <= 0:
        return ret, (1.0 if ret > 0 else (-1.0 if ret < 0 else 0.0))
    t = math.log1p(max(ret, -0.999999)) / (vol * math.sqrt(window))
    return ret, math.tanh(t / 2.0)


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _log_ratio(ratio: float | None) -> float:
    """A volume ratio on a symmetric log scale: 1.5x normal saturates at +/-1."""
    if not ratio or ratio <= 0:
        return 0.0
    return _clamp(math.log(ratio) / _RATIO_SCALE)


def _unavailable(bars_len: int, as_of: str | None, reason_zh: str, reason_en: str) -> VolumeState:
    return VolumeState(
        classification=VolumeClass.UNAVAILABLE, score=0.5, raw_score=0.0,
        ratios={k: None for k in WINDOWS},
        agreement=VolumePriceAgreement.NEUTRAL,
        latest_volume=None, baseline_volume=None, latest_ratio=None,
        up_volume_share=None, price_change_20d=None,
        bars=bars_len, as_of=as_of,
        evidence_zh=reason_zh, evidence_en=reason_en,
    )


def classify_volume(bars: Any) -> VolumeState:
    """Classify volume-price behaviour using only data up to the last bar.

    ``bars`` may be a :class:`libs.data.real_sources.DailyBars` or anything with
    ``.closes`` and ``.volumes`` (``.dates`` optional). Volume units are never
    compared across instruments — every figure below is a ratio to the
    instrument's own 250-bar median, which is the only comparison that survives
    A-share 手, US shares and OKX base-currency coins living in one codebase.

    An instrument with no volume series (Polymarket BTC-5m being the concrete
    case) returns an ``unavailable`` state. That is deliberate: no volume number
    is fabricated from order-book depth or anything else.
    """
    closes = [float(c) for c in getattr(bars, "closes", None) or []]
    raw_volumes = getattr(bars, "volumes", None)
    volumes = [float(v) for v in raw_volumes] if raw_volumes else []
    dates = list(getattr(bars, "dates", None) or [])
    as_of = dates[-1] if dates else None
    n = min(len(closes), len(volumes))

    if not volumes:
        return _unavailable(
            len(closes), as_of,
            "该标的没有成交量数据——不编造，也不用盘口深度冒充成交量",
            "This instrument has no volume series — none is fabricated, and order-book "
            "depth is not substituted for it",
        )
    if n < MIN_BARS:
        return _unavailable(
            n, as_of,
            f"成交量历史仅 {n} 根K线，不足 {MIN_BARS} 根，无法判断量价——不猜",
            f"Only {n} bars of volume history, fewer than {MIN_BARS}; the volume "
            "picture is unknown — this is not a guess",
        )

    closes, volumes = closes[-n:], volumes[-n:]
    zeros = sum(1 for v in volumes if v <= 0)
    if zeros > _MAX_ZERO_FRACTION * n:
        return _unavailable(
            n, as_of,
            f"{zeros}/{n} 根K线成交量为 0，视为数据缺失而非无人交易——不猜",
            f"{zeros}/{n} bars report zero volume; treated as missing data, not as "
            "genuine no-trade — this is not a guess",
        )

    baseline = _median(volumes[-min(BASELINE_WINDOW, n):])
    if baseline <= 0:
        return _unavailable(
            n, as_of,
            "成交量基准中位数为 0,无法构造比率——不猜",
            "The median baseline volume is zero, so no ratio can be formed — "
            "this is not a guess",
        )

    # --- Ratios: the only unit-free view of volume ---------------------------
    ratios: dict[str, float | None] = {}
    for label, w in WINDOWS.items():
        ratios[label] = (sum(volumes[-w:]) / w / baseline) if n >= w else None
    latest_volume = volumes[-1]
    latest_ratio = latest_volume / baseline
    ratio_20 = ratios["20d"]
    ratio_60 = ratios["60d"]

    # --- Price side, volatility-normalised -----------------------------------
    vol = _daily_vol(closes)
    price_change_20d, p20 = _normalised_move(closes, _PRICE_WINDOW, vol)
    _, p5 = _normalised_move(closes, _CLIMAX_WINDOW, vol)

    # Granville's on-balance logic over the same 20 bars.
    up_vol = sum(volumes[-i] for i in range(1, _PRICE_WINDOW + 1)
                 if closes[-i] > closes[-i - 1])
    win_vol = sum(volumes[-_PRICE_WINDOW:])
    up_share = (up_vol / win_vol) if win_vol > 0 else None

    # --- Agreement ------------------------------------------------------------
    rose = price_change_20d is not None and price_change_20d > _ADVANCE
    stalled = price_change_20d is not None and price_change_20d <= _ADVANCE
    heavy = ratio_20 is not None and ratio_20 >= _SURGE
    if rose and ratio_20 is not None and ratio_20 >= _MILD:
        agreement = VolumePriceAgreement.CONFIRM
    elif (rose and ratio_20 is not None and ratio_20 <= _THIN) or (stalled and heavy):
        agreement = VolumePriceAgreement.DIVERGE
    else:
        agreement = VolumePriceAgreement.NEUTRAL

    # --- Classification, first match wins ------------------------------------
    if latest_ratio >= _CLIMAX_RATIO and abs(p5) >= _CLIMAX_MOVE:
        cls = VolumeClass.CLIMAX
    elif heavy and stalled:
        cls = VolumeClass.DISTRIBUTION
    elif (ratio_20 is not None and ratio_20 <= _DRY) or (
        price_change_20d is not None and price_change_20d >= _STRONG_ADVANCE
        and ratio_20 is not None and ratio_20 <= _RALLY_THIN
    ):
        cls = VolumeClass.DRYING_UP
    elif heavy and rose:
        cls = VolumeClass.EXPANDING
    else:
        cls = VolumeClass.CONFIRMING

    # --- Score ----------------------------------------------------------------
    r20 = _log_ratio(ratio_20)
    direction = 1.0 if (price_change_20d or 0.0) > 0 else (
        -1.0 if (price_change_20d or 0.0) < 0 else 0.0)
    components = {
        "agreement": _clamp(p20 * r20),
        "up_volume_share": 0.0 if up_share is None else _clamp(2.0 * (up_share - 0.5)),
        "structure": _log_ratio(ratio_60) * direction,
    }
    raw = _clamp(sum(_WEIGHTS[k] * v for k, v in components.items()))
    score = _clamp((raw + 1.0) / 2.0, 0.0, 1.0)
    cap = _SCORE_CAP.get(cls)
    if cap is not None:
        score = min(score, cap)          # a warning state cannot be scored away
        raw = score * 2.0 - 1.0

    zh, en = _evidence(cls, agreement, ratios, latest_ratio, up_share,
                       price_change_20d, score)

    return VolumeState(
        classification=cls, score=score, raw_score=raw, ratios=ratios,
        agreement=agreement, latest_volume=latest_volume, baseline_volume=baseline,
        latest_ratio=latest_ratio, up_volume_share=up_share,
        price_change_20d=price_change_20d, bars=n, as_of=as_of,
        evidence_zh=zh, evidence_en=en, components=components,
    )


_LABEL_ZH = {
    VolumeClass.CONFIRMING: "量价基本配合", VolumeClass.EXPANDING: "放量上涨",
    VolumeClass.DRYING_UP: "缩量", VolumeClass.DISTRIBUTION: "量增价滞(派发)",
    VolumeClass.CLIMAX: "成交量高潮(衰竭)", VolumeClass.UNAVAILABLE: "无成交量数据",
}
_LABEL_EN = {
    VolumeClass.CONFIRMING: "volume in line with price",
    VolumeClass.EXPANDING: "advance on expanding volume",
    VolumeClass.DRYING_UP: "volume drying up",
    VolumeClass.DISTRIBUTION: "volume up, price stalled (distribution)",
    VolumeClass.CLIMAX: "volume climax (exhaustion)",
    VolumeClass.UNAVAILABLE: "no volume data",
}
_AGREE_ZH = {VolumePriceAgreement.CONFIRM: "量价配合",
             VolumePriceAgreement.DIVERGE: "量价背离",
             VolumePriceAgreement.NEUTRAL: "量价无明确配合"}
_AGREE_EN = {VolumePriceAgreement.CONFIRM: "volume confirms price",
             VolumePriceAgreement.DIVERGE: "volume diverges from price",
             VolumePriceAgreement.NEUTRAL: "no clear volume-price agreement"}


def _evidence(cls, agreement, ratios, latest_ratio, up_share, price_change_20d, score):
    """Human-readable evidence — the ratios themselves, not an adjective."""
    def x(label: str) -> str:
        v = ratios.get(label)
        return "n/a" if v is None else f"{v:.2f}x"

    spans = f"5日 {x('5d')} / 20日 {x('20d')} / 60日 {x('60d')}"
    spans_en = f"5d {x('5d')} / 20d {x('20d')} / 60d {x('60d')}"
    pc = "n/a" if price_change_20d is None else f"{price_change_20d:+.1%}"
    share = "n/a" if up_share is None else f"{up_share:.0%}"
    zh = (f"{_LABEL_ZH[cls]}(评分 {score:.2f})：成交量/年中位数 {spans}，"
          f"最近一根 {latest_ratio:.2f}x；20日价格 {pc}，上涨日成交量占比 {share}；"
          f"{_AGREE_ZH[agreement]}")
    en = (f"{_LABEL_EN[cls]} (score {score:.2f}): volume vs its 1-year median "
          f"{spans_en}, latest bar {latest_ratio:.2f}x; 20-bar price {pc}, "
          f"{share} of that volume on up days; {_AGREE_EN[agreement]}")
    return zh, en


__all__ = ["BASELINE_WINDOW", "MIN_BARS", "WINDOWS", "VolumeClass",
           "VolumePriceAgreement", "VolumeState", "classify_volume"]
