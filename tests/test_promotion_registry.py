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
        {"strategy": "tsmom", "instrument": "BTCUSDT", "approved": True, "sharpe": 1.2, "dsr": 0.95, "failed": []},
        {"strategy": "mean_reversion", "instrument": "BTCUSDT", "approved": False, "sharpe": -0.5,
         "dsr": 0.01, "failed": ["deflated_sharpe", "cost_stress"]},
    ])
    reg = PromotionRegistry(p)
    assert reg.is_promoted("tsmom") is True
    assert reg.is_promoted("tsmom", "BTCUSDT") is True
    assert reg.is_promoted("tsmom", "ETHUSDT") is False   # not approved on that instrument
    assert reg.is_promoted("mean_reversion") is False
    assert {r.strategy for r in reg.promoted_pairs()} == {"tsmom"}


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
        {"strategy": s, "instrument": "BTCUSDT", "approved": False, "sharpe": 0.1,
         "dsr": 0.1, "failed": ["deflated_sharpe"]}
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
