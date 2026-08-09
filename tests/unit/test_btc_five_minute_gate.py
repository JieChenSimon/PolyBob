"""The BTC 5m workbench must not out-run the study it came from.

The study (`data/btc5m_mispricing.json`) traded only when the model disagreed
with the quote by >= 10 points, and it still failed its hurdle (n=95, t=3.45 vs
3.77). Three separate ways the product code could quietly claim more than that
evidence supports, each pinned here:

1. a live entry threshold looser than the researched one — 0.02 vs 0.10 fires on
   noise the study never measured and would have counted as no-trade;
2. position sizing emitted for an edge that never cleared the promotion gate;
3. a fabricated number standing in for a missing one (a 0.08 spread nobody
   quoted, a 0.5 probability nothing computed), which reads downstream exactly
   like a measured value.

Plus the circularity: an "edge" is only evidence of mispricing if the model that
produced it does not itself contain the market price.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from libs.polymarket import btc_five_minute as btc
from libs.polymarket.btc_five_minute import (
    BtcFiveMinuteConfig,
    NormalizedBook,
    blend_up_probability,
    build_workbench_snapshot,
    load_research_thresholds,
    normalize_book,
)
from libs.quant.promotion_registry import PromotionRegistry

NOW = datetime.fromtimestamp(1782388810, tz=timezone.utc)


def _market_with_target(now: datetime, target: float) -> dict:
    return {
        "id": "2665625",
        "conditionId": "0xabc",
        "slug": "btc-updown-5m-1782388800",
        "question": "Bitcoin Up or Down",
        "endDate": (now + timedelta(seconds=180)).isoformat().replace("+00:00", "Z"),
        "polymarketPageTargetPrice": {
            "source": "polymarket_page_crypto_prices",
            "price": target,
            "field": "crypto-prices.openPrice",
        },
    }


def _fresh_book(token_id: str, now: datetime, *, bid: float, ask: float) -> NormalizedBook:
    return normalize_book(
        token_id,
        {
            "timestamp": str(int(now.timestamp() * 1000)),
            "bids": [{"price": str(bid), "size": "900"}],
            "asks": [{"price": str(ask), "size": "900"}],
        },
        now,
    )


def _snapshot(**overrides):
    kwargs = dict(
        market=_market_with_target(NOW, target=61187.70),
        up_book=_fresh_book("up-token", NOW, bid=0.48, ask=0.50),
        down_book=_fresh_book("down-token", NOW, bid=0.47, ask=0.49),
        btc_reference={"price": 61280.0, "timestamp": NOW.isoformat(), "source": "binance_futures"},
        now=NOW,
    )
    kwargs.update(overrides)
    return build_workbench_snapshot(**kwargs)


@pytest.fixture()
def promoted(monkeypatch, tmp_path):
    """Pretend the board promoted btc5m_mispricing, to test the ungated path."""
    path = tmp_path / "board.json"
    path.write_text(json.dumps({"board": [{
        "strategy": "btc5m_mispricing", "instrument": "BTC_5M",
        "approved": True, "role": "trade", "failed": [],
    }]}))
    registry = PromotionRegistry(path)
    monkeypatch.setattr(btc, "get_registry", lambda: registry)
    return registry


# ------------------------------------------------------- threshold provenance
def test_live_threshold_is_read_from_the_research_file_not_hardcoded():
    research = load_research_thresholds()
    assert research.edge_threshold == pytest.approx(0.10)
    # The config must not carry an independent number that can drift from it.
    assert BtcFiveMinuteConfig().min_edge is None

    snapshot = _snapshot()
    thresholds = snapshot["thresholds"]
    assert thresholds["min_edge"] == pytest.approx(research.edge_threshold)
    assert thresholds["source"].endswith("btc5m_mispricing.json")
    assert thresholds["consistent"] is True


def test_a_looser_live_threshold_is_reported_and_never_applied():
    """0.02 vs the researched 0.10 would fire on five times more noise."""
    snapshot = _snapshot(config=BtcFiveMinuteConfig(min_edge=0.02))
    thresholds = snapshot["thresholds"]

    assert thresholds["consistent"] is False
    assert thresholds["configured_min_edge"] == pytest.approx(0.02)
    assert "0.02" in thresholds["error"] and "0.1" in thresholds["error"]
    assert thresholds["min_edge"] == pytest.approx(0.10)  # the stricter one wins
    assert "LIVE_THRESHOLD_DISAGREES_WITH_RESEARCH" in snapshot["reason_codes"]


def test_unreadable_research_file_blocks_everything(tmp_path, promoted):
    missing = tmp_path / "nope.json"
    snapshot = _snapshot(research_path=missing)

    assert snapshot["thresholds"]["min_edge"] is None
    assert "MISSING_RESEARCH_THRESHOLD" in snapshot["reason_codes"]
    assert snapshot["entry_optimizer"]["decision"] != "enter"
    assert snapshot["entry_optimizer"].get("kelly_fraction") is None


# -------------------------------------------------------------- promotion gate
def test_ungated_edge_never_produces_a_position_recommendation():
    """This exact book produced `enter` + a Kelly size before the gate existed."""
    snapshot = _snapshot()

    gate = snapshot["gate_status"]
    assert gate["promoted"] is False
    assert gate["strategy"] == "btc5m_mispricing" and gate["instrument"] == "BTC_5M"

    optimizer = snapshot["entry_optimizer"]
    assert optimizer["decision"] == "research_only"
    assert optimizer["recommended_outcome"] is None
    assert optimizer.get("kelly_fraction") is None
    assert optimizer.get("max_acceptable_price") is None
    assert "建议仓位" not in optimizer["core_conclusion"]

    up = snapshot["outcomes"]["UP"]["entry_analysis"]
    assert up["entry_decision"] == "research_only"
    assert up["kelly_fraction"] is None
    assert up["max_acceptable_price"] is None
    assert up["entry_band"] is None
    assert snapshot["outcomes"]["UP"]["candidate_entry_price"] is None
    assert snapshot["action"] == "research_only"
    assert snapshot["recommended_outcome"] is None


def test_ungated_snapshot_still_serves_calibration():
    """The point is to grow n from 95, so the calibration inputs must survive."""
    snapshot = _snapshot()

    assert snapshot["outcomes"]["UP"]["model_probability"] > 0.5
    assert snapshot["outcomes"]["UP"]["best_ask"] == pytest.approx(0.50)
    gate = snapshot["gate_status"]
    assert gate["n"] == 95
    assert gate["t_stat"] == pytest.approx(3.45)
    assert gate["significant"] is False
    assert gate["brier_model"] == pytest.approx(0.2221)
    assert gate["brier_market"] == pytest.approx(0.2491)
    assert gate["brier_model"] < gate["brier_market"]


def test_a_promoted_board_restores_sizing(promoted):
    snapshot = _snapshot()

    assert snapshot["gate_status"]["promoted"] is True
    optimizer = snapshot["entry_optimizer"]
    assert optimizer["decision"] == "enter"
    assert optimizer["kelly_fraction"] > 0
    assert optimizer["max_acceptable_price"] is not None


def test_experimental_indicators_detach_the_model_from_the_evidence(promoted):
    """The study's model was the digital option alone; anything else is untested."""
    snapshot = _snapshot(enabled_indicators=["digital_option", "momentum_1m"])

    assert snapshot["gate_status"]["model_matches_evidence"] is False
    assert snapshot["entry_optimizer"]["decision"] == "research_only"


