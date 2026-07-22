from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from libs.polymarket.btc_five_minute import (
    BtcFiveMinuteConfig,
    build_btc_five_minute_slug,
    build_workbench_snapshot,
    map_outcome_tokens,
    normalize_book,
)


def test_builds_five_minute_slug_from_unix_boundary():
    now = datetime.fromtimestamp(1782384799, tz=timezone.utc)

    assert build_btc_five_minute_slug(now) == "btc-updown-5m-1782384600"
    assert build_btc_five_minute_slug(now, offset_windows=1) == "btc-updown-5m-1782384900"


def test_maps_up_and_down_tokens_from_gamma_market():
    market = {
        "id": "2665625",
        "conditionId": "0xabc",
        "slug": "btc-updown-5m-1782384600",
        "question": "Bitcoin Up or Down - June 25, 6:50AM-6:55AM ET",
        "outcomes": '["Up", "Down"]',
        "clobTokenIds": '["up-token", "down-token"]',
    }

    mapped = map_outcome_tokens(market)

    assert mapped["UP"] == "up-token"
    assert mapped["DOWN"] == "down-token"


def test_rejects_unverified_outcome_mapping():
    market = {
        "outcomes": '["Up"]',
        "clobTokenIds": '["up-token", "down-token"]',
    }

    with pytest.raises(ValueError, match="outcome token mapping"):
        map_outcome_tokens(market)


def test_normalizes_order_book_sorting_and_depth():
    book = normalize_book(
        token_id="up-token",
        raw_book={
            "timestamp": "1782384700000",
            "hash": "hash-1",
            "bids": [
                {"price": "0.41", "size": "120"},
                {"price": "0.44", "size": "50"},
            ],
            "asks": [
                {"price": "0.58", "size": "40"},
                {"price": "0.55", "size": "80"},
            ],
        },
        received_at=datetime.fromtimestamp(1782384701, tz=timezone.utc),
    )

    assert book.is_real_orderbook is True
    assert book.source == "polymarket_clob"
    assert book.best_bid.price == pytest.approx(0.44)
    assert book.best_ask.price == pytest.approx(0.55)
    assert book.spread == pytest.approx(0.11)
    assert book.bid_depth_top3 == pytest.approx(170)
    assert book.ask_depth_top3 == pytest.approx(120)
    assert book.freshness_ms == 1000


def test_keeps_one_sided_order_book_visible_but_not_tradable():
    now = datetime.fromtimestamp(1782384701, tz=timezone.utc)
    up_book = normalize_book(
        token_id="up-token",
        raw_book={
            "timestamp": str(int(now.timestamp() * 1000)),
            "bids": [{"price": "0.44", "size": "120"}],
            "asks": [],
        },
        received_at=now,
    )
    down_book = normalize_book(
        token_id="down-token",
        raw_book={
            "timestamp": str(int(now.timestamp() * 1000)),
            "bids": [{"price": "0.52", "size": "150"}],
            "asks": [{"price": "0.55", "size": "200"}],
        },
        received_at=now,
    )

    snapshot = build_workbench_snapshot(
        market=_market_with_target(now, target=61187.70),
        up_book=up_book,
        down_book=down_book,
        btc_reference={"price": 61200.0, "timestamp": now.isoformat(), "source": "binance_futures"},
        now=now,
    )

    assert snapshot["source"] == "polymarket_clob"
    assert snapshot["action"] == "no_trade"
    assert "UP_ASK_MISSING" in snapshot["reason_codes"]
    assert snapshot["outcomes"]["UP"]["is_real_orderbook"] is True
    assert snapshot["outcomes"]["UP"]["best_bid"] == pytest.approx(0.44)
    assert snapshot["outcomes"]["UP"]["best_ask"] is None
    assert snapshot["outcomes"]["UP"]["spread"] is None
    assert snapshot["outcomes"]["UP"]["candidate_entry_price"] is None
    assert snapshot["outcomes"]["UP"]["entry_analysis"]["entry_decision"] == "no_trade"
    assert snapshot["entry_optimizer"]["decision"] == "no_trade"


