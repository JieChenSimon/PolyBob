"""Tests for the investment-principle verdict engine."""

from __future__ import annotations

from datetime import UTC, datetime

from libs.quant.edge_instance import EdgeInstance, EdgeStatus
from libs.quant.trend_state import TrendClass, TrendState
from libs.quant.verdict import CheckStatus, Verdict, judge
from libs.quant.volume_state import VolumeClass, VolumePriceAgreement, VolumeState

# ``daily_vol`` is part of the base case because the stop check is now judged
# against the instrument's own volatility: a 5% stop is generous on a utility
# and inside the noise on an altcoin, and the engine must be told which it is.
# ``now`` is pinned: the data check is a freshness check, so a fixed ``as_of``
# with a real clock silently turns every case stale once the date rolls over.
BASE = dict(symbol="600519", domain="a_share", data_source="tencent",
            as_of="2026-07-29", bars=641, daily_vol=0.015,
            now=datetime(2026, 7, 30, tzinfo=UTC))


def _edge(status: EdgeStatus, strategy: str = "a_share_billboard_reversal") -> EdgeInstance:
    """An edge-instance stub — the detectors are tested in test_edge_instance."""
    return EdgeInstance(strategy, "600519", status, "边证据", "edge evidence")


EDGE_ON = [_edge(EdgeStatus.ACTIVE)]
EDGE_OFF = [_edge(EdgeStatus.INACTIVE)]
EDGE_UNKNOWN = [_edge(EdgeStatus.UNKNOWN)]

TRAP_CLEAR = EdgeInstance("a_share_billboard_reversal", "600519",
                          EdgeStatus.INACTIVE, "最近未上榜", "not listed recently")
TRAP_HIT = EdgeInstance("a_share_billboard_reversal", "600519",
                        EdgeStatus.ACTIVE, "于 2026-07-28 上榜", "listed 2026-07-28")


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
    r = judge(**BASE, edges=EDGE_ON,
              signals=[{"direction": "buy", "stop_pct": 0.05}],
              trap=TRAP_HIT)
    assert r.verdict is Verdict.AVOID
    # The evidence, not an opinion, must be in the finding — and it must be the
    # evidence for THIS symbol, produced by actually checking it.
    finding = next(c.finding_zh for c in r.checks if c.key == "known_mistake")
    assert "龙虎榜" in finding and "2026-07-28" in finding


def test_buy_signal_without_stop_is_refused():
    r = judge(**BASE, edges=EDGE_ON, signals=[{"direction": "buy"}])
    assert r.verdict is Verdict.WAIT
    assert _status(r, "risk") is CheckStatus.FAIL


def test_stop_beyond_ceiling_is_refused():
    r = judge(**BASE, edges=EDGE_ON, signals=[{"direction": "buy", "stop_pct": 0.35}])
    assert r.verdict is Verdict.WAIT
    assert _status(r, "risk") is CheckStatus.FAIL


def test_signal_without_validated_edge_is_only_watch():
    r = judge(**BASE, edges=EDGE_OFF, signals=[{"direction": "buy", "stop_pct": 0.05}])
    assert r.verdict is Verdict.WATCH
    assert _status(r, "edge") is CheckStatus.FAIL


def test_all_conditions_met_allows_action():
    r = judge(**BASE, edges=EDGE_ON, trap=TRAP_CLEAR,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=VOL_OK)
    assert r.verdict is Verdict.ACT
    assert _status(r, "trend") is CheckStatus.PASS
    assert _status(r, "volume") is CheckStatus.PASS


def test_downtrend_blocks_action_even_when_everything_else_passes():
    """《炒股的智慧》: 绝不要在跌势时入市 — this is a prohibition, not a preference."""
    r = judge(**BASE, edges=EDGE_ON,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=DOWN)
    assert r.verdict is Verdict.AVOID
    assert _status(r, "trend") is CheckStatus.FAIL
    assert "跌势" in r.headline_zh


def test_strong_downtrend_also_blocks_action():
    r = judge(**BASE, edges=EDGE_ON,
              signals=[{"direction": "buy", "stop_pct": 0.05}],
              trend=_trend(TrendClass.STRONG_DOWNTREND, 0.05))
    assert r.verdict is Verdict.AVOID


def test_downtrend_without_a_buy_signal_is_only_wait():
    """Nothing to avoid if you were not about to buy."""
    r = judge(**BASE, edges=EDGE_ON, signals=[], trend=DOWN)
    assert r.verdict is Verdict.WAIT
    assert _status(r, "trend") is CheckStatus.FAIL


def test_missing_trend_is_unknown_and_cannot_support_action():
    r = judge(**BASE, edges=EDGE_ON,
              signals=[{"direction": "buy", "stop_pct": 0.05}])
    assert _status(r, "trend") is CheckStatus.UNKNOWN
    assert r.verdict is Verdict.WATCH


