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

import hashlib
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
from libs.data.data_lake import read_manifest, write_records
from libs.polymarket.btc_five_minute import map_outcome_tokens
from libs.quant import clustered_inference
from libs.quant.pbo import deflated_t_stat_threshold

UA = {"User-Agent": "Mozilla/5.0 (PolyBob research)"}
CACHE_DIR = Path("data/market_cache/btc5m")
CHECKPOINT = CACHE_DIR / "collection_checkpoint.json"
COLLECTOR_SPEC = "btc5m-v6-atomic-window-provenance-open-price-up-token-cache-checkpoint"
N_WINDOWS = int(os.environ.get("POLYBOB_BTC5M_N_WINDOWS", "220"))
MAX_NEW_WINDOWS = int(os.environ.get("POLYBOB_BTC5M_MAX_NEW_WINDOWS", "60"))
NORMALIZED_DATASET = "btc5m_settled_windows_v6"
BATCH_SIZE = max(1, int(os.environ.get("POLYBOB_BTC5M_COMMIT_BATCH", "100")))
FETCH_TIMEOUT_SECONDS = max(
    1.0, float(os.environ.get("POLYBOB_BTC5M_FETCH_TIMEOUT_SECONDS", "8"))
)
FETCH_ATTEMPTS = max(1, int(os.environ.get("POLYBOB_BTC5M_FETCH_ATTEMPTS", "2")))
EDGE_THRESHOLD = 0.10     # model must disagree with the market by >= 10 points
FEE = 0.02                # round-trip spread/fee assumption, in probability terms
OOS_START_DATE = "2026-08-20"  # fixed before this audit; never tuned on OOS results
TERMINAL_WINDOW_STATUSES = frozenset({
    "sample", "no_market", "invalid_market", "insufficient_bars",
})


def _should_skip_checkpoint_window(status: object) -> bool:
    """Only skip terminal states; time-dependent provider states are retryable."""
    return str(status) in TERMINAL_WINDOW_STATUSES


def _period_audit(
    trade_details: list[dict[str, object]],
    *,
    initial_capital: float = 10_000.0,
    position_fraction: float = 0.10,
) -> dict[str, object]:
    """Build a fixed-initial-capital daily/monthly audit from per-contract PnL.

    This is deliberately not presented as executable PnL: it uses one fixed
    contract stake per event.  Keeping the sizing basis explicit prevents the
    event average from being silently annualized or compounded.
    """
    daily: dict[str, dict[str, float | int]] = {}
    for detail in trade_details:
        day = str(detail["date"])
        entry = float(detail["entry_price"])
        pnl = float(detail["pnl"])
        cash_pnl = pnl / entry * initial_capital * position_fraction
        row = daily.setdefault(day, {"events": 0, "pnl": 0.0})
        row["events"] = int(row["events"]) + 1
        row["pnl"] = float(row["pnl"]) + cash_pnl

    ordered_days = sorted(daily)
    equity = initial_capital
    peak = equity
    max_drawdown = 0.0
    daily_rows: list[dict[str, object]] = []
    for day in ordered_days:
        pnl = float(daily[day]["pnl"])
        equity += pnl
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak if peak > 0 else None
        if drawdown is not None:
            max_drawdown = max(max_drawdown, drawdown)
        daily_rows.append({
            "date": day, "events": int(daily[day]["events"]),
            "pnl": round(pnl, 6), "return": round(pnl / initial_capital, 8),
            "equity": round(equity, 6),
            "drawdown": round(drawdown, 8) if drawdown is not None else None,
        })

    monthly: dict[str, dict[str, float | int]] = {}
    for row in daily_rows:
        month = str(row["date"])[:7]
        item = monthly.setdefault(month, {"events": 0, "pnl": 0.0})
        item["events"] = int(item["events"]) + int(row["events"])
        item["pnl"] = float(item["pnl"]) + float(row["pnl"])
    monthly_rows = [
        {"month": month, "events": int(item["events"]),
         "pnl": round(float(item["pnl"]), 6),
         "return": round(float(item["pnl"]) / initial_capital, 8)}
        for month, item in sorted(monthly.items())
    ]
    return {
        "basis": "fixed_initial_capital_per_event",
        "initial_capital": initial_capital,
        "position_fraction": position_fraction,
        "daily": daily_rows,
        "monthly": monthly_rows,
        "max_drawdown": round(max_drawdown, 8),
        "total_return": round((equity - initial_capital) / initial_capital, 8),
        "return_target": {
            "status": "UNKNOWN" if len(monthly_rows) < 12 else "NOT_EVALUATED",
            "annual_min": 0.50, "monthly_min": 0.15,
            "complete_months": len(monthly_rows), "required_months": 12,
        },
    }