def test_builds_no_trade_when_spread_is_too_wide():
    now = datetime.fromtimestamp(1782384701, tz=timezone.utc)
    market = {
        "id": "2665625",
        "conditionId": "0xabc",
        "slug": "btc-updown-5m-1782384600",
        "question": "Bitcoin Up or Down",
        "outcomes": '["Up", "Down"]',
        "clobTokenIds": '["up-token", "down-token"]',
        "endDate": (now + timedelta(seconds=180)).isoformat().replace("+00:00", "Z"),
        "active": True,
        "closed": False,
        "enableOrderBook": True,
        "polymarketPageTargetPrice": {
            "source": "polymarket_page_crypto_prices",
            "price": 107000.0,
            "field": "crypto-prices.openPrice",
        },
    }
    up_book = normalize_book(
        "up-token",
        {
            "timestamp": str(int(now.timestamp() * 1000)),
            "bids": [{"price": "0.40", "size": "500"}],
            "asks": [{"price": "0.62", "size": "500"}],
        },
        now,
    )
    down_book = normalize_book(
        "down-token",
        {
            "timestamp": str(int(now.timestamp() * 1000)),
            "bids": [{"price": "0.37", "size": "500"}],
            "asks": [{"price": "0.58", "size": "500"}],
        },
        now,
    )

    snapshot = build_workbench_snapshot(
        market=market,
        up_book=up_book,
        down_book=down_book,
        btc_reference={"price": 107500.0, "timestamp": now.isoformat(), "source": "binance_futures"},
        now=now,
        config=BtcFiveMinuteConfig(max_spread=0.08),
    )

    assert snapshot["action"] == "no_trade"
    assert "WIDE_SPREAD" in snapshot["reason_codes"]
    assert snapshot["source"] == "polymarket_clob"
    assert snapshot["outcomes"]["UP"]["candidate_entry_price"] is None


def test_builds_candidate_entry_for_best_edge_side():
    now = datetime.fromtimestamp(1782384701, tz=timezone.utc)
    market = {
        "id": "2665625",
        "conditionId": "0xabc",
        "slug": "btc-updown-5m-1782384600",
        "question": "Bitcoin Up or Down",
        "outcomes": '["Up", "Down"]',
        "clobTokenIds": '["up-token", "down-token"]',
        "endDate": (now + timedelta(seconds=180)).isoformat().replace("+00:00", "Z"),
        "active": True,
        "closed": False,
        "enableOrderBook": True,
        "polymarketPageTargetPrice": {
            "source": "polymarket_page_crypto_prices",
            "price": 107000.0,
            "field": "crypto-prices.openPrice",
        },
    }
    up_book = normalize_book(
        "up-token",
        {
            "timestamp": str(int(now.timestamp() * 1000)),
            "bids": [{"price": "0.48", "size": "900"}],
            "asks": [{"price": "0.50", "size": "900"}],
        },
        now,
    )
    down_book = normalize_book(
        "down-token",
        {
            "timestamp": str(int(now.timestamp() * 1000)),
            "bids": [{"price": "0.47", "size": "900"}],
            "asks": [{"price": "0.49", "size": "900"}],
        },
        now,
    )

    snapshot = build_workbench_snapshot(
        market=market,
        up_book=up_book,
        down_book=down_book,
        btc_reference={"price": 107500.0, "timestamp": now.isoformat(), "source": "binance_futures"},
        now=now,
        config=BtcFiveMinuteConfig(model_probability_up=0.56, min_edge=0.02),
    )

    assert snapshot["action"] == "watch_up"
    assert snapshot["recommended_outcome"] == "UP"
    assert snapshot["outcomes"]["UP"]["candidate_entry_price"] == pytest.approx(0.50)
    assert snapshot["outcomes"]["UP"]["estimated_edge"] > 0


