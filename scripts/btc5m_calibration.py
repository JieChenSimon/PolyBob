"""Calibrate the BTC 5-minute up/down predictor on real 1-minute history.

Compares the CURRENT price-distance model (ad-hoc guessed volatility + sigmoid)
against an IMPROVED digital-option model that uses the *real realized
volatility* of BTC and the normal CDF:

    d = ln(current / strike) / (sigma_per_min * sqrt(remaining_minutes))
    P(up) = Phi(d)

Everything else in the workbench (market-implied blend, entry optimizer,
EV/Kelly) is kept — this only fixes the weakest link: the probability itself.
We measure calibration (Brier + reliability), not just accuracy, because the
whole point of a probability is EV/position sizing.
"""

from __future__ import annotations

import json
import math
import urllib.request

import numpy as np


# ---- current model (replica of _win_probability_up price part) --------------
def _sigmoid(v: float) -> float:
    if v >= 12:
        return 0.999994
    if v <= -12:
        return 0.000006
    return 1.0 / (1.0 + math.e ** (-v))


def prob_v1_guessed_vol(cur: float, strike: float, remaining_s: int) -> float:
    if strike <= 0:
        return 0.5
    tf = min(1.0, max(0.05, remaining_s / 300))
    scale = strike * (0.0008 + 0.0012 * (tf ** 0.5))
    return _sigmoid((cur - strike) / max(1.0, scale))


# ---- improved model (real realized vol + digital option normal CDF) ---------
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def prob_v2_real_vol(cur: float, strike: float, remaining_s: int, sigma_per_min: float) -> float:
    if strike <= 0 or sigma_per_min <= 0 or remaining_s <= 0:
        return 0.5
    denom = sigma_per_min * math.sqrt(remaining_s / 60.0)
    if denom <= 0:
        return 0.5
    return _norm_cdf(math.log(cur / strike) / denom)


def fetch_1m(symbol: str, minutes: int = 12000) -> np.ndarray | None:
    out: list[list[float]] = []
    end = None
    try:
        while len(out) < minutes:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=1000"
            if end:
                url += f"&endTime={end}"
            req = urllib.request.Request(url, headers={"User-Agent": "PolyBobCal/0.1"})
            rows = json.loads(urllib.request.urlopen(req, timeout=20).read())
            if not rows:
                break
            out = [[int(r[0]), float(r[1]), float(r[4])] for r in rows] + out
            end = int(rows[0][0]) - 1
            if len(rows) < 1000:
                break
    except Exception as exc:
        print("fetch failed:", exc)
        return None
    return np.array(out[-minutes:], dtype=float)


def brier(p, o):
    return float(np.mean((np.asarray(p) - np.asarray(o, float)) ** 2))


def reliability(p, o, bins=10):
    p = np.asarray(p); o = np.asarray(o, float)
    edges = np.linspace(0, 1, bins + 1); rows = []
    for i in range(bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= 1.0))
        if m.sum() >= 20:
            rows.append((f"{edges[i]:.1f}-{edges[i+1]:.1f}", int(m.sum()),
                         round(float(p[m].mean()), 3), round(float(o[m].mean()), 3)))
    return rows


VOL_WIN = 30  # trailing minutes for realized-vol estimate


def main():
    print("Fetching BTC 1m klines…")
    k = fetch_1m("BTCUSDT")
    if k is None:
        return
    times = k[:, 0].astype(np.int64); opens = k[:, 1]; closes = k[:, 2]
    # index by minute-open time for contiguous trailing windows
    logret = np.diff(np.log(closes), prepend=0.0)

    # aligned 5-minute windows: need 5 contiguous minutes + VOL_WIN trailing mins
    step = 5 * 60_000
    wid_of = (times // step)
    windows = []
    i = 0
    n = len(times)
    while i + 5 <= n:
        if wid_of[i + 4] == wid_of[i] and (i == 0 or True):
            # ensure the 5 are contiguous minutes of the same 5-min bucket
            if all(wid_of[i + j] == wid_of[i] for j in range(5)) and i >= VOL_WIN:
                windows.append(i)
            i += 5
        else:
            i += 1
    print(f"usable 5-min windows: {len(windows)}")

    for decision_min in (1, 2, 3):
        remaining = (5 - decision_min) * 60
        p1, p2, outs, naive = [], [], [], []
        for i in windows:
            strike = opens[i]
            cur = closes[i + decision_min - 1]
            final = closes[i + 4]
            outcome = 1 if final > strike else 0
            sigma = float(np.std(logret[i - VOL_WIN:i]))  # trailing realized vol (per-min), causal
            p1.append(prob_v1_guessed_vol(cur, strike, remaining))
            p2.append(prob_v2_real_vol(cur, strike, remaining, sigma))
            outs.append(outcome); naive.append(1 if cur > strike else 0)
        p1 = np.array(p1); p2 = np.array(p2); outs = np.array(outs)
        print(f"\n=== 决策点 进场{decision_min}min (剩{remaining}s), 样本 {len(outs)}  上涨占比 {outs.mean():.3f} ===")
        print(f"  Brier   旧(猜测vol)={brier(p1,outs):.4f}   新(真实vol)={brier(p2,outs):.4f}   恒0.5=0.2500  (越低越好)")
        print(f"  准确率  旧={np.mean((p1>0.5)==(outs==1)):.3f}   新={np.mean((p2>0.5)==(outs==1)):.3f}")
        print("  可靠性对比 (预测概率档 -> 实际上涨频率):")
        r1 = {x[0]: x for x in reliability(p1, outs)}
        r2 = {x[0]: x for x in reliability(p2, outs)}
        for label in sorted(set(r1) | set(r2)):
            a = r1.get(label); b = r2.get(label)
            s1 = f"旧 预测{a[2]:.2f}→实际{a[3]:.2f}" if a else "旧 —"
            s2 = f"新 预测{b[2]:.2f}→实际{b[3]:.2f}" if b else "新 —"
            print(f"    {label}   {s1:26}   {s2}")


if __name__ == "__main__":
    main()
