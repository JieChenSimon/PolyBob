"""Print the local real-data catalog and bitemporal store coverage."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from libs.data import data_lake, store


def main() -> int:
    report = {
        "data_lake": data_lake.inventory(),
        "bitemporal_store": {
            dataset.name: store.coverage(dataset) for dataset in store.DATASETS
        },
        "contracts": store.dataset_contracts(),
        "raw_manifest": str(data_lake.MANIFEST),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
