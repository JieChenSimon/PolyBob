"""Tests for the point-in-time, survivorship-free universe."""

from __future__ import annotations

from datetime import datetime

import pytest

from libs.quant.universe import PointInTimeUniverse, UniverseMember

T0 = datetime(2026, 1, 1)
T1 = datetime(2026, 2, 1)
T2 = datetime(2026, 3, 1)
T3 = datetime(2026, 4, 1)


def _universe():
    u = PointInTimeUniverse()
    # A resolved Polymarket market: active Jan–Feb, gone after.
    u.add_market("resolved-mkt", listed_at=T0, delisted_at=T2, kind="polymarket")
    # A still-active market.
    u.add_market("live-mkt", listed_at=T1, delisted_at=None, kind="polymarket")
    # A delisted token.
    u.add_market("dead-token", listed_at=T0, delisted_at=T1, kind="crypto")
    return u


def test_member_rejects_delist_before_list():
    with pytest.raises(ValueError):
        UniverseMember("x", listed_at=T2, delisted_at=T0)


def test_active_as_of_includes_only_live_members():
    u = _universe()
    # At T0: resolved-mkt and dead-token active; live-mkt not yet listed.
    assert u.active_ids_as_of(T0) == ["dead-token", "resolved-mkt"]
    # At T1 (dead-token delists exactly here, live-mkt lists): boundaries.
    assert u.active_ids_as_of(T1) == ["live-mkt", "resolved-mkt"]
    # At T2 (resolved-mkt resolves): only live-mkt.
    assert u.active_ids_as_of(T2) == ["live-mkt"]


def test_delisted_boundary_is_exclusive():
    u = _universe()
    # dead-token delists at T1 -> not active AT T1.
    assert "dead-token" not in u.active_ids_as_of(T1)


def test_listed_boundary_is_inclusive():
    u = _universe()
    assert "live-mkt" in u.active_ids_as_of(T1)


def test_constituents_between_spans_lifespans():
    u = _universe()
    members = u.constituents_between(T0, T3)
    assert {m.instrument_id for m in members} == {"resolved-mkt", "live-mkt", "dead-token"}


def test_survivorship_excluded_flags_vanished_instruments():
    u = _universe()
    # Building a universe "as of T0" but only from things alive at T3 (reference)
    # would wrongly drop resolved-mkt and dead-token.
    excluded = u.survivorship_excluded(as_of=T0, reference=T3)
    assert set(excluded) == {"resolved-mkt", "dead-token"}


def test_delisted_before():
    u = _universe()
    gone = {m.instrument_id for m in u.delisted_before(T2)}
    assert gone == {"resolved-mkt", "dead-token"}
