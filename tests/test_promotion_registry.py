"""Tests for the promotion registry (lab-vs-promoted gate)."""

from __future__ import annotations

import json

from libs.quant.promotion_registry import PromotionRegistry


def _write_board(path, board):
    path.write_text(json.dumps({"board": board}, ensure_ascii=False))


def test_missing_board_promotes_nothing(tmp_path):
    reg = PromotionRegistry(tmp_path / "nope.json")
    assert reg.is_promoted("tsmom") is False
    assert reg.promoted_pairs() == []


def test_only_approved_pairs_are_promoted(tmp_path):
    p = tmp_path / "board.json"
    _write_board(p, [
        {"strategy": "tsmom", "instrument": "BTCUSDT", "approved": True, "role": "trade",
         "sharpe": 1.2, "dsr": 0.95, "failed": []},
        {"strategy": "mean_reversion", "instrument": "BTCUSDT", "approved": False, "role": "trade",
         "sharpe": -0.5, "dsr": 0.01, "failed": ["deflated_sharpe", "cost_stress"]},
    ])
    reg = PromotionRegistry(p)
    assert reg.is_promoted("tsmom") is True
    assert reg.is_promoted("tsmom", "BTCUSDT") is True
    assert reg.is_promoted("tsmom", "ETHUSDT") is False   # not approved on that instrument
    assert reg.is_promoted("mean_reversion") is False
    assert {r.strategy for r in reg.promoted_pairs()} == {"tsmom"}


def test_avoid_filter_is_approved_but_never_tradable(tmp_path):
    """An avoidance filter is a real finding and still not permission.

    The A-share dragon-tiger result is a reliable *negative* drift in a market
    where the stock cannot be shorted: it tells you not to buy and earns nothing.
    Listing it as a promoted edge is what made the desk look three edges deep
    when it was one.
    """
    p = tmp_path / "board.json"
    _write_board(p, [
        {"strategy": "a_share_billboard_reversal", "instrument": "A_SHARE_ALL",
         "approved": True, "role": "avoid", "domain": "a_share",
         "mean_excess_pct": -2.74, "failed": []},
    ])
    reg = PromotionRegistry(p)

    assert reg.is_promoted("a_share_billboard_reversal") is False
    assert reg.promoted_pairs() == []
    assert [r.strategy for r in reg.avoid_filters()] == ["a_share_billboard_reversal"]
    assert [r.strategy for r in reg.avoid_filters("a_share")] == ["a_share_billboard_reversal"]
    assert reg.avoid_filters("us_equity") == []
    assert "回避过滤器" in reg.reason_blocked("a_share_billboard_reversal")


def test_row_without_a_role_is_not_promoted(tmp_path):
    """Fail closed on an unlabelled row — a hand-written board must not trade.

    The board this replaced was hand-written and unreproducible; the gate has to
    treat "no role stated" as "no permission", exactly like a missing board.
    """
    p = tmp_path / "board.json"
    _write_board(p, [
        {"strategy": "mystery_edge", "instrument": "US_ALL", "approved": True, "failed": []},
    ])
    reg = PromotionRegistry(p)

    assert reg.is_promoted("mystery_edge") is False
    assert reg.promoted_pairs() == []
    assert "role" in reg.reason_blocked("mystery_edge")


def test_reason_blocked_messages(tmp_path):
    p = tmp_path / "board.json"
    _write_board(p, [
        {"strategy": "dual_ma", "instrument": "BTCUSDT", "approved": False, "sharpe": 0.0,
         "dsr": 0.02, "failed": ["deflated_sharpe"]},
    ])
    reg = PromotionRegistry(p)
    assert "未过门禁" in reg.reason_blocked("dual_ma")
    assert "deflated_sharpe" in reg.reason_blocked("dual_ma")
    assert "留 lab" in reg.reason_blocked("never_tested")   # no record at all


def test_all_lab_when_none_pass(tmp_path):
    # Mirrors the real result: 0/N approved -> nothing may go live.
    p = tmp_path / "board.json"
    _write_board(p, [
        {"strategy": s, "instrument": "BTCUSDT", "approved": False, "role": "trade",
         "sharpe": 0.1, "dsr": 0.1, "failed": ["deflated_sharpe"]}
        for s in ("tsmom", "dual_ma", "signal_fusion")
    ])
    reg = PromotionRegistry(p)
    assert reg.promoted_pairs() == []
    assert all(not reg.is_promoted(s) for s in ("tsmom", "dual_ma", "signal_fusion"))


