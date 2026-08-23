"""Truthful product capability inventory for the operator workbench."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from fastapi import APIRouter

from libs.config import get_settings
from libs.quant.promotion_registry import get_registry


router = APIRouter(prefix="/api/capabilities", tags=["capability-boundary"])

Tier = Literal["core", "lab", "archive"]
State = Literal["available", "disabled", "degraded", "unknown", "blocked"]


@dataclass(frozen=True)
class Capability:
    capability_id: str
    label: str
    tier: Tier
    state: State
    routes: tuple[str, ...]
    api_prefixes: tuple[str, ...]
    trade_permission: bool
    truth: str
    missing: tuple[str, ...] = ()


def capability_inventory() -> list[Capability]:
    settings = get_settings()
    registry = get_registry()
    approved_trade_count = len(registry.promoted_pairs())
    # Import lazily to avoid the capability router creating an application
    # import cycle. The Paper Lab endpoint is the runtime source of truth when
    # an operator has enabled it from the frontend.
    from apps.api import main as api_main

    simulation_enabled = api_main.lab_backtest_enabled()
    simulation_running = api_main.simulation_service is not None

    kronos_enabled = settings.enable_lab_kronos_forecasting
    portfolio_configured = settings.polybob_account_equity is not None
    return [
        Capability(
            "market_observation",
            "Market and instrument observation",
            "core",
            "available",
            ("/overview", "/markets", "/polymarket", "/crypto", "/us-equities"),
            (
                "/api/markets", "/api/market", "/api/crypto", "/api/us-equities",
                "/api/btc-5m", "/api/onchain", "/api/knowledge",
            ),
            False,
            "Observation and research surfaces; provider freshness and coverage remain visible.",
        ),
        Capability(
            "research_promotion",
            "Research evidence and promotion gate",
            "core",
            "available" if settings.require_strategy_promotion else "degraded",
            ("/overview",),
            ("/api/edges", "/api/research"),
            False,
            f"Promotion gate currently reports {approved_trade_count} trade-approved edge(s).",
            () if settings.require_strategy_promotion else ("promotion gate is disabled",),
        ),
        Capability(
            "manual_journal",
            "Manual trade journal",
            "core",
            "degraded",
            ("/journal",),
            ("/api/journal", "/api/portfolio"),
            False,
            "Manual research record, not an authoritative broker or double-entry ledger.",
            ("execution fills are not yet the journal's sole source",),
        ),
        Capability(
            "portfolio_risk",
            "Portfolio and risk state",
            "core",
            "degraded" if portfolio_configured else "unknown",
            ("/overview", "/journal"),
            ("/api/portfolio", "/api/risk"),
            False,
            "Risk output is not execution-authoritative until the fill ledger is connected.",
            (() if portfolio_configured else ("account equity is not configured",))
            + ("canonical fill ledger is not connected to portfolio views",),
        ),
        Capability(
            "kronos_forecast",
            "Kronos forecasting",
            "lab",
            "available" if kronos_enabled else "disabled",
            ("/us-equities", "/crypto"),
            ("/api/forecasting",),
            False,
            "Opt-in probabilistic experiment; forecasts never grant trade permission.",
            ("rolling out-of-sample calibration is not yet available",),
        ),
        Capability(
            "development_control",
            "Development control and runtime boundaries",
            "core",
            "available",
            ("/dev-control", "/settings"),
            ("/api/dev-control", "/api/capabilities"),
            False,
            "Git-backed task state and read-only capability truth for this local workbench.",
        ),
        Capability(
            "paper_execution",
            "Paper intent and basket execution",
            "lab",
            "blocked",
            (),
            ("/api/execution",),
            False,
            "Prototype paths exist but no authoritative order/fill/reconciliation chain is connected.",
            ("execution ledger integration", "reconciliation", "enforced kill switch"),
        ),
        Capability(
            "strategy_runtime",
            "Strategy templates and runtime instances",
            "lab",
            "blocked",
            (),
            ("/api/strategies", "/api/pairs"),
            False,
            "Templates and stopped instances are retained for research; none imply a promoted trading system.",
            ("approved trade edge", "versioned decision lineage", "canonical portfolio integration"),
        ),
        Capability(
            "simulation",
            "Research simulation",
            "lab",
            "available" if simulation_running else ("degraded" if simulation_enabled else "disabled"),
            ("/simulation",),
            ("/api/simulation",),
            False,
            "Paper-only research comparison driven by the configured market event bus; never live execution.",
            ("runtime service is not started",) if simulation_enabled and not simulation_running else (),
        ),
        Capability(
            "auto_trader",
            "Automatic trader",
            "archive",
            "disabled",
            (),
            ("/api/trading",),
            False,
            "Legacy lab prototype; excluded from the core product and disabled by default.",
            ("approved trade edge", "certified venue adapter", "execution risk controls"),
        ),
    ]


@router.get("")
async def list_capabilities():
    rows = capability_inventory()
    return {
        "product_mode": get_settings().product_mode,
        "trade_execution_ready": False,
        "rows": [asdict(row) for row in rows],
    }
