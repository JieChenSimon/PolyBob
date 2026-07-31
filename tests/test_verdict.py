"""Tests for the investment-principle verdict engine."""

from __future__ import annotations

from libs.quant.trend_state import TrendClass, TrendState
from libs.quant.verdict import CheckStatus, Verdict, judge
from libs.quant.volume_state import VolumeClass, VolumePriceAgreement, VolumeState

BASE = dict(symbol="600519", domain="a_share", data_source="tencent",
            as_of="2026-07-29", bars=641)


def _trend(cls: TrendClass, score: float = 0.8) -> TrendState:
    """A trend state stub — the classifier itself is tested in test_trend_state."""
    return TrendState(
        classification=cls, score=score, raw_score=score * 2 - 1,
        returns={"1w": 0.01, "1m": 0.05, "2m": 0.08, "3m": 0.1, "6m": 0.2, "1y": 0.3},
        ma={"price": 100.0, "ma20": 98.0, "ma50": 95.0, "ma200": 90.0,
            "ma200_slope_20d": 0.01},
        aligned=cls is TrendClass.STRONG_UPTREND, alignment=0, bars=641,
        as_of="2026-07-29", evidence_zh="证据", evidence_en="evidence",
    )


UP = _trend(TrendClass.UPTREND)
DOWN = _trend(TrendClass.DOWNTREND, 0.2)


def _volume(cls: VolumeClass, agreement: VolumePriceAgreement,
            score: float = 0.7) -> VolumeState:
    """A volume state stub — the classifier itself is tested in test_volume_state."""
    return VolumeState(
        classification=cls, score=score, raw_score=score * 2 - 1,
        ratios={"5d": 1.4, "20d": 1.35, "60d": 1.1}, agreement=agreement,
        latest_volume=12345.0, baseline_volume=10000.0, latest_ratio=1.23,
        up_volume_share=0.62, price_change_20d=0.08, bars=641, as_of="2026-07-29",
        evidence_zh="量价证据", evidence_en="volume evidence",
    )


VOL_OK = _volume(VolumeClass.EXPANDING, VolumePriceAgreement.CONFIRM)
VOL_THIN = _volume(VolumeClass.DRYING_UP, VolumePriceAgreement.DIVERGE, 0.35)
VOL_DIST = _volume(VolumeClass.DISTRIBUTION, VolumePriceAgreement.DIVERGE, 0.3)


def _status(report, key):
    return next(c.status for c in report.checks if c.key == key)


def test_no_data_means_wait_not_a_guess():
    r = judge(symbol="X", domain="a_share", data_source=None, bars=0)
    assert r.verdict is Verdict.WAIT
    assert _status(r, "data") is CheckStatus.FAIL


def test_known_trap_overrides_everything_into_avoid():
    r = judge(**BASE, promoted_edges=["a_share_billboard_reversal"],
              signals=[{"direction": "buy", "stop_pct": 0.05}],
              trap_flags={"a_share": True})
    assert r.verdict is Verdict.AVOID
    # The evidence, not an opinion, must be in the finding.
    finding = next(c.finding_zh for c in r.checks if c.key == "known_mistake")
    assert "44,750" in finding


def test_buy_signal_without_stop_is_refused():
    r = judge(**BASE, promoted_edges=["e"], signals=[{"direction": "buy"}])
    assert r.verdict is Verdict.WAIT
    assert _status(r, "risk") is CheckStatus.FAIL


def test_stop_beyond_ceiling_is_refused():
    r = judge(**BASE, promoted_edges=["e"], signals=[{"direction": "buy", "stop_pct": 0.35}])
    assert r.verdict is Verdict.WAIT
    assert _status(r, "risk") is CheckStatus.FAIL


def test_signal_without_validated_edge_is_only_watch():
    r = judge(**BASE, promoted_edges=[], signals=[{"direction": "buy", "stop_pct": 0.05}])
    assert r.verdict is Verdict.WATCH
    assert _status(r, "edge") is CheckStatus.FAIL


def test_all_conditions_met_allows_action():
    r = judge(**BASE, promoted_edges=["a_share_billboard_reversal"],
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=VOL_OK)
    assert r.verdict is Verdict.ACT
    assert _status(r, "trend") is CheckStatus.PASS
    assert _status(r, "volume") is CheckStatus.PASS


def test_downtrend_blocks_action_even_when_everything_else_passes():
    """《炒股的智慧》: 绝不要在跌势时入市 — this is a prohibition, not a preference."""
    r = judge(**BASE, promoted_edges=["a_share_billboard_reversal"],
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=DOWN)
    assert r.verdict is Verdict.AVOID
    assert _status(r, "trend") is CheckStatus.FAIL
    assert "跌势" in r.headline_zh


def test_strong_downtrend_also_blocks_action():
    r = judge(**BASE, promoted_edges=["e"],
              signals=[{"direction": "buy", "stop_pct": 0.05}],
              trend=_trend(TrendClass.STRONG_DOWNTREND, 0.05))
    assert r.verdict is Verdict.AVOID


def test_downtrend_without_a_buy_signal_is_only_wait():
    """Nothing to avoid if you were not about to buy."""
    r = judge(**BASE, promoted_edges=["e"], signals=[], trend=DOWN)
    assert r.verdict is Verdict.WAIT
    assert _status(r, "trend") is CheckStatus.FAIL


