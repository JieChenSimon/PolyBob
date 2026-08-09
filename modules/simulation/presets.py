"""Preset simulation test types (预设集中模拟测试类型).

Each preset is a ready-to-run paper-trading scenario that pins a strategy,
tuned run config, and a suggested universe shape, so the operator can start a
focused test without hand-tuning every field. Presets are the *starting point*
of a run — any field the operator supplies at create time overrides the preset.

Design intent (why these five):

- Every preset uses one of the three executable strategy factories wired in
  ``service.SimulationService.source_factories`` (``signal_fusion``,
  ``spread_reversion_v1``, ``spread_arbitrage_v1``) so it actually runs.
- They span the axes that matter for building trustworthy edge evidence:
  isolate one instrument (deep), spread across many (robustness), a specific
  microstructure edge (reversion / pair arbitrage), and a worst-case fill
  assumption (stress). "集中" = each preset concentrates the test on one
  question instead of mixing everything.
- ``suggested_universe`` holds example instrument ids the operator is expected
  to replace with real market ids / symbols from their own watchlist. The
  fields are placeholders, not live subscriptions.
- ``recommended_days`` is guidance only: honest edge measurement needs a large
  closed-trade sample (see the feedback guardrail, min 20 closed trades), so
  every preset nudges toward a long run rather than a quick look.

The config keys map to ``service.DEFAULT_RUN_CONFIG``:
``position_fraction``, ``mid_penalty_bps``, ``fee_bps``/``fee``,
``feedback_min_closed_trades``, ``feedback_max_weight_delta``.
"""

from __future__ import annotations

from typing import Any

