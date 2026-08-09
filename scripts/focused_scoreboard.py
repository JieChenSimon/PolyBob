"""Focused scoreboard — fixes the two problems the broad loop exposed.

Problem 1: hypothesis direction was guessed, and guessed wrong (fading gaps and
following range-expansion both tested negative; their inverses were positive).
Fix: test both directions programmatically and let the data pick — but *count
both as trials* so the deflated Sharpe compensates for the extra search.

Problem 2: nothing could clear the bar because of sample size. Per-instrument
runs trade ~7% of days, and 184 simultaneous trials push the multiple-testing
threshold out of reach. Three fixes applied together:
  a) wider universe (more altcoins => more independent samples),
  b) domain portfolios (pool an edge across names, as it would be traded),
  c) *far fewer trials* — only the hypotheses that showed broad signal, which
     lowers the deflated-Sharpe hurdle honestly rather than by weakening it.

Everything runs on real OKX / Yahoo / Tencent data.
"""

from __future__ import annotations

import argparse
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
from libs.quant.edges import range_expansion, gap_fade, volume_confirmed_trend
from libs.quant.hypothesis import HypothesisRegistry
from libs.data.universe import A_SHARE_LIQUID, US_LIQUID
from libs.quant.promotion import PromotionGate, annualized_sharpe

US_EQUITIES = list(US_LIQUID)      # 见 libs/data/universe
A_SHARES = list(A_SHARE_LIQUID)
COST_BPS = {"altcoin": 10.0, "us_equity": 5.0, "a_share": 8.0}
PERIODS = {"altcoin": 365, "us_equity": 252, "a_share": 244}

# Only hypotheses that showed broad signal in the wide sweep. Fewer trials =>
# a lower (and honest) multiple-testing hurdle.
FOCUSED = {
    "range": range_expansion,          # inverse (contraction) was the winner
    "gap": gap_fade,                   # inverse (continuation) was positive
    "volume_trend": volume_confirmed_trend,
}


def backtest(prices: np.ndarray, positions: np.ndarray, cost_bps: float) -> np.ndarray:
    rets = prices[1:] / prices[:-1] - 1.0
    pos = positions[:-1]
    prev = np.concatenate([[0.0], pos[:-1]])
    return pos * rets - (cost_bps / 1e4) * np.abs(pos - prev)


def stats(rets: np.ndarray, periods: int) -> dict:
    active = rets != 0
    wins = int((rets[active] > 0).sum())
    n = int(active.sum())
    return {
        "sharpe": round(annualized_sharpe(rets, periods), 2),
        "win_rate": round(wins / n, 4) if n else None,
        "total_return": round(float(np.prod(1.0 + rets)) - 1.0, 4),
        "active_bars": n,
    }


def oos(rets: np.ndarray, periods: int, folds: int = 4) -> float:
    if len(rets) < folds * 40:
        return 0.0
    return sum(1 for c in np.array_split(rets, folds) if annualized_sharpe(c, periods) > 0) / folds


def load(domain: str, symbols: list[str]) -> list[DailyBars]:
    fetch = {"altcoin": fetch_altcoin_daily, "us_equity": fetch_us_equity_daily,
             "a_share": fetch_a_share_daily}[domain]
    out: list[DailyBars] = []
    for sym in symbols:
        try:
            bars = fetch(sym)
        except DataUnavailable:
            continue
        if bars.is_usable and bars.has_ohlc and bars.volumes:
            out.append(bars)
    print(f"  {domain:10} loaded {len(out)}/{len(symbols)}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alt-universe", type=int, default=50)
    args = parser.parse_args()

    print("Loading REAL history (wider universe)…")
    try:
        alts = [s for s in okx_usdt_universe() if s not in ("BTC-USDT", "ETH-USDT")][: args.alt_universe]
    except DataUnavailable:
        alts = ["SOL-USDT", "ADA-USDT", "AVAX-USDT", "LINK-USDT", "DOGE-USDT"]
    data = {
        "altcoin": load("altcoin", alts),
        "us_equity": load("us_equity", US_EQUITIES),
        "a_share": load("a_share", A_SHARES),
    }

    # Domain portfolios only, both directions — pooled sample, few trials.
    tests: list[tuple[str, str, str, np.ndarray]] = []
    for domain, series in data.items():
        if len(series) < 3:
            continue
        for edge_name, gen in FOCUSED.items():
            legs_fwd, legs_rev = [], []
            for bars in series:
                prices = np.asarray(bars.closes, float)
                pos = gen(bars)
                legs_fwd.append(backtest(prices, pos, COST_BPS[domain]))
                legs_rev.append(backtest(prices, -pos, COST_BPS[domain]))
            length = min(len(x) for x in legs_fwd)
            for label, legs in (("follow", legs_fwd), ("fade", legs_rev)):
                port = np.mean([x[-length:] for x in legs], axis=0)
                tests.append((f"{edge_name}_{label}", f"{domain.upper()}_x{len(legs)}", domain, port))

    # Both directions counted — no free lunch. But this script's own tests are not
    # the only search that has happened: the event studies registered 35 trials and
    # the wide chart-pattern sweep another 184, all drawn from the same distribution
    # of things this project looked at. A local ``len(tests)`` made this board's bar
    # the lowest in the repository purely because it forgot the rest.
    registry = HypothesisRegistry()
    registry.record_search(
        "focused_directional_board", len(tests),
        "定向板:3 个域 x 3 条边 x 双向(follow/fade),方向由数据挑选。",
        outcome="见 data/focused_board.json",
    )
    n_trials = registry.n_trials
    print(f"试验次数 {n_trials}(本板 {len(tests)} 组 + 注册表其余搜索)")
    gate = PromotionGate(n_trials=n_trials, min_dsr=0.90, min_observations=200,
                         min_oos_stability_rate=0.5)

    board = []
    for edge, instrument, domain, rets in tests:
        rets = np.asarray(rets, float)
        rets = rets[np.isfinite(rets)]
        if len(rets) < 100:
            continue
        periods = PERIODS[domain]
        s = stats(rets, periods)
        decision = gate.evaluate(rets, oos_stability_rate=oos(rets, periods))
        board.append({
            "strategy": edge, "instrument": instrument, "domain": domain,
            "approved": decision.approved, **s, "n": len(rets),
            "dsr": next((c.value for c in decision.checks if c.name == "deflated_sharpe"), None),
            "failed": [c.name for c in decision.checks if not c.passed],
        })

    board.sort(key=lambda r: (-r["approved"], -(r["dsr"] or 0)))
    out = Path("data/focused_board.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "n_trials": n_trials, "universe_sizes": {k: len(v) for k, v in data.items()},
        "board": board,
    }, indent=2, ensure_ascii=False))

    print(f"\n{'='*92}\nFOCUSED BOARD  (n_trials={n_trials}, 双向都测且计入试验次数)\n{'='*92}")
    print(f"{'edge':22} {'universe':16} {'Sharpe':>7} {'win%':>6} {'return':>9} {'DSR':>6}  verdict")
    for r in board:
        wr = f"{r['win_rate']*100:.1f}" if r["win_rate"] else "  - "
        v = "✅ PROMOTE" if r["approved"] else "🔒 " + ",".join(r["failed"])
        print(f"{r['strategy']:22} {r['instrument']:16} {r['sharpe']:7.2f} {wr:>6} "
              f"{r['total_return']*100:8.1f}% {(r['dsr'] or 0):6.3f}  {v}")
    ok = sum(r["approved"] for r in board)
    print(f"\n{ok}/{len(board)} 达标。写入 {out}")


if __name__ == "__main__":
    main()
