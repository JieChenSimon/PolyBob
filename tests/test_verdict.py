"""Tests for the investment-principle verdict engine."""

from __future__ import annotations

from libs.quant.trend_state import TrendClass, TrendState
from libs.quant.verdict import CheckStatus, Verdict, judge

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
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP)
    assert r.verdict is Verdict.ACT
    assert _status(r, "trend") is CheckStatus.PASS


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
              trend=_trend(TrendClass.STRONG_UPTREND, 0.95))
    assert r.verdict is Verdict.ACT


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
    d = judge(**BASE, trend=UP).to_dict()
    assert set(d) >= {"symbol", "verdict", "headline_zh", "checks"}
    assert len(d["checks"]) == 5
    assert [c["key"] for c in d["checks"]][-1] == "trend"
    trend_check = d["checks"][-1]
    assert trend_check["question_zh"] == "顺势还是逆势？"
    assert trend_check["question_en"] == "With or against the trend?"
