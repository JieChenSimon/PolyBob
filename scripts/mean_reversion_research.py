"""Real-data walk-forward screen for a causal long-only mean-reversion edge.

This is a research screen, not a promotion or live-trading command. It uses the
local PIT daily-bar store and the canonical causal ``simulate_position_series``
accounting. A candidate must first survive this screen and then be replayed
through Paper Lab before it can affect any execution configuration.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

import numpy as np

from libs.data import run_manifest, store
from libs.quant.research_pipeline import aggregate_portfolio, walk_forward_symbol


COST_BPS = {"a_share": 8.0, "us_equity": 5.0, "crypto": 10.0}
MAX_SINGLE_BAR_MULTIPLE = {"a_share": 1.5, "us_equity": 1.5, "crypto": 5.0}
CANDIDATES = tuple(
    {"lookback": lookback, "entry_bps": entry}
    for lookback, entry in (
        (10, 50), (10, 100), (20, 50), (20, 100), (20, 200),
        (40, 50), (40, 100), (40, 200), (60, 100), (60, 200),
    )
)


def _domain(symbol: str) -> str:
    if symbol.isdigit():
        return "a_share"
    if symbol.endswith("-USDT"):
        return "crypto"
    return "us_equity"


def mean_reversion_positions(
    prices: Sequence[float], *, lookback: int, entry_bps: int, exit_bps: int | None = None,
) -> np.ndarray:
    """Buy a trailing discount and flatten after mean recovery.

    The rolling mean excludes the current close, so the signal is causal. This
    implementation is long-only: it is valid for A-shares and avoids silently
    assuming borrow availability in the screening result.
    """
    if lookback <= 1 or entry_bps <= 0:
        raise ValueError("lookback and entry_bps must be positive")
    exit = int(exit_bps if exit_bps is not None else max(1, entry_bps // 2))
    values = np.asarray(prices, dtype=float)
    positions = np.zeros(len(values), dtype=float)
    active = 0.0
    for index in range(lookback, len(values)):
        mean = float(np.mean(values[index - lookback:index]))
        if not math.isfinite(mean) or mean <= 0:
            continue
        deviation_bps = (values[index] / mean - 1.0) * 10_000.0
        if deviation_bps <= -entry_bps:
            active = 1.0
        elif deviation_bps >= -exit:
            active = 0.0
        positions[index] = active
    return positions


def _result_payload(result) -> dict:
    return {
        "symbol": result.symbol,
        "status": result.status,
        "oos_return": result.oos_return,
        "oos_sharpe": result.oos_sharpe,
        "oos_max_drawdown": result.oos_max_drawdown,
        "baseline_return": result.baseline_return,
        "excess_return": (
            result.oos_return - result.baseline_return
            if result.oos_return is not None and result.baseline_return is not None
            else None
        ),
        "folds": len(result.folds),
        "selected_params": list(result.selected_params),
    }


def _has_unresolved_price_jump(prices: Sequence[float], max_multiple: float) -> bool:
    values = np.asarray(prices, dtype=float)
    if len(values) < 2 or np.any(~np.isfinite(values)) or np.any(values <= 0):
        return True
    ratios = values[1:] / values[:-1]
    return bool(np.any(ratios > max_multiple) or np.any(ratios < 1.0 / max_multiple))


def main() -> int:
    as_of = datetime.now(UTC)
    symbols = store.symbols(store.DAILY_BARS)
    manifest = run_manifest.pin(
        "mean_reversion_walk_forward",
        as_of=as_of,
        params={"candidates": CANDIDATES, "cost_bps": COST_BPS,
                "train_size": 252, "test_size": 63, "step": 63},
    )
    manifest.record_input("daily_bars", symbols=len(symbols), coverage=store.coverage(store.DAILY_BARS))
    domains: dict[str, dict] = {}
    for domain in COST_BPS:
        rows = []
        usable = []
        domain_symbols = [symbol for symbol in symbols if _domain(symbol) == domain]
        for symbol in domain_symbols:
            try:
                frame = store.read(store.DAILY_BARS, symbol, as_of=as_of)
                prices = frame["close"].dropna().astype(float).tolist()
            except Exception as exc:
                rows.append({"symbol": symbol, "status": "unknown", "error": str(exc)})
                continue
            max_multiple = MAX_SINGLE_BAR_MULTIPLE[domain]
            if _has_unresolved_price_jump(prices, max_multiple):
                rows.append({"symbol": symbol, "status": "unknown_unresolved_price_jump",
                             "reason": f"single-bar price multiple outside [1/{max_multiple}, {max_multiple}]"})
                continue
            result = walk_forward_symbol(
                symbol, prices, candidates=CANDIDATES, cost_bps=COST_BPS[domain],
                position_builder=mean_reversion_positions,
            )
            payload = _result_payload(result)
            rows.append(payload)
            if result.oos_return is not None:
                usable.append(result)
        domains[domain] = {
            "symbols": rows,
            "portfolio": aggregate_portfolio(usable),
        }

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": as_of.isoformat(),
        "real_data_only": True,
        "research_only": True,
        "strategy": "long_only_mean_reversion",
        "parameters": {"candidates": CANDIDATES, "cost_bps": COST_BPS,
                        "train_size": 252, "test_size": 63, "step": 63},
        "domains": domains,
        "manifest": manifest.to_dict(),
    }
    out = Path("data/mean_reversion_results.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    manifest.save(out)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps({domain: item["portfolio"] for domain, item in domains.items()}, ensure_ascii=False, indent=2))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