def test_neutral_trend_warns_and_downgrades_action_to_watch():
    r = judge(**BASE, edges=EDGE_ON,
              signals=[{"direction": "buy", "stop_pct": 0.05}],
              trend=_trend(TrendClass.NEUTRAL, 0.5))
    assert _status(r, "trend") is CheckStatus.WARN
    assert r.verdict is Verdict.WATCH


def test_strong_uptrend_supports_action():
    r = judge(**BASE, edges=EDGE_ON, trap=TRAP_CLEAR,
              signals=[{"direction": "buy", "stop_pct": 0.05}],
              trend=_trend(TrendClass.STRONG_UPTREND, 0.95), volume=VOL_OK)
    assert r.verdict is Verdict.ACT


def test_missing_volume_is_unknown_and_cannot_support_action():
    """无成交量数据 is not "volume is fine" — it cannot carry a verdict to ACT."""
    r = judge(**BASE, edges=EDGE_ON,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP)
    assert _status(r, "volume") is CheckStatus.UNKNOWN
    assert r.verdict is Verdict.WATCH


def test_thin_volume_warns_and_downgrades_action_to_watch():
    """书中：没有成交量的突破并没有很大意义."""
    r = judge(**BASE, edges=EDGE_ON,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=VOL_THIN)
    assert _status(r, "volume") is CheckStatus.WARN
    assert r.verdict is Verdict.WATCH
    assert "成交量" in r.headline_zh


def test_distribution_volume_blocks_action_even_in_an_uptrend():
    """量增价滞 — heavy volume with no price progress is the book's top."""
    r = judge(**BASE, edges=EDGE_ON,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=VOL_DIST)
    assert _status(r, "volume") is CheckStatus.FAIL
    assert r.verdict is Verdict.AVOID


def test_distribution_without_a_buy_signal_is_only_wait():
    r = judge(**BASE, edges=EDGE_ON, signals=[], trend=UP, volume=VOL_DIST)
    assert r.verdict is Verdict.WAIT
    assert _status(r, "volume") is CheckStatus.FAIL


def test_climax_volume_also_fails():
    climax = _volume(VolumeClass.CLIMAX, VolumePriceAgreement.CONFIRM, 0.2)
    r = judge(**BASE, edges=EDGE_ON,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=climax)
    assert _status(r, "volume") is CheckStatus.FAIL
    assert r.verdict is Verdict.AVOID


def test_confirming_but_without_agreement_is_only_a_warning():
    """"Nothing is wrong" is not "volume confirms" — fail-closed by design."""
    neutral = _volume(VolumeClass.CONFIRMING, VolumePriceAgreement.NEUTRAL, 0.5)
    r = judge(**BASE, edges=EDGE_ON,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=neutral)
    assert _status(r, "volume") is CheckStatus.WARN
    assert r.verdict is Verdict.WATCH


def test_trend_failure_still_outranks_the_volume_check():
    r = judge(**BASE, edges=EDGE_ON,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=DOWN,
              volume=VOL_DIST)
    assert r.verdict is Verdict.AVOID
    assert "跌势" in r.headline_zh


def test_measured_trap_still_outranks_the_trend_check():
    r = judge(**BASE, edges=EDGE_ON,
              signals=[{"direction": "buy", "stop_pct": 0.05}],
              trap=TRAP_HIT, trend=UP)
    assert r.verdict is Verdict.AVOID
    assert "2026-07-28" in next(c.finding_zh for c in r.checks if c.key == "known_mistake")


def test_default_is_wait_when_there_is_nothing_to_do():
    r = judge(**BASE, edges=EDGE_ON, signals=[])
    assert r.verdict is Verdict.WAIT
    assert _status(r, "risk") is CheckStatus.UNKNOWN


def test_stale_data_fails_and_cannot_reach_action():
    """A judgement on months-old data is not a judgement about now.

    Staleness used to be a WARN that nothing acted on, so a fresh-looking ACT
    could rest on a price series from three months earlier.
    """
    r = judge(symbol="X", domain="us_equity", data_source="yahoo",
              as_of="2026-01-01", bars=500, edges=EDGE_ON, trap=TRAP_CLEAR,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=VOL_OK, daily_vol=0.015,
              now=datetime(2026, 7, 30, tzinfo=UTC))
    assert _status(r, "data") is CheckStatus.FAIL
    assert r.verdict is not Verdict.ACT


def test_staleness_limit_is_per_market():
    """A weekend-old A-share bar is normal; a two-day-old altcoin bar is not."""
    stale_for_alt = dict(data_source="okx", as_of="2026-07-25", bars=500,
                         edges=EDGE_ON, trap=TRAP_CLEAR, daily_vol=0.04,
                         now=None)
    from datetime import UTC, datetime
    now = datetime(2026, 7, 28, tzinfo=UTC)

    alt = judge(symbol="SOL-USDT", domain="altcoin",
                **{**stale_for_alt, "now": now})
    equity = judge(symbol="AAPL", domain="us_equity",
                   **{**stale_for_alt, "now": now})

    assert _status(alt, "data") is CheckStatus.FAIL       # 3 days > altcoin limit of 2
    assert _status(equity, "data") is CheckStatus.PASS    # 3 days is inside 5


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


