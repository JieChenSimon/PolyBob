"""Tests for the volume-price classifier.

The fixtures here are *shaped* volume/price paths, not claims about any market:
they exist to prove the classifier's arithmetic and its causality. Every
real-data claim in this project still comes from real data — see the verdict
endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from libs.quant.pit import LookaheadError, assert_no_lookahead
from libs.quant.volume_state import (
    BASELINE_WINDOW, MIN_BARS, VolumeClass, VolumePriceAgreement, classify_volume,
)


@dataclass
class FakeBars:
    """The minimal DailyBars shape the classifier consumes."""

    closes: list[float]
    volumes: list[float] | None
    dates: list[str]

    @classmethod
    def build(cls, closes: list[float], volumes: list[float] | None) -> "FakeBars":
        return cls(closes=closes, volumes=volumes,
                   dates=[f"2024-{1 + i // 400:02d}-{1 + i % 28:02d}"
                          for i in range(len(closes))])


def _path(n: int, daily: float, start: float = 100.0) -> list[float]:
    """A deterministic price path compounding at ``daily`` per bar."""
    closes = [start]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1.0 + daily))
    return closes


def _flat_volume(n: int, level: float = 1_000_000.0) -> list[float]:
    """Volume that alternates gently around ``level`` so the median is stable."""
    return [level * (1.0 + 0.02 * (-1) ** i) for i in range(n)]


def _bars(closes: list[float], volumes: list[float] | None) -> FakeBars:
    return FakeBars.build(closes, volumes)


# --- unavailable: the honest-absence paths ---------------------------------

def test_no_volume_series_is_unavailable_not_a_pass():
    """Polymarket BTC-5m case: no bar volume exists, so none is invented."""
    state = classify_volume(_bars(_path(300, 0.001), None))
    assert state.classification is VolumeClass.UNAVAILABLE
    assert state.available is False
    assert state.confirms is False
    assert state.ratios == {"5d": None, "20d": None, "60d": None}
    assert state.latest_volume is None
    assert "不编造" in state.evidence_zh and "fabricated" in state.evidence_en


def test_none_bars_is_unavailable():
    state = classify_volume(None)
    assert state.classification is VolumeClass.UNAVAILABLE


def test_short_history_is_unavailable():
    n = MIN_BARS - 5
    state = classify_volume(_bars(_path(n, 0.001), _flat_volume(n)))
    assert state.classification is VolumeClass.UNAVAILABLE
    assert str(MIN_BARS) in state.evidence_en


def test_mostly_zero_volume_is_missing_data_not_no_trading():
    n = 300
    volumes = [1_000_000.0 if i % 3 == 0 else 0.0 for i in range(n)]
    state = classify_volume(_bars(_path(n, 0.001), volumes))
    assert state.classification is VolumeClass.UNAVAILABLE


# --- the five live classifications ------------------------------------------

def test_advance_on_expanding_volume_is_expanding_and_confirms():
    n = 300
    closes = _path(n, 0.0)
    volumes = _flat_volume(n)
    for i in range(1, 21):                       # last month: +8% price, 1.8x volume
        closes[-i] = closes[-21] * (1.0 + 0.08 * (21 - i) / 20.0)
        volumes[-i] *= 1.8
    state = classify_volume(_bars(closes, volumes))
    assert state.classification is VolumeClass.EXPANDING
    assert state.agreement is VolumePriceAgreement.CONFIRM
    assert state.confirms is True
    assert state.ratios["20d"] > 1.3
    assert state.score > 0.5


def test_mild_advance_on_mildly_higher_volume_is_confirming():
    n = 300
    closes = _path(n, 0.0)
    volumes = _flat_volume(n)
    for i in range(1, 21):
        closes[-i] = closes[-21] * (1.0 + 0.06 * (21 - i) / 20.0)
        volumes[-i] *= 1.15
    state = classify_volume(_bars(closes, volumes))
    assert state.classification is VolumeClass.CONFIRMING
    assert state.agreement is VolumePriceAgreement.CONFIRM
    assert state.confirms is True


def test_rally_on_thin_volume_is_drying_up_and_diverges():
    """无量上涨 — the book: a breakout without volume 并没有很大意义."""
    n = 300
    closes = _path(n, 0.0)
    volumes = _flat_volume(n)
    for i in range(1, 21):
        closes[-i] = closes[-21] * (1.0 + 0.09 * (21 - i) / 20.0)
        volumes[-i] *= 0.55
    state = classify_volume(_bars(closes, volumes))
    assert state.classification is VolumeClass.DRYING_UP
    assert state.agreement is VolumePriceAgreement.DIVERGE
    assert state.confirms is False
    assert state.warns is True
    assert state.score <= 0.5


def test_structural_dry_up_is_drying_up():
    n = 300
    closes = _path(n, 0.0)
    volumes = _flat_volume(n)
    for i in range(1, 61):                       # a quiet quarter, price flat
        volumes[-i] *= 0.5
    state = classify_volume(_bars(closes, volumes))
    assert state.classification is VolumeClass.DRYING_UP
    assert state.ratios["60d"] < 0.7


def test_heavy_volume_with_stalled_price_is_distribution():
    """量增价滞 — heavy volume producing no progress is someone selling."""
    n = 300
    closes = _path(n, 0.0)
    volumes = _flat_volume(n)
    for i in range(1, 21):
        volumes[-i] *= 1.9                       # volume up, price unchanged
    state = classify_volume(_bars(closes, volumes))
    assert state.classification is VolumeClass.DISTRIBUTION
    assert state.agreement is VolumePriceAgreement.DIVERGE
    assert state.blocks_act is True
    assert state.score <= 0.35


def test_falling_price_on_surging_volume_is_distribution():
    n = 300
    closes = _path(n, 0.0)
    volumes = _flat_volume(n)
    for i in range(1, 21):
        closes[-i] = closes[-21] * (1.0 - 0.10 * (21 - i) / 20.0)
        volumes[-i] *= 2.0
    state = classify_volume(_bars(closes, volumes))
    assert state.classification is VolumeClass.DISTRIBUTION
    assert state.blocks_act is True


def test_single_bar_volume_spike_on_a_vertical_move_is_climax():
    n = 300
    closes = _path(n, 0.0005)
    volumes = _flat_volume(n)
    for i in range(1, 6):                        # a vertical five days
        closes[-i] = closes[-6] * (1.0 + 0.12 * (6 - i) / 5.0)
    volumes[-1] *= 6.0                           # 6x the year's median in one bar
    state = classify_volume(_bars(closes, volumes))
    assert state.classification is VolumeClass.CLIMAX
    assert state.blocks_act is True
    assert state.score <= 0.25


def test_orderly_low_volume_pullback_is_neutral_never_confirm():
    """A falling price on falling volume is not distribution — but not a buy."""
    n = 300
    closes = _path(n, 0.0)
    volumes = _flat_volume(n)
    for i in range(1, 21):
        closes[-i] = closes[-21] * (1.0 - 0.05 * (21 - i) / 20.0)
        volumes[-i] *= 0.92
    state = classify_volume(_bars(closes, volumes))
    assert state.agreement is VolumePriceAgreement.NEUTRAL
    assert state.confirms is False
    assert state.warns is True


# --- ratios are unit-free ----------------------------------------------------

def test_classification_is_invariant_to_volume_units():
    """A-share 手, US shares and OKX coins must score identically."""
    n = 300
    closes = _path(n, 0.0)
    volumes = _flat_volume(n)
    for i in range(1, 21):
        closes[-i] = closes[-21] * (1.0 + 0.08 * (21 - i) / 20.0)
        volumes[-i] *= 1.8

    small = classify_volume(_bars(closes, [v * 1e-7 for v in volumes]))
    large = classify_volume(_bars(closes, [v * 1e4 for v in volumes]))
    assert small.classification is large.classification
    assert small.ratios["20d"] == pytest.approx(large.ratios["20d"])
    assert small.score == pytest.approx(large.score)
    assert small.latest_volume != large.latest_volume   # only the raw figure differs


def test_baseline_is_a_median_so_one_spike_does_not_rescale_everything():
    n = BASELINE_WINDOW + 50
    closes = _path(n, 0.0)
    volumes = _flat_volume(n)
    clean = classify_volume(_bars(closes, list(volumes)))
    volumes[-120] *= 200.0                       # one enormous historical day
    spiked = classify_volume(_bars(closes, volumes))
    assert spiked.baseline_volume == pytest.approx(clean.baseline_volume, rel=0.01)


# --- causality ---------------------------------------------------------------

def test_classifier_is_causal():
    """Bar k's classification must not change when later bars are appended."""
    n = 200
    closes = _path(n, 0.0012)
    volumes = _flat_volume(n)
    history = list(zip(closes, volumes))

    def signal_fn(hist):
        out = []
        for k in range(len(hist)):
            window = hist[: k + 1]
            prefix = FakeBars(closes=[c for c, _ in window],
                              volumes=[v for _, v in window],
                              dates=[f"d{i}" for i in range(k + 1)])
            out.append(classify_volume(prefix).classification.value)
        return out

    # Spot-check across the usable region; the harness is O(n^2) in classify calls.
    assert_no_lookahead(signal_fn, history,
                        check_indices=[59, 80, 120, 160, 199])


