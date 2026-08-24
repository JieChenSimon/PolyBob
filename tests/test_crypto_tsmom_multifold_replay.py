from scripts.crypto_tsmom_multifold_replay import MAJOR_CRYPTO, signed_positions


def test_major_crypto_universe_is_predeclared_and_includes_benchmarks():
    assert {"BTC-USDT", "ETH-USDT", "SOL-USDT"}.issubset(MAJOR_CRYPTO)


def test_signed_momentum_threshold_is_explicit():
    prices = [100.0 + i for i in range(150)]
    low = signed_positions(prices, threshold=0.25)
    high = signed_positions(prices, threshold=0.5)
    assert low.shape == high.shape
