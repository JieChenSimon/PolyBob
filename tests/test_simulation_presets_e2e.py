"""End-to-end "is this preset actually usable?" tests.

A preset is only useful if an operator can pick it, feed it live-shaped
snapshots, and watch it open positions and produce metrics. These tests do
exactly that: for every runnable preset (and the new momentum strategy) we
resolve the preset into ``create_run`` kwargs, start the run, drive it with
synthetic ``FEATURE_SNAPSHOT`` / ``PAIR_SNAPSHOT`` dicts shaped like the ones
``services/simulation/service.py`` dispatches, then assert the run booked
trades (including a closed, pnl-realizing trade) and computes non-trivial
metrics. If a preset can't trade against representative data it is not usable,
and this file would fail.
"""

from datetime import UTC, datetime

import pytest

from services.simulation.metrics import compute_run_metrics
from services.simulation.presets import resolve_run_params
from services.simulation.service import SimulationService


def make_service(tmp_path) -> SimulationService:
    return SimulationService(tmp_path / "sim.sqlite3", equity_poll_seconds=3600)


def _now() -> datetime:
    # Naive UTC matches the service's staleness handling for tz-naive stamps.
    return datetime.utcnow()


# ---------------------------------------------------------------- run helpers


async def start_preset_run(
    service: SimulationService,
    preset_id: str,
    universe: list[str],
    *,
    initial_capital: float = 10_000.0,
    extra_config: dict | None = None,
) -> str:
    """Resolve a preset, create the run with a concrete universe, and start it."""
    config_overrides = {"cooldown_seconds": 0.0, "impact_coefficient": 0.0}
    if extra_config:
        config_overrides.update(extra_config)
    params = resolve_run_params(
        preset_id,
        universe=universe,
        initial_capital=initial_capital,
        config_overrides=config_overrides,
    )
    params.pop("preset_id", None)
    run = await service.create_run(**params)
    run_id = run["run_id"]
    await service.start_run(run_id)
    return run_id


def assert_usable(service: SimulationService, run_id: str, *, min_trades: int = 2) -> dict:
    """A preset is 'usable' iff it booked trades, closed one, and has metrics."""
    trades = service.store.list_trades(run_id)
    assert len(trades) >= min_trades, f"expected >= {min_trades} trades, got {len(trades)}"
    metrics = compute_run_metrics(service.store, run_id)
    assert metrics["trade_count"] >= min_trades
    assert metrics["closed_trade_count"] >= 1, "no closed (pnl-realizing) trade"
    assert metrics["realized_pnl"] != 0.0, "closed trades produced zero pnl"
    assert metrics["total_fees"] > 0.0, "no fees charged — fills did not happen"
    assert len(service.store.list_equity_points(run_id)) >= 1, "no equity points"
    return metrics


# ------------------------------------------------------------- snapshot builders


def fusion_snapshot(market_id: str, ai_direction: int, bid: float, ask: float, ts=None) -> dict:
    """Feature snapshot carrying an AI indicator so SignalFusion emits a signal."""
    mid = (bid + ask) / 2.0
    return {
        "market_id": market_id,
        "timestamp": ts or _now(),
        "mid_price": mid,
        "spread_bps": (ask - bid) / mid * 10_000.0,
        "bid_price": bid,
        "ask_price": ask,
        "bid_size": 1_000_000.0,
        "ask_size": 1_000_000.0,
        "depth_imbalance": 0.0,
        # A single high-confidence AI signal fuses to a decisive direction.
        "ai_direction": ai_direction,
        "ai_confidence": 0.9,
    }


def reversion_snapshot(
    market_id: str, spread_bps: float, depth_imbalance: float, bid: float, ask: float, ts=None
) -> dict:
    """Wide-spread, balanced-book feature snapshot for spread_reversion_v1."""
    mid = (bid + ask) / 2.0
    return {
        "market_id": market_id,
        "timestamp": ts or _now(),
        "mid_price": mid,
        "spread_bps": spread_bps,
        "bid_price": bid,
        "ask_price": ask,
        "bid_size": 1_000_000.0,
        "ask_size": 1_000_000.0,
        "depth_imbalance": depth_imbalance,
    }


def momentum_snapshot(market_id: str, price: float, ts=None) -> dict:
    """Feature snapshot whose mid price drives the dual-MA momentum source."""
    bid = price * 0.999
    ask = price * 1.001
    return {
        "market_id": market_id,
        "timestamp": ts or _now(),
        "mid_price": price,
        "spread_bps": (ask - bid) / price * 10_000.0,
        "bid_price": bid,
        "ask_price": ask,
        "bid_size": 1_000_000.0,
        "ask_size": 1_000_000.0,
    }


def pair_snapshot(pair_id: str, opportunity_side: str, prices: dict, ts=None) -> dict:
    """Pair snapshot shaped like PairFeatureEngine output for spread_arbitrage_v1."""
    return {
        "pair_id": pair_id,
        "timestamp": ts or _now(),
        "left": {"venue": "binance", "symbol": "ETHUSDT"},
        "right": {"venue": "hyperliquid", "symbol": "ETH"},
        "left_bid": prices["left_bid"],
        "left_ask": prices["left_ask"],
        "right_bid": prices["right_bid"],
        "right_ask": prices["right_ask"],
        "spread_bps": 8.0,
        "z_score": 1.5,
        "net_edge_bps": 12.0,
        "opportunity_side": opportunity_side,
    }


# ------------------------------------------------------------------ fusion presets

