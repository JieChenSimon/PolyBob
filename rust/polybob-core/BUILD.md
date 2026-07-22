# Building the `polybob_core` native extension

`polybob_core` is an optional PyO3/maturin extension that provides Rust
implementations of a few CPU-heavy quant kernels (rolling z-score, Kalman hedge
ratio, risk metrics, slippage). It is **optional at runtime**: `libs/compute`
defaults to the pure-Python path and only uses the native core when it is built
and importable (see `libs/compute/backend.py::native_core_status`).

## Prerequisites

- Rust toolchain (`cargo`, `rustc`) — install via <https://rustup.rs>.
- `maturin` in the active Python env: `pip install "maturin>=1.7,<2.0"`.
- The macOS crate links with `dynamic_lookup` (see `.cargo/config.toml`) so the
  extension resolves Python symbols at load time.

## Verify it compiles (no install)

```bash
cd rust/polybob-core
cargo check --release      # fast type/borrow check
cargo test                 # runs the Rust unit tests in src/*.rs
```

## Build and install into the active environment

```bash
cd rust/polybob-core
maturin develop --release  # builds and installs polybob_core into the current venv
# or produce a wheel:
maturin build --release    # wheel lands in target/wheels/
pip install target/wheels/polybob_core-*.whl
```

Confirm it is active:

```bash
python -c "from libs.compute import native_core_status; print(native_core_status())"
# -> {'native_core_built': True, 'status': 'native core built', ...}
```

Then run the profiled hot loop against both backends:

```bash
python -c "from libs.compute import benchmark_rolling_zscore; print(benchmark_rolling_zscore())"
```

## Using the native core at runtime

The native path is opt-in and never changes numerical results (the `verify`
backend asserts Rust == Python):

- `POLYBOB_COMPUTE_BACKEND=auto` — use native when built, else Python (recommended).
- `POLYBOB_COMPUTE_BACKEND=rust` — force native; falls back to Python unless
  `POLYBOB_RUST_FALLBACK_ENABLED=false`.
- `POLYBOB_COMPUTE_BACKEND=verify` — run both and fail on any mismatch.

## CI: build the wheel

The extension is **not** required for the Python test suite (tests skip the
native-only cases when `polybob_core` is absent). To ship it, add a wheel-build
job, e.g. with `PyO3/maturin-action`:

```yaml
jobs:
  build-native-core:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - uses: PyO3/maturin-action@v1
        with:
          command: build
          args: --release -m rust/polybob-core/pyproject.toml
      - uses: actions/upload-artifact@v4
        with:
          name: polybob-core-wheels-${{ matrix.os }}
          path: target/wheels/*.whl
```

Optionally run `cargo test -m rust/polybob-core` in a separate step to exercise
the Rust unit tests. Install the produced wheel in the Python job before the
`test_rust_core_benchmark` / `test_infra_compute_native` tests to exercise the
native comparison path in CI.
