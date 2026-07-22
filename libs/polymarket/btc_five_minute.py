"""BTC 5-minute Polymarket Up/Down workbench domain logic."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class BtcFiveMinuteConfig:
    max_spread: float = 0.08
    min_top_depth: float = 100.0
    max_stale_ms: int = 5_000
    near_expiry_seconds: int = 20
    model_probability_up: float = 0.5
    min_edge: float = 0.02
    min_win_probability: float = 0.58
    min_expected_value: float = 0.01
    watch_expected_value: float = -0.02
    price_probability_weight: float = 0.70
    fractional_kelly: float = 0.25
    max_kelly_fraction: float = 0.05


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class NormalizedBook:
    token_id: str
    source: str
    timestamp: datetime | None
    received_at: datetime
    hash: str | None
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    is_real_orderbook: bool

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None

    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return round(self.best_ask.price - self.best_bid.price, 4)

    @property
    def bid_depth_top3(self) -> float:
        return sum(level.size for level in self.bids[:3])

    @property
    def ask_depth_top3(self) -> float:
        return sum(level.size for level in self.asks[:3])

    @property
    def is_complete(self) -> bool:
        return self.best_bid is not None and self.best_ask is not None and self.best_bid.price < self.best_ask.price

    @property
    def freshness_ms(self) -> int | None:
        if self.timestamp is None:
            return None
        return max(0, int((self.received_at - self.timestamp).total_seconds() * 1000))


def build_btc_five_minute_slug(now: datetime, offset_windows: int = 0) -> str:
    timestamp = int(_ensure_utc(now).timestamp())
    window_start = timestamp - timestamp % 300 + offset_windows * 300
    return f"btc-updown-5m-{window_start}"


def map_outcome_tokens(market: dict[str, Any]) -> dict[str, str]:
    outcomes = _parse_json_list(market.get("outcomes"))
    token_ids = _parse_json_list(market.get("clobTokenIds") or market.get("clob_token_ids"))
    if len(outcomes) != 2 or len(token_ids) != 2:
        raise ValueError("outcome token mapping is unverified")

    mapped: dict[str, str] = {}
    for outcome, token_id in zip(outcomes, token_ids, strict=True):
        label = str(outcome).strip().upper()
        if label in {"UP", "YES"}:
            mapped["UP"] = str(token_id)
        elif label in {"DOWN", "NO"}:
            mapped["DOWN"] = str(token_id)

    if set(mapped) != {"UP", "DOWN"}:
        raise ValueError("outcome token mapping is unverified")
    return mapped


def normalize_book(
    token_id: str,
    raw_book: dict[str, Any],
    received_at: datetime,
) -> NormalizedBook:
    bids = tuple(sorted(_parse_levels(raw_book.get("bids", [])), key=lambda level: level.price, reverse=True))
    asks = tuple(sorted(_parse_levels(raw_book.get("asks", [])), key=lambda level: level.price))
    if bids and asks and bids[0].price >= asks[0].price:
        raise ValueError("CLOB order book is crossed or locked")

    return NormalizedBook(
        token_id=token_id,
        source="polymarket_clob",
        timestamp=_parse_timestamp(raw_book.get("timestamp")),
        received_at=_ensure_utc(received_at),
        hash=str(raw_book.get("hash")) if raw_book.get("hash") else None,
        bids=bids,
        asks=asks,
        is_real_orderbook=bool(bids or asks),
    )


def build_workbench_snapshot(
    *,
    market: dict[str, Any],
    up_book: NormalizedBook,
    down_book: NormalizedBook,
    btc_reference: dict[str, Any],
    now: datetime,
    config: BtcFiveMinuteConfig | None = None,
) -> dict[str, Any]:
    config = config or BtcFiveMinuteConfig()
    now = _ensure_utc(now)
    end_time = _parse_datetime(market.get("endDate") or market.get("endDateIso"))
    seconds_to_expiry = int((end_time - now).total_seconds()) if end_time else None
    target_price = _target_price(market)
    btc_price = _btc_reference_price(btc_reference)

    reason_codes = _quality_reasons(up_book, down_book, seconds_to_expiry, config)
    if target_price is None:
        reason_codes.append("MISSING_TARGET_PRICE")
    if btc_price is None:
        reason_codes.append("MISSING_BTC_REFERENCE")
    reason_codes = sorted(set(reason_codes))

    up_probability = _win_probability_up(
        up_book=up_book,
        down_book=down_book,
        btc_price=btc_price,
        target_price=target_price["price"] if target_price else None,
        seconds_to_expiry=seconds_to_expiry,
        config=config,
    )
    down_probability = 1.0 - up_probability
    outcomes = {
        "UP": _outcome_payload(up_book, up_probability, reason_codes, config),
        "DOWN": _outcome_payload(down_book, down_probability, reason_codes, config),
    }
    entry_optimizer = _entry_optimizer_payload(outcomes, reason_codes, config)

    recommended = None
    action = "no_trade"
    if not reason_codes:
        best_label = max(outcomes, key=lambda label: outcomes[label]["estimated_edge"])
        best = outcomes[best_label]
        if best["estimated_edge"] >= config.min_edge:
            recommended = best_label
            action = f"watch_{best_label.lower()}"
        else:
            reason_codes.append("EDGE_TOO_SMALL")

    return {
        "source": "polymarket_clob",
        "market_id": str(market.get("conditionId") or market.get("condition_id") or ""),
        "gamma_market_id": str(market.get("id") or ""),
        "slug": str(market.get("slug") or ""),
        "question": str(market.get("question") or ""),
        "now": now.isoformat(),
        "end_time": end_time.isoformat() if end_time else None,
        "seconds_to_expiry": seconds_to_expiry,
        "target_price": target_price,
        "final_price": _event_metadata_price(market, "finalPrice"),
        "btc_reference": btc_reference,
        "action": action,
        "recommended_outcome": recommended,
        "reason_codes": reason_codes,
        "entry_optimizer": entry_optimizer,
        "outcomes": outcomes,
    }


def _outcome_payload(
    book: NormalizedBook,
    model_probability: float,
    reason_codes: list[str],
    config: BtcFiveMinuteConfig,
) -> dict[str, Any]:
    executable_price = book.best_ask.price if book.best_ask else None
    cost_penalty = _cost_penalty(book)
    estimated_edge = round(model_probability - executable_price, 4) if executable_price is not None else None
    expected_value = round(model_probability - executable_price - cost_penalty, 4) if executable_price is not None else None
    candidate_entry_price = (
        executable_price
        if executable_price is not None
        and not reason_codes
        and expected_value is not None
        and expected_value >= config.min_expected_value
        else None
    )
    entry_analysis = _entry_analysis_payload(
        book=book,
        win_probability=model_probability,
        cost_penalty=cost_penalty,
        expected_value=expected_value,
        reason_codes=reason_codes,
        config=config,
    )
    return {
        "token_id": book.token_id,
        "source": book.source,
        "is_real_orderbook": book.is_real_orderbook,
        "book_timestamp": book.timestamp.isoformat() if book.timestamp else None,
        "freshness_ms": book.freshness_ms,
        "best_bid": book.best_bid.price if book.best_bid else None,
        "best_ask": book.best_ask.price if book.best_ask else None,
        "spread": book.spread,
        "bid_depth_top3": book.bid_depth_top3,
        "ask_depth_top3": book.ask_depth_top3,
        "model_probability": round(model_probability, 4),
        "candidate_entry_price": candidate_entry_price,
        "estimated_edge": estimated_edge,
        "entry_analysis": entry_analysis,
        "levels": {
            "bids": [level.__dict__ for level in book.bids[:10]],
            "asks": [level.__dict__ for level in book.asks[:10]],
        },
    }


def _entry_analysis_payload(
    *,
    book: NormalizedBook,
    win_probability: float,
    cost_penalty: float,
    expected_value: float,
    reason_codes: list[str],
    config: BtcFiveMinuteConfig,
) -> dict[str, Any]:
    entry_price = book.best_ask.price if book.best_ask else None
    enter_below = _clamp_probability(win_probability - cost_penalty - config.min_expected_value)
    watch_below = _clamp_probability(win_probability - cost_penalty)
    avoid_above = _clamp_probability(watch_below + max(0.02, book.spread or 0.0))
    raw_kelly = (
        max(0.0, (win_probability - entry_price) / max(0.01, 1.0 - entry_price))
        if entry_price is not None
        else 0.0
    )
    kelly_fraction = min(config.max_kelly_fraction, raw_kelly * config.fractional_kelly)

    risk_notes = list(reason_codes)
    if entry_price is None:
        risk_notes.append("MISSING_EXECUTABLE_ASK")
    if win_probability < config.min_win_probability:
        risk_notes.append("LOW_WIN_PROBABILITY")
    if expected_value is None or expected_value < config.min_expected_value:
        risk_notes.append("NEGATIVE_OR_SMALL_EV")

    if entry_price is None:
        decision = "no_trade"
    elif reason_codes:
        decision = "avoid"
    elif entry_price <= enter_below and win_probability >= config.min_win_probability and expected_value >= config.min_expected_value:
        decision = "enter"
    elif entry_price <= watch_below and expected_value >= config.watch_expected_value:
        decision = "watch"
    else:
        decision = "avoid"

    return {
        "entry_decision": decision,
        "entry_price": entry_price,
        "max_acceptable_price": enter_below,
        "win_probability": round(win_probability, 4),
        "expected_value": expected_value,
        "cost_penalty": round(cost_penalty, 4),
        "kelly_fraction": round(kelly_fraction, 4),
        "entry_band": {
            "enter_below": enter_below,
            "watch_below": watch_below,
            "avoid_above": avoid_above,
        },
        "risk_notes": sorted(set(risk_notes)),
    }


def _entry_optimizer_payload(
    outcomes: dict[str, dict[str, Any]],
    reason_codes: list[str],
    config: BtcFiveMinuteConfig,
) -> dict[str, Any]:
    if "MISSING_TARGET_PRICE" in reason_codes or "MISSING_BTC_REFERENCE" in reason_codes:
        return {
            "decision": "no_trade",
            "recommended_outcome": None,
            "core_conclusion": "缺少目标价或实时价，跳过交易。",
        }
    if reason_codes:
        return {
            "decision": "no_trade",
            "recommended_outcome": None,
            "core_conclusion": "盘口质量不满足入场条件，跳过交易。",
        }

    ranked = sorted(
        outcomes.items(),
        key=lambda item: item[1]["entry_analysis"]["expected_value"],
        reverse=True,
    )
    best_label, best = ranked[0]
    analysis = best["entry_analysis"]
    if analysis["entry_decision"] == "enter":
        conclusion = (
            f"当前入场候选：{best_label}，限价不高于 "
            f"{analysis['max_acceptable_price']:.3f}，建议仓位 {analysis['kelly_fraction']:.2%}。"
        )
        return {
            "decision": "enter",
            "recommended_outcome": best_label,
            "core_conclusion": conclusion,
            "max_acceptable_price": analysis["max_acceptable_price"],
            "kelly_fraction": analysis["kelly_fraction"],
            "expected_value": analysis["expected_value"],
            "win_probability": analysis["win_probability"],
        }
    if analysis["entry_decision"] == "watch":
        return {
            "decision": "watch",
            "recommended_outcome": best_label,
            "core_conclusion": f"{best_label} 接近可入场区，等待更好的限价。",
            "max_acceptable_price": analysis["max_acceptable_price"],
            "expected_value": analysis["expected_value"],
            "win_probability": analysis["win_probability"],
        }
    return {
        "decision": "no_trade",
        "recommended_outcome": None,
        "core_conclusion": "当前价格没有正期望入场点，跳过交易。",
        "minimum_expected_value": config.min_expected_value,
    }


def _quality_reasons(
    up_book: NormalizedBook,
    down_book: NormalizedBook,
    seconds_to_expiry: int | None,
    config: BtcFiveMinuteConfig,
) -> list[str]:
    reasons: list[str] = []
    for label, book in {"UP": up_book, "DOWN": down_book}.items():
        if not book.bids and not book.asks:
            reasons.append(f"{label}_BOOK_EMPTY")
        elif not book.bids:
            reasons.append(f"{label}_BID_MISSING")
        elif not book.asks:
            reasons.append(f"{label}_ASK_MISSING")
        if book.freshness_ms is None or book.freshness_ms > config.max_stale_ms:
            reasons.append(f"{label}_BOOK_STALE")
        if book.spread is not None and book.spread > config.max_spread:
            reasons.append("WIDE_SPREAD")
        if book.is_complete and min(book.bid_depth_top3, book.ask_depth_top3) < config.min_top_depth:
            reasons.append("LOW_LIQUIDITY")
    if seconds_to_expiry is None:
        reasons.append("MISSING_EXPIRY")
    elif seconds_to_expiry <= config.near_expiry_seconds:
        reasons.append("NEAR_EXPIRY")
    return sorted(set(reasons))


def _win_probability_up(
    *,
    up_book: NormalizedBook,
    down_book: NormalizedBook,
    btc_price: float | None,
    target_price: float | None,
    seconds_to_expiry: int | None,
    config: BtcFiveMinuteConfig,
) -> float:
    market_probability = _market_implied_up_probability(up_book, down_book)
    if btc_price is None or target_price is None or target_price <= 0:
        return _clamp_probability(config.model_probability_up)

    remaining = max(1, seconds_to_expiry if seconds_to_expiry is not None else 300)
    time_fraction = min(1.0, max(0.05, remaining / 300))
    scale = target_price * (0.0008 + 0.0012 * (time_fraction ** 0.5))
    distance_score = (btc_price - target_price) / max(1.0, scale)
    price_probability = _sigmoid(distance_score)
    weight = min(1.0, max(0.0, config.price_probability_weight))
    blended = weight * price_probability + (1.0 - weight) * market_probability
    return _clamp_probability(blended)


def _market_implied_up_probability(up_book: NormalizedBook, down_book: NormalizedBook) -> float:
    up_mid = _book_reference_probability(up_book)
    down_mid = _book_reference_probability(down_book)
    total = up_mid + down_mid
    if total <= 0:
        return 0.5
    return _clamp_probability(up_mid / total)


def _cost_penalty(book: NormalizedBook) -> float:
    spread_cost = (book.spread or 0.08) / 2
    depth = min(book.bid_depth_top3, book.ask_depth_top3) if book.is_complete else 0
    depth_penalty = 0.0 if depth >= 500 else min(0.03, (500 - depth) / 50_000)
    return round(spread_cost + depth_penalty, 4)


def _book_reference_probability(book: NormalizedBook) -> float:
    if book.best_bid is not None and book.best_ask is not None:
        return (book.best_bid.price + book.best_ask.price) / 2
    if book.best_ask is not None:
        return book.best_ask.price
    if book.best_bid is not None:
        return book.best_bid.price
    return 0.5


def _btc_reference_price(btc_reference: dict[str, Any]) -> float | None:
    try:
        price = float(btc_reference["price"])
    except (KeyError, TypeError, ValueError):
        return None
    return price if price > 0 else None


def _sigmoid(value: float) -> float:
    if value >= 12:
        return 0.999994
    if value <= -12:
        return 0.000006
    return 1.0 / (1.0 + 2.718281828459045 ** (-value))


def _clamp_probability(value: float) -> float:
    return round(min(0.99, max(0.01, value)), 4)


def _event_metadata_price(market: dict[str, Any], field: str) -> dict[str, Any] | None:
    metadata = market.get("eventMetadata") or market.get("event_metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = None
    if not isinstance(metadata, dict):
        return None
    try:
        price = float(metadata[field])
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "source": "polymarket_event_metadata",
        "price": price,
        "field": f"eventMetadata.{field}",
    }


def _target_price(market: dict[str, Any]) -> dict[str, Any] | None:
    metadata_price = _event_metadata_price(market, "priceToBeat")
    if metadata_price:
        return metadata_price

    page_target = market.get("polymarketPageTargetPrice")
    if not isinstance(page_target, dict):
        return None
    try:
        price = float(page_target["price"])
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "source": str(page_target.get("source") or "polymarket_page_crypto_prices"),
        "price": price,
        "field": str(page_target.get("field") or "crypto-prices.openPrice"),
    }


def _parse_levels(levels: Any) -> list[BookLevel]:
    parsed: list[BookLevel] = []
    if not isinstance(levels, list):
        return parsed
    for level in levels:
        if isinstance(level, dict):
            price = level.get("price")
            size = level.get("size")
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            price, size = level[0], level[1]
        else:
            continue
        try:
            parsed.append(BookLevel(price=float(price), size=float(size)))
        except (TypeError, ValueError):
            continue
    return parsed


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
    return []


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        return datetime.fromtimestamp(raw / 1000 if raw > 10_000_000_000 else raw, tz=timezone.utc)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            raw = int(stripped)
            return datetime.fromtimestamp(raw / 1000 if raw > 10_000_000_000 else raw, tz=timezone.utc)
        return _parse_datetime(stripped)
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