# ------------------------------------------------------------- no fabrication
def test_missing_spread_does_not_become_a_fabricated_eight_cents():
    one_sided = normalize_book(
        "up-token",
        {"timestamp": str(int(NOW.timestamp() * 1000)),
         "bids": [{"price": "0.44", "size": "120"}], "asks": []},
        NOW,
    )
    assert one_sided.spread is None
    assert btc._cost_penalty(one_sided) is None


def test_an_empty_book_is_not_a_coin_flip():
    empty = NormalizedBook(
        token_id="t", source="test", timestamp=None, received_at=NOW,
        hash=None, bids=(), asks=(), is_real_orderbook=False,
    )
    assert btc._book_reference_probability(empty) is None
    assert btc._market_implied_up_probability(empty, empty) is None

    prob, _ = blend_up_probability(
        up_book=empty, down_book=empty, btc_price=None, target_price=None,
        seconds_to_expiry=120, config=BtcFiveMinuteConfig(),
    )
    assert prob is None  # nothing was computed, so nothing is reported


def test_no_model_probability_means_no_edge_and_no_decision():
    snapshot = _snapshot(
        btc_reference={"timestamp": NOW.isoformat(), "source": "binance_futures"},
    )

    up = snapshot["outcomes"]["UP"]
    assert up["model_probability"] is None
    assert up["estimated_edge"] is None
    assert up["entry_analysis"]["expected_value"] is None
    assert "MISSING_MODEL_PROBABILITY" in snapshot["reason_codes"]


# ------------------------------------------------------------- non-circularity
def test_the_edge_is_not_measured_against_a_model_containing_the_price(promoted):
    """`estimated_edge = model - ask` only means something if `model` is price-free.

    With the quote weighted 0.30 into the model, ~30% of any "mispricing" was the
    bid-ask mechanism arguing with itself.
    """
    assert "market_implied" not in btc.DEFAULT_ENABLED_INDICATORS

    snapshot = _snapshot(enabled_indicators=["digital_option", "market_implied"])
    breakdown = {b["id"]: b for b in snapshot["indicator_breakdown"]}

    assert breakdown["market_implied"]["used"] is False
    assert breakdown["market_implied"]["excluded_reason"] == "circular_with_estimated_edge"
    assert breakdown["market_implied"]["probability"] is not None  # still shown
    assert snapshot["gate_status"]["model_matches_evidence"] is True

    up = snapshot["outcomes"]["UP"]
    assert up["model_vs_mid"] is not None
    assert up["estimated_edge"] == pytest.approx(
        up["model_probability"] - up["best_ask"], abs=1e-4
    )