def test_builds_target_price_from_polymarket_event_metadata():
    now = datetime.fromtimestamp(1782384701, tz=timezone.utc)
    market = {
        "id": "2665625",
        "conditionId": "0xabc",
        "slug": "btc-updown-5m-1782384600",
        "question": "Bitcoin Up or Down",
        "endDate": (now + timedelta(seconds=180)).isoformat().replace("+00:00", "Z"),
        "eventMetadata": {
            "priceToBeat": 61189.13539580122,
            "finalPrice": 61152.24342405366,
        },
    }
    up_book = normalize_book(
        "up-token",
        {
            "timestamp": str(int(now.timestamp() * 1000)),
            "bids": [{"price": "0.48", "size": "900"}],
            "asks": [{"price": "0.50", "size": "900"}],
        },
        now,
    )
    down_book = normalize_book(
        "down-token",
        {
            "timestamp": str(int(now.timestamp() * 1000)),
            "bids": [{"price": "0.47", "size": "900"}],
            "asks": [{"price": "0.49", "size": "900"}],
        },
        now,
    )

    snapshot = build_workbench_snapshot(
        market=market,
        up_book=up_book,
        down_book=down_book,
        btc_reference={"price": 61200.0, "timestamp": now.isoformat(), "source": "binance_futures"},
        now=now,
    )

    assert snapshot["target_price"] == {
        "source": "polymarket_event_metadata",
        "price": 61189.13539580122,
        "field": "eventMetadata.priceToBeat",
    }
    assert snapshot["final_price"] == {
        "source": "polymarket_event_metadata",
        "price": 61152.24342405366,
        "field": "eventMetadata.finalPrice",
    }


def test_builds_live_target_price_from_polymarket_page_crypto_prices():
    now = datetime.fromtimestamp(1782388810, tz=timezone.utc)
    market = {
        "id": "2665625",
        "conditionId": "0xabc",
        "slug": "btc-updown-5m-1782388800",
        "question": "Bitcoin Up or Down",
        "endDate": (now + timedelta(seconds=180)).isoformat().replace("+00:00", "Z"),
        "polymarketPageTargetPrice": {
            "source": "polymarket_page_crypto_prices",
            "price": 61187.70127318885,
            "field": "crypto-prices.openPrice",
        },
    }
    up_book = normalize_book(
        "up-token",
        {
            "timestamp": str(int(now.timestamp() * 1000)),
            "bids": [{"price": "0.48", "size": "900"}],
            "asks": [{"price": "0.50", "size": "900"}],
        },
        now,
    )
    down_book = normalize_book(
        "down-token",
        {
            "timestamp": str(int(now.timestamp() * 1000)),
            "bids": [{"price": "0.47", "size": "900"}],
            "asks": [{"price": "0.49", "size": "900"}],
        },
        now,
    )

    snapshot = build_workbench_snapshot(
        market=market,
        up_book=up_book,
        down_book=down_book,
        btc_reference={"price": 61200.0, "timestamp": now.isoformat(), "source": "binance_futures"},
        now=now,
    )

    assert snapshot["target_price"] == {
        "source": "polymarket_page_crypto_prices",
        "price": 61187.70127318885,
        "field": "crypto-prices.openPrice",
    }


def test_entry_optimizer_rejects_missing_target_price():
    now = datetime.fromtimestamp(1782388810, tz=timezone.utc)
    snapshot = build_workbench_snapshot(
        market={
            "id": "2665625",
            "conditionId": "0xabc",
            "slug": "btc-updown-5m-1782388800",
            "question": "Bitcoin Up or Down",
            "endDate": (now + timedelta(seconds=180)).isoformat().replace("+00:00", "Z"),
        },
        up_book=_fresh_book("up-token", now, bid=0.48, ask=0.50),
        down_book=_fresh_book("down-token", now, bid=0.47, ask=0.49),
        btc_reference={"price": 61200.0, "timestamp": now.isoformat(), "source": "binance_futures"},
        now=now,
    )

    assert snapshot["action"] == "no_trade"
    assert "MISSING_TARGET_PRICE" in snapshot["reason_codes"]
    assert snapshot["entry_optimizer"]["decision"] == "no_trade"
    assert snapshot["entry_optimizer"]["core_conclusion"] == "缺少目标价或实时价，跳过交易。"


