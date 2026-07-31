"""Tests for the investment-principle verdict engine."""

from __future__ import annotations

from libs.quant.verdict import CheckStatus, Verdict, judge

BASE = dict(symbol="600519", domain="a_share", data_source="tencent",
            as_of="2026-07-29", bars=641)


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
              signals=[{"direction": "buy", "stop_pct": 0.05}])
    assert r.verdict is Verdict.ACT


def test_default_is_wait_when_there_is_nothing_to_do():
    r = judge(**BASE, promoted_edges=["e"], signals=[])
    assert r.verdict is Verdict.WAIT
    assert _status(r, "risk") is CheckStatus.UNKNOWN


def test_stale_data_warns():
    r = judge(symbol="X", domain="us_equity", data_source="yahoo",
              as_of="2026-01-01", bars=500)
    assert _status(r, "data") is CheckStatus.WARN


def test_report_serialises():
    d = judge(**BASE).to_dict()
    assert set(d) >= {"symbol", "verdict", "headline_zh", "checks"}
    assert len(d["checks"]) == 4
