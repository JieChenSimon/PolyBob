"""Pre-registered test: is the BTC 5-minute market mispriced against the model?

The calibration work showed the model's probabilities are only trustworthy once
they use real realized volatility. This asks the question that actually matters
for trading: when the calibrated digital-option probability disagrees with the
Polymarket price, does the *market* turn out to be wrong?

Design: reconstruct settled 5-minute windows from Gamma (each closed market
carries its realised outcome), take the CLOB price history for the UP token, and
compute the model probability from real Binance/OKX 1-minute BTC data at the same
instant. An edge exists only if the model's disagreement predicts the settled
outcome after the spread is paid.

Hypothesis registered up front: quoted prices in a 5-minute market are set mostly
by flow and cannot fully track realised volatility, so extreme model-vs-market
disagreement should favour the model. The honest prior is that this fails —
these markets are fast and bot-dominated — and a null result is reported as such.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.quant.hypothesis import Hypothesis, HypothesisRegistry, Rationale
from libs.data import run_manifest
from libs.data.http_client import HttpFetchError
from libs.data.resilient import FetchPolicy, fetch_cached_bytes, load_checkpoint, save_checkpoint
from libs.data.data_lake import write_records
from libs.quant import clustered_inference
from libs.quant.pbo import deflated_t_stat_threshold

UA = {"User-Agent": "Mozilla/5.0 (PolyBob research)"}
CACHE_DIR = Path("data/market_cache/btc5m")
CHECKPOINT = CACHE_DIR / "collection_checkpoint.json"
COLLECTOR_SPEC = "btc5m-v3-completed-bar-open-strike-cache-checkpoint"
N_WINDOWS = int(os.environ.get("POLYBOB_BTC5M_N_WINDOWS", "220"))
MAX_NEW_WINDOWS = int(os.environ.get("POLYBOB_BTC5M_MAX_NEW_WINDOWS", "60"))
EDGE_THRESHOLD = 0.10     # model must disagree with the market by >= 10 points
FEE = 0.02                # round-trip spread/fee assumption, in probability terms


def preregister(registry: HypothesisRegistry) -> None:
    registry.register(Hypothesis(
        hypothesis_id="btc5m_model_vs_market",
        claim=("When the volatility-calibrated model disagrees strongly with the quoted "
               "price, the model predicts the settled outcome better."),
        rationale=Rationale.STRUCTURAL,
        mechanism=("Quotes in a 5-minute market are driven by order flow and cannot fully "
                   "track realised volatility, so the fair value implied by current price "
                   "distance and volatility can drift away from the quote."),
        literature=("Short-horizon prediction markets show flow-driven pricing; the honest "
                    "prior is that fast bot-dominated markets are efficient."),
        direction="buy_side_favoured_by_model_when_edge_exceeds_threshold",
        universe="Polymarket btc-updown-5m", horizon_days=1, cost_bps=200.0,
    ))


def _get(url: str, timeout: float = 20.0):
    raw = fetch_cached_bytes(
        url, cache_dir=CACHE_DIR / "responses",
        policy=FetchPolicy(attempts=2, timeout_seconds=min(timeout, 8.0),
                           initial_backoff_seconds=0.5, max_backoff_seconds=4.0),
        headers=UA,
        dataset="btc5m_provider_raw", source=url.split('/')[2],
    )
    return json.loads(raw)


def btc_minute_bars(start_ms: int, end_ms: int) -> list[tuple[int, float, float]]:
    """Completed 1-minute BTC bars available before ``end_ms``.

    OKX timestamps identify the bar *open*.  A bar at ``end_ms`` is still
    forming at the decision instant, so including its close would leak up to
    one minute of future information into the model.
    """
    url = ("https://www.okx.com/api/v5/market/history-candles"
           f"?instId=BTC-USDT&bar=1m&limit=300&after={end_ms}")
    rows = _get(url).get("data", [])
    out = [
        (int(r[0]), float(r[5]), float(r[4]))
        for r in rows
        if start_ms - 3_600_000 <= int(r[0]) < end_ms
    ]
    from libs.data.data_lake import write_records
    write_records(
        "btc_1m_bars",
        [
            {
                "symbol": "BTC-USDT",
                "event_at": datetime.fromtimestamp(ts / 1000, tz=UTC).isoformat(),
                "open": opening,
                "close": closing,
                "source": "okx_history_candles",
            }
            for ts, opening, closing in out
        ],
        source="okx_history_candles",
        partition_by=("symbol",),
    )
    return sorted(out)


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def main() -> None:
    print("=" * 84)
    print("PRE-REGISTERED — BTC 5m model-vs-market mispricing (settled windows)")
    print("=" * 84)
    registry = HypothesisRegistry()
    preregister(registry)
    manifest = run_manifest.pin("btc5m_model_vs_market", params={
        "n_windows": N_WINDOWS, "edge_threshold": EDGE_THRESHOLD, "fee": FEE,
        "model_revision": "realized-volatility-normal-cdf-v3",
    })
    print(f"观测时点 as_of = {manifest.as_of.isoformat()}")
    print(f"累计试验 {registry.n_trials}\n")

    now = int(time.time())
    base = (now // 300) * 300
    samples: list[tuple[float, float, int]] = []   # (model_p, market_p, outcome_up)
    checkpoint = load_checkpoint(CHECKPOINT, spec=COLLECTOR_SPEC)
    saved_samples = checkpoint.get("samples", [])
    if isinstance(saved_samples, list):
        samples = [tuple(item) for item in saved_samples if isinstance(item, list) and len(item) == 4]
    completed = checkpoint.setdefault("items", {})
    provider_failures = int(checkpoint.get("provider_failures", 0))
    new_attempts = 0
    budget_exhausted = False

    for i in range(1, N_WINDOWS + 1):
        window_start = base - i * 300
        key = str(window_start)
        if key in completed:
            continue
        if new_attempts >= MAX_NEW_WINDOWS:
            budget_exhausted = True
            break
        new_attempts += 1
        try:
            event = _get(f"https://gamma-api.polymarket.com/events/slug/btc-updown-5m-{window_start}")
        except HttpFetchError:
            provider_failures += 1
            save_checkpoint(CHECKPOINT, {"spec": COLLECTOR_SPEC, "items": completed,
                                         "samples": [list(s) for s in samples],
                                         "provider_failures": provider_failures})
            continue
        markets = event.get("markets") or []
        if not markets:
            completed[key] = "no_market"
            save_checkpoint(CHECKPOINT, {"spec": COLLECTOR_SPEC, "items": completed,
                                         "samples": [list(s) for s in samples],
                                         "provider_failures": provider_failures})
            continue
        market = markets[0]
        if not market.get("closed"):
            completed[key] = "open"
            save_checkpoint(CHECKPOINT, {"spec": COLLECTOR_SPEC, "items": completed,
                                         "samples": [list(s) for s in samples],
                                         "provider_failures": provider_failures})
            continue
        try:
            outcome_prices = json.loads(market.get("outcomePrices", "[]"))
            outcome_up = 1 if float(outcome_prices[0]) > 0.5 else 0
            token = json.loads(market.get("clobTokenIds", "[]"))[0]
        except (ValueError, IndexError, TypeError):
            completed[key] = "invalid_market"
            continue

        # Market quote roughly 2 minutes into the window.
        decision_ts = window_start + 120
        try:
            history = _get(f"https://clob.polymarket.com/prices-history"
                           f"?market={token}&interval=max&fidelity=1").get("history", [])
        except HttpFetchError:
            provider_failures += 1
            continue
        quotes = [h for h in history if h.get("t", 0) <= decision_ts]
        if not quotes:
            continue
        market_p = float(quotes[-1]["p"])

        # Model probability from real BTC minute data at the same instant.
        try:
            bars = btc_minute_bars(window_start * 1000, decision_ts * 1000)
        except HttpFetchError:
            provider_failures += 1
            continue
        if len(bars) < 25:
            completed[key] = "insufficient_bars"
            continue
        # The binary contract's reference is the first price of the 5-minute
        # bucket. Keep this identical to btc5m_calibration.py (which uses opens).
        strike = next((o for t, o, _ in bars if t == window_start * 1000), None)
        current = bars[-1][2]
        if strike is None or strike <= 0:
            continue
        prices = np.array([c for _, _, c in bars[-30:]], dtype=float)
        logret = np.diff(np.log(prices))
        sigma = float(logret.std(ddof=1)) if len(logret) > 5 else 0.0
        if sigma <= 0:
            continue
        remaining_min = max((window_start + 300 - decision_ts) / 60.0, 0.1)
        model_p = normal_cdf(math.log(current / strike) / (sigma * math.sqrt(remaining_min)))
        # The window's own date travels with the sample. Without it the only
        # available standard error is the i.i.d. one, and consecutive 5-minute
        # windows are not independent draws: they share the same BTC price path and
        # the same volatility regime, so the model's error is correlated within a
        # day. This is the field whose absence left the board unable to verify this
        # row at all ("no_per_event_data_cannot_verify_t").
        window_date = datetime.fromtimestamp(window_start, tz=UTC).date().isoformat()
        samples.append((model_p, market_p, outcome_up, window_date))
        completed[key] = "sample"
        save_checkpoint(CHECKPOINT, {"spec": COLLECTOR_SPEC, "items": completed,
                                     "samples": [list(s) for s in samples],
                                     "provider_failures": provider_failures})
        if len(samples) % 25 == 0:
            print(f"  已重建 {len(samples)} 个已结算窗口…")
        time.sleep(0.15)

    print(f"\n可用已结算窗口: {len(samples)}，提供方失败: {provider_failures}")
    write_records(
        "btc5m_settled_windows",
        [
            {
                "symbol": "BTC-USDT",
                "event_at": f"{day}T00:00:00+00:00",
                "model_probability": model_p,
                "market_probability": market_p,
                "outcome_up": outcome,
                "source": "polymarket_gamma_clob_okx",
            }
            for model_p, market_p, outcome, day in samples
        ],
        source="polymarket_gamma_clob_okx",
        partition_by=("symbol",),
    )
    if len(samples) < 60:
        print("样本不足,不做结论(遵守真实数据规则,不用模拟数据凑)")
        return

    model_ps = np.array([s[0] for s in samples])
    market_ps = np.array([s[1] for s in samples])
    outcomes = np.array([s[2] for s in samples])
    dates = [s[3] for s in samples]

    brier_model = float(np.mean((model_ps - outcomes) ** 2))
    brier_market = float(np.mean((market_ps - outcomes) ** 2))
    print(f"Brier  模型 {brier_model:.4f}  |  市场 {brier_market:.4f}  (越低越好)")
    print(f"准确率 模型 {np.mean((model_ps>0.5)==(outcomes==1))*100:.1f}%  |  "
          f"市场 {np.mean((market_ps>0.5)==(outcomes==1))*100:.1f}%")

    # Trade only when the model disagrees materially; pay the spread.
    edge = model_ps - market_ps
    trades: list[tuple[float, str]] = []
    for q, o, e, day in zip(market_ps, outcomes, edge, dates):
        if e >= EDGE_THRESHOLD:            # model says UP is cheap -> buy UP
            trades.append(((1.0 if o == 1 else 0.0) - q - FEE, day))
        elif e <= -EDGE_THRESHOLD:         # model says UP is rich -> buy DOWN
            trades.append(((1.0 if o == 0 else 0.0) - (1.0 - q) - FEE, day))
    hurdle = deflated_t_stat_threshold(registry.n_trials)

    if len(trades) < 30:
        result = {"strategy": "btc5m_mispricing", "n": len(trades),
                  "note": "too few qualifying signals to conclude"}
        print(f"\n触发交易 {len(trades)} 笔 — 样本不足,不下结论")
    else:
        # Clustered by day: ``hold_days=1`` because a 5-minute binary settles inside
        # the session, and the unit that is actually independent is the day, not the
        # window. Windows minutes apart share one price path.
        inference = clustered_inference.analyse(
            [pnl for pnl, _ in trades], [d for _, d in trades],
            t_hurdle=hurdle, hold_days=1,
        )
        result = {"strategy": "btc5m_mispricing", **inference.to_dict()}
        # The board keys the effect size off this name for contract-priced edges,
        # where "excess return" is per-contract P&L rather than a percentage.
        result["mean_pnl_per_contract"] = round(inference.mean, 4)
        result["brier_model"] = round(brier_model, 4)
        result["brier_market"] = round(brier_market, 4)
        # Per-event P&L and dates, so the board recomputes rather than copies.
        result["events"] = [
            {"date": d, "excess": round(pnl, 6)}
            for pnl, d in sorted(trades, key=lambda x: x[1])
        ]
        print(f"\n触发交易 {inference.n} 笔  独立日 {inference.n_clusters}  "
              f"每张平均盈亏 {inference.mean:+.4f}  胜率 {inference.win_rate*100:.1f}%  "
              f"t(iid)={inference.t_iid:+.2f}  t(按日聚类)={inference.t_clustered:+.2f} "
              f"(门槛 {hurdle:.2f})  {'✅ 显著' if inference.significant else '❌ 不显著'}")
        for warning in inference.warnings:
            print(f"  ⚠ {warning}")

    out = Path("data/btc5m_mispricing.json")
    out.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "n_windows": len(samples), "edge_threshold": EDGE_THRESHOLD, "fee": FEE,
        "collection_status": "complete" if (
            len(samples) >= N_WINDOWS and provider_failures == 0 and not budget_exhausted
        ) else "partial",
        "new_attempts": new_attempts,
        "budget_exhausted": budget_exhausted,
        "provider_failures": provider_failures,
        "hold_days": 1,          # the replay/board reads this to pick the cluster unit
        "inference": "cluster_robust",
        "result": result,
    }, indent=2, ensure_ascii=False))
    manifest.record_input("polymarket_windows", settled=len(samples),
                          qualifying_trades=len(trades))
    written = manifest.save(out)
    registry.record_result(
        "btc5m_model_vs_market", {k: v for k, v in result.items() if k != "events"}
    )
    print(f"运行清单 {written}")
    for warning in manifest.warn_lines():
        print(f"  ⚠ {warning}")
    print(f"写入 {out}")


if __name__ == "__main__":
    main()
