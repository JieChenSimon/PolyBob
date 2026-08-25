"""Promotion backtest: run every strategy on real history through the gate.

Fetches real daily bars (Binance for crypto, Stooq for US equities), backtests
each strategy *causally* (signals use only past data; positions earn the next
bar's move; costs charged on turnover), and runs each result through
``libs.quant.promotion.PromotionGate`` (Deflated Sharpe with multiple-testing
correction, cost-stress, walk-forward stability, minimum sample). Emits a
red/green board and writes it to ``data/promotion_backtest.json`` so only
gate-passing (strategy, instrument) pairs are marked promotable.

This is a *vectorized, OHLCV-level* screen — indicative, not the full
event-driven engine. Its purpose is to discard strategies that cannot even
clear the bar on real data, per the "backtest is a filter" principle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import numpy as np

from libs.data.http_client import HttpFetchError, http_get_bytes, http_get_json
from libs.quant.promotion import PromotionGate, annualized_sharpe
from strategies.dual_ma_strategy import DualMAStrategy
from strategies.proven_signals import short_term_reversal, time_series_momentum
from strategies.signal_core import SpreadReversionParams, spread_reversion_entry
from strategies.signal_fusion import SignalFusion
from strategies.ensemble import risk_parity_combine

CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
EQUITIES = ["spy.us", "aapl.us", "nvda.us"]
COST_BPS = 10.0  # 10 bps per unit turnover (round-ish for liquid crypto/equity)


# --------------------------------------------------------------------------- data
def fetch_binance_daily(symbol: str, days: int = 1500) -> np.ndarray | None:
    out: list[float] = []
    end = None
    try:
        while len(out) < days:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit=1000"
            if end:
                url += f"&endTime={end}"
            rows = http_get_json(
                url, timeout=20.0, headers={"User-Agent": "PolyBobBT/0.1"}
            )
            if not rows:
                break
            closes = [float(r[4]) for r in rows]
            out = closes + out
            end = int(rows[0][0]) - 1
            if len(rows) < 1000:
                break
    except Exception as exc:
        print(f"  ! {symbol} fetch failed: {exc}")
        return None
    return np.array(out[-days:], dtype=float) if out else None


def fetch_stooq_daily(symbol: str) -> np.ndarray | None:
    try:
        url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
        text = http_get_bytes(
            url, timeout=20.0, headers={"User-Agent": "PolyBobBT/0.1"}
        ).decode()
        lines = text.strip().splitlines()[1:]
        closes = [float(ln.split(",")[4]) for ln in lines if len(ln.split(",")) >= 5 and ln.split(",")[4] != "N/D"]
        return np.array(closes[-2500:], dtype=float) if len(closes) > 300 else None
    except (HttpFetchError, ValueError, IndexError, KeyError) as exc:
        print(f"  ! {symbol} fetch failed: {exc}")
        return None


# --------------------------------------------------------------------- indicators
def rsi(prices: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(prices, prepend=prices[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    out = np.full(len(prices), 50.0)
    au = ad = 0.0
    for i in range(1, len(prices)):
        au = (au * (n - 1) + up[i]) / n
        ad = (ad * (n - 1) + dn[i]) / n
        out[i] = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
    return out


def ema(prices: np.ndarray, n: int) -> np.ndarray:
    a = 2 / (n + 1)
    out = np.empty_like(prices)
    out[0] = prices[0]
    for i in range(1, len(prices)):
        out[i] = a * prices[i] + (1 - a) * out[i - 1]
    return out


# -------------------------------------------------------------------- signal gens
def sig_tsmom(prices):
    return np.sign(np.asarray(time_series_momentum(list(prices), lookback=30, vol_lookback=30)))


def sig_reversal(prices):
    return np.sign(np.asarray(short_term_reversal(list(prices), lookback=5, vol_lookback=20)))


def sig_dual_ma(prices):
    strat = DualMAStrategy(fast_period=10, slow_period=30)
    pos = np.zeros(len(prices)); cur = 0.0
    for i in range(len(prices)):
        r = strat.calculate_signals(prices[: i + 1])
        if r and r["signal"] == "golden_cross":
            cur = 1.0
        elif r and r["signal"] == "death_cross":
            cur = -1.0
        pos[i] = cur
    return pos


def sig_mean_reversion(prices):
    p = SpreadReversionParams(entry_threshold_std=2.0, min_spread_bps=0.0, lookback_window=40, min_samples=20)
    pos = np.zeros(len(prices)); cur = 0.0
    for i in range(len(prices)):
        window = prices[max(0, i - p.lookback_window + 1): i + 1]
        s = spread_reversion_entry(list(window), p)
        if s.enter:
            cur = -np.sign(s.z_score)          # fade: above mean -> short
        elif abs(s.z_score) < 0.5:
            cur = 0.0
        pos[i] = cur
    return pos


def sig_signal_fusion(prices):
    fusion = SignalFusion()
    r = rsi(prices); mf = ema(prices, 10); ms = ema(prices, 30)
    macd = ema(prices, 12) - ema(prices, 26); macd_sig = ema(macd, 9)
    pos = np.zeros(len(prices)); cur = 0.0
    for i in range(len(prices)):
        feats = {"market_id": "x", "rsi": float(r[i]), "ma_fast": float(mf[i]),
                 "ma_slow": float(ms[i]), "macd": float(macd[i]), "macd_signal": float(macd_sig[i]),
                 "price": float(prices[i])}
        direction, _conf, _reason = fusion._fuse_signals(fusion._calculate_signal_scores(feats))
        if direction != 0:
            cur = float(direction)
        pos[i] = cur
    return pos


def sig_ensemble(prices):
    s1 = np.asarray(time_series_momentum(list(prices), lookback=30, vol_lookback=30))
    s2 = np.asarray(short_term_reversal(list(prices), lookback=5, vol_lookback=20))
    s3 = sig_dual_ma(prices)
    vols = [max(np.std(s1), 1e-6), max(np.std(s2), 1e-6), max(np.std(s3), 1e-6)]
    pos = np.array([risk_parity_combine([s1[i], s2[i], s3[i]], vols) for i in range(len(prices))])
    return np.sign(pos)


SINGLE = {
    "tsmom": sig_tsmom,
    "short_reversal": sig_reversal,
    "dual_ma": sig_dual_ma,
    "mean_reversion": sig_mean_reversion,
    "signal_fusion": sig_signal_fusion,
    "ensemble": sig_ensemble,
}


# ----------------------------------------------------------------------- backtest
def strat_returns(prices: np.ndarray, positions: np.ndarray, cost_bps: float) -> np.ndarray:
    rets = prices[1:] / prices[:-1] - 1.0
    pos = positions[:-1]
    prev = np.concatenate([[0.0], pos[:-1]])
    turn = np.abs(pos - prev)
    return pos * rets - (cost_bps / 1e4) * turn


def oos_stability(returns: np.ndarray, folds: int = 4, ppy: int = 365) -> float:
    if len(returns) < folds * 30:
        return 0.0
    chunks = np.array_split(returns, folds)
    good = sum(1 for c in chunks if annualized_sharpe(c, ppy) > 0.0)
    return good / folds


def statarb_pair_returns(a: np.ndarray, b: np.ndarray, cost_bps: float) -> np.ndarray:
    """Causal cointegration pair (expanding OLS beta, rolling z, fade the spread)."""
    n = min(len(a), len(b)); a, b = a[-n:], b[-n:]
    la, lb = np.log(a), np.log(b)
    pos = np.zeros(n); cur = 0.0; lb_win = 60
    z = np.zeros(n)
    for i in range(n):
        if i < lb_win:
            continue
        x = lb[: i + 1]; y = la[: i + 1]
        beta = np.polyfit(x, y, 1)[0]
        spread = y - beta * x
        w = spread[i - lb_win + 1: i + 1]
        sd = w.std()
        z[i] = 0.0 if sd == 0 else (spread[i] - w.mean()) / sd
        if z[i] > 2.0:
            cur = -1.0
        elif z[i] < -2.0:
            cur = 1.0
        elif abs(z[i]) < 0.5:
            cur = 0.0
        pos[i] = cur
    spread_ret = np.diff(la) - np.diff(lb)  # approx market-neutral leg pnl
    p = pos[:-1]
    prev = np.concatenate([[0.0], p[:-1]])
    turn = np.abs(p - prev)
    return p * spread_ret - (cost_bps / 1e4) * turn


# --------------------------------------------------------------------------- main
def main() -> None:
    print("Fetching real history…")
    series: dict[str, np.ndarray] = {}
    for s in CRYPTO:
        px = fetch_binance_daily(s)
        if px is not None and len(px) > 300:
            series[s] = px; print(f"  {s}: {len(px)} daily bars")
    for s in EQUITIES:
        px = fetch_stooq_daily(s)
        if px is not None:
            series[s.upper().replace('.US','')] = px; print(f"  {s}: {len(px)} daily bars")

    tests: list[tuple[str, str, np.ndarray, int]] = []
    for name, px in series.items():
        ppy = 365 if name in CRYPTO else 252
        for sname, gen in SINGLE.items():
            pos = gen(px)
            tests.append((sname, name, strat_returns(px, pos, COST_BPS), ppy))
    # pair stat-arb on BTC/ETH if both present
    if "BTCUSDT" in series and "ETHUSDT" in series:
        r = statarb_pair_returns(series["ETHUSDT"], series["BTCUSDT"], COST_BPS)
        tests.append(("stat_arb_pair", "ETH~BTC", r, 365))

    n_trials = len(tests)   # honest multiple-testing correction
    gate = PromotionGate(n_trials=n_trials, min_dsr=0.90, min_observations=252,
                         min_oos_stability_rate=0.5, cost_min_sharpe=0.3)

    board = []
    for sname, inst, rets, ppy in tests:
        rets = np.asarray(rets, float)
        rets = rets[np.isfinite(rets)]
        def cost_fn(mult, _s=sname, _i=inst, _p=ppy):
            px = series.get(_i) if _i != "ETH~BTC" else None
            if _i == "ETH~BTC":
                return statarb_pair_returns(series["ETHUSDT"], series["BTCUSDT"], COST_BPS * mult)
            return strat_returns(px, SINGLE[_s](px), COST_BPS * mult)
        decision = gate.evaluate(
            rets, cost_returns_fn=cost_fn, cost_multiples=(1.0, 2.0, 3.0),
            oos_stability_rate=oos_stability(rets, ppy=ppy),
        )
        sh = annualized_sharpe(rets, ppy)
        checks = {c.name: c.passed for c in decision.checks}
        board.append({
            "strategy": sname, "instrument": inst, "approved": decision.approved,
            "sharpe": round(sh, 2), "n": len(rets),
            "dsr": next((c.value for c in decision.checks if c.name == "deflated_sharpe"), None),
            "cost_stress": checks.get("cost_stress"), "oos": checks.get("oos_stability"),
            "failed": [c.name for c in decision.checks if not c.passed],
        })

    board.sort(key=lambda r: (-r["approved"], -r["sharpe"]))
    # See scripts/real_scoreboard.py: the promotion board has a single writer,
    # scripts/event_study_board.py. This script publishes its own results.
    out = Path("data/promotion_backtest.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"n_trials": n_trials, "cost_bps": COST_BPS, "board": board},
                              indent=2, ensure_ascii=False))

    print(f"\n{'='*78}\nPROMOTION BOARD  (n_trials={n_trials}, cost={COST_BPS}bps, gate: DSR>=0.90)\n{'='*78}")
    print(f"{'strat':16} {'instrument':10} {'Sharpe':>7} {'DSR':>5} {'cost':>5} {'oos':>4}  verdict")
    for r in board:
        v = "✅ PROMOTE" if r["approved"] else "🔒 lab: " + ",".join(r["failed"])
        print(f"{r['strategy']:16} {r['instrument']:10} {r['sharpe']:7.2f} "
              f"{(r['dsr'] or 0):5.2f} {str(r['cost_stress'])[:5]:>5} {str(r['oos'])[:4]:>4}  {v}")
    promoted = [r for r in board if r["approved"]]
    print(f"\n{len(promoted)}/{len(board)} 达标 -> 可上执行台; 其余留 lab。写入 {out}")


if __name__ == "__main__":
    main()
