"""Canonical Polymarket order-book state and snapshot+incremental reducer.

This module is the single implementation of book reconstruction used both by
the live realtime ingestor and by deterministic replay (libs/polymarket/replay).

Semantics (see docs/order-book-platform-plan.md):

- ``book`` messages are full snapshots and reset per-asset state.
- ``price_change`` messages are incremental level updates (size 0 removes the
  level). A ``price_change`` for an asset with no prior snapshot marks the book
  stale instead of guessing; callers should trigger a snapshot resync.
- Bids are sorted descending, asks ascending; duplicate price levels are
  merged by summing sizes.
- A crossed book (best_bid >= best_ask) is marked ``degraded`` instead of
  being published as-is.
- Provider timestamps are kept when present; when absent ``source_ts`` is
  ``None`` and quality is downgraded to ``no_timestamp``. Local time is never
  substituted as exchange time.
- Polymarket's market channel exposes a message ``hash`` but no monotonic
  sequence number, so states carry ``sequence_status="no_sequence_available"``
  plus a local per-asset ``message_count`` and the last provider hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

QUALITY_OK = "ok"
QUALITY_STALE = "stale"
QUALITY_DEGRADED = "degraded"
QUALITY_NO_TIMESTAMP = "no_timestamp"

SEQUENCE_UNAVAILABLE = "no_sequence_available"

_BID_SIDES = {"buy", "bid", "bids"}
_ASK_SIDES = {"sell", "ask", "asks"}


def parse_provider_timestamp(value: Any) -> datetime | None:
    """Parse a provider timestamp (ms epoch or ISO 8601) to naive UTC.

    Returns ``None`` when the value is missing or unparseable — callers must
    NOT substitute local time for a missing exchange timestamp.
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(float(value) / 1000)
        except (OverflowError, OSError, ValueError):
            return None

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.isdigit():
            try:
                return datetime.utcfromtimestamp(int(stripped) / 1000)
            except (OverflowError, OSError, ValueError):
                return None
        normalized = stripped.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    return None


def normalize_levels(levels: Iterable[Any]) -> dict[float, float]:
    """Normalize raw levels to ``{price: size}``, merging duplicate prices.

    Accepts ``{"price": .., "size": ..}`` dicts or ``[price, size]`` pairs.
    Invalid entries and non-positive sizes are dropped.
    """
    merged: dict[float, float] = {}
    for level in levels or []:
        if isinstance(level, Mapping):
            price, size = level.get("price"), level.get("size")
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            price, size = level[0], level[1]
        else:
            continue
        try:
            price_f, size_f = float(price), float(size)
        except (TypeError, ValueError):
            continue
        if size_f <= 0:
            continue
        merged[price_f] = merged.get(price_f, 0.0) + size_f
    return merged


