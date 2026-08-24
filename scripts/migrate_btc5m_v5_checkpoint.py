"""One-time migration of the valid v5 window samples into the atomic v6 lake."""

from __future__ import annotations

import json
from pathlib import Path

from libs.data.data_lake import write_records
from libs.data.resilient import save_checkpoint
from scripts.btc5m_mispricing import _normalized_record

CHECKPOINT = Path("data/market_cache/btc5m/collection_checkpoint.json")
OLD_SPEC = "btc5m-v5-window-provenance-open-price-up-token-cache-checkpoint"
NEW_SPEC = "btc5m-v6-atomic-window-provenance-open-price-up-token-cache-checkpoint"
DATASET = "btc5m_settled_windows_v6"


def main() -> int:
    payload = json.loads(CHECKPOINT.read_text())
    if payload.get("spec") != OLD_SPEC:
        raise RuntimeError(f"expected {OLD_SPEC}, got {payload.get('spec')}")
    unique: dict[int, dict] = {}
    for sample in payload.get("samples", []):
        if isinstance(sample, dict):
            unique[int(sample["window_start"])] = sample
    samples = [unique[key] for key in sorted(unique)]
    write_records(
        DATASET, [_normalized_record(sample) for sample in samples],
        source="polymarket_gamma_clob_okx_migrated_v5", partition_by=("symbol",),
    )
    save_checkpoint(CHECKPOINT, {
        "spec": NEW_SPEC, "items": payload.get("items", {}),
        "samples": samples, "provider_failures": payload.get("provider_failures", 0),
        "migrated_from": OLD_SPEC,
    })
    print(f"migrated {len(samples)} unique windows into {DATASET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