def test_edge_elsewhere_in_the_asset_class_is_not_an_edge_here():
    """The composition fallacy this engine used to commit.

    An approved US edge exists because *some* ticker had insider cluster buying.
    On a ticker where nothing fired, the honest answer is that there is no edge —
    not "this market has a validated edge", which is what the banner printed on
    every US stock page.
    """
    r = judge(**BASE, edges=EDGE_OFF, trap=TRAP_CLEAR,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=VOL_OK)

    assert _status(r, "edge") is CheckStatus.FAIL
    assert r.verdict is Verdict.WATCH          # a signal, but nothing validated behind it
    assert r.verdict is not Verdict.ACT


def test_unknown_edge_check_cannot_support_action():
    """A detector outage is not a clean edge check."""
    r = judge(**BASE, edges=EDGE_UNKNOWN, trap=TRAP_CLEAR,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=VOL_OK)

    assert _status(r, "edge") is CheckStatus.UNKNOWN
    assert r.verdict is not Verdict.ACT


def test_unchecked_trap_is_unknown_not_a_pass():
    """The A-share bug: the dragon-tiger list was never fetched, yet every stock
    reported "未触发本项目实测的陷阱" — a claim that a check ran when it never did.
    """
    r = judge(**BASE, edges=EDGE_ON, trap=None,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=VOL_OK)

    assert _status(r, "known_mistake") is CheckStatus.UNKNOWN
    assert "没查过" in next(c.finding_zh for c in r.checks if c.key == "known_mistake")
    assert r.verdict is not Verdict.ACT


def test_trap_that_could_not_be_checked_is_reported_as_such():
    trap_unknown = EdgeInstance("a_share_billboard_reversal", "600519",
                                EdgeStatus.UNKNOWN, "数据不可用", "data unavailable")
    r = judge(**BASE, edges=EDGE_ON, trap=trap_unknown,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=VOL_OK)

    assert _status(r, "known_mistake") is CheckStatus.UNKNOWN
    assert r.verdict is not Verdict.ACT


def test_stop_inside_daily_noise_is_refused():
    """A 2% stop on an instrument that moves 4% a day is not risk control.

    The old check only compared against a fixed 20% ceiling, so the same stop
    passed on a utility and on a high-volatility altcoin alike.
    """
    r = judge(symbol="SOL-USDT", domain="altcoin", data_source="okx",
              as_of="2026-07-29", bars=641, edges=EDGE_ON, trap=TRAP_CLEAR,
              signals=[{"direction": "buy", "stop_pct": 0.02}], trend=UP,
              volume=VOL_OK, daily_vol=0.04,
              now=datetime(2026, 7, 30, tzinfo=UTC))

    assert _status(r, "risk") is CheckStatus.FAIL
    assert r.verdict is not Verdict.ACT


def test_stop_wide_enough_for_the_instrument_passes():
    r = judge(**BASE, edges=EDGE_ON, trap=TRAP_CLEAR,
              signals=[{"direction": "buy", "stop_pct": 0.06}], trend=UP,
              volume=VOL_OK)

    assert _status(r, "risk") is CheckStatus.PASS
    assert r.verdict is Verdict.ACT


def test_unknown_volatility_cannot_certify_a_stop():
    """Without the instrument's volatility the stop cannot be judged at all."""
    base = {k: v for k, v in BASE.items() if k != "daily_vol"}
    r = judge(**base, daily_vol=None, edges=EDGE_ON, trap=TRAP_CLEAR,
              signals=[{"direction": "buy", "stop_pct": 0.05}], trend=UP,
              volume=VOL_OK)

    assert _status(r, "risk") is CheckStatus.UNKNOWN
    assert r.verdict is not Verdict.ACT


def test_trap_evidence_comes_from_the_experiment_output(tmp_path, monkeypatch):
    """The numbers must track the data files, not a sentence in the source.

    The hard-coded text claimed 44,750 events while the committed result file
    held 6,446 — a figure no one could reproduce.
    """
    import json

    from libs.quant import verdict as verdict_module

    payload = {"hold_days": 5, "results": [
        {"strategy": "H1 全部上榜(超额,净成本)", "n": 1234,
         "mean_excess_pct": -3.5, "win_rate": 0.31},
    ]}
    path = tmp_path / "billboard.json"
    path.write_text(json.dumps(payload, ensure_ascii=False))
    monkeypatch.setitem(verdict_module.KNOWN_TRAPS["a_share"], "source", str(path))

    zh, en = verdict_module.trap_evidence("a_share")
    assert "1,234" in zh and "-3.50%" in zh and "31.0%" in zh
    assert "1,234" in en


def test_trap_evidence_is_empty_when_the_file_is_missing(monkeypatch):
    """No file, no numbers — never an invented figure."""
    from libs.quant import verdict as verdict_module

    monkeypatch.setitem(verdict_module.KNOWN_TRAPS["a_share"], "source", "/nope.json")
    assert verdict_module.trap_evidence("a_share") == ("", "")