# Each entry: id, localized name/description, strategy_id, config overrides,
# suggested_universe (example placeholder ids), recommended_days, focus tag.
SIMULATION_PRESETS: list[dict[str, Any]] = [
    {
        "id": "single_instrument_deep",
        "name": {"zh": "单标的深度验证", "en": "Single-Instrument Deep Test"},
        "description": {
            "zh": "在一个标的上长期运行信号融合策略，小仓位、隔离其它变量，专注检验策略在这个市场上是否真有 edge。",
            "en": "Run signal fusion on ONE instrument at small size to isolate whether the strategy has real edge there.",
        },
        "strategy_id": "signal_fusion",
        "config": {
            "position_fraction": 0.03,
            "mid_penalty_bps": 10.0,
        },
        "suggested_universe": ["MARKET_ID_1"],
        "recommended_days": 30,
        "focus": "isolation",
    },
    {
        "id": "multi_instrument_robust",
        "name": {"zh": "多标的稳健性", "en": "Multi-Instrument Robustness"},
        "description": {
            "zh": "同一策略分散到一篮子标的上，检验它是否跨市场稳健，而不是只在个别标的上凑巧盈利。",
            "en": "Spread one strategy across a basket to test cross-market robustness rather than a lucky single market.",
        },
        "strategy_id": "signal_fusion",
        "config": {
            "position_fraction": 0.05,
            "mid_penalty_bps": 10.0,
        },
        "suggested_universe": ["MARKET_ID_1", "MARKET_ID_2", "MARKET_ID_3"],
        "recommended_days": 45,
        "focus": "diversification",
    },
    {
        "id": "spread_reversion_focus",
        "name": {"zh": "价差回归专项", "en": "Spread Reversion Focus"},
        "description": {
            "zh": "专门测试宽价差均值回归策略：只在盘口价差异常、买卖两侧均衡时入场，检验回归假设的真实成交表现。",
            "en": "Test wide-spread mean reversion: enter only on abnormal spread with balanced book, measure real-fill performance.",
        },
        "strategy_id": "spread_reversion_v1",
        "config": {
            "position_fraction": 0.04,
            "mid_penalty_bps": 12.0,
        },
        "suggested_universe": ["MARKET_ID_1"],
        "recommended_days": 30,
        "focus": "microstructure",
    },
    {
        "id": "pair_arbitrage_focus",
        "name": {"zh": "配对套利专项", "en": "Pair Arbitrage Focus"},
        "description": {
            "zh": "在相关配对上运行价差套利，按腿建仓（venue:symbol）。检验配对价差是否稳定可交易，注意配对腿数据要成对可用。",
            "en": "Run pair spread arbitrage on a correlated pair, one signal per leg. Tests whether the pair spread is tradable.",
        },
        "strategy_id": "spread_arbitrage_v1",
        "config": {
            "position_fraction": 0.04,
            "mid_penalty_bps": 12.0,
        },
        "suggested_universe": ["binance:BTCUSDT", "hyperliquid:BTC"],
        "recommended_days": 30,
        "focus": "pair",
    },
    {
        "id": "conservative_stress",
        "name": {"zh": "保守压力测试", "en": "Conservative Stress Test"},
        "description": {
            "zh": "最保守假设：更高的滑点惩罚、更小的仓位。如果策略在这种最坏成交条件下还能盈利，edge 才更可信。",
            "en": "Worst-case assumptions: higher slippage penalty, smaller size. Edge that survives this is more trustworthy.",
        },
        "strategy_id": "signal_fusion",
        "config": {
            "position_fraction": 0.02,
            "mid_penalty_bps": 25.0,
            "fee_bps": 30.0,
        },
        "suggested_universe": ["MARKET_ID_1", "MARKET_ID_2"],
        "recommended_days": 60,
        "focus": "stress",
    },
    {
        "id": "high_conviction_concentrated",
        "name": {"zh": "高信念集中持仓", "en": "High-Conviction Concentrated"},
        "description": {
            "zh": "在单一标的上放大仓位到 8%，检验策略最看好的市场在更高仓位下的盈亏与回撤——集中度的上行/下行同时放大。",
            "en": "Size up to 8% on ONE instrument to test how the strategy's best market behaves at higher conviction — both upside and drawdown scale up.",
        },
        "strategy_id": "signal_fusion",
        "config": {
            "position_fraction": 0.08,
            "mid_penalty_bps": 10.0,
        },
        "suggested_universe": ["MARKET_ID_1"],
        "recommended_days": 30,
        "focus": "conviction",
    },
    {
        "id": "fusion_active_cycle",
        "name": {"zh": "融合高频轮动", "en": "Fusion Active Cycle"},
        "description": {
            "zh": "缩短每标的交易冷却时间，让信号融合在小篮子上更频繁地进出，用于快速累积成交样本、检验高换手下成本是否吞掉 edge。",
            "en": "Shorten the per-instrument cooldown so signal fusion trades in and out more often on a small basket — builds a trade sample fast and tests whether higher turnover lets costs eat the edge.",
        },
        "strategy_id": "signal_fusion",
        "config": {
            "position_fraction": 0.04,
            "mid_penalty_bps": 10.0,
            "cooldown_seconds": 15.0,
        },
        "suggested_universe": ["MARKET_ID_1", "MARKET_ID_2"],
        "recommended_days": 21,
        "focus": "turnover",
    },
    {
        "id": "reversion_sensitive_scan",
        "name": {"zh": "价差回归灵敏扫描", "en": "Reversion Sensitive Scan"},
        "description": {
            "zh": "放宽价差与深度门槛，在一篮子标的上捕捉更温和的均值回归机会，交易样本更大——用于检验回归 edge 在更宽入场条件下是否仍成立。",
            "en": "Loosen the spread and depth gates to capture milder mean-reversion entries across a basket for a larger sample — tests whether the reversion edge survives a wider entry filter.",
        },
        "strategy_id": "spread_reversion_v1",
        "config": {
            "position_fraction": 0.03,
            "mid_penalty_bps": 12.0,
            "spread_threshold_bps": 80.0,
            "min_depth_ratio": 0.4,
            "min_size": 5.0,
        },
        "suggested_universe": ["MARKET_ID_1", "MARKET_ID_2", "MARKET_ID_3"],
        "recommended_days": 30,
        "focus": "microstructure",
    },
    {
        "id": "pair_arbitrage_sensitive",
        "name": {"zh": "配对套利灵敏版", "en": "Pair Arbitrage Sensitive"},
        "description": {
            "zh": "降低净 edge 与价差门槛，捕捉更多套利入场。注意：universe 填的是配对快照的 pair_id（不是单腿），运行时按 pair_id 订阅 PAIR_SNAPSHOT，成交仍按两条腿 venue:symbol 分别建仓。",
            "en": "Lower the net-edge and spread thresholds to admit more pair entries. Note: the universe is the PAIR_SNAPSHOT pair_id (not a single leg) — the run subscribes by pair_id and still books one position per leg (venue:symbol).",
        },
        "strategy_id": "spread_arbitrage_v1",
        "config": {
            "position_fraction": 0.04,
            "mid_penalty_bps": 12.0,
            "min_net_edge_bps": 6.0,
            "min_abs_spread_bps": 4.0,
            "min_confidence": 0.5,
        },
        "suggested_universe": ["eth_binance_hyperliquid"],
        "recommended_days": 30,
        "focus": "pair",
    },
]

_PRESET_BY_ID = {p["id"]: p for p in SIMULATION_PRESETS}


def list_presets() -> list[dict[str, Any]]:
    """Return the preset catalog (safe copies)."""
    return [dict(p) for p in SIMULATION_PRESETS]


def get_preset(preset_id: str) -> dict[str, Any] | None:
    preset = _PRESET_BY_ID.get(preset_id)
    return dict(preset) if preset else None


def resolve_run_params(
    preset_id: str,
    *,
    name: str | None = None,
    universe: list[str] | None = None,
    initial_capital: float | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn a preset + optional operator overrides into create_run kwargs.

    Operator-supplied values always win over the preset. Raises KeyError for an
    unknown preset id so the API can map it to a 404.
    """
    preset = _PRESET_BY_ID.get(preset_id)
    if preset is None:
        raise KeyError(preset_id)

    merged_config = dict(preset.get("config", {}))
    if config_overrides:
        merged_config.update(config_overrides)

    resolved_universe = universe if universe else list(preset.get("suggested_universe", []))
    default_name = preset["name"]["zh"]

    return {
        "name": name or default_name,
        "strategy_id": preset["strategy_id"],
        "universe": resolved_universe,
        "initial_capital": float(initial_capital) if initial_capital else 10000.0,
        "config": merged_config,
        "preset_id": preset_id,
    }