def test_lookahead_harness_would_catch_a_leak():
    """Sanity: the guard above is a real test, not a tautology."""
    history = list(zip(_path(60, 0.002), _flat_volume(60)))

    def leaky(hist):
        # Peeks at the final bar of whatever window it is given.
        return [1.0 if hist[-1][0] > c else -1.0 for c, _ in hist]

    with pytest.raises(LookaheadError):
        assert_no_lookahead(leaky, history, check_indices=[10, 20, 30])


# --- wire contract -----------------------------------------------------------

def test_wire_contract_shape():
    n = 300
    state = classify_volume(_bars(_path(n, 0.001), _flat_volume(n)))
    d = state.to_dict()
    assert set(d) >= {"classification", "score", "ratio_20d", "ratios",
                      "price_volume_agreement", "latest_volume",
                      "evidence_zh", "evidence_en"}
    assert set(d["ratios"]) == {"5d", "20d", "60d"}
    assert d["ratio_20d"] == d["ratios"]["20d"]
    assert d["price_volume_agreement"] in {"confirm", "diverge", "neutral"}
    assert d["classification"] in {"confirming", "expanding", "drying_up",
                                   "distribution", "climax", "unavailable"}
    assert 0.0 <= d["score"] <= 1.0
    assert d["evidence_zh"] and d["evidence_en"]


def test_api_emits_null_volume_for_an_instrument_with_no_volume_concept():
    """Polymarket BTC-5m publishes a book, not volume bars — so: null, not a number."""
    from apps.api.main import _classify_volume_or_unknown

    assert _classify_volume_or_unknown(None, "btc5m") is None
    assert _classify_volume_or_unknown(None, "polymarket") is None
    # A daily-bar market with no series still gets an explicit unavailable state.
    state = _classify_volume_or_unknown(None, "a_share")
    assert state is not None and state.classification is VolumeClass.UNAVAILABLE


def test_unavailable_wire_contract_nulls_the_numbers():
    d = classify_volume(None).to_dict()
    assert d["classification"] == "unavailable"
    assert d["ratio_20d"] is None
    assert d["ratios"] == {"5d": None, "20d": None, "60d": None}
    assert d["latest_volume"] is None
    assert 0.0 <= d["score"] <= 1.0
