"""Simulation (paper-trading) service.

Runs one or more long-lived paper-trading "runs", each binding a strategy
signal source (see :mod:`modules.simulation.sources`) to a universe of
instruments, fed by the live event bus (FEATURE_SNAPSHOT / PAIR_SNAPSHOT —
lossy topics, which is acceptable for simulation). Every fill, position and
equity point is persisted via :class:`libs.db.simulation_store.SimulationStore`
so metrics are computed from durable data and runs survive restarts.

Conservative fill model — every assumption, explicitly
------------------------------------------------------
Paper results must not overstate edge, so fills are deliberately pessimistic:

1. **Fills cross the spread.** Buys fill at the ask, sells at the bid — never
   at mid, never inside the spread, no maker fills, no queue-position credit.
2. **No BBO, pay a penalty.** When only a mid price is available the fill is
   ``mid * (1 ± mid_penalty_bps/1e4)`` (default 10 bps against the trade).
3. **Impact slippage on top.** When top-of-book depth is known, the existing
   sqrt market-impact model (:class:`libs.backtest.execution.SlippageModel`)
   worsens the price by ``impact_coefficient * sqrt(size/depth)`` of the base
   price. Unknown depth ⇒ no impact credit either way (spread + penalty still
   apply).
4. **Taker fee on every fill.** ``fee_bps`` (default 20 bps) of notional is
   charged per trade and folded into the effective price, so entry costs are
   inside ``avg_price`` and exit costs inside ``realized_pnl`` — win rate can
   never ignore costs.
5. **No fill on bad or stale data.** A signal with a crossed/incomplete book
   and no mid, a missing snapshot timestamp, or data older than
   ``max_staleness_seconds`` (default 30) is dropped. Unknown != safe.
6. **Risk-gated sizing.** Position size is a configurable fraction of current
   equity (``position_fraction``, default 5%), and every proposed trade passes
   through :class:`PortfolioRiskChecker` with positions loaded from the run's
   own book; rejected trades are counted, not retried.
7. **No partial-fill optimism.** A trade either fills fully at the modeled
   price or not at all; there is no "lucky partial at a better level".

Accounting is signed avg-price: opening/extending updates the average
effective price; reducing/closing realizes ``(exit_eff - avg) * closed_qty``
(sign-adjusted for shorts). Cash moves by ``-signed_qty * effective_price``.
Equity = cash + Σ size × last known mark (mid), persisted every
``equity_interval_minutes`` (default 5) and on every trade.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import structlog

from libs.backtest.execution import SlippageModel
from libs.db import fact_store
from libs.db.simulation_store import SimRunRecord, SimulationStore
from libs.db.strategy_state import StrategyStateStore
from libs.db.execution_ledger import ExecutionLedger, FillCommand
from libs.events import Topics, get_event_bus
from libs.research.registry import ExperimentRegistry
from modules.risk_manager.risk_checker import PortfolioRiskChecker
from modules.simulation import metrics as sim_metrics
from modules.simulation.sources import (
    FusionSignalSource,
    MomentumSignalSource,
    PairSpreadSignalSource,
    SignalSource,
    SimSignal,
    SpreadReversionSignalSource,
)

logger = structlog.get_logger()

_EPS = 1e-9


class UnknownRunError(KeyError):
    """Raised when a run_id does not exist."""


class InvalidRunTransitionError(RuntimeError):
    """Raised on an invalid lifecycle transition (API maps this to 409)."""


DEFAULT_RUN_CONFIG: dict[str, Any] = {
    "position_fraction": 0.05,
    "fee_bps": 20.0,
    "mid_penalty_bps": 10.0,
    "impact_coefficient": 0.1,
    "max_staleness_seconds": 30.0,
    "cooldown_seconds": 60.0,
    "min_trade_notional": 10.0,
    # Avoid paying spread/impact to resize a position for immaterial price
    # moves. A value of zero preserves the historical per-bar rebalance.
    "min_rebalance_bps": 0.0,
    # Paper Lab supports shorting, but a strategy can explicitly be long-only
    # for venues/instruments where short inventory is not available.
    "allow_short": True,
    # Funding rates must declare the settlement cadence when enabled. Eight
    # hours matches standard perpetual funding; daily research sources override
    # this explicitly instead of silently applying the same rate per snapshot.
    "funding_interval_seconds": 8 * 60 * 60,
    "equity_interval_minutes": 5.0,
    # Feedback guardrails (see modules/simulation/metrics.py docstring).
    "auto_feedback": False,
    "auto_run": False,
    "feedback_min_closed_trades": sim_metrics.DEFAULT_MIN_CLOSED_TRADES,
    "feedback_max_weight_delta": sim_metrics.DEFAULT_MAX_WEIGHT_DELTA,
}


SourceFactory = Callable[[dict[str, Any], Path], SignalSource]


def _default_source_factories() -> dict[str, SourceFactory]:
    def build_fusion(config: dict[str, Any], db_path: Path) -> SignalSource:
        from strategies.signal_fusion import SignalFusion

        return FusionSignalSource(
            SignalFusion(dict(config), state_store=StrategyStateStore(db_path))
        )

    return {
        "signal_fusion": build_fusion,
        "spread_reversion_v1": lambda config, db_path: SpreadReversionSignalSource(config),
        "spread_arbitrage_v1": lambda config, db_path: PairSpreadSignalSource(config),
        "momentum_dualma_v1": lambda config, db_path: MomentumSignalSource(config),
    }


def apply_avg_price_fill(
    size: float, avg_price: float, qty: float, price: float
) -> tuple[float, float, float | None]:
    """Signed avg-price bookkeeping for one fill at effective ``price``.

    Returns ``(new_size, new_avg_price, realized_pnl)`` where realized_pnl is
    ``None`` for pure opens/extends. A fill that flips through zero realizes
    pnl on the closed part and opens the remainder at the fill price.
    """
    if abs(size) < _EPS or size * qty > 0:
        new_size = size + qty
        new_avg = (avg_price * abs(size) + price * abs(qty)) / abs(new_size)
        return new_size, new_avg, None

    closed = min(abs(qty), abs(size))
    direction = 1.0 if size > 0 else -1.0
    realized = (price - avg_price) * closed * direction
    new_size = size + qty
    if abs(new_size) < _EPS:
        return 0.0, 0.0, realized
    if abs(qty) > abs(size):  # flipped through zero
        return new_size, price, realized
    return new_size, avg_price, realized


class _ActiveRun:
    """In-memory companion of a persisted run (source binding, marks, locks)."""

    __slots__ = ("record", "source", "marks", "mark_times", "last_trade_at", "lock",
                 "last_equity_at", "last_feedback_at", "risk_rejections",
                 "risk_rejection_events")

    def __init__(self, record: SimRunRecord, source: SignalSource):
        self.record = record
        self.source = source
        self.marks: dict[str, float] = {}
        # When each mark was last observed. Without it a mark can be arbitrarily
        # old and still be used to value a position at face value.
        self.mark_times: dict[str, datetime] = {}
        self.last_trade_at: dict[str, datetime] = {}
        self.lock = asyncio.Lock()
        self.last_equity_at: datetime | None = None
        self.last_feedback_at: datetime | None = None
        self.risk_rejections = 0
        # Diagnostic-only evidence.  These events do not alter the risk
        # decision; they make a rejected entry/settlement explainable.
        self.risk_rejection_events: list[dict[str, Any]] = []

    def config_value(self, key: str) -> Any:
        return self.record.config.get(key, DEFAULT_RUN_CONFIG.get(key))


class SimulationService:
    """Manages concurrent paper-trading runs fed by live feature snapshots."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        risk_checker: PortfolioRiskChecker | None = None,
        source_factories: dict[str, SourceFactory] | None = None,
        equity_poll_seconds: float = 30.0,
        registry: ExperimentRegistry | None = None,
        ledger: ExecutionLedger | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.store = SimulationStore(db_path)
        self.event_bus = get_event_bus()
        self.risk_checker = risk_checker or PortfolioRiskChecker(
            audit_db_path=self.store.db_path
        )
        # Experiment registry (P8b): every run's params + versions are logged at
        # creation and its metrics at finalize, so a paper result is reproducible
        # and queryable rather than a transient in the sim store only.
        self.registry = registry or ExperimentRegistry(self.store.db_path)
        self.ledger = ledger or ExecutionLedger(self.store.db_path)
        self.source_factories = source_factories or _default_source_factories()
        self.equity_poll_seconds = equity_poll_seconds
        self._active: dict[str, _ActiveRun] = {}
        # Snapshot routing index: a live feed should not scan every run when
        # only a small subset subscribes to this instrument/topic.
        self._active_routes: dict[tuple[str, str], set[str]] = {}
        self._running = False
        self._equity_task: asyncio.Task | None = None
        self._auto_run = False
        self._auto_run_task: asyncio.Task | None = None
        # Production uses wall-clock time. Historical replay injects the event
        # clock so the exact same stale-data, cooldown and equity logic is used
        # without treating every historical signal as years old.
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    # ------------------------------------------------------------- lifecycle

    async def start(self, *, auto_run: bool = False) -> None:
        logger.info("starting_simulation_service")
        self._running = True
        await self.event_bus.subscribe(Topics.FEATURE_SNAPSHOT, self._on_feature_snapshot)
        await self.event_bus.subscribe(Topics.PAIR_SNAPSHOT, self._on_pair_snapshot)
        self._equity_task = asyncio.create_task(self._equity_loop())
        await self.set_auto_run(auto_run)

    async def stop(self) -> None:
        logger.info("stopping_simulation_service")
        self._running = False
        if self._equity_task is not None:
            self._equity_task.cancel()
            try:
                await self._equity_task
            except asyncio.CancelledError:
                pass
            self._equity_task = None
        if self._auto_run_task is not None:
            self._auto_run_task.cancel()
            try:
                await self._auto_run_task
            except asyncio.CancelledError:
                pass
            self._auto_run_task = None
        await self.event_bus.unsubscribe(Topics.FEATURE_SNAPSHOT, self._on_feature_snapshot)
        await self.event_bus.unsubscribe(Topics.PAIR_SNAPSHOT, self._on_pair_snapshot)

    async def set_auto_run(self, enabled: bool) -> None:
        """Enable the bounded Paper Lab runner.

        Only runs explicitly created with ``config.auto_run`` are eligible.
        The runner starts paused runs; it never creates a run, changes a
        strategy outside the simulation service, or submits an order.
        """
        self._auto_run = bool(enabled)
        if not self._running:
            return
        if enabled and self._auto_run_task is None:
            self._auto_run_task = asyncio.create_task(self._auto_run_loop())
        elif not enabled and self._auto_run_task is not None:
            self._auto_run_task.cancel()
            try:
                await self._auto_run_task
            except asyncio.CancelledError:
                pass
            self._auto_run_task = None

    async def _auto_run_loop(self) -> None:
        while self._running and self._auto_run:
            try:
                for active in list(self._active.values()):
                    if active.record.status == "paused" and bool(active.config_value("auto_run")):
                        await self.start_run(active.record.run_id)
                await asyncio.sleep(30.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("sim_auto_run_loop_error", error=str(exc), exc_info=True)
                await asyncio.sleep(30.0)

    async def restore_state(self) -> None:
        """Reload non-stopped runs from SQLite and resume their bindings."""
        records = await asyncio.to_thread(self.store.list_runs)
        restored = 0
        for record in records:
            if record.status not in ("running", "paused"):
                continue
            if record.run_id in self._active:
                continue
            try:
                active = self._bind(record)
                self._active[record.run_id] = active
                self._index_active(active)
                restored += 1
            except Exception as exc:
                logger.warning(
                    "sim_run_restore_failed",
                    run_id=record.run_id,
                    error=str(exc) or exc.__class__.__name__,
                )
        if restored:
            logger.info("sim_runs_restored", count=restored)

    def _bind(self, record: SimRunRecord) -> _ActiveRun:
        factory = self.source_factories.get(record.strategy_id)
        if factory is None:
            raise ValueError(f"No simulation source for strategy: {record.strategy_id}")
        return _ActiveRun(record, factory(dict(record.config), self.store.db_path))

    def _index_active(self, active: _ActiveRun) -> None:
        for topic in getattr(active.source, "topics", ()):
            for instrument in active.record.universe:
                self._active_routes.setdefault((topic, str(instrument)), set()).add(active.record.run_id)

    def _unindex_active(self, active: _ActiveRun) -> None:
        for topic in getattr(active.source, "topics", ()):
            for instrument in active.record.universe:
                key = (topic, str(instrument))
                run_ids = self._active_routes.get(key)
                if run_ids is None:
                    continue
                run_ids.discard(active.record.run_id)
                if not run_ids:
                    self._active_routes.pop(key, None)

    # ------------------------------------------------------------ run admin

    async def create_run(
        self,
        *,
        name: str,
        strategy_id: str,
        universe: list[str],
        initial_capital: float,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if strategy_id not in self.source_factories:
            raise ValueError(
                f"Unknown simulation strategy: {strategy_id}. "
                f"Supported: {sorted(self.source_factories)}"
            )
        if not universe:
            raise ValueError("universe must contain at least one instrument")
        if not initial_capital or float(initial_capital) <= 0:
            raise ValueError("initial_capital must be positive")

        merged_config = dict(DEFAULT_RUN_CONFIG)
        merged_config.update(config or {})
        record = SimRunRecord(
            run_id=f"sim_{uuid.uuid4().hex[:10]}",
            name=name,
            strategy_id=strategy_id,
            universe=[str(item) for item in universe],
            initial_capital=float(initial_capital),
            cash=float(initial_capital),
            status="paused",
            config=merged_config,
            created_at=datetime.now(UTC).isoformat(),
        )
        active = self._bind(record)
        await asyncio.to_thread(self.store.save_run, record)
        await asyncio.to_thread(
            self.ledger.register_account,
            f"paper:{record.run_id}", initial_cash=record.initial_capital,
        )
        self._active[record.run_id] = active
        self._index_active(active)
        await self._audit("sim.run.created", record.run_id, {
            "strategy_id": strategy_id,
            "universe": record.universe,
            "initial_capital": record.initial_capital,
        })
        await self._log_experiment(record, phase="created")
        return record.to_dict()

    async def start_run(self, run_id: str) -> dict[str, Any]:
        return await self._transition(run_id, "running", allowed_from=("paused",))

    async def pause_run(self, run_id: str) -> dict[str, Any]:
        return await self._transition(run_id, "paused", allowed_from=("running",))

    async def stop_run(self, run_id: str) -> dict[str, Any]:
        result = await self._transition(
            run_id, "stopped", allowed_from=("running", "paused")
        )
        active = self._active.pop(run_id, None)
        if active is not None:
            self._unindex_active(active)
            await self._record_equity(active)
        record = active.record if active else await asyncio.to_thread(self.store.get_run, run_id)
        if record is not None:
            await self._log_experiment(record, phase="final")
        return result

    async def _transition(
        self, run_id: str, status: str, *, allowed_from: tuple[str, ...]
    ) -> dict[str, Any]:
        active = self._active.get(run_id)
        record = active.record if active else await asyncio.to_thread(self.store.get_run, run_id)
        if record is None:
            raise UnknownRunError(run_id)
        if record.status not in allowed_from:
            raise InvalidRunTransitionError(
                f"cannot move run {run_id} from '{record.status}' to '{status}'"
            )
        await asyncio.to_thread(self.store.update_run, run_id, status=status)
        updated = await asyncio.to_thread(self.store.get_run, run_id)
        if active is not None:
            active.record = updated
        elif status in ("running", "paused"):
            self._active[run_id] = self._bind(updated)
            self._index_active(self._active[run_id])
        await self._audit(f"sim.run.{status}", run_id, {"from": record.status})
        return updated.to_dict()

    def get_run_record(self, run_id: str) -> SimRunRecord | None:
        active = self._active.get(run_id)
        if active is not None:
            return active.record
        return self.store.get_run(run_id)

    # -------------------------------------------------------------- feedback

    async def apply_feedback(self, run_id: str) -> dict[str, Any]:
        active = self._active.get(run_id)
        record = active.record if active else await asyncio.to_thread(self.store.get_run, run_id)
        if record is None:
            raise UnknownRunError(run_id)
        fusion = getattr(active.source, "fusion", None) if active else None
        result = await asyncio.to_thread(
            sim_metrics.apply_feedback,
            self.store,
            run_id,
            fusion,
            min_closed_trades=int(
                record.config.get(
                    "feedback_min_closed_trades", sim_metrics.DEFAULT_MIN_CLOSED_TRADES
                )
            ),
            max_weight_delta=float(
                record.config.get(
                    "feedback_max_weight_delta", sim_metrics.DEFAULT_MAX_WEIGHT_DELTA
                )
            ),
        )
        if active is not None:
            refreshed = await asyncio.to_thread(self.store.get_run, run_id)
            if refreshed is not None:
                active.record = refreshed
        return result

    # ------------------------------------------------------------- snapshots

    async def _on_feature_snapshot(self, snapshot: dict) -> None:
        await self._dispatch(Topics.FEATURE_SNAPSHOT, snapshot)

    async def _on_pair_snapshot(self, snapshot: dict) -> None:
        await self._dispatch(Topics.PAIR_SNAPSHOT, snapshot)

    async def _dispatch(self, topic: str, snapshot: Any) -> None:
        # Run status (not the service flag) gates trading: stopped/paused runs
        # ignore snapshots, and unsubscribing at stop() severs the feed.
        if not isinstance(snapshot, dict):
            return
        key = snapshot.get("market_id") or snapshot.get("pair_id")
        if key is None:
            return
        run_ids = self._active_routes.get((topic, str(key)), ())
        for run_id in tuple(run_ids):
            active = self._active.get(run_id)
            if active is None:
                continue
            if active.record.status != "running":
                continue
            # Marks follow every snapshot, not only the ones that happen to
            # produce a signal. They used to be written inside _process_signal,
            # so between two signals a position was valued at its own entry
            # price — unrealised P&L was structurally zero and the equity curve
            # moved only when cash did. Every return, drawdown and Sharpe this
            # project reports is computed from that curve.
            self._update_mark(active, snapshot)
            if bool(active.config_value("funding_enabled")) and snapshot.get("funding_rate") is None:
                logger.warning(
                    "sim_funding_missing",
                    run_id=active.record.run_id,
                    instrument=str(key),
                )
                continue
            await self._apply_funding(active, snapshot)
            try:
                signals = await active.source.on_snapshot(topic, snapshot)
            except Exception as exc:
                logger.error(
                    "sim_source_error",
                    run_id=active.record.run_id,
                    error=str(exc),
                    exc_info=True,
                )
                continue
            for signal in signals:
                await self._process_signal(active, signal)

    # ----------------------------------------------------------- trade logic

    def _age_seconds(self, timestamp: datetime | None) -> float | None:
        if timestamp is None:
            return None
        observed = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)
        return (self._now() - observed).total_seconds()

    def _fill_price(
        self, active: _ActiveRun, signal: SimSignal, size: float
    ) -> tuple[float, float] | None:
        """Return (execution_price, slippage_vs_reference) or None for no fill.

        Conservative by construction: cross the spread at BBO, otherwise mid
        plus a penalty; sqrt impact on top when depth is known.
        """
        buying = signal.side == "buy"
        book_ok = (
            signal.bid is not None
            and signal.ask is not None
            and signal.ask >= signal.bid
        )
        if book_ok:
            base = signal.ask if buying else signal.bid
            depth = signal.ask_depth if buying else signal.bid_depth
        elif signal.mid is not None:
            penalty = float(active.config_value("mid_penalty_bps")) / 10_000.0
            base = signal.mid * (1.0 + penalty) if buying else signal.mid * (1.0 - penalty)
            depth = None
        else:
            return None

        impact = 0.0
        if depth is not None and depth > 0:
            impact = base * SlippageModel.sqrt_impact(
                abs(size), depth, float(active.config_value("impact_coefficient"))
            )
        price = base + impact if buying else base - impact
        if price <= 0:
            return None
        reference = signal.mid if signal.mid is not None else base
        slippage = abs(price - reference)
        return price, slippage

    def _update_mark(self, active: _ActiveRun, snapshot: dict) -> None:
        """Record the latest observed price for an instrument, with its time."""
        key = str(snapshot.get("market_id") or snapshot.get("pair_id") or "")
        if not key:
            return
        mid = snapshot.get("mid_price")
        if mid is None:
            bid, ask = snapshot.get("bid_price"), snapshot.get("ask_price")
            if bid is not None and ask is not None:
                mid = (float(bid) + float(ask)) / 2.0
        if mid is None or not isinstance(mid, (int, float)) or mid <= 0:
            return
        active.marks[key] = float(mid)
        stamp = snapshot.get("timestamp")
        active.mark_times[key] = stamp if isinstance(stamp, datetime) else self._now()

    async def _apply_funding(self, active: _ActiveRun, snapshot: dict) -> None:
        """Book exchange funding from a real snapshot exactly once."""
        rate = snapshot.get("funding_rate")
        if rate is None:
            return
        instrument = str(snapshot.get("market_id") or snapshot.get("pair_id") or "")
        position = next(
            (p for p in await asyncio.to_thread(self.store.list_positions, active.record.run_id)
             if p.instrument_id == instrument),
            None,
        )
        mark = active.marks.get(instrument)
        timestamp = snapshot.get("timestamp")
        if position is None or mark is None or timestamp is None:
            return
        interval = int(active.config_value("funding_interval_seconds") or 0)
        if interval > 0:
            stamp = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(str(timestamp))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            epoch = int(stamp.timestamp())
            applied_at = datetime.fromtimestamp(epoch - (epoch % interval), tz=UTC).isoformat()
        else:
            applied_at = timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp)
        notional = abs(position.size) * mark
        pnl = -position.size * mark * float(rate)
        inserted = await asyncio.to_thread(
            self.store.append_funding, active.record.run_id,
            instrument_id=instrument, rate=float(rate), notional=notional,
            pnl=pnl, applied_at=applied_at,
        )
        if inserted:
            await asyncio.to_thread(
                self.store.update_run, active.record.run_id,
                cash=active.record.cash + pnl,
            )
            refreshed = await asyncio.to_thread(self.store.get_run, active.record.run_id)
            if refreshed is not None:
                active.record = refreshed

    def _equity_snapshot(
        self, active: _ActiveRun
    ) -> tuple[float, float, dict[str, float], bool]:
        """Return (equity, gross_exposure, per-instrument abs notional, degraded).

        ``degraded`` is True when any position had to be valued at something
        other than a fresh mark — no mark at all, or one older than
        ``max_staleness_seconds``. The caller stamps the equity point with it so
        the curve carries its own provenance, and ``compute_run_metrics``
        refuses to summarise a curve that contains one.
        """
        positions = self.store.list_positions(active.record.run_id)
        cash = active.record.cash
        equity = cash
        gross = 0.0
        notionals: dict[str, float] = {}
        degraded = False
        limit = float(active.config_value("max_staleness_seconds"))
        now = self._now()
        for position in positions:
            mark = active.marks.get(position.instrument_id)
            seen = active.mark_times.get(position.instrument_id)
            if mark is None:
                # Falling back to the entry price is not a neutral approximation:
                # it reports unrealised P&L of exactly zero, which is a claim.
                mark = position.avg_price
                degraded = True
            elif seen is not None:
                age = (now - (seen if seen.tzinfo else seen.replace(tzinfo=UTC))).total_seconds()
                if age > limit:
                    degraded = True
            equity += position.size * mark
            notional = abs(position.size) * mark
            gross += notional
            notionals[position.instrument_id] = notional
        return equity, gross, notionals, degraded

    async def _process_signal(self, active: _ActiveRun, signal: SimSignal) -> None:
        async with active.lock:
            if active.record.status != "running":
                return
            run_id = active.record.run_id
            instrument = signal.instrument_id

            if signal.mid is not None:
                active.marks[instrument] = signal.mid
            elif signal.bid is not None and signal.ask is not None:
                active.marks[instrument] = (signal.bid + signal.ask) / 2.0

            # Stale/missing timestamp: no fill (unknown != safe).
            age = self._age_seconds(signal.timestamp)
            if age is None or age > float(active.config_value("max_staleness_seconds")):
                return

            # Per-instrument cooldown against trade spam on 5s snapshots.
            now = self._now()
            last = active.last_trade_at.get(instrument)
            if last is not None and (now - last).total_seconds() < float(
                active.config_value("cooldown_seconds")
            ):
                return

            equity, _, notionals, _degraded = await asyncio.to_thread(
                self._equity_snapshot, active
            )
            if equity <= 0:
                return

            positions = {
                p.instrument_id: p
                for p in await asyncio.to_thread(self.store.list_positions, run_id)
            }
            current = positions.get(instrument)
            current_size = current.size if current else 0.0
            current_avg = current.avg_price if current else 0.0

            est_price = signal.ask if signal.side == "buy" else signal.bid
            if est_price is None:
                est_price = signal.mid
            if est_price is None or est_price <= 0:
                return

            fraction = float(active.config_value("position_fraction"))
            fraction_by_instrument = active.config_value("position_fraction_by_instrument")
            if isinstance(fraction_by_instrument, dict) and instrument in fraction_by_instrument:
                fraction = float(fraction_by_instrument[instrument])
            if not math.isfinite(fraction) or fraction < 0:
                return
            direction = 1.0 if signal.side == "buy" else -1.0
            allow_short = bool(active.config_value("allow_short"))
            sizing_basis = str(active.config_value("position_fraction_basis") or "equity").lower()
            sizing_equity = (
                float(active.record.initial_capital)
                if sizing_basis == "initial_capital" else equity
            )
            target_size = (
                direction * (fraction * sizing_equity) / est_price
                if direction > 0 or allow_short
                else 0.0
            )
            qty = target_size - current_size
            # Only trade in the signal's direction (a buy signal never sells
            # beyond flattening toward its own target, and vice versa).
            if qty * direction <= 0:
                return
            # A same-direction signal may otherwise resize on every daily
            # mark as price changes. Only pay costs when the target has moved
            # materially; reversals and long-only exits always pass through.
            min_rebalance_bps = max(0.0, float(active.config_value("min_rebalance_bps")))
            same_direction = current_size * target_size > 0
            if (
                same_direction
                and min_rebalance_bps > 0
                and abs(qty) / max(abs(current_size), _EPS) * 10_000.0 < min_rebalance_bps
            ):
                return
            if abs(qty) * est_price < float(active.config_value("min_trade_notional")):
                return

            decision = self.risk_checker.evaluate_intent(
                [{
                    "market_id": instrument,
                    "quantity": qty,
                    "price": est_price,
                    "reduces_exposure": (
                        direction < 0 and current_size > 0
                        and abs(qty) <= abs(current_size) + _EPS
                    ),
                }],
                notionals,
                cash=active.record.cash,
                subject_id=run_id,
            )
            if not decision.allowed:
                active.risk_rejections += 1
                active.risk_rejection_events.append({
                    "stage": str(signal.signal_meta.get("execution_stage", "unknown")),
                    "instrument": instrument,
                    "side": signal.side,
                    "quantity": float(qty),
                    "price": float(est_price),
                    "reasons": list(decision.reasons),
                    "measurements": dict(decision.measurements),
                    "timestamp": now.isoformat(),
                })
                logger.info(
                    "sim_trade_risk_rejected",
                    run_id=run_id,
                    instrument=instrument,
                    reasons=decision.reasons,
                )
                return

            fill = self._fill_price(active, signal, qty)
            if fill is None:
                return
            raw_price, slippage = fill

            fee_rate = float(active.config_value("fee_bps")) / 10_000.0
            notional = abs(qty) * raw_price
            fee = notional * fee_rate
            # Fold the fee into the effective price so costs live inside
            # avg_price (entries) and realized_pnl (exits).
            effective_price = raw_price + (fee / abs(qty)) * (1.0 if qty > 0 else -1.0)

            new_size, new_avg, realized = apply_avg_price_fill(
                current_size, current_avg, qty, effective_price
            )
            new_cash = active.record.cash - qty * effective_price

            executed_at = now.isoformat()
            signal_meta = dict(signal.signal_meta)
            signal_meta["confidence"] = signal.confidence

            def persist() -> None:
                receipt = self.ledger.apply_fill(FillCommand(
                    fill_id=f"{run_id}:{instrument}:{executed_at}:{uuid.uuid4().hex[:8]}",
                    account_id=f"paper:{run_id}", order_id=f"paper:{run_id}:{instrument}",
                    instrument_id=instrument, side=signal.side, quantity=abs(qty),
                    price=raw_price, fee=fee, executed_at=executed_at,
                    metadata={"source": "simulation", "signal_meta": signal_meta},
                ))
                signal_meta["ledger_sequence"] = receipt.sequence
                self.store.append_trade(
                    run_id,
                    instrument_id=instrument,
                    side=signal.side,
                    size=abs(qty),
                    price=raw_price,
                    fee=fee,
                    slippage=slippage,
                    signal_meta=signal_meta,
                    realized_pnl=realized,
                    executed_at=executed_at,
                )
                self.store.upsert_position(run_id, instrument, new_size, new_avg)
                self.store.update_run(run_id, cash=new_cash)

            await asyncio.to_thread(persist)
            refreshed = await asyncio.to_thread(self.store.get_run, run_id)
            if refreshed is not None:
                active.record = refreshed
            active.last_trade_at[instrument] = now
            await self._record_equity(active)
            logger.info(
                "sim_trade_executed",
                run_id=run_id,
                instrument=instrument,
                side=signal.side,
                size=abs(qty),
                price=raw_price,
                fee=fee,
                realized_pnl=realized,
            )

    # ---------------------------------------------------------------- equity

    async def _record_equity(self, active: _ActiveRun) -> None:
        equity, gross, _, degraded = await asyncio.to_thread(self._equity_snapshot, active)
        now = self._now()
        await asyncio.to_thread(
            self.store.append_equity_point,
            active.record.run_id,
            equity=equity,
            cash=active.record.cash,
            gross_exposure=gross,
            ts=now.isoformat(),
            degraded=degraded,
        )
        active.last_equity_at = now

    async def _equity_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.equity_poll_seconds)
                now = self._now()
                for active in list(self._active.values()):
                    if active.record.status != "running":
                        continue
                    interval = float(active.config_value("equity_interval_minutes")) * 60.0
                    if (
                        active.last_equity_at is None
                        or (now - active.last_equity_at).total_seconds() >= interval
                    ):
                        await self._record_equity(active)
                    if bool(active.config_value("auto_feedback")):
                        feedback_interval = float(
                            active.record.config.get("feedback_interval_minutes", 60.0)
                        ) * 60.0
                        if (
                            active.last_feedback_at is None
                            or (now - active.last_feedback_at).total_seconds()
                            >= feedback_interval
                        ):
                            active.last_feedback_at = now
                            await self.apply_feedback(active.record.run_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("sim_equity_loop_error", error=str(exc), exc_info=True)

    # ------------------------------------------------------------------ misc

    async def _log_experiment(self, record: SimRunRecord, *, phase: str) -> None:
        """Log a run to the experiment registry (P8b).

        ``phase="created"`` records params + versions with empty metrics; a later
        ``phase="final"`` records the computed metrics so the result is
        reproducible. Registry ``run_id`` is the sim run id suffixed by phase so
        both phases coexist under the append-only store and stay queryable by run.
        Never allowed to break the run lifecycle.
        """
        try:
            metrics: dict[str, float] = {}
            if phase == "final":
                raw = await asyncio.to_thread(sim_metrics.compute_run_metrics, self.store, record.run_id)
                metrics = {
                    key: float(value)
                    for key, value in raw.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
            params: dict[str, Any] = {
                "strategy_id": record.strategy_id,
                "universe": list(record.universe),
                "initial_capital": record.initial_capital,
                "config": dict(record.config),
            }
            # A content hash of the inputs doubles as a lightweight data version.
            data_version = f"{record.strategy_id}:{len(record.universe)}insts"
            await asyncio.to_thread(
                self.registry.log_run,
                "simulation",
                params=params,
                metrics=metrics,
                data_version=data_version,
                model_version=record.strategy_id,
                tags=[phase, record.strategy_id],
                notes=f"sim run {record.run_id} ({record.name}) phase={phase}",
                run_id=f"{record.run_id}:{phase}",
            )
        except Exception as exc:  # experiment logging must never break a run
            logger.warning(
                "sim_experiment_log_failed",
                run_id=record.run_id,
                phase=phase,
                error=str(exc) or exc.__class__.__name__,
            )

    async def _audit(self, event_type: str, run_id: str, payload: dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(
                fact_store.append_audit_event,
                event_type,
                actor="simulation",
                subject_type="sim_run",
                subject_id=run_id,
                payload=payload,
                db_path=self.store.db_path,
            )
        except Exception as exc:  # audit must never break the run lifecycle
            logger.warning("sim_audit_failed", error=str(exc) or exc.__class__.__name__)


def downsample_equity_curve(
    points: list[Any], max_points: int = 500
) -> list[dict[str, Any]]:
    """Downsample an equity curve to <= max_points, keeping first/last points."""
    serialized = [{"ts": p.ts, "equity": p.equity} for p in points]
    n = len(serialized)
    if n <= max_points:
        return serialized
    step = (n - 1) / (max_points - 1)
    indices = sorted({round(i * step) for i in range(max_points)} | {0, n - 1})
    return [serialized[i] for i in indices if 0 <= i < n]


__all__ = [
    "DEFAULT_RUN_CONFIG",
    "InvalidRunTransitionError",
    "SimulationService",
    "UnknownRunError",
    "apply_avg_price_fill",
    "downsample_equity_curve",
]
