"""The scientific experiment: pre-registered hypotheses, PBO, honest verdict.

Replaces the brute-force sweep. Differences that matter:

1. **Theory first.** Only hypotheses with an ex-ante economic rationale are
   admissible. ``range_contraction`` — invented by flipping the sign of a losing
   chart pattern — is deliberately *not* here; it has no mechanism, and the
   replication literature shows that corner of the factor zoo (trading frictions
   / pattern signals) is where ~93% of published anomalies die.
2. **Pre-registered.** Direction, universe, horizon and costs are fixed before
   any backtest runs, and every hypothesis counts as a trial.
3. **Two independent overfitting tests.** Deflated Sharpe (is the level real
   given N trials?) *and* PBO/CSCV (does in-sample selection survive
   out-of-sample?), plus a t-stat hurdle raised above the factor-zoo standard.

The hypotheses tested are the ones with the strongest replication record —
momentum (cross-sectional and time-series), which survives out-of-sample,
internationally, across asset classes, and net of costs at scale.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.data.real_sources import (
    DailyBars,
    DataUnavailable,
    fetch_a_share_daily,
    fetch_altcoin_daily,
    fetch_us_equity_daily,
    okx_usdt_universe,
)
from libs.quant.hypothesis import Hypothesis, HypothesisRegistry, Rationale
from libs.quant.pbo import deflated_t_stat_threshold, probability_of_backtest_overfitting
from libs.quant.promotion import PromotionGate, annualized_sharpe

US = ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "GOOGL", "AMD", "JPM", "XOM"]
CN = ["600519", "000001", "300750", "601318", "000858", "600036", "000651", "002594"]
COST = {"altcoin": 10.0, "us_equity": 5.0, "a_share": 8.0}
PERIODS = {"altcoin": 365, "us_equity": 252, "a_share": 244}
# Both hypotheses are searched over a four-lookback grid and the best config is
# reported, so each (hypothesis, domain) pair burns four trials, not one. The
# grids below are the single source of truth for both the search and the count.
LOOKBACK_GRID = {"xs_momentum": (20, 30, 60, 90), "ts_momentum": (30, 60, 90, 120)}


# ----------------------------------------------------------- pre-registration
def preregister(registry: HypothesisRegistry) -> list[Hypothesis]:
    """Fixed BEFORE any backtest runs. Each needs a mechanism, not a pattern."""
    specs = [
        dict(
            hypothesis_id="xs_momentum",
            claim="Recent winners keep outperforming recent losers over the next month.",
            rationale=Rationale.BEHAVIOURAL,
            mechanism=("Investors underreact to news, so prices adjust with a lag; the "
                       "trade is hard to arbitrage away because it suffers long, "
                       "career-threatening drawdowns."),
            literature=("Momentum replicates out-of-sample, internationally and across "
                        "asset classes, and survives realistic trading costs at scale."),
            direction="long_top_quintile_short_bottom",
            horizon_days=30,
        ),
        dict(
            hypothesis_id="ts_momentum",
            claim="An asset that has risen over the past quarter keeps rising over the next month.",
            rationale=Rationale.BEHAVIOURAL,
            mechanism=("Gradual information diffusion plus flows from trend followers; "
                       "limits to arbitrage keep the drift from being fully priced."),
            literature=("Time-series momentum documented across equities, bonds, "
                        "commodities and currencies over decades."),
            direction="long_if_positive_trailing_return",
            horizon_days=60,
        ),
    ]
    hypotheses = []
    for spec in specs:
        for domain in ("altcoin", "us_equity", "a_share"):
            h = Hypothesis(
                hypothesis_id=f"{spec['hypothesis_id']}@{domain}",
                claim=spec["claim"], rationale=spec["rationale"],
                mechanism=spec["mechanism"], literature=spec["literature"],
                direction=spec["direction"], universe=domain,
                horizon_days=spec["horizon_days"], cost_bps=COST[domain],
                n_configs=len(LOOKBACK_GRID[spec["hypothesis_id"]]),
            )
            registry.register(h)
            hypotheses.append(h)
    return hypotheses


# ------------------------------------------------------------------ mechanics
def load(domain: str, symbols: list[str]) -> list[DailyBars]:
    fetch = {"altcoin": fetch_altcoin_daily, "us_equity": fetch_us_equity_daily,
             "a_share": fetch_a_share_daily}[domain]
    out = []
    for sym in symbols:
        try:
            bars = fetch(sym)
        except DataUnavailable:
            continue
        if bars.is_usable:
            out.append(bars)
    print(f"  {domain:10} {len(out)}/{len(symbols)} instruments")
    return out


def xs_momentum_returns(series: list[DailyBars], lookback: int, cost_bps: float) -> np.ndarray:
    """Cross-sectional: long top quintile, short bottom, rebalanced daily."""
    length = min(len(b) for b in series)
    matrix = np.array([b.closes[-length:] for b in series], dtype=float)
    n_assets, n_days = matrix.shape
    k = max(1, n_assets // 5)
    rets = matrix[:, 1:] / matrix[:, :-1] - 1.0
    pnl = np.zeros(n_days - 1)
    prev_pos = np.zeros(n_assets)
    for day in range(lookback, n_days - 1):
        past = matrix[:, day - lookback]
        trailing = np.where(past > 0, matrix[:, day] / np.maximum(past, 1e-12) - 1.0, np.nan)
        order = np.argsort(np.where(np.isnan(trailing), -np.inf, trailing))
        pos = np.zeros(n_assets)
        pos[order[-k:]] = 1.0 / k
        pos[order[:k]] = -1.0 / k
        pnl[day] = float((pos * rets[:, day]).sum() - (cost_bps / 1e4) * np.abs(pos - prev_pos).sum())
        prev_pos = pos
    return pnl[lookback:]


def ts_momentum_returns(series: list[DailyBars], lookback: int, cost_bps: float) -> np.ndarray:
    """Time-series: hold each asset long when its trailing return is positive."""
    legs = []
    for bars in series:
        prices = np.asarray(bars.closes, float)
        pos = np.zeros(len(prices))
        for i in range(lookback, len(prices)):
            if prices[i - lookback] > 0:
                pos[i] = 1.0 if prices[i] / prices[i - lookback] - 1.0 > 0 else 0.0
        rets = prices[1:] / prices[:-1] - 1.0
        p = pos[:-1]
        prev = np.concatenate([[0.0], p[:-1]])
        legs.append(p * rets - (cost_bps / 1e4) * np.abs(p - prev))
    length = min(len(x) for x in legs)
    return np.mean([x[-length:] for x in legs], axis=0)


def main() -> None:
    print("=" * 92)
    print("SCIENTIFIC EXPERIMENT — pre-registered hypotheses, real data, PBO + DSR")
    print("=" * 92)

    registry = HypothesisRegistry()
    hypotheses = preregister(registry)
    print(f"\n预注册 {len(hypotheses)} 个假设(每个都有经济学机制);历史累计试验 {registry.n_trials}\n")

    print("Loading REAL history…")
    try:
        alts = [s for s in okx_usdt_universe() if s not in ("BTC-USDT", "ETH-USDT")][:40]
    except DataUnavailable:
        alts = ["SOL-USDT", "ADA-USDT", "AVAX-USDT", "LINK-USDT", "DOGE-USDT"]
    data = {"altcoin": load("altcoin", alts), "us_equity": load("us_equity", US),
            "a_share": load("a_share", CN)}

    # Robustness grid per hypothesis: several lookbacks, so PBO has configs to
    # select between (that is the point of CSCV) — all counted as trials.
    results = []
    for domain, series in data.items():
        if len(series) < 5:
            continue
        for name, fn in (
            ("xs_momentum", xs_momentum_returns),
            ("ts_momentum", ts_momentum_returns),
        ):
            lookbacks = LOOKBACK_GRID[name]
            configs = []
            for lb in lookbacks:
                try:
                    configs.append(fn(series, lb, COST[domain]))
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! {name}@{domain} lb={lb}: {exc}")
            if len(configs) < 2:
                continue
            length = min(len(c) for c in configs)
            matrix = np.array([c[-length:] for c in configs])

            pbo = probability_of_backtest_overfitting(matrix, n_blocks=10)
            periods = PERIODS[domain]
            sharpes = [annualized_sharpe(c, periods) for c in matrix]
            best = int(np.argmax(sharpes))
            best_rets = matrix[best]
            t_stat = float(np.mean(best_rets) / (np.std(best_rets, ddof=1) / np.sqrt(len(best_rets)))) \
                if np.std(best_rets, ddof=1) > 0 else 0.0
            t_hurdle = deflated_t_stat_threshold(registry.n_trials)

            gate = PromotionGate(n_trials=registry.n_trials, min_dsr=0.90, min_observations=200)
            decision = gate.evaluate(best_rets)
            dsr = next((c.value for c in decision.checks if c.name == "deflated_sharpe"), 0.0)
            active = best_rets != 0
            win = float((best_rets[active] > 0).mean()) if active.sum() else 0.0

            approved = decision.approved and pbo.pbo <= 0.25 and abs(t_stat) >= t_hurdle
            results.append({
                "hypothesis": f"{name}@{domain}", "best_lookback": lookbacks[best],
                "sharpe": round(sharpes[best], 2), "win_rate": round(win, 4),
                "total_return": round(float(np.prod(1 + best_rets)) - 1.0, 4),
                "t_stat": round(t_stat, 2), "t_hurdle": round(t_hurdle, 2),
                "dsr": dsr, "pbo": pbo.pbo, "pbo_verdict": pbo.verdict,
                "approved": approved, "n": len(best_rets),
            })
            registry.record_result(f"{name}@{domain}", results[-1])

    results.sort(key=lambda r: (-r["approved"], r["pbo"], -r["sharpe"]))
    out = Path("data/scientific_results.json")
    out.write_text(json.dumps({"generated_at": datetime.now(UTC).isoformat(),
                               "real_data_only": True, "n_trials": registry.n_trials,
                               "results": results}, indent=2, ensure_ascii=False))

    print(f"\n{'假设':22} {'Sharpe':>7} {'win%':>6} {'return':>9} {'t':>6} {'t门槛':>6} {'DSR':>6} {'PBO':>6} {'PBO判定':>11}  结论")
    for r in results:
        v = "✅ PROMOTE" if r["approved"] else "🔒 lab"
        print(f"{r['hypothesis']:22} {r['sharpe']:7.2f} {r['win_rate']*100:5.1f}% "
              f"{r['total_return']*100:8.1f}% {r['t_stat']:6.2f} {r['t_hurdle']:6.2f} "
              f"{r['dsr']:6.3f} {r['pbo']:6.2f} {r['pbo_verdict']:>11}  {v}")
    print(f"\n{sum(r['approved'] for r in results)}/{len(results)} 达标。写入 {out}")


if __name__ == "__main__":
    main()