FUSION_PRESETS = [
    "single_instrument_deep",
    "multi_instrument_robust",
    "conservative_stress",
    "high_conviction_concentrated",
    "fusion_active_cycle",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("preset_id", FUSION_PRESETS)
async def test_fusion_preset_opens_and_closes(tmp_path, preset_id):
    service = make_service(tmp_path)
    inst = "mkt_fusion"
    run_id = await start_preset_run(service, preset_id, [inst])

    # Buy signal opens a long, then an opposite signal at a higher price closes
    # it (and flips short), realizing pnl net of the folded fee.
    await service._on_feature_snapshot(
        fusion_snapshot(inst, ai_direction=1, bid=0.50, ask=0.52)
    )
    await service._on_feature_snapshot(
        fusion_snapshot(inst, ai_direction=-1, bid=0.60, ask=0.62)
    )

    metrics = assert_usable(service, run_id)
    # Bought low (~0.52), sold higher (~0.60): the closed trade is a winner.
    assert metrics["realized_pnl"] > 0.0


# --------------------------------------------------------------- reversion presets


@pytest.mark.asyncio
@pytest.mark.parametrize("preset_id", ["spread_reversion_focus", "reversion_sensitive_scan"])
async def test_reversion_preset_opens_and_closes(tmp_path, preset_id):
    service = make_service(tmp_path)
    inst = "mkt_rev"
    run_id = await start_preset_run(service, preset_id, [inst])

    # Balanced book with a wide spread: imbalance >= 0 -> buy, then a negative
    # imbalance at a higher price -> sell that closes the long.
    await service._on_feature_snapshot(
        reversion_snapshot(inst, spread_bps=220.0, depth_imbalance=0.1, bid=0.90, ask=0.94)
    )
    await service._on_feature_snapshot(
        reversion_snapshot(inst, spread_bps=220.0, depth_imbalance=-0.1, bid=1.10, ask=1.14)
    )

    assert_usable(service, run_id)


# --------------------------------------------------------------------- pair preset


@pytest.mark.asyncio
async def test_pair_arbitrage_sensitive_preset_trades_both_legs(tmp_path):
    service = make_service(tmp_path)
    pair_id = "eth_binance_hyperliquid"
    # The preset's suggested universe IS the pair id (that is how PAIR_SNAPSHOTs
    # are matched); confirm resolve_run_params keeps it and the run subscribes.
    run_id = await start_preset_run(service, "pair_arbitrage_sensitive", [pair_id])

    # Entry: long left / short right.
    await service._on_pair_snapshot(
        pair_snapshot(
            pair_id,
            "long_left_short_right",
            {"left_bid": 3000.0, "left_ask": 3002.0, "right_bid": 2998.0, "right_ask": 3000.0},
        )
    )
    # Exit: opportunity flips -> short left / long right, at levels that let
    # both legs close (left sold higher, right bought back lower).
    await service._on_pair_snapshot(
        pair_snapshot(
            pair_id,
            "long_right_short_left",
            {"left_bid": 3010.0, "left_ask": 3012.0, "right_bid": 2990.0, "right_ask": 2992.0},
        )
    )

    metrics = assert_usable(service, run_id, min_trades=3)
    # Both legs were booked (positions keyed by "venue:symbol").
    assert {"binance:ETHUSDT", "hyperliquid:ETH"} <= set(metrics["per_instrument"])


# ------------------------------------------------------- new momentum strategy


@pytest.mark.asyncio
async def test_momentum_strategy_trades_a_trend_reversal(tmp_path):
    service = make_service(tmp_path)
    inst = "mkt_mom"
    run = await service.create_run(
        name="momentum e2e",
        strategy_id="momentum_dualma_v1",
        universe=[inst],
        initial_capital=10_000.0,
        config={
            "cooldown_seconds": 0.0,
            "impact_coefficient": 0.0,
            "fast_window": 2,
            "slow_window": 4,
            "min_separation_bps": 2.0,
            "position_fraction": 0.05,
        },
    )
    run_id = run["run_id"]
    await service.start_run(run_id)

    # Warm the window flat (no signal), ramp up (fast MA > slow MA -> buy long),
    # then ramp down (fast MA < slow MA -> sell, closing the long).
    up = [1.00, 1.00, 1.00, 1.00, 1.03, 1.06, 1.10, 1.15, 1.20]
    down = [1.15, 1.08, 1.00, 0.92, 0.85]
    for price in up + down:
        await service._on_feature_snapshot(momentum_snapshot(inst, price))

    metrics = assert_usable(service, run_id)
    assert metrics["per_instrument"][inst]["trade_count"] >= 2


@pytest.mark.asyncio
async def test_momentum_source_is_causal_no_signal_before_full_window(tmp_path):
    """The momentum source must not act before it has slow_window prices."""
    service = make_service(tmp_path)
    inst = "mkt_mom2"
    run = await service.create_run(
        name="momentum causal",
        strategy_id="momentum_dualma_v1",
        universe=[inst],
        initial_capital=10_000.0,
        config={"cooldown_seconds": 0.0, "fast_window": 2, "slow_window": 5},
    )
    run_id = run["run_id"]
    await service.start_run(run_id)

    # Fewer prices than slow_window -> the window is not full -> no trades yet.
    for price in [1.00, 1.10, 1.20, 1.30]:
        await service._on_feature_snapshot(momentum_snapshot(inst, price))
    assert service.store.list_trades(run_id) == []
