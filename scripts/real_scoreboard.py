"""The scoreboard: win rate & return per (edge, instrument) on REAL data.

This is the project's north-star instrument: it measures, on real history for
the three in-scope domains (altcoins, US + A-shares, and separately BTC-5m),
whether any edge hypothesis actually produces a win rate and return that
survives costs and multiple-testing correction.

Nothing here uses simulated data. Every bar comes from OKX / Yahoo / Tencent.
Results are written to ``data/price_edge_scoreboard.json``. They reach the
execution desk only through ``scripts/event_study_board.py``, the single writer
of the promotion board, and only for edges declared in its ``EDGE_SPECS``.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.data.real_sources import (
    DataUnavailable,
    DailyBars,
    fetch_a_share_daily,
    fetch_altcoin_daily,
    fetch_us_equity_daily,
    okx_usdt_universe,
)
from libs.data import store
from libs.quant.edges import (
    OHLCV_EDGES,
    SINGLE_ASSET_EDGES,
    cross_sectional_momentum_positions,
    funding_contrarian,
)
from libs.data.universe import A_SHARE_LIQUID, US_LIQUID
from libs.quant.promotion import PromotionGate, annualized_sharpe
from libs.quant.funding_readiness import assess_store, research_symbols

# In-scope instruments only (see project memory: BTC-5m / US+A-share / altcoins).
US_EQUITIES = list(US_LIQUID)      # 见 libs/data/universe
A_SHARES = list(A_SHARE_LIQUID)
ALTCOIN_FALLBACK = ["SOL-USDT", "DOGE-USDT", "AVAX-USDT", "LINK-USDT", "ADA-USDT"]

COST_BPS = {"altcoin": 10.0, "us_equity": 5.0, "a_share": 8.0}
PERIODS = {"altcoin": 365, "us_equity": 252, "a_share": 244}


# ------------------------------------------------------------------ backtest
def backtest(prices: np.ndarray, positions: np.ndarray, cost_bps: float) -> np.ndarray:
    """Causal PnL: position at bar i earns the i -> i+1 return, minus turnover cost."""
    rets = prices[1:] / prices[:-1] - 1.0
    pos = positions[:-1]
    prev = np.concatenate([[0.0], pos[:-1]])
    turnover = np.abs(pos - prev)
    return pos * rets - (cost_bps / 1e4) * turnover


def trade_stats(strategy_rets: np.ndarray, positions: np.ndarray) -> dict:
    """Win rate over *active* bars plus total/annual return — the headline numbers."""
    active = positions[:-1] != 0
    active_rets = strategy_rets[active]
    wins = int((active_rets > 0).sum())
    n = int(active.sum())
    equity = float(np.prod(1.0 + strategy_rets))
    return {
        "win_rate": round(wins / n, 4) if n else None,
        "active_bars": n,
        "total_return": round(equity - 1.0, 4),
    }


def oos_stability(rets: np.ndarray, periods: int, folds: int = 4) -> float:
    if len(rets) < folds * 40:
        return 0.0
    chunks = np.array_split(rets, folds)
    return sum(1 for c in chunks if annualized_sharpe(c, periods) > 0) / folds


# ---------------------------------------------------------------------- load
def load_domain(domain: str, symbols: list[str], limit: int) -> list[DailyBars]:
    out: list[DailyBars] = []
    fetch = {
        "altcoin": fetch_altcoin_daily,
        "us_equity": fetch_us_equity_daily,
        "a_share": fetch_a_share_daily,
    }[domain]
    for sym in symbols[:limit]:
        try:
            bars = fetch(sym)
        except DataUnavailable as exc:
            print(f"  ! {domain} {sym}: {exc}")
            continue
        if bars.is_usable:
            out.append(bars)
            print(f"  {domain:9} {bars.symbol:12} {len(bars):5} bars  {bars.dates[0]}..{bars.dates[-1]}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alt-universe", type=int, default=12, help="how many OKX pairs to test")
    args = parser.parse_args()

    print("Loading REAL history (OKX / Yahoo / Tencent)…")
    try:
        universe = [s for s in okx_usdt_universe() if s not in ("BTC-USDT", "ETH-USDT")]
    except DataUnavailable:
        universe = ALTCOIN_FALLBACK
    alt_syms = universe[: args.alt_universe] or ALTCOIN_FALLBACK

    data = {
        "altcoin": load_domain("altcoin", alt_syms, args.alt_universe),
        "us_equity": load_domain("us_equity", US_EQUITIES, len(US_EQUITIES)),
        "a_share": load_domain("a_share", A_SHARES, len(A_SHARES)),
    }

    tests: list[tuple[str, str, str, np.ndarray, np.ndarray]] = []
    for domain, series in data.items():
        for bars in series:
            prices = np.asarray(bars.closes, dtype=float)
            # Round 1: close-only generic TA.
            for edge_name, gen in SINGLE_ASSET_EDGES.items():
                pos = gen(prices)
                tests.append((edge_name, bars.symbol, domain,
                              backtest(prices, pos, COST_BPS[domain]), pos))
            # Round 2: differentiated edges using OHLCV (gaps, volume, range).
            if bars.has_ohlc and bars.volumes:
                for edge_name, gen in OHLCV_EDGES.items():
                    pos = gen(bars)
                    tests.append((edge_name, bars.symbol, domain,
                                  backtest(prices, pos, COST_BPS[domain]), pos))

    # Round 3: per-domain equal-weight portfolios of each edge.
    # Per-instrument runs trade on only ~7% of days, so the deflated Sharpe has
    # too little sample to ever clear the bar even when the edge is real.
    # Pooling the same edge across a domain multiplies the effective sample
    # (e.g. range_contraction on altcoins: DSR 0.03 -> 0.83) and is also how the
    # edge would actually be traded — as a basket, not one name.
    for domain, series in data.items():
        for edge_name, gen in OHLCV_EDGES.items():
            legs = [
                backtest(np.asarray(b.closes, float), gen(b), COST_BPS[domain])
                for b in series if b.has_ohlc and b.volumes
            ]
            if len(legs) < 3:
                continue
            length = min(len(x) for x in legs)
            port = np.mean([x[-length:] for x in legs], axis=0)
            tests.append((f"{edge_name}_portfolio", f"{domain.upper()}_x{len(legs)}",
                          domain, port, np.ones(len(port) + 1)))

    # Round 2: altcoin perp funding contrarian (crowded-positioning edge).  Funding
    # is read from the bitemporal local store only after its history passes the
    # explicit long-history/OOS gate.  A short OKX response is not evidence.
    funding_readiness = assess_store()
    ready_funding = set(research_symbols(funding_readiness))
    for bars in data["altcoin"]:
        swap_symbol = f"{bars.symbol}-SWAP"
        if swap_symbol not in ready_funding:
            continue
        funding_frame = store.read(store.FUNDING_RATES, swap_symbol)
        funding_map = dict(zip(funding_frame["event_date"], funding_frame["rate"]))
        aligned = np.array([funding_map.get(d, np.nan) for d in bars.dates], dtype=float)
        if np.isfinite(aligned).sum() < 60:      # need real overlap, never pad
            continue
        prices = np.asarray(bars.closes, dtype=float)
        pos = funding_contrarian(prices, aligned)
        tests.append(("funding_contrarian", bars.symbol, "altcoin",
                      backtest(prices, pos, COST_BPS["altcoin"]), pos))

    # Cross-sectional altcoin momentum (portfolio-level, the strongest crypto prior)
    alts = data["altcoin"]
    if len(alts) >= 4:
        length = min(len(b) for b in alts)
        matrix = np.array([b.closes[-length:] for b in alts], dtype=float)
        pos_matrix = cross_sectional_momentum_positions(matrix)
        rets_matrix = matrix[:, 1:] / matrix[:, :-1] - 1.0
        pos = pos_matrix[:, :-1]
        prev = np.concatenate([np.zeros((pos.shape[0], 1)), pos[:, :-1]], axis=1)
        turnover = np.abs(pos - prev).sum(axis=0)
        port = (pos * rets_matrix).sum(axis=0) - (COST_BPS["altcoin"] / 1e4) * turnover
        tests.append(("xs_momentum_portfolio", f"ALT_x{len(alts)}", "altcoin", port,
                      np.ones(len(port) + 1)))

    n_trials = len(tests)
    gate = PromotionGate(n_trials=n_trials, min_dsr=0.90, min_observations=200,
                         min_oos_stability_rate=0.5, cost_min_sharpe=0.3)

    board = []
    for edge, symbol, domain, rets, pos in tests:
        rets = np.asarray(rets, float)
        rets = rets[np.isfinite(rets)]
        if len(rets) < 50:
            continue
        periods = PERIODS[domain]
        stats = trade_stats(rets, pos)
        decision = gate.evaluate(rets, oos_stability_rate=oos_stability(rets, periods))
        board.append({
            "strategy": edge, "instrument": symbol, "domain": domain,
            "approved": decision.approved,
            "sharpe": round(annualized_sharpe(rets, periods), 2),
            "win_rate": stats["win_rate"], "total_return": stats["total_return"],
            "active_bars": stats["active_bars"], "n": len(rets),
            "dsr": next((c.value for c in decision.checks if c.name == "deflated_sharpe"), None),
            "failed": [c.name for c in decision.checks if not c.passed],
        })

    board.sort(key=lambda r: (-r["approved"], -(r["sharpe"] or 0)))
    # Its own file. This script tests price-based edges; it used to write the
    # promotion board directly, which meant running it silently replaced the
    # event-study edges with an unrelated experiment. The board now has exactly
    # one writer (scripts/event_study_board.py), which reads files like this one.
    out = Path("data/price_edge_scoreboard.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(),
        "data_sources": {"altcoin": "okx", "us_equity": "yahoo", "a_share": "tencent",
                          "funding": "local_bitemporal_store"},
        "funding_readiness": funding_readiness,
        "real_data_only": True, "n_trials": n_trials, "cost_bps": COST_BPS,
        "board": board,
    }, indent=2, ensure_ascii=False))

    print(f"\n{'='*94}\nREAL-DATA SCOREBOARD  (n_trials={n_trials}, gate: DSR>=0.90)\n{'='*94}")
    print(f"{'edge':24} {'instrument':12} {'domain':10} {'Sharpe':>7} {'win%':>6} {'return':>9}  verdict")
    for r in board:
        wr = f"{r['win_rate']*100:.1f}" if r["win_rate"] is not None else "  - "
        v = "✅ PROMOTE" if r["approved"] else "🔒 lab"
        print(f"{r['strategy']:24} {r['instrument']:12} {r['domain']:10} "
              f"{r['sharpe']:7.2f} {wr:>6} {r['total_return']*100:8.1f}%  {v}")
    ok = [r for r in board if r["approved"]]
    print(f"\n{len(ok)}/{len(board)} 达标 -> 可上执行台;其余留 lab。写入 {out}")
    for domain in ("altcoin", "us_equity", "a_share"):
        rows = [r for r in board if r["domain"] == domain]
        if rows:
            best = max(rows, key=lambda r: r["sharpe"])
            print(f"  {domain:10} 最佳: {best['strategy']} @ {best['instrument']} "
                  f"Sharpe={best['sharpe']} win={best['win_rate']} ret={best['total_return']*100:.1f}%")


if __name__ == "__main__":
    main()
