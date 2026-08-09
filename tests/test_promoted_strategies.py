"""The two strategies whose edges cleared the gate must obey the gate.

These exist because the project's central defect was that the board and the desk
described different objects: every approved edge was un-implemented, and every
runnable strategy was unvalidated, so a fail-closed gate blocked everything and
proved nothing. Now that the two are the same object, the rules that make them
the same have to be enforced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

import pytest

from libs.quant.promotion_registry import PromotionRegistry
from strategies.altcoin_retail_crowding import AltcoinRetailCrowding
from strategies.altcoin_retail_crowding import strategy as alt_module
from strategies.us_insider_cluster_buy import UsInsiderClusterBuy, find_clusters
from strategies.us_insider_cluster_buy import strategy as insider_module


@dataclass(frozen=True)
class _Trade:
    symbol: str
    filing_date: str
    shares: float = 1000.0
    price: float = 100.0
    trans_code: str = "P"

    @property
    def is_open_market_buy(self) -> bool:
        return self.trans_code == "P" and self.shares > 0

    @property
    def value_usd(self) -> float:
        return self.shares * self.price


@dataclass(frozen=True)
class _Point:
    date: str
    long_short_ratio: float
    open_interest: float = 0.0


class _RecordingIntentService:
    def __init__(self):
        self.created: list[dict] = []

    async def create_intent(self, **kwargs):
        self.created.append(kwargs)
        return {"intent_id": f"intent_{len(self.created)}", **kwargs}


def _board(tmp_path, strategy, instrument, role="trade", approved=True):
    path = tmp_path / "board.json"
    path.write_text(json.dumps({"board": [{
        "strategy": strategy, "instrument": instrument, "approved": approved,
        "role": role, "failed": [],
    }]}, ensure_ascii=False))
    return path


@pytest.fixture()
def use_board(tmp_path, monkeypatch):
    def _install(strategy, instrument, role="trade", approved=True):
        path = _board(tmp_path, strategy, instrument, role, approved)
        registry = PromotionRegistry(path)
        for module in (insider_module, alt_module):
            monkeypatch.setattr(module, "get_registry", lambda registry=registry: registry)
        return registry
    return _install


# --------------------------------------------------------------- insider edge
def test_find_clusters_uses_the_validated_thresholds():
    trades = [_Trade("ACME", "2026-07-28"), _Trade("ACME", "2026-07-28"),
              _Trade("SOLO", "2026-07-28")]
    found = find_clusters(trades, as_of=date(2026, 7, 30), max_age_days=5,
                          min_insiders=2, min_value_usd=50_000.0)
    assert [c.symbol for c in found] == ["ACME"]
    assert found[0].insiders == 2


@pytest.mark.asyncio
async def test_insider_strategy_creates_an_intent_when_promoted(use_board):
    use_board("us_insider_cluster_buy", "US_ALL")
    service = _RecordingIntentService()
    strategy = UsInsiderClusterBuy(
        {}, intent_service=service,
        trade_source=lambda y, q: [_Trade("ACME", "2026-07-28"),
                                   _Trade("ACME", "2026-07-28")],
    )

    created = await strategy.run_once(as_of=date(2026, 7, 30))

    assert len(created) == 1
    leg = created[0]["legs"][0]
    assert leg["side"] == "buy" and leg["symbol"] == "ACME"
    assert created[0]["metadata"]["filing_date"] == "2026-07-28"


@pytest.mark.asyncio
async def test_intent_is_idempotent_per_event(use_board):
    """One filing is one trade, however often the scanner runs."""
    use_board("us_insider_cluster_buy", "US_ALL")
    service = _RecordingIntentService()
    strategy = UsInsiderClusterBuy(
        {}, intent_service=service,
        trade_source=lambda y, q: [_Trade("ACME", "2026-07-28"),
                                   _Trade("ACME", "2026-07-28")],
    )

    await strategy.run_once(as_of=date(2026, 7, 30))
    again = await strategy.run_once(as_of=date(2026, 7, 30))

    assert again == []
    assert len(service.created) == 1


@pytest.mark.asyncio
async def test_unpromoted_strategy_creates_nothing(use_board):
    use_board("us_insider_cluster_buy", "US_ALL", approved=False)
    service = _RecordingIntentService()
    strategy = UsInsiderClusterBuy(
        {}, intent_service=service,
        trade_source=lambda y, q: [_Trade("ACME", "2026-07-28"),
                                   _Trade("ACME", "2026-07-28")],
    )

    assert await strategy.run_once(as_of=date(2026, 7, 30)) == []
    assert service.created == []


@pytest.mark.asyncio
async def test_an_avoid_role_never_lets_the_strategy_trade(use_board):
    use_board("us_insider_cluster_buy", "US_ALL", role="avoid")
    service = _RecordingIntentService()
    strategy = UsInsiderClusterBuy(
        {}, intent_service=service,
        trade_source=lambda y, q: [_Trade("ACME", "2026-07-28"),
                                   _Trade("ACME", "2026-07-28")],
    )

    assert await strategy.run_once(as_of=date(2026, 7, 30)) == []


@pytest.mark.asyncio
async def test_parameters_drifting_from_the_evidence_stops_trading(use_board):
    """Loosening to a single insider trades something never validated.

    The single-buyer group was the control and did not clear the hurdle, so a
    strategy configured that way is not the strategy the board approved.
    """
    use_board("us_insider_cluster_buy", "US_ALL")
    service = _RecordingIntentService()
    strategy = UsInsiderClusterBuy(
        {"min_insiders": 1}, intent_service=service,
        trade_source=lambda y, q: [_Trade("ACME", "2026-07-28")],
    )

    assert strategy.parameters_match_evidence() is False
    assert await strategy.run_once(as_of=date(2026, 7, 30)) == []


# -------------------------------------------------------------- altcoin edge
def _crowded(ccy):
    points = [_Point(f"2026-06-{d:02d}", 1.0) for d in range(1, 31)]
    points.append(_Point("2026-07-01", 5.0))
    return points


@pytest.mark.asyncio
async def test_crowding_strategy_shorts_the_perp(use_board):
    """The tradable leg is the short — the same leg the study measured."""
    use_board("altcoin_retail_crowding", "ALTCOIN_x8")
    service = _RecordingIntentService()
    strategy = AltcoinRetailCrowding(
        {"universe": ["SOL"]}, intent_service=service, positioning_source=_crowded
    )

    created = await strategy.run_once()

    assert len(created) == 1
    leg = created[0]["legs"][0]
    assert leg["side"] == "sell"
    assert leg["symbol"] == "SOL-USDT-SWAP"


@pytest.mark.asyncio
async def test_crowding_strategy_respects_the_gate(use_board):
    use_board("altcoin_retail_crowding", "ALTCOIN_x8", approved=False)
    service = _RecordingIntentService()
    strategy = AltcoinRetailCrowding(
        {"universe": ["SOL"]}, intent_service=service, positioning_source=_crowded
    )

    assert await strategy.run_once() == []


@pytest.mark.asyncio
async def test_coin_outside_the_validated_universe_is_extrapolation(use_board):
    use_board("altcoin_retail_crowding", "ALTCOIN_x8")
    service = _RecordingIntentService()
    strategy = AltcoinRetailCrowding(
        {"universe": ["PEPE"]}, intent_service=service, positioning_source=_crowded
    )

    assert strategy.parameters_match_evidence() is False
    assert await strategy.run_once() == []


def test_uncrowded_market_produces_no_candidates():
    def flat(ccy):
        return [_Point(f"2026-06-{d:02d}", 1.0 + d * 0.01) for d in range(1, 31)] + [
            _Point("2026-07-01", 1.0)
        ]

    strategy = AltcoinRetailCrowding({"universe": ["SOL"]}, positioning_source=flat)
    assert strategy.scan() == []


# ------------------------------------------------------------------ catalogue
def test_promoted_strategies_are_registered_in_the_manager():
    """A board row that names a strategy the manager cannot build is a dead gate."""
    from modules.strategy_manager.service import StrategyManagerService

    manager = StrategyManagerService()
    registry = PromotionRegistry()
    for record in registry.promoted_pairs():
        assert record.strategy in manager._factories, (
            f"{record.strategy} is promoted for trading but the strategy manager "
            "has no factory for it"
        )