def test_promotion_gate_is_fail_closed_by_default():
    """The safe state must be the default state.

    An unvalidated strategy reaching the execution desk is the failure mode this
    project exists to prevent, so ``require_strategy_promotion`` defaults to on.
    Opening the gate has to be a deliberate act (``REQUIRE_STRATEGY_PROMOTION=false``),
    not something a fresh checkout does silently.
    """
    from libs.config import Settings

    assert Settings(_env_file=None).require_strategy_promotion is True


# --------------------------------------------------------- evidence expiry
def _record(**kw):
    from libs.quant.promotion_registry import PromotionRecord

    base = dict(strategy="e", instrument="I", approved=True, role="trade",
                sharpe=0.0, dsr=None, failed=[], max_evidence_age_days=90)
    return PromotionRecord(**{**base, **kw})


def _days_ago(n: int) -> str:
    import datetime as dt

    return (dt.datetime.now(dt.UTC).date() - dt.timedelta(days=n)).isoformat()


def test_expiry_is_evaluated_now_not_baked_into_the_board():
    """Age is a question about today, so it is answered at read time.

    It used to be written into ``data/promotion_board.json``, which meant the file
    stopped reproducing the moment the date rolled over — the board's one
    guarantee is that the same evidence rebuilds the same bytes.
    """
    fresh = _record(evidence_end=_days_ago(10))
    stale = _record(evidence_end=_days_ago(400))
    assert fresh.evidence_age_days == 10
    assert fresh.evidence_expired is False
    assert stale.evidence_expired is True


def test_expired_evidence_withdraws_trade_permission():
    """A finding kept its permission for as long as the file sat on disk."""
    assert _record(evidence_end=_days_ago(10)).tradable is True
    assert _record(evidence_end=_days_ago(400)).tradable is False


def test_an_expired_avoid_filter_also_stops_applying():
    """"These 257 A-shares fell last quarter" is not a reason to skip them today.

    An avoidance filter grants no position, but it does change behaviour — it
    stops you buying. Letting it outlive its evidence means acting on a stale
    finding in the one direction the gate does not otherwise police.
    """
    assert _record(role="avoid", evidence_end=_days_ago(10)).is_avoid_filter is True
    assert _record(role="avoid", evidence_end=_days_ago(400)).is_avoid_filter is False


def test_a_row_with_no_boundary_does_not_expire_but_earns_nothing_either():
    """No boundary means the source carried no per-event data.

    Such a row already fails the board on ``no_per_event_data_cannot_verify_t``,
    so it must not *additionally* be treated as fresh — but neither may a missing
    date be read as "infinitely old", which would be inventing a fact.
    """
    unknown = _record(evidence_end=None)
    assert unknown.evidence_age_days is None
    assert unknown.evidence_expired is False


def test_a_malformed_boundary_is_unknown_not_expired():
    assert _record(evidence_end="not-a-date").evidence_age_days is None


def test_a_row_without_a_declared_shelf_life_cannot_silently_expire():
    """Absent limit means the spec forgot to declare one; that is a board bug,
    not licence to expire the row on an invented default."""
    assert _record(evidence_end=_days_ago(9999), max_evidence_age_days=None).evidence_expired is False


def test_to_dict_carries_the_computed_fields():
    """``asdict`` walks declared fields only, so properties would vanish silently
    and reach the dashboard as ``undefined`` — which slips past a ``!== null``
    guard and renders as ``NaN``."""
    payload = _record(evidence_end=_days_ago(400)).to_dict()
    assert payload["evidence_age_days"] == 400
    assert payload["evidence_expired"] is True
    assert payload["tradable"] is False


def test_reason_blocked_distinguishes_stale_from_never_significant(tmp_path):
    """The two need different actions: re-run the experiment vs drop the hypothesis."""
    import json

    from libs.quant.promotion_registry import PromotionRegistry

    board = {"generated_at": "x", "board": [{
        "strategy": "e", "instrument": "I", "approved": True, "role": "trade",
        "failed": [], "evidence_end": _days_ago(400), "max_evidence_age_days": 90,
    }]}
    path = tmp_path / "board.json"
    path.write_text(json.dumps(board))
    registry = PromotionRegistry(path)
    reason = registry.reason_blocked("e")
    assert registry.is_promoted("e") is False
    assert "证据已过期" in reason
    assert "重跑该实验" in reason
