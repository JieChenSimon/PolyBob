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
import os
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.data.data_lake import record_raw


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


def fetch_1m(symbol: str, minutes: int = 2000) -> np.ndarray | None:
    """Fetch real contiguous OKX history; Binance can be region-blocked (451)."""
    out: list[list[float]] = []
    after = None
    try:
        while len(out) < minutes:
            inst_id = "BTC-USDT" if symbol == "BTCUSDT" else symbol.replace("USDT", "-USDT")
            url = f"https://www.okx.com/api/v5/market/history-candles?instId={inst_id}&bar=1m&limit=100"
            if after:
                url += f"&after={after}"
            req = urllib.request.Request(url, headers={"User-Agent": "PolyBobCal/0.1"})
            raw = None
            for attempt in range(4):
                try:
                    raw = urllib.request.urlopen(req, timeout=60).read()
                    break
                except Exception as exc:
                    if attempt == 3:
                        print(f"page failed after retries: {exc}", flush=True)
                    else:
                        time.sleep(2 ** attempt)
            if raw is None:
                break
            record_raw("btc5m_provider_raw", raw, source="okx_history_candles", request=url)
            payload = json.loads(raw)
            rows = payload.get("data") or []
            if not rows or payload.get("code") not in (None, "0", 0):
                break
            out = [[int(r[0]), float(r[1]), float(r[4])] for r in rows] + out
            next_after = rows[-1][0]
            if next_after == after:
                break
            after = next_after
            if len(out) % 500 < 100:
                print(f"  fetched {len(out)} raw 1m bars", flush=True)
            if len(rows) < 1000:
                # OKX history-candles pages are normally 100 rows; keep paging
                # until the requested window is covered.
                continue
            time.sleep(0.05)
    except Exception as exc:
        print("fetch failed:", exc)
        if not out:
            return None
    unique = {int(row[0]): row for row in out}
    return np.array([unique[k] for k in sorted(unique)[-minutes:]], dtype=float)


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
    requested_minutes = max(2_000, int(os.environ.get("POLYBOB_BTC5M_MINUTES", "2000")))
    print(f"requested real 1m bars: {requested_minutes}")
    k = fetch_1m("BTCUSDT", minutes=requested_minutes)
    if k is None:
        return
    times = k[:, 0].astype(np.int64); opens = k[:, 1]; closes = k[:, 2]
    # index by minute-open time for contiguous trailing windows
    logret = np.diff(np.log(closes), prepend=np.log(closes[0]))

    # aligned 5-minute windows: need 5 contiguous minutes + VOL_WIN trailing mins
    step = 5 * 60_000
    wid_of = (times // step)
    windows = []
    i = 0
    n = len(times)
    while i + 5 <= n:
        contiguous = all(times[i + j + 1] - times[i + j] == 60_000 for j in range(4))
        if wid_of[i + 4] == wid_of[i] and contiguous:
            # ensure the 5 are contiguous minutes of the same 5-min bucket
            if all(wid_of[i + j] == wid_of[i] for j in range(5)) and i >= VOL_WIN:
                windows.append(i)
            i += 5
        else:
            i += 1
    print(f"usable 5-min windows: {len(windows)}")

    report_rows = []
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
        row = {
            "decision_minute": decision_min,
            "remaining_seconds": remaining,
            "samples": int(len(outs)),
            "up_rate": float(outs.mean()) if len(outs) else None,
            "brier_v1_guessed_vol": brier(p1, outs),
            "brier_v2_real_vol": brier(p2, outs),
            "accuracy_v1_guessed_vol": float(np.mean((p1 > 0.5) == (outs == 1))),
            "accuracy_v2_real_vol": float(np.mean((p2 > 0.5) == (outs == 1))),
            "reliability_v1": reliability(p1, outs),
            "reliability_v2": reliability(p2, outs),
        }
        report_rows.append(row)
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
    out = Path("data/btc5m_calibration.json")
    out.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "okx_history_candles",
        "real_data_only": True,
        "raw_1m_bars": int(len(k)),
        "usable_5m_windows": int(len(windows)),
        "independent_days": int(len(set(time.strftime("%Y-%m-%d", time.gmtime(t / 1000)) for t in times))),
        "rows": report_rows,
        "status": "calibration_only_not_trading_evidence",
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"写入 {out}")


if __name__ == "__main__":
    main()
