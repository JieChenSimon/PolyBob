# Backtest boundaries

`libs.backtest.engine.simulate_position_series` is the canonical causal
accounting kernel. It owns fills, fees, positions, marks, missing-price
fail-closed behavior, short-margin checks and equity results.

`libs.quant.research_pipeline.walk_forward_symbol` is the canonical research
entry point. It selects parameters on a training window and scores only the
following out-of-sample window, with optional bar-based purge and embargo.

`libs.backtest.walk_forward.WalkForwardAnalyzer` is retained as a compatibility
window-orchestration API for existing callers. It does not implement a second
accounting engine; callers must pass a backtest function backed by the
canonical kernel. Do not add fee, fill, position, or PnL calculations there.
