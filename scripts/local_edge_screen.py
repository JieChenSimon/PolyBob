"""Screen pre-declared single-asset edges on the local real-data store."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.backtest import simulate_position_series
from libs.data import run_manifest, store
from libs.quant.edges import SINGLE_ASSET_EDGES

COST_BPS = {"a_share": 8.0, "us_equity": 5.0, "crypto": 10.0}
MAX_MULTIPLE = {"a_share": 1.5, "us_equity": 1.5, "crypto": 5.0}


def domain(symbol: str) -> str:
    if symbol.isdigit():
        return "a_share"
    if symbol.endswith("-USDT"):
        return "crypto"
    return "us_equity"


def unresolved_jump(prices: np.ndarray, maximum: float) -> bool:
    if len(prices) < 2 or np.any(~np.isfinite(prices)) or np.any(prices <= 0):
        return True
    ratio = prices[1:] / prices[:-1]
    return bool(np.any(ratio > maximum) or np.any(ratio < 1.0 / maximum))


def main() -> int:
    as_of = datetime.now(UTC)
    manifest = run_manifest.pin("local_edge_screen", as_of=as_of,
                               params={"edges": sorted(SINGLE_ASSET_EDGES),
                                       "cost_bps": COST_BPS, "oos_fraction": 0.3})
    symbols = store.symbols(store.DAILY_BARS)
    manifest.record_input("daily_bars", symbols=len(symbols), coverage=store.coverage(store.DAILY_BARS))
    rows = []
    for symbol in symbols:
        d = domain(symbol)
        try:
            prices = store.read(store.DAILY_BARS, symbol, as_of=as_of)["close"].dropna().astype(float).to_numpy()
        except Exception as exc:
            rows.append({"symbol": symbol, "domain": d, "status": "unknown", "error": str(exc)})
            continue
        if len(prices) < 300 or unresolved_jump(prices, MAX_MULTIPLE[d]):
            rows.append({"symbol": symbol, "domain": d, "status": "unknown_data_quality"})
            continue
        cut = int(len(prices) * 0.7)
        train, test = prices[:cut], prices[cut:]
        for edge, builder in SINGLE_ASSET_EDGES.items():
            try:
                positions = builder(np.concatenate((train, test)))[-len(test):]
                # The canonical replay has an explicit borrow/margin contract;
                # this fixed-family screen is deliberately comparable across
                # domains, so it evaluates the cash-funded long-only variant.
                # Short legs need a separate margin model and are not silently
                # treated as free leverage here.
                positions = np.clip(positions, 0.0, 1.0)
                returns, _ = simulate_position_series(
                    test, positions, cost_bps=COST_BPS[d], allow_short=False
                )
                oos = float(np.prod(1.0 + returns) - 1.0)
                baseline = float(test[-1] / test[0] - 1.0)
                rows.append({"symbol": symbol, "domain": d, "edge": edge,
                             "status": "tested", "oos_return": oos,
                             "baseline_return": baseline, "excess_return": oos - baseline})
            except (ValueError, FloatingPointError) as exc:
                rows.append({"symbol": symbol, "domain": d, "edge": edge,
                             "status": "unknown_accounting", "error": str(exc)})

    summary = {}
    for d in COST_BPS:
        summary[d] = {}
        for edge in SINGLE_ASSET_EDGES:
            tested = [r for r in rows if r.get("domain") == d and r.get("edge") == edge and r.get("status") == "tested"]
            oos = np.asarray([r["oos_return"] for r in tested], dtype=float)
            excess = np.asarray([r["excess_return"] for r in tested], dtype=float)
            summary[d][edge] = {
                "symbols": len(tested),
                "mean_oos_return": float(np.mean(oos)) if len(oos) else None,
                "median_oos_return": float(np.median(oos)) if len(oos) else None,
                "median_excess_return": float(np.median(excess)) if len(excess) else None,
                "positive_excess_fraction": float(np.mean(excess > 0)) if len(excess) else None,
                "status": "tested_no_edge" if not len(excess) or float(np.median(excess)) <= 0 else "screen_only",
            }
    report = {"generated_at": datetime.now(UTC).isoformat(), "as_of": as_of.isoformat(),
              "real_data_only": True, "research_only": True,
              "parameters": {"cost_bps": COST_BPS, "oos_fraction": 0.3,
                              "long_only": True,
                              "max_single_bar_multiple": MAX_MULTIPLE},
              "summary": summary, "rows": rows, "manifest": manifest.to_dict()}
    out = Path("data/local_edge_screen.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    manifest.save(out)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
