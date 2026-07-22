import pytest

from libs.crypto.discovery.trade_plan import RISK_FRACTIONS, build_trade_plan, risk_quantity


def market_structure():
    closes = [
        10.0,
        10.2,
        10.5,
        11.0,
        11.5,
        12.0,
        12.5,
        12.0,
        11.5,
        11.0,
        10.8,
        10.6,
        10.5,
        10.4,
        10.45,
        10.5,
        10.55,
        10.6,
        10.58,
        10.6,
    ]
    highs = [value + 0.3 for value in closes]
    lows = [value - 0.3 for value in closes]
    volumes = [1000.0] * len(closes)
    return closes, highs, lows, volumes


def eligible_plan(account_equity: float | None = 10_000.0):
    closes, highs, lows, volumes = market_structure()
    return build_trade_plan(
        closes=closes,
        highs=highs,
        lows=lows,
        volumes=volumes,
        pump_potential=80.0,
        cashout_risk=30.0,
        coverage=0.85,
        account_equity=account_equity,
        liquidity_usd=2_000_000.0,
        volume_24h_usd=5_000_000.0,
        quantity_step=0.1,
    )


def test_trade_plan_returns_structural_levels_and_three_risk_modes():
    result = eligible_plan()

    assert result.eligible is True
    assert result.entry_low < result.entry_high
    assert result.stop < result.entry_low
    assert result.target_1 > result.entry_high
    assert result.target_2 >= result.target_1
    assert result.reward_risk >= 2.0
    assert set(result.position_sizes) == set(RISK_FRACTIONS)
    assert result.position_sizes["conservative"].quantity < result.position_sizes["balanced"].quantity
    assert result.position_sizes["balanced"].quantity <= result.position_sizes["aggressive"].quantity


def test_missing_equity_keeps_levels_but_not_fake_quantity():
    result = eligible_plan(account_equity=None)

    assert result.eligible is True
    assert all(size.quantity is None for size in result.position_sizes.values())
    assert all(size.max_loss_usd is None for size in result.position_sizes.values())


@pytest.mark.parametrize(
    ("pump_potential", "cashout_risk", "coverage", "expected_veto"),
    [
        (69.9, 30.0, 0.85, "PUMP_POTENTIAL_BELOW_MINIMUM"),
        (80.0, 45.1, 0.85, "CASHOUT_RISK_ABOVE_MAXIMUM"),
        (80.0, 30.0, 0.69, "COVERAGE_BELOW_MINIMUM"),
    ],
)
def test_trade_plan_enforces_score_risk_and_coverage_gates(
    pump_potential: float,
    cashout_risk: float,
    coverage: float,
    expected_veto: str,
):
    closes, highs, lows, volumes = market_structure()
    result = build_trade_plan(
        closes=closes,
        highs=highs,
        lows=lows,
        volumes=volumes,
        pump_potential=pump_potential,
        cashout_risk=cashout_risk,
        coverage=coverage,
        account_equity=10_000.0,
        liquidity_usd=2_000_000.0,
        volume_24h_usd=5_000_000.0,
        quantity_step=0.1,
    )

    assert result.eligible is False
    assert expected_veto in result.vetoes


def test_trade_plan_enforces_liquidity_and_volume_gates():
    closes, highs, lows, volumes = market_structure()
    result = build_trade_plan(
        closes=closes,
        highs=highs,
        lows=lows,
        volumes=volumes,
        pump_potential=80.0,
        cashout_risk=30.0,
        coverage=0.85,
        account_equity=10_000.0,
        liquidity_usd=499_999.0,
        volume_24h_usd=999_999.0,
        quantity_step=0.1,
    )

    assert "LIQUIDITY_BELOW_MINIMUM" in result.vetoes
    assert "VOLUME_BELOW_MINIMUM" in result.vetoes


def test_risk_quantity_rejects_zero_distance():
    with pytest.raises(ValueError, match="entry and stop must differ"):
        risk_quantity(10_000.0, 0.01, 10.0, 10.0)


def test_trade_plan_rejects_insufficient_candles():
    result = build_trade_plan(
        closes=[10.0] * 14,
        highs=[10.2] * 14,
        lows=[9.8] * 14,
        volumes=[1000.0] * 14,
        pump_potential=80.0,
        cashout_risk=30.0,
        coverage=0.85,
        account_equity=10_000.0,
        liquidity_usd=2_000_000.0,
        volume_24h_usd=5_000_000.0,
        quantity_step=0.1,
    )

    assert result.eligible is False
    assert result.vetoes == ["INSUFFICIENT_CANDLES"]


def test_old_extreme_high_does_not_create_an_unbounded_target():
    closes, highs, lows, volumes = market_structure()
    highs[0] = 1_000.0
    result = build_trade_plan(
        closes=closes,
        highs=highs,
        lows=lows,
        volumes=volumes,
        pump_potential=80.0,
        cashout_risk=30.0,
        coverage=0.85,
        account_equity=None,
        liquidity_usd=2_000_000.0,
        volume_24h_usd=5_000_000.0,
        quantity_step=None,
    )

    entry_mid = (result.entry_low + result.entry_high) / 2
    unit_risk = entry_mid - result.stop
    assert result.target_2 <= entry_mid + 4 * unit_risk
