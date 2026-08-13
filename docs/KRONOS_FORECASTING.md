# Kronos Forecast Lab

## Boundary

Kronos is an opt-in forecasting research capability. It is disabled by default,
does not load during API startup, and cannot grant trade permission. `Kronos/`
remains an independent reference checkout: PolyBob never tracks, modifies, tests,
commits, pushes, rolls back, or imports it at runtime.

The reproducible local runtime lives under ignored `data/models/kronos/`:

```bash
uv sync --extra forecasting --locked
uv run --extra forecasting --locked python scripts/kronos_models.py pull
uv run --extra forecasting --locked python scripts/kronos_models.py prepare --source Kronos
uv run --extra forecasting --locked python scripts/kronos_models.py verify
```

`prepare` reads three implementation files from a pinned reference checkout and
copies them into the ignored runtime cache. It does not change the checkout.

To enable the API deliberately:

```bash
ENABLE_LAB_KRONOS_FORECASTING=true \
uv run --extra forecasting --locked uvicorn apps.api.main:app --port 18000
```

Engine availability is only the outer kill switch. Every instrument is still
disabled by default and must be enabled independently from its workbench row or
instrument page. The setting is stored in the local PolyBob SQLite fact store;
missing rows are disabled, and the forecasting API rejects a run before market
data is fetched unless that exact `domain:symbol` is enabled. Enabling an
instrument never grants trade permission.

New clients start expensive inference with `POST /api/forecasting/runs`. The
older GET endpoint remains only for compatibility and enforces the same gates.

Each completed run also returns an `explanation` object. It contains a short
history for the fan chart, deterministic input-state summaries, an unchanged
last-close baseline, historical-validation state and an explicit interval
breach rule. `causal_attribution_available` is always false: descriptive OHLCV
statistics must never be presented as reasons the transformer made a forecast.
Until at least 100 paths are sampled, the dashboard shows the integer path
count rather than labelling it as a probability. Missing walk-forward evidence
is displayed as `UNKNOWN`, never inferred from a single run.

## Local artifacts

| Artifact | Revision | SHA-256 | Size |
|---|---|---|---:|
| `NeoQuasar/Kronos-base` | `2b554741eca47781b64468546e77fef3e85130e6` | `abff193acab6db1a0368e9773e75799d11403b6d054ee6d5f0a11aeabc5f4b83` | 390 MiB |
| `NeoQuasar/Kronos-Tokenizer-base` | `0e0117387f39004a9016484a186a908917e22426` | `59d85f6af76a2c3b8240ea06cb21db4213b4eeca053f246b23e29cf832fc6bee` | 15 MiB |
| Runtime source | `67b630e67f6a18c9e9be918d9b4337c960db1e9a` | prepared locally | 3 source files |

## Base benchmark on this machine

Measured on Apple M5 Pro, 48 GiB unified memory, PyTorch 2.11 MPS:

| Probe | Result |
|---|---:|
| Model load | 0.750 s |
| Context | 64 bars |
| Forecast | 4 bars, deterministic path |
| Forecast time | 4.309 s |
| Process maximum RSS | 1.05 GiB |
| Output | finite OHLC values, successful |

This is a smoke benchmark, not an accuracy claim. Accuracy must be measured on
post-June-2024 point-in-time data against naive baselines.

## Asset boundaries

| Domain | Initial mode | Status |
|---|---|---|
| A-share | Daily OHLCV, explicit adjustment metadata | Supported in Lab |
| US equity | Daily OHLCV, provider adjustment marked unknown | Supported in Lab |
| Crypto spot | Daily OHLCV, 24/7 calendar | Supported in Lab |
| Crypto perpetual | Forecast price separately; funding remains a downstream feature | Contract defined, adapter pending |
| Polymarket | Requires bounded-probability, liquidity and time-to-resolution adapter | Blocked intentionally |
| Pairs/spreads | Forecast each leg, then construct the spread distribution | Evaluation stage |

Missing OHLC is `UNKNOWN`. If volume is absent, the artifact explicitly reports
`ohlc_only`; if amount is absent while volume exists, it reports
`ohlcv_amount_derived`. The distinction is never hidden.

## Can PolyBob train Kronos-large?

### What is reproducible

The paper publishes the architecture: 18 layers, model dimension 1664, FFN
dimension 3072, 32 heads, 20-bit hierarchical vocabulary, 499.2M parameters.
`config/kronos_large_research.json` records those settings and the published
optimizer values. Instantiating that configuration with the official code
produced exactly **499,246,976 parameters**.

### Measured local training probes

Randomly initialized architecture, full forward/backward and AdamW step:

```bash
uv run --extra forecasting --locked python scripts/benchmark_kronos_large.py --batch-size 4
```

| Batch × sequence | Step time | Throughput | MPS allocated | MPS driver |
|---|---:|---:|---:|---:|
| 1 × 512 | 1.491 s | 343 tokens/s | 8.82 GiB | 10.19 GiB |
| 4 × 512 | 2.877 s | 712 tokens/s | 9.33 GiB | 10.24 GiB |
| 16 × 512 | 9.704 s | 844 tokens/s | 15.06 GiB | 33.18 GiB |

Therefore this Mac can instantiate and train the large architecture. It is
appropriate for correctness tests, small-domain experiments and possibly LoRA
or short full-parameter runs. Batch 16 is too close to the recommended MPS
memory ceiling for unattended training; batch 4 plus gradient accumulation is
the safer local setting.

### What is not reproducible today

The official large weights are unavailable. More importantly, the exact
curated corpus, split, cleaning results, resampling distribution, training step
count, batch schedule and random state are not published as downloadable
artifacts. The paper reports approximately 12.11B K-line observations across
96,569 assets, more than 40 exchanges and seven frequencies.

At the measured best local probe of 844 tokens/s, merely visiting 12.11B bars
once would take about **166 continuous days**. That excludes data preparation,
tokenization, validation, checkpoints, retries and additional epochs. Raw six
channel float32 values alone are about 291 GB; a usable point-in-time corpus
with timestamps, identifiers, quality metadata and intermediate shards is more
realistically hundreds of GB to several TB.

So the precise verdict is:

- **Can build and train a 499.2M Kronos-compatible model:** yes.
- **Can locally fine-tune or distill one on PolyBob domains:** yes, with a much
  smaller, legally obtained point-in-time corpus.
- **Can reproduce the official Kronos-large model:** no, because the defining
  weights and training dataset are unavailable.
- **Should train from random initialization now:** no. First prove that
  Kronos-base beats naive baselines on PolyBob's out-of-sample data.

### Scientific training path

1. Freeze the current base model/revisions and build post-June-2024 walk-forward
   benchmarks for A-shares, US equities and crypto.
2. Accumulate clean point-in-time OHLCVA with exchange calendars and corporate
   action policy; report coverage rather than filling gaps.
3. Fine-tune base and compare against frozen base. Stop if the improvement does
   not survive independent time clusters.
4. Train a 100M model from scratch on the same corpus to validate the complete
   data/training pipeline.
5. Only if scaling curves remain positive, train the public 499M architecture
   on CUDA infrastructure. Call it `PolyBob-Kline-499M`, not `Kronos-large`,
   because it will not be the unavailable official model.

No forecast may enter execution until the existing promotion board has a real,
reproducible, unexpired `trade` record for the exact strategy and instrument.
