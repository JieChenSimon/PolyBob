"""Run the real local-data walk-forward research pipeline across all in-scope symbols."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from libs.data import store
from libs.data import run_manifest
from libs.data.universe import A_SHARE_LIQUID, ALTCOIN_MAJORS, US_LIQUID, altcoin_pairs
from libs.quant.research_pipeline import aggregate_portfolio, walk_forward_symbol


DOMAINS = {
    "us_equity": list(US_LIQUID),
    "a_share": list(A_SHARE_LIQUID),
    "altcoin": list(altcoin_pairs()),
}
COST_BPS = {"us_equity": 5.0, "a_share": 8.0, "altcoin": 10.0}
CANDIDATES = tuple({"fast": fast, "slow": slow} for fast, slow in ((5, 20), (10, 40), (20, 60)))


def main() -> int:
    now = dt.datetime.now(dt.UTC)
    report: dict[str, object] = {
        "run_id": f"quant-{now.strftime('%Y%m%dT%H%M%S%fZ')}",
        "generated_at": now.isoformat(), "real_data_only": True,
        "parameters": {"candidates": CANDIDATES, "cost_bps": COST_BPS,
                        "train_size": 252, "test_size": 63, "step": 63},
        "domains": {},
    }
    manifest = run_manifest.pin("multi_asset_walk_forward", params=report["parameters"])
    for domain, symbols in DOMAINS.items():
        manifest.record_input(f"daily_bars:{domain}", symbols=symbols,
                              coverage=store.coverage(store.DAILY_BARS))
    for domain, symbols in DOMAINS.items():
        rows = []
        usable = []
        for symbol in symbols:
            try:
                frame = store.read(store.DAILY_BARS, symbol, as_of=now)
                prices = frame["close"].dropna().astype(float).tolist()
            except Exception as exc:  # a missing symbol is UNKNOWN, not zero return
                rows.append({"symbol": symbol, "status": "unknown", "error": str(exc)})
                continue
            result = walk_forward_symbol(
                symbol, prices, candidates=CANDIDATES, cost_bps=COST_BPS[domain],
            )
            usable.append(result)
            rows.append({"symbol": result.symbol, "status": result.status,
                         "oos_return": result.oos_return, "oos_sharpe": result.oos_sharpe,
                         "oos_max_drawdown": result.oos_max_drawdown,
                         "baseline_return": result.baseline_return,
                         "folds": len(result.folds),
                         "selected_params": list(result.selected_params)})
        report["domains"][domain] = {"symbols": rows, "portfolio": aggregate_portfolio(usable)}
    out = Path("data/quant_pipeline_results.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n")
    manifest_path = manifest.save(out)
    report["manifest"] = str(manifest_path)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({d: report["domains"][d]["portfolio"] for d in DOMAINS}, ensure_ascii=False, indent=2))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
