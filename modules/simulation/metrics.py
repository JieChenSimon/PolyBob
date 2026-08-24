"""Per-run performance metrics and the strategy feedback loop.

Metric definitions (all computed from persisted rows, never in-memory state):

- ``total_return``       ``latest_equity / initial_capital - 1``. Latest equity
                         comes from the newest ``sim_equity_points`` row; when
                         no point exists yet it falls back to
                         ``cash + sum(size * avg_price)`` (positions marked at
                         their own entry price — a neutral, not optimistic,
                         approximation).
- ``win_rate``           wins / closed trades, where a closed trade is a
                         ``sim_trades`` row with non-NULL ``realized_pnl`` and
                         a win is ``realized_pnl > 0``. ``None`` (not 0) when
                         there are no closed trades — an empty sample is not a
                         0% win rate.
- ``profit_factor``      gross profit / gross loss over closed trades; ``None``
                         when there are no losing trades (undefined, not
                         infinite edge).
- ``max_drawdown``       max over the equity curve of ``(peak - equity)/peak``.
- ``sharpe``             mean/std of simple per-point equity returns, annualized
                         by ``sqrt(seconds_per_year / mean_interval_seconds)``
                         where the interval is measured from the equity-point
                         timestamps themselves. ``None`` with fewer than three
                         points or zero variance. This is an equity-curve
                         Sharpe with rf=0; treat it as a comparative statistic,
                         not an investable claim.
- ``avg_win`` / ``avg_loss``  mean realized pnl of winning / losing closed trades.
- ``per_instrument``     realized pnl, closed-trade count and win rate per
                         instrument.

Feedback loop & overfitting guardrails
--------------------------------------
``apply_feedback`` pushes realized per-signal outcomes into SignalFusion's
existing ``update_performance``/weight mechanism (persisted via
StrategyStateStore). It is intentionally **not** applied automatically by
default, because a feedback loop that retunes weights on its own paper results
is the textbook way to overfit: with few trades the "win rate" is mostly
noise, and chasing it turns the strategy into a fit of its own recent luck.

Guardrails enforced here:

1. Only CLOSED trades (realized_pnl set) feed the loop — open positions carry
   no outcome yet.
2. A minimum sample of newly closed trades (default 20) is required per
   application; below that the call is a no-op with an explicit reason.
3. Each application caps the per-signal weight change to ``max_weight_delta``
   (default 0.05) regardless of what the underlying mechanism computed, then
   renormalizes weights to sum to 1. (SignalFusion's own ``_update_weights``
   renormalizes but does NOT cap — inspected, so the cap lives here.)
4. Every application appends a ``sim.feedback.applied`` audit event with
   before/after weights, and trades are consumed at most once (a watermark
   trade id is stored in the run config).
5. Auto-apply is opt-in via the run config flag ``auto_feedback``; the API
   endpoint is the default trigger.

Outcome attribution: realized pnl of a closing trade is attributed to the
contributing sub-signal names recorded on the most recent *opening* trade of
the same instrument (avg-price books make exact lot attribution impossible;
this approximation is documented rather than hidden).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from libs.db.simulation_store import SimulationStore
from libs.quant.return_target import evaluate_return_target

_SECONDS_PER_YEAR = 365.0 * 24 * 3600

DEFAULT_MIN_CLOSED_TRADES = 20
DEFAULT_MAX_WEIGHT_DELTA = 0.05


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def compute_run_metrics(store: SimulationStore, run_id: str) -> dict[str, Any]:
    """Compute honest per-run metrics from persisted trades and equity points."""
    run = store.get_run(run_id)
    if run is None:
        raise KeyError(run_id)

    trades = store.list_trades(run_id)
    settlements = store.list_settlements(run_id)
    quote_observations = store.list_quote_observations(run_id)
    instrument_pnl_points = store.list_instrument_pnl_points(run_id)
    points = store.list_equity_points(run_id)
    quote_quality_counts: dict[str, int] = {}
    synthetic_quote_count = 0
    for trade in trades:
        quality = trade.quote_quality or "unknown"
        quote_quality_counts[quality] = quote_quality_counts.get(quality, 0) + 1
        if trade.quote_source.startswith("synthetic"):
            synthetic_quote_count += 1
    observation_quality_counts: dict[str, int] = {}
    for observation in quote_observations:
        quality = observation.quality or "unknown"
        observation_quality_counts[quality] = observation_quality_counts.get(quality, 0) + 1
    latest_quote = max(quote_observations, key=lambda item: item.observed_at, default=None)
    closed = [t for t in trades if t.realized_pnl is not None]
    settlement_pnls = [float(item.realized_pnl) for item in settlements]
    closed_pnls = [float(t.realized_pnl) for t in closed] + settlement_pnls
    wins = [pnl for pnl in closed_pnls if pnl > 0]
    losses = [pnl for pnl in closed_pnls if pnl < 0]

    if points:
        latest_equity = points[-1].equity
    else:
        positions = store.list_positions(run_id)
        latest_equity = run.cash + sum(p.size * p.avg_price for p in positions)

    # Without at least one persisted equity observation there is no measured
    # equity path.  Cash plus entry-price positions is only a diagnostic
    # snapshot and must not be presented as a verified 0% return.
    total_return = (
        latest_equity / run.initial_capital - 1.0
        if points and run.initial_capital > 0
        else None
    )

    win_rate = len(wins) / len(closed_pnls) if closed_pnls else None
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    avg_win = gross_profit / len(wins) if wins else None
    avg_loss = -gross_loss / len(losses) if losses else None

    # A curve containing a point that was valued without a fresh mark cannot be
    # summarised. Reporting a return, a drawdown and a Sharpe off it would give
    # three precise numbers describing an equity path that partly consists of
    # entry prices — and would understate volatility, which flatters Sharpe in
    # exactly the direction that makes a strategy look tradable.
    curve_degraded = any(getattr(point, "degraded", False) for point in points)

    max_drawdown = 0.0 if points else None
    peak = None
    for point in points:
        if peak is None or point.equity > peak:
            peak = point.equity
        if peak and peak > 0 and max_drawdown is not None:
            drawdown = (peak - point.equity) / peak
            max_drawdown = max(max_drawdown, drawdown)

    sharpe = _equity_sharpe(points)
    if curve_degraded:
        total_return = None
        max_drawdown = None
        sharpe = None

    per_instrument: dict[str, dict[str, Any]] = {}
    for trade in trades:
        bucket = per_instrument.setdefault(
            trade.instrument_id,
            {
                "trade_count": 0, "closed_trades": 0, "wins": 0,
                "realized_pnl": 0.0, "total_fees": 0.0, "total_slippage": 0.0,
            },
        )
        bucket["trade_count"] += 1
        bucket["total_fees"] += float(trade.fee)
        bucket["total_slippage"] += float(trade.slippage) * float(trade.size)
        if trade.realized_pnl is not None:
            bucket["closed_trades"] += 1
            bucket["realized_pnl"] += trade.realized_pnl
            if trade.realized_pnl > 0:
                bucket["wins"] += 1
    for settlement in settlements:
        bucket = per_instrument.setdefault(
            settlement.instrument_id,
            {
                "trade_count": 0, "closed_trades": 0, "wins": 0,
                "realized_pnl": 0.0, "total_fees": 0.0, "total_slippage": 0.0,
            },
        )
        bucket["closed_trades"] += 1
        bucket["realized_pnl"] += settlement.realized_pnl
        if settlement.realized_pnl > 0:
            bucket["wins"] += 1
    for bucket in per_instrument.values():
        bucket["win_rate"] = (
            bucket["wins"] / bucket["closed_trades"] if bucket["closed_trades"] else None
        )
        bucket.pop("wins")
        bucket["total_explicit_cost"] = bucket["total_fees"] + bucket["total_slippage"]

    for funding in store.list_funding(run_id):
        funding_instrument = str(funding["instrument_id"])
        bucket = per_instrument.setdefault(
            funding_instrument,
            {
                "trade_count": 0, "closed_trades": 0, "wins": 0,
                "realized_pnl": 0.0, "total_fees": 0.0, "total_slippage": 0.0,
                "total_explicit_cost": 0.0,
            },
        )
        bucket["funding_pnl"] = bucket.get("funding_pnl", 0.0) + float(funding["pnl"])
    for bucket in per_instrument.values():
        bucket.setdefault("funding_pnl", 0.0)

    return {
        "total_return": total_return,
        "equity": latest_equity,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "equity_curve_degraded": curve_degraded,
        "sharpe": sharpe,
        "trade_count": len(trades),
        "closed_trade_count": len(closed_pnls),
        "settlement_count": len(settlements),
        "realized_pnl": sum(closed_pnls),
        "total_fees": sum(t.fee for t in trades),
        # SimulationStore records slippage as a per-unit price difference;
        # convert it to cash before aggregating with fees.
        "total_slippage": sum(t.slippage * t.size for t in trades),
        "total_explicit_cost": sum(t.fee + t.slippage * t.size for t in trades),
        "execution_evidence": {
            "trade_count": len(trades),
            "quote_quality_counts": quote_quality_counts,
            "full_depth_trade_count": quote_quality_counts.get("full_depth", 0),
            "missing_depth_trade_count": quote_quality_counts.get("missing_depth", 0),
            "synthetic_quote_trade_count": synthetic_quote_count,
            "quote_observation_count": len(quote_observations),
            "quote_observation_quality_counts": observation_quality_counts,
            "trade_quote_observation_link_count": sum(
                1 for trade in trades if trade.quote_observation_id
            ),
            "latest_observed_at": latest_quote.observed_at if latest_quote else None,
            "latest_observed_instrument": latest_quote.instrument_id if latest_quote else None,
            "latest_quote_quality": latest_quote.quality if latest_quote else "unknown",
        },
        "instrument_pnl_curve": [point.to_dict() for point in instrument_pnl_points],
        "funding_pnl": store.total_funding(run_id),
        # The user's annual/monthly target is a separate, fail-closed gate:
        # short paper runs remain UNKNOWN rather than being treated as a pass.
        "return_target": evaluate_return_target(points).to_dict(),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "per_instrument": per_instrument,
    }


def summarize_feature_attribution(store: SimulationStore, run_id: str) -> dict[str, Any]:
    """Summarize stored feature snapshots without making a causal claim.

    ``model_contribution`` is the weighted signal-score term recorded at the
    decision. ``associated_realized_pnl`` is a descriptive join to the same
    fill's realized result. It is not a counterfactual PnL decomposition and
    must stay visibly separate in API/UI consumers.
    """
    rows = store.list_feature_attributions(run_id)
    trades = {trade.trade_id: trade for trade in store.list_trades(run_id)}
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = grouped.setdefault(row.feature_name, {
            "feature_name": row.feature_name,
            "model_weight_sum": 0.0,
            "model_weight_count": 0,
            "model_contribution": 0.0,
            "associated_realized_pnl": 0.0,
            "associated_closed_fill_count": 0,
            "fill_ids": set(),
            "instrument_ids": set(),
            "methods": set(),
            "quality": set(),
        })
        if row.model_weight is not None:
            bucket["model_weight_sum"] += row.model_weight
            bucket["model_weight_count"] += 1
        if row.weighted_contribution is not None:
            bucket["model_contribution"] += row.weighted_contribution
        if row.trade_id is not None:
            bucket["fill_ids"].add(row.trade_id)
            trade = trades.get(row.trade_id)
            if trade is not None and trade.realized_pnl is not None:
                # One feature appears once per fill, so this adds each fill's
                # realized outcome exactly once per feature.
                bucket["associated_realized_pnl"] += float(trade.realized_pnl)
                bucket["associated_closed_fill_count"] += 1
        bucket["instrument_ids"].add(row.instrument_id)
        bucket["methods"].add(row.method)
        bucket["quality"].add(row.quality)

    output: list[dict[str, Any]] = []
    for bucket in grouped.values():
        closed = bucket["associated_closed_fill_count"]
        output.append({
            "feature_name": bucket["feature_name"],
            "average_model_weight": (
                bucket["model_weight_sum"] / bucket["model_weight_count"]
                if bucket["model_weight_count"] else None
            ),
            "model_contribution": bucket["model_contribution"] or None,
            "associated_realized_pnl": (
                bucket["associated_realized_pnl"] if closed else None
            ),
            "fill_count": len(bucket["fill_ids"]),
            "closed_fill_count": closed,
            "instrument_count": len(bucket["instrument_ids"]),
            "methods": sorted(bucket["methods"]),
            "quality": sorted(bucket["quality"]),
            "attribution_status": "outcome_association_available" if closed else "descriptive_only",
            "causal_claim": False,
        })
    output.sort(key=lambda item: item["feature_name"])
    return {
        "status": "available" if rows else "UNKNOWN",
        "causal_claim": False,
        "interpretation": "descriptive_model_contribution_and_fill_outcome_association",
        "row_count": len(rows),
        "features": output,
    }


def downsample_instrument_pnl_curves(points: list, max_points: int = 500) -> dict[str, list[dict[str, Any]]]:
    """Return bounded per-instrument PnL curves while preserving endpoints."""
    grouped: dict[str, list] = {}
    for point in points:
        grouped.setdefault(point.instrument_id, []).append(point)
    result: dict[str, list[dict[str, Any]]] = {}
    for instrument, values in grouped.items():
        values = sorted(values, key=lambda item: item.ts)
        if len(values) <= max_points:
            sampled = values
        else:
            stride = max(1, (len(values) - 2) // max(1, max_points - 2))
            sampled = [values[0], *values[1:-1:stride], values[-1]][:max_points - 1] + [values[-1]]
        result[instrument] = [value.to_dict() for value in sampled]
    return result


def _equity_sharpe(points: list) -> float | None:
    if len(points) < 3:
        return None
    returns: list[float] = []
    timestamps: list[datetime] = []
    for point in points:
        ts = _parse_ts(point.ts)
        if ts is not None:
            timestamps.append(ts)
    for previous, current in zip(points, points[1:]):
        if previous.equity > 0:
            returns.append(current.equity / previous.equity - 1.0)
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std <= 0:
        return None
    if len(timestamps) >= 2:
        span = (timestamps[-1] - timestamps[0]).total_seconds()
        mean_interval = span / (len(timestamps) - 1) if span > 0 else 0.0
    else:
        mean_interval = 0.0
    if mean_interval <= 0:
        return None
    periods_per_year = _SECONDS_PER_YEAR / mean_interval
    return (mean / std) * math.sqrt(periods_per_year)


def apply_feedback(
    store: SimulationStore,
    run_id: str,
    fusion: Any,
    *,
    min_closed_trades: int = DEFAULT_MIN_CLOSED_TRADES,
    max_weight_delta: float = DEFAULT_MAX_WEIGHT_DELTA,
    audit_db_path: Any = None,
) -> dict[str, Any]:
    """Feed realized closed-trade outcomes into a SignalFusion instance.

    See the module docstring for the guardrail design. Returns a payload with
    ``applied`` plus before/after weights and deltas when the update ran.
    """
    run = store.get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    if fusion is None or not hasattr(fusion, "update_performance"):
        return {
            "applied": False,
            "reason": "strategy does not support weight feedback",
            "weight_deltas": {},
        }

    watermark = int(run.config.get("feedback_last_trade_id", 0) or 0)
    trades = store.list_trades(run_id)

    # Attribution pass: remember the signal names of the latest opening trade
    # per instrument, then pair them with subsequent closing trades.
    entry_signals: dict[str, list[str]] = {}
    outcomes: list[tuple[int, list[str], float]] = []
    for trade in trades:
        names = trade.signal_meta.get("signals") or []
        if trade.realized_pnl is None:
            if names:
                entry_signals[trade.instrument_id] = list(names)
            continue
        attributed = entry_signals.get(trade.instrument_id) or list(names)
        if trade.trade_id > watermark:
            outcomes.append((trade.trade_id, attributed, float(trade.realized_pnl)))

    if len(outcomes) < min_closed_trades:
        return {
            "applied": False,
            "reason": (
                f"insufficient closed trades since last feedback: "
                f"{len(outcomes)} < {min_closed_trades}"
            ),
            "closed_trades_available": len(outcomes),
            "min_closed_trades": min_closed_trades,
            "weight_deltas": {},
        }

    weights_before = dict(fusion.weights)
    for _, names, realized in outcomes:
        for name in names:
            if name in fusion.weights:
                fusion.update_performance(name, realized)

    # Cap the per-application weight change. SignalFusion's own update
    # renormalizes but does not cap (inspected), so the cap lives here: the
    # raw delta vector (which sums to ~0 since both weight sets are
    # normalized) is scaled down uniformly until its largest component fits
    # inside max_weight_delta — weights stay normalized and every per-signal
    # change is bounded.
    raw_deltas = {
        name: float(fusion.weights.get(name, before)) - before
        for name, before in weights_before.items()
    }
    largest = max((abs(delta) for delta in raw_deltas.values()), default=0.0)
    scale = 1.0 if largest <= max_weight_delta else max_weight_delta / largest
    capped = {
        name: weights_before[name] + raw_deltas[name] * scale for name in weights_before
    }
    fusion.weights = capped
    if hasattr(fusion, "save_state"):
        fusion.save_state()

    weight_deltas = {
        name: capped[name] - weights_before[name] for name in weights_before
    }
    new_watermark = max(trade_id for trade_id, _, _ in outcomes)
    config = dict(run.config)
    config["feedback_last_trade_id"] = new_watermark
    store.update_run(run_id, config=config)

    from libs.db import fact_store

    fact_store.append_audit_event(
        "sim.feedback.applied",
        actor="simulation",
        subject_type="sim_run",
        subject_id=run_id,
        payload={
            "closed_trades_used": len(outcomes),
            "weights_before": weights_before,
            "weights_after": capped,
            "weight_deltas": weight_deltas,
            "max_weight_delta": max_weight_delta,
        },
        db_path=audit_db_path or store.db_path,
    )

    return {
        "applied": True,
        "closed_trades_used": len(outcomes),
        "weights_before": weights_before,
        "weights_after": capped,
        "weight_deltas": weight_deltas,
    }


__all__ = [
    "DEFAULT_MAX_WEIGHT_DELTA",
    "DEFAULT_MIN_CLOSED_TRADES",
    "apply_feedback",
    "compute_run_metrics",
]