@dataclass(frozen=True)
class BookState:
    """Immutable canonical per-asset book state."""

    asset_id: str
    market_id: str | None
    bids: tuple[tuple[float, float], ...]  # sorted by price descending
    asks: tuple[tuple[float, float], ...]  # sorted by price ascending
    source_ts: datetime | None
    receive_ts: datetime
    quality: str
    has_snapshot: bool = True
    message_count: int = 0
    last_hash: str | None = None
    sequence_status: str = SEQUENCE_UNAVAILABLE

    @property
    def best_bid(self) -> tuple[float, float] | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> tuple[float, float] | None:
        return self.asks[0] if self.asks else None

    @property
    def is_crossed(self) -> bool:
        return bool(self.bids and self.asks and self.bids[0][0] >= self.asks[0][0])

    def book_hash(self) -> str:
        """Deterministic content hash of the book state (for replay checks)."""
        payload = json.dumps(
            {
                "asset_id": self.asset_id,
                "bids": self.bids,
                "asks": self.asks,
                "source_ts": self.source_ts.isoformat() if self.source_ts else None,
                "quality": self.quality,
                "message_count": self.message_count,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PolymarketBookReducer:
    """Per-asset snapshot + incremental reducer for the Polymarket CLOB feed."""

    def __init__(self) -> None:
        self._bids: dict[str, dict[float, float]] = {}
        self._asks: dict[str, dict[float, float]] = {}
        self._has_snapshot: dict[str, bool] = {}
        self._market_ids: dict[str, str | None] = {}
        self._message_counts: dict[str, int] = {}
        self._states: dict[str, BookState] = {}

    def get_state(self, asset_id: str) -> BookState | None:
        return self._states.get(asset_id)

    def apply_snapshot(
        self,
        data: Mapping[str, Any],
        *,
        receive_ts: datetime | None = None,
        asset_id: str | None = None,
        market_id: str | None = None,
    ) -> BookState | None:
        """Apply a full ``book`` snapshot, replacing any prior state."""
        asset = asset_id or data.get("asset_id")
        if not asset:
            return None
        receive_ts = receive_ts or datetime.utcnow()

        self._bids[asset] = normalize_levels(data.get("bids", []))
        self._asks[asset] = normalize_levels(data.get("asks", []))
        self._has_snapshot[asset] = True
        self._market_ids[asset] = market_id or data.get("market") or self._market_ids.get(asset)
        self._message_counts[asset] = self._message_counts.get(asset, 0) + 1

        return self._finalize(
            asset,
            source_ts=parse_provider_timestamp(data.get("timestamp")),
            receive_ts=receive_ts,
            provider_hash=data.get("hash"),
        )

    def apply_price_change(
        self,
        data: Mapping[str, Any],
        *,
        receive_ts: datetime | None = None,
    ) -> list[BookState]:
        """Apply a ``price_change`` message; returns one state per touched asset.

        Supported payload shapes (all observed CLOB market-channel variants):
        - top-level ``asset_id`` + ``changes: [{price, side, size}, ...]``
        - top-level ``price_changes: [{asset_id?, price, side, size}, ...]``
        - flat ``{asset_id, price, side, size}``

        If an asset has no prior snapshot the book is marked stale
        (``has_snapshot=False``) with empty levels — never a guessed book.
        """
        receive_ts = receive_ts or datetime.utcnow()
        source_ts = parse_provider_timestamp(data.get("timestamp"))
        provider_hash = data.get("hash")
        default_asset = data.get("asset_id")
        market_id = data.get("market")

        changes_by_asset: dict[str, list[Mapping[str, Any]]] = {}
        raw_changes = data.get("changes") or data.get("price_changes")
        if raw_changes is None and data.get("price") is not None:
            raw_changes = [data]
        for change in raw_changes or []:
            if not isinstance(change, Mapping):
                continue
            asset = change.get("asset_id") or default_asset
            if not asset:
                continue
            changes_by_asset.setdefault(asset, []).append(change)

        states: list[BookState] = []
        for asset, changes in changes_by_asset.items():
            self._message_counts[asset] = self._message_counts.get(asset, 0) + 1
            if market_id and asset not in self._market_ids:
                self._market_ids[asset] = market_id

            if not self._has_snapshot.get(asset, False):
                # Conservative: no base snapshot — mark stale, do not guess.
                self._bids.setdefault(asset, {})
                self._asks.setdefault(asset, {})
                states.append(
                    self._finalize(
                        asset,
                        source_ts=source_ts,
                        receive_ts=receive_ts,
                        provider_hash=provider_hash,
                    )
                )
                continue

            for change in changes:
                self._apply_level(asset, change)

            states.append(
                self._finalize(
                    asset,
                    source_ts=source_ts,
                    receive_ts=receive_ts,
                    provider_hash=provider_hash,
                )
            )
        return states

    def invalidate(self, asset_id: str) -> None:
        """Mark an asset's book as needing a fresh snapshot (e.g. reconnect)."""
        self._has_snapshot[asset_id] = False

    def _apply_level(self, asset: str, change: Mapping[str, Any]) -> None:
        side = str(change.get("side", "")).strip().lower()
        try:
            price = float(change.get("price"))
            size = float(change.get("size"))
        except (TypeError, ValueError):
            return

        if side in _BID_SIDES:
            book = self._bids[asset]
        elif side in _ASK_SIDES:
            book = self._asks[asset]
        else:
            return

        if size <= 0:
            book.pop(price, None)
        else:
            book[price] = size

    def _finalize(
        self,
        asset: str,
        *,
        source_ts: datetime | None,
        receive_ts: datetime,
        provider_hash: str | None,
    ) -> BookState:
        bids = tuple(sorted(self._bids.get(asset, {}).items(), key=lambda l: -l[0]))
        asks = tuple(sorted(self._asks.get(asset, {}).items(), key=lambda l: l[0]))
        has_snapshot = self._has_snapshot.get(asset, False)

        if not has_snapshot:
            quality = QUALITY_STALE
        elif bids and asks and bids[0][0] >= asks[0][0]:
            quality = QUALITY_DEGRADED
        elif source_ts is None:
            quality = QUALITY_NO_TIMESTAMP
        else:
            quality = QUALITY_OK

        state = BookState(
            asset_id=asset,
            market_id=self._market_ids.get(asset),
            bids=bids,
            asks=asks,
            source_ts=source_ts,
            receive_ts=receive_ts,
            quality=quality,
            has_snapshot=has_snapshot,
            message_count=self._message_counts.get(asset, 0),
            last_hash=provider_hash if isinstance(provider_hash, str) else None,
        )
        self._states[asset] = state
        return state
