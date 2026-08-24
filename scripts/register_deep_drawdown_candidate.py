"""Pre-register the cross-asset deep-drawdown research candidate.

The file intentionally records no result.  A result may only be attached by a
later real-data replay that uses the fixed configuration in
``config/research/deep_drawdown_rebound.yaml``.
"""

from __future__ import annotations

from libs.quant.hypothesis import Hypothesis, HypothesisRegistry, Rationale


def main() -> None:
    registry = HypothesisRegistry()
    registry.register(
        Hypothesis(
            hypothesis_id="deep_drawdown_rebound_v1",
            claim=(
                "Assets that lose at least 50% from a prior point-in-time peak may earn "
                "positive cost-adjusted forward returns after staged entry, but the effect "
                "must be tested separately by asset domain and holding horizon."
            ),
            rationale=Rationale.BEHAVIOURAL,
            mechanism=(
                "Forced selling and attention shocks can create temporary dislocations, "
                "while limits to arbitrage and uncertainty delay recovery; permanent "
                "impairment is an explicit competing outcome."
            ),
            literature=(
                "Pre-registered as a drawdown-conditioned reversal candidate; related "
                "momentum-crash evidence motivates regime and risk controls, not a claim "
                "that every 50% drawdown recovers."
            ),
            direction="long_after_drawdown",
            universe="A_SHARE,US_EQUITY,BTC,ALTCOIN with PIT and survivorship controls",
            horizon_days=252,
            cost_bps=40.0,
            min_sharpe=0.5,
            n_configs=16,
        )
    )
    print("registered deep_drawdown_rebound_v1 with no result")


if __name__ == "__main__":
    main()