def test_missing_trend_is_unknown_and_cannot_support_action():
    r = judge(**BASE, promoted_edges=["a_share_billboard_reversal"],
              signals=[{"direction": "buy", "stop_pct": 0.05}])
    assert _status(r, "trend") is CheckStatus.UNKNOWN
    assert r.verdict is Verdict.WATCH


def test_neutral_trend_warns_and_downgrades_action_to_watch():
    r = judge(**BASE, promoted_edges=["a_share_billboard_reversal"],
              signals=[{"direction": "buy", "stop_pct": 0.05}],
              trend=_trend(TrendClass.NEUTRAL, 0.5))
    assert _status(r, "trend") is CheckStatus.WARN
    assert r.verdict is Verdict.WATCH


def test_strong_uptrend_supports_action():
    r = judge(**BASE, promoted_edges=["a_share_billboard_reversal"],
              signals=[{"direction": "buy", "stop_pct": 0.05}],
              trend=_trend(TrendClass.STRONG_UPTREND, 0.95), volume=VOL_OK)
    assert r.verdict is Verdict.ACT


def test_missing_volume_is_unknown_and_cannot_support_action():
    """无成交量数据 is not "volume is fine" — it cannot carry a verdict to ACT."""
    r = judge(**BASE, promoted_edges=["a_share_billboard_reversal"],
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP)
    assert _status(r, "volume") is CheckStatus.UNKNOWN
    assert r.verdict is Verdict.WATCH


def test_thin_volume_warns_and_downgrades_action_to_watch():
    """书中：没有成交量的突破并没有很大意义."""
    r = judge(**BASE, promoted_edges=["a_share_billboard_reversal"],
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=VOL_THIN)
    assert _status(r, "volume") is CheckStatus.WARN
    assert r.verdict is Verdict.WATCH
    assert "成交量" in r.headline_zh


def test_distribution_volume_blocks_action_even_in_an_uptrend():
    """量增价滞 — heavy volume with no price progress is the book's top."""
    r = judge(**BASE, promoted_edges=["a_share_billboard_reversal"],
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=VOL_DIST)
    assert _status(r, "volume") is CheckStatus.FAIL
    assert r.verdict is Verdict.AVOID


def test_distribution_without_a_buy_signal_is_only_wait():
    r = judge(**BASE, promoted_edges=["e"], signals=[], trend=UP, volume=VOL_DIST)
    assert r.verdict is Verdict.WAIT
    assert _status(r, "volume") is CheckStatus.FAIL


def test_climax_volume_also_fails():
    climax = _volume(VolumeClass.CLIMAX, VolumePriceAgreement.CONFIRM, 0.2)
    r = judge(**BASE, promoted_edges=["e"],
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=climax)
    assert _status(r, "volume") is CheckStatus.FAIL
    assert r.verdict is Verdict.AVOID


def test_confirming_but_without_agreement_is_only_a_warning():
    """"Nothing is wrong" is not "volume confirms" — fail-closed by design."""
    neutral = _volume(VolumeClass.CONFIRMING, VolumePriceAgreement.NEUTRAL, 0.5)
    r = judge(**BASE, promoted_edges=["e"],
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=neutral)
    assert _status(r, "volume") is CheckStatus.WARN
    assert r.verdict is Verdict.WATCH


def test_trend_failure_still_outranks_the_volume_check():
    r = judge(**BASE, promoted_edges=["e"],
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=DOWN,
              volume=VOL_DIST)
    assert r.verdict is Verdict.AVOID
    assert "跌势" in r.headline_zh


def test_measured_trap_still_outranks_the_trend_check():
    r = judge(**BASE, promoted_edges=["e"],
              signals=[{"direction": "buy", "stop_pct": 0.05}],
              trap_flags={"a_share": True}, trend=UP)
    assert r.verdict is Verdict.AVOID
    assert "44,750" in next(c.finding_zh for c in r.checks if c.key == "known_mistake")


def test_default_is_wait_when_there_is_nothing_to_do():
    r = judge(**BASE, promoted_edges=["e"], signals=[])
    assert r.verdict is Verdict.WAIT
    assert _status(r, "risk") is CheckStatus.UNKNOWN


def test_stale_data_warns():
    r = judge(symbol="X", domain="us_equity", data_source="yahoo",
              as_of="2026-01-01", bars=500)
    assert _status(r, "data") is CheckStatus.WARN


def test_report_serialises():
    d = judge(**BASE, trend=UP, volume=VOL_OK).to_dict()
    assert set(d) >= {"symbol", "verdict", "headline_zh", "checks"}
    assert len(d["checks"]) == 6
    keys = [c["key"] for c in d["checks"]]
    assert keys[-2:] == ["trend", "volume"]
    trend_check = d["checks"][-2]
    assert trend_check["question_zh"] == "顺势还是逆势？"
    assert trend_check["question_en"] == "With or against the trend?"
    volume_check = d["checks"][-1]
    assert volume_check["question_zh"] == "量价配合吗？"
    assert volume_check["question_en"] == "Does volume confirm the price?"