def _time_split_audit(
    trade_details: list[dict[str, object]],
    *,
    oos_start: str = OOS_START_DATE,
    min_independent_days: int = 20,
) -> dict[str, object]:
    """Summarize a fixed chronological train/OOS split without retuning."""
    groups = {
        "train": [row for row in trade_details if str(row["date"]) < oos_start],
        "oos": [row for row in trade_details if str(row["date"]) >= oos_start],
    }
    summary: dict[str, object] = {"oos_start": oos_start, "min_independent_days": min_independent_days}
    for name, rows in groups.items():
        days = sorted({str(row["date"]) for row in rows})
        pnls = [float(row["pnl"]) for row in rows]
        summary[name] = {
            "n_trades": len(rows), "independent_days": len(days),
            "first_date": days[0] if days else None,
            "last_date": days[-1] if days else None,
            "mean_pnl_per_contract": round(float(np.mean(pnls)), 8) if pnls else None,
            "win_rate": round(float(np.mean(np.asarray(pnls) > 0)), 8) if pnls else None,
            "status": "AVAILABLE" if len(days) >= min_independent_days else "UNKNOWN",
        }
    summary["status"] = "AVAILABLE" if all(
        summary[name]["status"] == "AVAILABLE" for name in groups
    ) else "UNKNOWN"
    return summary


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
    return _get_with_digest(url, timeout=timeout)[0]


def _get_with_digest(url: str, timeout: float = 20.0):
    raw = fetch_cached_bytes(
        url, cache_dir=CACHE_DIR / "responses",
        policy=FetchPolicy(attempts=FETCH_ATTEMPTS,
                           timeout_seconds=min(timeout, FETCH_TIMEOUT_SECONDS),
                           initial_backoff_seconds=0.5, max_backoff_seconds=4.0),
        headers=UA,
        dataset="btc5m_provider_raw", source=url.split('/')[2],
    )
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def btc_minute_bars(start_ms: int, end_ms: int) -> list[tuple[int, float, float]]:
    return _btc_minute_bars_with_provenance(start_ms, end_ms)[0]


