# PB-0044 Universal Data Retirement Gate — 2026-08-25

## Decision

The compaction-and-source-retirement rule applies to every dataset under `data/`, including
A-share, US-equity, crypto, SEC, funding, model inputs, feature snapshots, caches, replay
artifacts, and logs. It does not authorize bulk deletion by itself.

Current inventory was generated with:

```text
uv run --locked python scripts/dataset_file_governance.py inventory --root data --top-level-limit 20
```

Observed: 226,980 files, 5,658,515,496 bytes, and 224,892 files below 64 KiB. The largest
groups include datasets, market cache, and store. This confirms a real small-file and storage
governance problem, but inventory alone cannot establish provenance, PIT coverage, active
consumers, or safe recovery boundaries.

## Enforced controls

- The project constraint now explicitly covers all data types.
- Compaction remains sidecar-only by default; source retirement is a separate cutover.
- `compact_dataset_parts.py` records source hashes and schema fingerprints, refuses a plan when
  source contents or schemas changed, and verifies output rows, schema, and hash.
- Unknown purpose, missing provenance, active consumers, or incomplete recovery evidence remains
  `UNKNOWN` and must not be deleted.

## Retirement status

No additional source data was deleted in this iteration. The previously verified BTC-1m retired
tree remains the only source tree with a completed retirement evidence chain. All other data stays
in place until it has a dataset-specific manifest, consumer cutover, replay/read recovery test,
precise deletion plan, and post-retirement inventory.

## Required next dataset-specific work

1. Produce inventory and classification manifests for each top-level dataset family.
2. Compact one family at a time with bounded resources and immutable source snapshots.
3. Run query, replay, API, PIT/provenance, and shutdown/recovery checks against the sidecar.
4. Retire only an exact approved path list, then rerun inventory and stale-reference checks.