def test_entry_optimizer_finds_favorable_up_entry_with_price_zones_and_kelly():
    now = datetime.fromtimestamp(1782388810, tz=timezone.utc)
    snapshot = build_workbench_snapshot(
        market=_market_with_target(now, target=61187.70),
        up_book=_fresh_book("up-token", now, bid=0.48, ask=0.50),
        down_book=_fresh_book("down-token", now, bid=0.47, ask=0.49),
        btc_reference={"price": 61280.0, "timestamp": now.isoformat(), "source": "binance_futures"},
        now=now,
    )

    up = snapshot["outcomes"]["UP"]["entry_analysis"]
    down = snapshot["outcomes"]["DOWN"]["entry_analysis"]

    assert snapshot["action"] == "watch_up"
    assert snapshot["recommended_outcome"] == "UP"
    assert snapshot["entry_optimizer"]["decision"] == "enter"
    assert snapshot["entry_optimizer"]["recommended_outcome"] == "UP"
    assert "UP" in snapshot["entry_optimizer"]["core_conclusion"]
    assert up["entry_decision"] == "enter"
    assert up["win_probability"] > 0.60
    assert up["expected_value"] > 0
    assert up["kelly_fraction"] > 0
    assert up["entry_band"]["enter_below"] < up["entry_band"]["watch_below"] < up["entry_band"]["avoid_above"]
    assert up["max_acceptable_price"] == pytest.approx(up["entry_band"]["enter_below"])
    assert down["entry_decision"] == "avoid"


def test_entry_optimizer_avoids_high_ask_even_when_direction_is_right():
    now = datetime.fromtimestamp(1782388810, tz=timezone.utc)
    snapshot = build_workbench_snapshot(
        market=_market_with_target(now, target=61187.70),
        up_book=_fresh_book("up-token", now, bid=0.78, ask=0.82),
        down_book=_fresh_book("down-token", now, bid=0.18, ask=0.22),
        btc_reference={"price": 61280.0, "timestamp": now.isoformat(), "source": "binance_futures"},
        now=now,
    )

    up = snapshot["outcomes"]["UP"]["entry_analysis"]

    assert snapshot["entry_optimizer"]["decision"] in {"watch", "no_trade"}
    assert up["entry_decision"] != "enter"
    assert up["expected_value"] < 0
    assert up["risk_notes"]


def test_entry_optimizer_caps_fractional_kelly():
    now = datetime.fromtimestamp(1782388810, tz=timezone.utc)
    snapshot = build_workbench_snapshot(
        market=_market_with_target(now, target=61187.70),
        up_book=_fresh_book("up-token", now, bid=0.18, ask=0.20),
        down_book=_fresh_book("down-token", now, bid=0.78, ask=0.80),
        btc_reference={"price": 61500.0, "timestamp": now.isoformat(), "source": "binance_futures"},
        now=now,
        config=BtcFiveMinuteConfig(max_kelly_fraction=0.04),
    )

    assert snapshot["outcomes"]["UP"]["entry_analysis"]["kelly_fraction"] == pytest.approx(0.04)


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


def _fresh_book(token_id: str, now: datetime, *, bid: float, ask: float):
    return normalize_book(
        token_id,
        {
            "timestamp": str(int(now.timestamp() * 1000)),
            "bids": [{"price": str(bid), "size": "900"}],
            "asks": [{"price": str(ask), "size": "900"}],
        },
        now,
    )