def _btc_minute_bars_with_provenance(
    start_ms: int, end_ms: int,
) -> tuple[list[tuple[int, float, float]], str]:
    """Completed 1-minute BTC bars available before ``end_ms``.

    OKX timestamps identify the bar *open*.  A bar at ``end_ms`` is still
    forming at the decision instant, so including its close would leak up to
    one minute of future information into the model.
    """
    url = ("https://www.okx.com/api/v5/market/history-candles"
           f"?instId=BTC-USDT&bar=1m&limit=300&after={end_ms}")
    payload, raw_sha = _get_with_digest(url)
    rows = payload.get("data", [])
    out = [
        # OKX history-candles schema: ts, open, high, low, close, volume.
        # Keep the open and close explicit; volume is never a price input.
        (int(r[0]), float(r[1]), float(r[4]))
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
    return sorted(out), raw_sha


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _closed_market_contract(market: dict) -> tuple[str, int]:
    """Resolve the UP token and settled UP outcome without trusting array order."""
    outcomes = json.loads(market.get("outcomes", "[]"))
    outcome_prices = json.loads(market.get("outcomePrices", "[]"))
    if len(outcomes) != len(outcome_prices):
        raise ValueError("outcome prices are not aligned with outcomes")
    up_index = next(
        index for index, label in enumerate(outcomes)
        if str(label).strip().upper() in {"UP", "YES"}
    )
    token = map_outcome_tokens(market)["UP"]
    return token, 1 if float(outcome_prices[up_index]) > 0.5 else 0


def _normalized_record(sample: dict[str, object]) -> dict[str, object]:
    """Map one checkpoint sample to its unique normalized lake row."""
    return {
        "symbol": "BTC-USDT",
        "event_at": datetime.fromtimestamp(int(sample["decision_ts"]), tz=UTC).isoformat(),
        "window_start": sample["window_start"],
        "window_end": sample["window_end"],
        "decision_ts": sample["decision_ts"],
        "model_probability": sample["model_probability"],
        "market_probability": sample["market_probability"],
        "outcome_up": sample["outcome_up"],
        "market_token_up": sample["market_token_up"],
        "gamma_raw_sha256": sample["gamma_raw_sha256"],
        "clob_raw_sha256": sample["clob_raw_sha256"],
        "okx_raw_sha256": sample["okx_raw_sha256"],
        "source": "polymarket_gamma_clob_okx",
    }


def _json_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_lineage(samples: list[dict[str, object]]) -> dict[str, object]:
    """Return a content fingerprint and fail-closed consistency check."""
    entries = [entry for entry in read_manifest()
               if entry.get("kind") == "normalized"
               and entry.get("dataset") == NORMALIZED_DATASET]
    paths = [Path(str(entry["path"])) for entry in entries if entry.get("path")]
    normalized_rows: list[dict[str, object]] = []
    for path in paths:
        if not path.exists():
            continue
        import pyarrow.parquet as pq
        normalized_rows.extend(pq.read_table(path).to_pylist())
    sample_by_window = {int(row["window_start"]): row for row in samples}
    normalized_by_window = {
        int(row["window_start"]): row for row in normalized_rows
        if row.get("window_start") is not None
    }
    sample_digest = _json_digest(sorted(samples, key=lambda row: int(row["window_start"])))
    normalized_digest = _json_digest(sorted(
        [{key: value for key, value in row.items() if key != "observed_at"}
         for row in normalized_rows],
        key=lambda row: int(row["window_start"]),
    ))
    raw_sha_digest = _json_digest(sorted({
        str(row[field])
        for row in samples
        for field in ("gamma_raw_sha256", "clob_raw_sha256", "okx_raw_sha256")
    }))
    consistent = (
        len(normalized_rows) == len(normalized_by_window) == len(sample_by_window)
        and set(normalized_by_window) == set(sample_by_window)
        and all(
            all(normalized_by_window[key].get(field) == sample_by_window[key].get(field)
                for field in ("window_end", "decision_ts", "gamma_raw_sha256",
                              "clob_raw_sha256", "okx_raw_sha256"))
            for key in sample_by_window
        )
    )
    checkpoint_digest = hashlib.sha256(CHECKPOINT.read_bytes()).hexdigest()
    manifest_digest = _json_digest(sorted(entries, key=lambda entry: str(entry.get("path"))))
    return {
        "status": "consistent" if consistent else "blocked_inconsistent",
        "sample_rows": len(samples),
        "normalized_rows": len(normalized_rows),
        "unique_windows": len(normalized_by_window),
        "normalized_parts": len(paths),
        "checkpoint_sha256": checkpoint_digest,
        "sample_set_sha256": sample_digest,
        "normalized_rows_sha256": normalized_digest,
        "raw_sha_set_sha256": raw_sha_digest,
        "normalized_manifest_sha256": manifest_digest,
    }


def main() -> None:
    print("=" * 84)
    print("PRE-REGISTERED — BTC 5m model-vs-market mispricing (settled windows)")
    print("=" * 84)
    registry = HypothesisRegistry()
    preregister(registry)
    manifest = run_manifest.pin("btc5m_model_vs_market", params={
        "n_windows": N_WINDOWS, "edge_threshold": EDGE_THRESHOLD, "fee": FEE,
        "model_revision": "realized-volatility-normal-cdf-v3",
        "oos_start": OOS_START_DATE, "time_split": "fixed_chronological",
    })
    print(f"观测时点 as_of = {manifest.as_of.isoformat()}")
    print(f"累计试验 {registry.n_trials}\n")

    now = int(time.time())
    base = (now // 300) * 300
    samples: list[dict[str, object]] = []
    checkpoint = load_checkpoint(CHECKPOINT, spec=COLLECTOR_SPEC)
    saved_samples = checkpoint.get("samples", [])
    if isinstance(saved_samples, list):
        samples = [item for item in saved_samples if isinstance(item, dict)]
    completed = checkpoint.setdefault("items", {})
    provider_failures = int(checkpoint.get("provider_failures", 0))
    new_attempts = 0
    budget_exhausted = False
    pending_samples: list[dict[str, object]] = []

    def commit_pending() -> None:
        if not pending_samples:
            return
        # The Parquet write is the durable commit. The checkpoint is advanced
        # only after the batch exists, so an interruption leaves at most an
        # idempotent orphan part that the next retry can safely reuse.
        write_records(
            NORMALIZED_DATASET,
            [_normalized_record(sample) for sample in pending_samples],
            source="polymarket_gamma_clob_okx",
            partition_by=("symbol",),
        )
        samples.extend(pending_samples)
        for sample in pending_samples:
            completed[str(sample["window_start"])] = "sample"
        save_checkpoint(CHECKPOINT, {
            "spec": COLLECTOR_SPEC,
            "items": completed,
            "samples": samples,
            "provider_failures": provider_failures,
        })
        pending_samples.clear()

    for i in range(1, N_WINDOWS + 1):
        window_start = base - i * 300
        key = str(window_start)
        if _should_skip_checkpoint_window(completed.get(key)):
            continue
        if new_attempts >= MAX_NEW_WINDOWS:
            budget_exhausted = True
            break
        new_attempts += 1
        try:
            event, gamma_sha = _get_with_digest(
                f"https://gamma-api.polymarket.com/events/slug/btc-updown-5m-{window_start}"
            )
        except HttpFetchError:
            provider_failures += 1
            save_checkpoint(CHECKPOINT, {"spec": COLLECTOR_SPEC, "items": completed,
                                         "samples": samples,
                                         "provider_failures": provider_failures})
            continue
        markets = event.get("markets") or []
        if not markets:
            completed[key] = "no_market"
            save_checkpoint(CHECKPOINT, {"spec": COLLECTOR_SPEC, "items": completed,
                                         "samples": samples,
                                         "provider_failures": provider_failures})
            continue
        market = markets[0]
        if not market.get("closed"):
            completed[key] = "open"
            save_checkpoint(CHECKPOINT, {"spec": COLLECTOR_SPEC, "items": completed,
                                         "samples": samples,
                                         "provider_failures": provider_failures})
            continue
        try:
            token, outcome_up = _closed_market_contract(market)
        except (ValueError, IndexError, TypeError):
            completed[key] = "invalid_market"
            continue

        # Market quote roughly 2 minutes into the window.
        decision_ts = window_start + 120
        try:
            history_payload, clob_sha = _get_with_digest(
                f"https://clob.polymarket.com/prices-history"
                f"?market={token}&interval=max&fidelity=1"
            )
            history = history_payload.get("history", [])
        except HttpFetchError:
            provider_failures += 1
            continue
        quotes = [h for h in history if h.get("t", 0) <= decision_ts]
        if not quotes:
            continue
        market_p = float(quotes[-1]["p"])

        # Model probability from real BTC minute data at the same instant.
        try:
            bars, okx_sha = _btc_minute_bars_with_provenance(
                window_start * 1000, decision_ts * 1000
            )
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
        sample = {
            "window_start": window_start,
            "window_end": window_start + 300,
            "decision_ts": decision_ts,
            "date": window_date,
            "model_probability": model_p,
            "market_probability": market_p,
            "outcome_up": outcome_up,
            "market_token_up": token,
            "gamma_raw_sha256": gamma_sha,
            "clob_raw_sha256": clob_sha,
            "okx_raw_sha256": okx_sha,
        }
        pending_samples.append(sample)
        if len(pending_samples) >= BATCH_SIZE:
            commit_pending()
        if len(samples) % 25 == 0:
            print(f"  已重建 {len(samples)} 个已结算窗口…")
        time.sleep(0.15)

    commit_pending()
    print(f"\n可用已结算窗口: {len(samples)}，提供方失败: {provider_failures}")
    if len(samples) < 60:
        print("样本不足,不做结论(遵守真实数据规则,不用模拟数据凑)")

    model_ps = np.array([float(s["model_probability"]) for s in samples])
    market_ps = np.array([float(s["market_probability"]) for s in samples])
    outcomes = np.array([int(s["outcome_up"]) for s in samples])
    dates = [str(s["date"]) for s in samples]

    brier_model = float(np.mean((model_ps - outcomes) ** 2))
    brier_market = float(np.mean((market_ps - outcomes) ** 2))
    print(f"Brier  模型 {brier_model:.4f}  |  市场 {brier_market:.4f}  (越低越好)")
    print(f"准确率 模型 {np.mean((model_ps>0.5)==(outcomes==1))*100:.1f}%  |  "
          f"市场 {np.mean((market_ps>0.5)==(outcomes==1))*100:.1f}%")

    # Trade only when the model disagrees materially; pay the spread.
    edge = model_ps - market_ps
    trades: list[tuple[float, str]] = []
    trade_details: list[dict[str, object]] = []
    for q, o, e, day in zip(market_ps, outcomes, edge, dates):
        if e >= EDGE_THRESHOLD:            # model says UP is cheap -> buy UP
            pnl = (1.0 if o == 1 else 0.0) - q - FEE
            trades.append((pnl, day))
            trade_details.append({"date": day, "entry_price": q, "pnl": pnl, "side": "UP"})
        elif e <= -EDGE_THRESHOLD:         # model says UP is rich -> buy DOWN
            entry_price = 1.0 - q
            pnl = (1.0 if o == 0 else 0.0) - entry_price - FEE
            trades.append((pnl, day))
            trade_details.append({"date": day, "entry_price": entry_price,
                                  "pnl": pnl, "side": "DOWN"})
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
            {"date": str(detail["date"]), "excess": round(float(detail["pnl"]), 6),
             "entry_price": round(float(detail["entry_price"]), 8),
             "side": detail["side"]}
            for detail in sorted(trade_details, key=lambda x: str(x["date"]))
        ]
        result["period_audit"] = _period_audit(trade_details)
        result["time_split"] = _time_split_audit(trade_details)
        print(f"\n触发交易 {inference.n} 笔  独立日 {inference.n_clusters}  "
              f"每张平均盈亏 {inference.mean:+.4f}  胜率 {inference.win_rate*100:.1f}%  "
              f"t(iid)={inference.t_iid:+.2f}  t(按日聚类)={inference.t_clustered:+.2f} "
              f"(门槛 {hurdle:.2f})  {'✅ 显著' if inference.significant else '❌ 不显著'}")
        for warning in inference.warnings:
            print(f"  ⚠ {warning}")

    snapshot = _snapshot_lineage(samples)
    if snapshot["status"] != "consistent":
        raise RuntimeError(f"BTC 5m snapshot blocked: {snapshot}")

    out = Path("data/btc5m_mispricing.json")
    snapshot_lineage = _snapshot_lineage(samples)
    out.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "n_windows": len(samples), "edge_threshold": EDGE_THRESHOLD, "fee": FEE,
        "normalized_dataset": NORMALIZED_DATASET,
        "per_window_provenance": True,
        "snapshot": snapshot,
        "collection_status": "complete" if (
            len(samples) >= N_WINDOWS and provider_failures == 0 and not budget_exhausted
        ) else "partial",
        "new_attempts": new_attempts,
        "budget_exhausted": budget_exhausted,
        "provider_failures": provider_failures,
        "hold_days": 1,          # the replay/board reads this to pick the cluster unit
        "inference": "cluster_robust",
        "oos_start": OOS_START_DATE,
        "snapshot_lineage": snapshot_lineage,
        "result": result,
    }, indent=2, ensure_ascii=False))
    manifest.record_input("polymarket_windows", settled=len(samples),
                          qualifying_trades=len(trades), snapshot=snapshot)
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
