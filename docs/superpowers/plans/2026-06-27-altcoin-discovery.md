# Altcoin Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build PolyBob's real-data Crypto module and Altcoin Discovery workbench for the live Binance Alpha and USDⓈ-M perpetual intersection, with explainable 7-day, 30-day, and 90-day dual-axis scores and three risk-sized trade plans.

**Architecture:** Add a standalone async discovery domain under `libs/crypto/discovery` and expose it through the existing FastAPI lifecycle. Provider observations remain separate from deterministic universe, scoring, and trade-plan functions; the Next.js dashboard consumes a strict parsed API contract and renders a list/detail financial workbench.

**Tech Stack:** Python 3.11, FastAPI, httpx 0.28, Pydantic 2, pytest/pytest-asyncio, Next.js 15, React 19, TypeScript, Tailwind CSS, Vitest.

---

## File Structure

New backend files:

- `libs/networking.py`: proxy resolution and network failure classification.
- `libs/crypto/discovery/models.py`: Pydantic contracts shared by the discovery domain.
- `libs/crypto/discovery/providers/http.py`: bounded async JSON transport.
- `libs/crypto/discovery/providers/binance_alpha.py`: Alpha, dynamic-token, K-line, and smart-money provider.
- `libs/crypto/discovery/providers/binance_futures.py`: USDⓈ-M market and history provider.
- `libs/crypto/discovery/providers/dex_screener.py`: independent DEX liquidity provider.
- `libs/crypto/discovery/providers/evm.py`: Ethereum, BNB Chain, and Base evidence adapter.
- `libs/crypto/discovery/providers/solana.py`: Solana evidence adapter.
- `libs/crypto/discovery/universe.py`: Unicode-safe symbol matching and ambiguity gates.
- `libs/crypto/discovery/scoring.py`: feature normalization, coverage, and horizon scores.
- `libs/crypto/discovery/trade_plan.py`: structural levels and three risk modes.
- `libs/crypto/discovery/service.py`: refresh orchestration, cache, and detail enrichment.

New frontend files:

- `apps/dashboard/domain/altcoinDiscovery/workbench.ts`: strict response parser and display model.
- `apps/dashboard/domain/altcoinDiscovery/workbench.test.ts`: parser and no-fake-state tests.
- `apps/dashboard/components/AltcoinDiscoveryWorkspace.tsx`: responsive list/detail workbench.
- `apps/dashboard/app/crypto/page.tsx`: Crypto module index.
- `apps/dashboard/app/crypto/altcoin-discovery/page.tsx`: server-rendered initial discovery snapshot.

Existing files modified:

- `libs/config.py`: provider URLs, proxy, timeout, and thresholds.
- `apps/api/main.py`: service lifecycle and three read-only API routes.
- `apps/dashboard/components/PrimaryNav.tsx`: bilingual Crypto navigation item.
- `apps/dashboard/app/globals.css`: compact workbench primitives and responsive layout.
- `.env.example`: optional proxy and provider settings.

Test files:

- `tests/test_discovery_networking.py`
- `tests/unit/test_altcoin_universe.py`
- `tests/unit/test_altcoin_scoring.py`
- `tests/unit/test_altcoin_trade_plan.py`
- `tests/test_altcoin_providers.py`
- `tests/test_altcoin_discovery_service.py`
- `tests/test_api_altcoin_discovery.py`
- `tests/fixtures/altcoin_discovery/*.json`

## Task 1: Outbound Proxy and Network Diagnostics

**Files:**
- Create: `libs/networking.py`
- Modify: `libs/config.py`
- Modify: `.env.example`
- Test: `tests/test_discovery_networking.py`

- [ ] **Step 1: Write failing proxy precedence and redaction tests**

```python
from libs.networking import classify_network_error, redact_proxy_url, resolve_outbound_proxy


def test_explicit_polybob_proxy_wins():
    proxy = resolve_outbound_proxy(
        env={
            "POLYBOB_OUTBOUND_PROXY": "http://127.0.0.1:7892",
            "HTTPS_PROXY": "http://fallback:8080",
        },
        platform_name="Darwin",
        macos_proxy={"enabled": True, "host": "127.0.0.1", "port": 9999},
    )
    assert proxy == "http://127.0.0.1:7892"


def test_macos_proxy_is_used_when_environment_is_empty():
    proxy = resolve_outbound_proxy(
        env={},
        platform_name="Darwin",
        macos_proxy={"enabled": True, "host": "127.0.0.1", "port": 7892},
    )
    assert proxy == "http://127.0.0.1:7892"


def test_proxy_credentials_are_redacted():
    assert redact_proxy_url("http://user:secret@proxy.example:8080") == "http://proxy.example:8080"


def test_connect_timeout_is_classified():
    import httpx

    error = httpx.ConnectTimeout("connect timed out")
    assert classify_network_error(error).category == "connect_timeout"
    assert classify_network_error(error).retryable is True
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `conda run -n polybob python -m pytest tests/test_discovery_networking.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'libs.networking'`.

- [ ] **Step 3: Implement proxy resolution and typed diagnostics**

```python
# libs/networking.py
from __future__ import annotations

from dataclasses import dataclass
import os
import platform
import re
import subprocess
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

import httpx


@dataclass(frozen=True)
class NetworkFailure:
    category: str
    retryable: bool
    detail: str


def read_macos_https_proxy() -> dict[str, object]:
    if platform.system() != "Darwin":
        return {"enabled": False, "host": "", "port": 0}
    result = subprocess.run(
        ["scutil", "--proxy"],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    enabled = re.search(r"HTTPSEnable\s*:\s*1", result.stdout) is not None
    host_match = re.search(r"HTTPSProxy\s*:\s*([^\s]+)", result.stdout)
    port_match = re.search(r"HTTPSPort\s*:\s*(\d+)", result.stdout)
    return {
        "enabled": enabled,
        "host": host_match.group(1) if host_match else "",
        "port": int(port_match.group(1)) if port_match else 0,
    }


def resolve_outbound_proxy(
    *,
    env: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    macos_proxy: Mapping[str, object] | None = None,
) -> str | None:
    values = os.environ if env is None else env
    explicit = values.get("POLYBOB_OUTBOUND_PROXY") or values.get("HTTPS_PROXY") or values.get("ALL_PROXY")
    if explicit:
        return explicit
    system = platform.system() if platform_name is None else platform_name
    proxy = read_macos_https_proxy() if macos_proxy is None else macos_proxy
    if system == "Darwin" and proxy.get("enabled") and proxy.get("host") and proxy.get("port"):
        return f"http://{proxy['host']}:{proxy['port']}"
    return None


def redact_proxy_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def classify_network_error(error: Exception) -> NetworkFailure:
    if isinstance(error, httpx.ConnectTimeout):
        return NetworkFailure("connect_timeout", True, str(error))
    if isinstance(error, httpx.ReadTimeout):
        return NetworkFailure("read_timeout", True, str(error))
    if isinstance(error, httpx.ProxyError):
        return NetworkFailure("proxy_error", True, str(error))
    if isinstance(error, httpx.ConnectError):
        return NetworkFailure("connect_error", True, str(error))
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        return NetworkFailure(f"http_{code}", code in {418, 429} or code >= 500, str(error))
    return NetworkFailure("unexpected", False, str(error))
```

Add these exact settings to `Settings`:

```python
polybob_outbound_proxy: str = ""
binance_alpha_api_url: str = "https://web3.binance.com"
binance_futures_api_url: str = "https://fapi.binance.com"
dex_screener_api_url: str = "https://api.dexscreener.com"
discovery_request_timeout_seconds: float = 10.0
discovery_min_coverage: float = 0.70
discovery_max_cashout_risk: float = 45.0
discovery_min_pump_potential: float = 70.0
discovery_min_liquidity_usd: float = 500_000.0
discovery_min_volume_24h_usd: float = 1_000_000.0
```

Add these commented examples to `.env.example` without making the local proxy a default:

```dotenv
# POLYBOB_OUTBOUND_PROXY=http://127.0.0.1:7892
# DISCOVERY_MIN_COVERAGE=0.70
# DISCOVERY_MAX_CASHOUT_RISK=45
# DISCOVERY_MIN_PUMP_POTENTIAL=70
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `conda run -n polybob python -m pytest tests/test_discovery_networking.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add libs/networking.py libs/config.py .env.example tests/test_discovery_networking.py
git commit -m "feat: add outbound proxy diagnostics"
```

## Task 2: Real Provider Contracts and Captured Fixtures

**Files:**
- Create: `libs/crypto/discovery/__init__.py`
- Create: `libs/crypto/discovery/models.py`
- Create: `libs/crypto/discovery/providers/__init__.py`
- Create: `libs/crypto/discovery/providers/http.py`
- Create: `libs/crypto/discovery/providers/binance_alpha.py`
- Create: `libs/crypto/discovery/providers/binance_futures.py`
- Create: `libs/crypto/discovery/providers/dex_screener.py`
- Create: `libs/crypto/discovery/providers/evm.py`
- Create: `libs/crypto/discovery/providers/solana.py`
- Create: `tests/fixtures/altcoin_discovery/binance_alpha_bsc.json`
- Create: `tests/fixtures/altcoin_discovery/binance_futures_exchange_info.json`
- Create: `tests/fixtures/altcoin_discovery/binance_smart_money_bsc.json`
- Test: `tests/test_altcoin_providers.py`

- [ ] **Step 1: Save minimized real provider fixtures**

Use the captured 2026-06-27 responses. Keep source URL and capture timestamp in `_fixture_meta`; retain the exact VELVET Alpha fields `chainId`, `contractAddress`, `symbol`, `price`, `marketCap`, `liquidity`, `holders`, `holdersTop10Percent`, `auditInfo`, `tokenTag`, `metaInfo`, and `alphaInfo`. Keep one actively traded `VELVETUSDT` perpetual symbol and one inactive symbol in the futures fixture. These files are deterministic parser evidence and are never imported by production code.

- [ ] **Step 2: Write failing parser and pagination tests**

```python
import json
from pathlib import Path

import httpx
import pytest

from libs.crypto.discovery.providers.binance_alpha import BinanceAlphaProvider
from libs.crypto.discovery.providers.binance_futures import BinanceFuturesProvider

FIXTURES = Path(__file__).parent / "fixtures" / "altcoin_discovery"


@pytest.mark.asyncio
async def test_alpha_provider_parses_real_contract_identity():
    payload = json.loads((FIXTURES / "binance_alpha_bsc.json").read_text())
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        provider = BinanceAlphaProvider(client)
        tokens = await provider.list_alpha_tokens("56")
    assert tokens[0].asset_id == "56:0x8b194370825e37b33373e74a41009161808c1488"
    assert tokens[0].symbol == "VELVET"
    assert tokens[0].holders_top10_percent == 89.51263228445335
    assert tokens[0].is_alpha is True


@pytest.mark.asyncio
async def test_futures_provider_keeps_only_live_usdt_perpetuals():
    payload = json.loads((FIXTURES / "binance_futures_exchange_info.json").read_text())
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        symbols = await BinanceFuturesProvider(client).list_perpetuals()
    assert [item.symbol for item in symbols] == ["VELVETUSDT"]
```

- [ ] **Step 3: Run tests and verify RED**

Run: `conda run -n polybob python -m pytest tests/test_altcoin_providers.py -q`

Expected: imports fail because discovery provider modules do not exist.

- [ ] **Step 4: Implement typed observations and bounded HTTP transport**

Define Pydantic models `AlphaToken`, `FuturesContract`, `ProviderHealth`, `Evidence`, `HorizonScore`, `PositionSize`, `TradePlan`, `DiscoveryCandidate`, and `DiscoverySnapshot`. `ProviderHttpClient.request_json()` must use a 10-second timeout, pass the resolved proxy to `httpx.AsyncClient(proxy=resolved_proxy)`, reject non-object/list JSON, honor `Retry-After`, and return structured provider failures instead of `None`.

Implement these provider methods with the exact public routes:

```python
ALPHA_RANK_URL = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/unified/rank/list/ai"
TOKEN_DYNAMIC_URL = "https://web3.binance.com/bapi/defi/v4/public/wallet-direct/buw/wallet/market/token/dynamic/info/ai"
SMART_MONEY_URL = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/tracker/wallet/token/inflow/rank/query/ai"
FUTURES_EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
FUTURES_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
DEX_TOKEN_PAIRS_URL = "https://api.dexscreener.com/token-pairs/v1/{chain_id}/{contract_address}"
```

`BinanceAlphaProvider.list_alpha_tokens()` must request pages until `page * size >= total`, verify business code `000000`, and require the Alpha tag. Smart-money capability is `{"56", "8453", "CT_501"}`. EVM and Solana adapters expose observations only when their RPC calls succeed; unsupported methods return `status="unsupported"` rather than zero.

Add adapter contract tests using captured RPC envelopes:

```python
import httpx
from libs.crypto.discovery.providers.evm import EvmEvidenceProvider
from libs.crypto.discovery.providers.solana import SolanaEvidenceProvider


@pytest.mark.asyncio
async def test_evm_adapter_preserves_observed_block_number():
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        result = "0x1234" if method == "eth_blockNumber" else "0x0000000000000000000000000000000000000000000000000de0b6b3a7640000"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        evidence = await EvmEvidenceProvider(client).token_supply(
            chain_id="56",
            contract_address="0x8b194370825e37b33373e74a41009161808c1488",
            decimals=18,
        )
    assert evidence.status == "observed"
    assert evidence.block_number is not None


@pytest.mark.asyncio
async def test_solana_largest_accounts_keeps_provider_context():
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"context": {"slot": 1234}, "value": [{"address": "holder-1", "amount": "100", "decimals": 6, "uiAmountString": "0.0001"}]},
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        evidence = await SolanaEvidenceProvider(client).largest_accounts(
            mint_address="So11111111111111111111111111111111111111112",
        )
    assert evidence.status == "observed"
    assert evidence.provider == "solana_rpc"
    assert len(evidence.accounts) <= 20
```

- [ ] **Step 5: Run provider tests and verify GREEN**

Run: `conda run -n polybob python -m pytest tests/test_altcoin_providers.py -q`

Expected: all provider parser tests pass.

- [ ] **Step 6: Add opt-in live schema smoke tests**

```python
import os

import httpx
from libs.networking import resolve_outbound_proxy


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("POLYBOB_LIVE_PROVIDER_TESTS"), reason="live provider test")
async def test_live_alpha_schema_contains_identity_fields():
    async with httpx.AsyncClient(proxy=resolve_outbound_proxy(), timeout=10.0) as client:
        tokens = await BinanceAlphaProvider(client).list_alpha_tokens("56")
    assert tokens
    assert all(token.contract_address and token.symbol for token in tokens)
```

Run: `POLYBOB_LIVE_PROVIDER_TESTS=1 conda run -n polybob python -m pytest tests/test_altcoin_providers.py -q`

Expected: live schema test passes through the detected macOS proxy.

- [ ] **Step 7: Commit**

```bash
git add libs/crypto/discovery tests/fixtures/altcoin_discovery tests/test_altcoin_providers.py
git commit -m "feat: add real altcoin discovery providers"
```

## Task 3: Unicode-Safe Alpha and Futures Universe

**Files:**
- Create: `libs/crypto/discovery/universe.py`
- Test: `tests/unit/test_altcoin_universe.py`

- [ ] **Step 1: Write failing exact, multiplier, Unicode, and duplicate tests**

```python
from libs.crypto.discovery.models import AlphaToken, FuturesContract
from libs.crypto.discovery.universe import build_universe, normalize_symbol


def alpha(symbol: str, address: str) -> AlphaToken:
    return AlphaToken(chain_id="56", contract_address=address, symbol=symbol, is_alpha=True)


def future(base: str) -> FuturesContract:
    return FuturesContract(symbol=f"{base}USDT", base_asset=base, quote_asset="USDT", status="TRADING")


def test_normalization_preserves_unicode_and_rejects_empty():
    assert normalize_symbol("我踏马来了") == "我踏马来了"
    assert normalize_symbol("---") is None


def test_multiplier_contract_maps_uniquely():
    result = build_universe([alpha("Mog", "0x1")], [future("1000000MOG")])
    assert result.candidates[0].futures_symbol == "1000000MOGUSDT"
    assert result.candidates[0].mapping_status == "unique"


def test_duplicate_alpha_symbol_is_not_trade_eligible():
    result = build_universe(
        [alpha("BOB", "0x1"), alpha("BOB", "0x2")],
        [future("1000000BOB")],
    )
    assert {item.mapping_status for item in result.candidates} == {"ambiguous"}
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n polybob python -m pytest tests/unit/test_altcoin_universe.py -q`

Expected: import fails for `libs.crypto.discovery.universe`.

- [ ] **Step 3: Implement deterministic mapping**

```python
def normalize_symbol(value: str) -> str | None:
    normalized = unicodedata.normalize("NFC", value).strip().casefold().upper()
    normalized = "".join(character for character in normalized if character.isalnum() or character == "$")
    return normalized or None


def futures_variants(symbol: str) -> tuple[str, ...]:
    return (symbol, f"1000{symbol}", f"1000000{symbol}", f"1M{symbol}")
```

Group Alpha tokens globally by normalized symbol before matching. A group with more than one contract is ambiguous even if only one futures symbol matches. Return counts for Alpha total, futures total, unique intersections, ambiguous mappings, and per-chain coverage.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `conda run -n polybob python -m pytest tests/unit/test_altcoin_universe.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add libs/crypto/discovery/universe.py tests/unit/test_altcoin_universe.py
git commit -m "feat: build safe alpha futures universe"
```

## Task 4: Explainable Horizon Scoring

**Files:**
- Create: `libs/crypto/discovery/scoring.py`
- Test: `tests/unit/test_altcoin_scoring.py`

- [ ] **Step 1: Write failing horizon, coverage, and concentration tests**

```python
from libs.crypto.discovery.models import Evidence
from libs.crypto.discovery.scoring import derive_market_features, score_candidate


def observed(name: str, value: float) -> Evidence:
    return Evidence(name=name, value=value, status="observed", weight=1.0, provider="test")


def test_all_three_horizons_are_returned():
    result = score_candidate([
        observed("floor", 0.8),
        observed("washout", 0.7),
        observed("control", 0.9),
        observed("accumulation", 0.8),
        observed("historical_operator_strength", 0.6),
        observed("futures_squeeze", 0.7),
    ])
    assert set(result.pump_potential) == {"7d", "30d", "90d"}
    assert set(result.cashout_risk) == {"7d", "30d", "90d"}


def test_missing_evidence_reduces_coverage_without_becoming_zero():
    full = score_candidate([observed(name, 0.5) for name in (
        "floor", "washout", "control", "accumulation",
        "historical_operator_strength", "futures_squeeze",
    )])
    partial = score_candidate([observed("floor", 0.5)])
    assert partial.coverage < full.coverage
    assert partial.pump_potential["30d"].value == 50.0


def test_concentration_raises_potential_and_cashout_risk_separately():
    low = score_candidate([observed("control", 0.2), observed("dev_concentration", 0.2)])
    high = score_candidate([observed("control", 0.9), observed("dev_concentration", 0.9)])
    assert high.pump_potential["30d"].value > low.pump_potential["30d"].value
    assert high.cashout_risk["30d"].value > low.cashout_risk["30d"].value


def test_deep_retracement_after_real_rally_raises_floor_washout_and_operator_strength():
    closes = [1.0, 1.1, 1.3, 1.8, 2.6, 3.2, 2.7, 2.2, 1.8, 1.55, 1.45, 1.42, 1.44, 1.46]
    volumes = [100, 120, 180, 400, 900, 1200, 800, 500, 320, 220, 160, 130, 135, 145]
    features = derive_market_features(
        closes=closes,
        volumes=volumes,
        market_cap_percentile=0.1,
        top10_holder_percent=82.0,
        smart_money_inflow_percentile=0.8,
        buy_volume=600.0,
        sell_volume=400.0,
    )
    assert features["floor"] > 0.65
    assert features["washout"] > 0.5
    assert features["historical_operator_strength"] > 0.5
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n polybob python -m pytest tests/unit/test_altcoin_scoring.py -q`

Expected: import fails for `libs.crypto.discovery.scoring`.

- [ ] **Step 3: Implement weighted renormalization and explanations**

Use the approved pump-potential matrix exactly:

```python
PUMP_WEIGHTS = {
    "7d": {"floor": 0.10, "washout": 0.15, "control": 0.20, "accumulation": 0.20, "historical_operator_strength": 0.10, "futures_squeeze": 0.25},
    "30d": {"floor": 0.20, "washout": 0.20, "control": 0.15, "accumulation": 0.25, "historical_operator_strength": 0.15, "futures_squeeze": 0.05},
    "90d": {"floor": 0.25, "washout": 0.15, "control": 0.15, "accumulation": 0.25, "historical_operator_strength": 0.20, "futures_squeeze": 0.00},
}


def weighted_score(values: dict[str, float], weights: dict[str, float]) -> float | None:
    present = [(values[name], weight) for name, weight in weights.items() if name in values and weight > 0]
    if not present:
        return None
    denominator = sum(weight for _, weight in present)
    return 100.0 * sum(value * weight for value, weight in present) / denominator
```

Cash-out risk uses `dev_concentration`, `insider_concentration`, `adverse_flow`, `audit_risk`, `liquidity_risk`, `abnormal_turnover`, `crowded_longs`, and `unlock_risk`. Return each contribution and input evidence ID. Coverage uses expected feature weights and freshness/confidence multipliers.

Use this cash-out-risk matrix:

```python
CASHOUT_WEIGHTS = {
    "7d": {"dev_concentration": 0.20, "insider_concentration": 0.15, "adverse_flow": 0.20, "audit_risk": 0.15, "liquidity_risk": 0.10, "abnormal_turnover": 0.05, "crowded_longs": 0.15, "unlock_risk": 0.00},
    "30d": {"dev_concentration": 0.20, "insider_concentration": 0.15, "adverse_flow": 0.15, "audit_risk": 0.15, "liquidity_risk": 0.10, "abnormal_turnover": 0.05, "crowded_longs": 0.10, "unlock_risk": 0.10},
    "90d": {"dev_concentration": 0.20, "insider_concentration": 0.15, "adverse_flow": 0.10, "audit_risk": 0.15, "liquidity_risk": 0.10, "abnormal_turnover": 0.05, "crowded_longs": 0.05, "unlock_risk": 0.20},
}
```

`derive_market_features()` clamps every component to `[0, 1]` and uses these formulas with observed-input renormalization:

- `floor = 0.45 * inverse_market_cap_percentile + 0.35 * drawdown_from_peak + 0.20 * proximity_to_90d_low`;
- `washout = 0.50 * drawdown_from_prior_rally + 0.30 * volume_contraction + 0.20 * recent_price_stability`;
- `control = normalized_top10_holder_percent`, with separate developer and insider evidence reserved for cash-out risk;
- `accumulation = 0.40 * smart_money_inflow_percentile + 0.30 * buy_volume_ratio + 0.20 * holder_growth + 0.10 * concentration_change`;
- `historical_operator_strength = 0.60 * normalized_max_rolling_7d_return + 0.40 * normalized_repeat_rally_count`;
- `futures_squeeze = 0.35 * negative_funding_score + 0.35 * open_interest_price_divergence + 0.30 * short_crowding_score`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `conda run -n polybob python -m pytest tests/unit/test_altcoin_scoring.py -q`

Expected: all tests pass and the score matrix sums to 1.0 for every horizon.

- [ ] **Step 5: Commit**

```bash
git add libs/crypto/discovery/scoring.py tests/unit/test_altcoin_scoring.py
git commit -m "feat: add explainable altcoin scores"
```

## Task 5: Structural Trade Plans and Three Risk Modes

**Files:**
- Create: `libs/crypto/discovery/trade_plan.py`
- Test: `tests/unit/test_altcoin_trade_plan.py`

- [ ] **Step 1: Write failing gate and sizing tests**

```python
from libs.crypto.discovery.trade_plan import build_trade_plan


def test_trade_plan_requires_score_risk_coverage_and_reward_ratio():
    result = build_trade_plan(
        closes=[8.0, 8.2, 8.1, 8.4, 8.3, 8.5, 8.6, 8.4, 8.7, 8.8, 8.9, 9.0, 9.1, 9.0, 9.2],
        highs=[8.2, 8.4, 8.3, 8.6, 8.5, 8.7, 8.8, 8.6, 8.9, 9.0, 9.1, 9.2, 9.3, 9.2, 9.4],
        lows=[7.8, 8.0, 7.9, 8.2, 8.1, 8.3, 8.4, 8.2, 8.5, 8.6, 8.7, 8.8, 8.9, 8.8, 9.0],
        volumes=[1000.0] * 15,
        pump_potential=80.0,
        cashout_risk=30.0,
        coverage=0.85,
        account_equity=10_000.0,
        volume_24h_usd=5_000_000.0,
        quantity_step=0.1,
    )
    assert result.eligible is True
    assert set(result.position_sizes) == {"conservative", "balanced", "aggressive"}
    assert result.position_sizes["balanced"].risk_fraction == 0.01


def test_missing_equity_keeps_levels_but_not_fake_quantity():
    result = build_trade_plan(
        closes=[10.0] * 15,
        highs=[10.5] * 15,
        lows=[9.5] * 15,
        volumes=[1000.0] * 15,
        pump_potential=80.0,
        cashout_risk=30.0,
        coverage=0.85,
        account_equity=None,
        volume_24h_usd=5_000_000.0,
        quantity_step=0.1,
    )
    assert all(size.quantity is None for size in result.position_sizes.values())
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n polybob python -m pytest tests/unit/test_altcoin_trade_plan.py -q`

Expected: import fails for `libs.crypto.discovery.trade_plan`.

- [ ] **Step 3: Implement ATR, anchored VWAP, support, stop, targets, and sizing**

Use pure functions. Reject fewer than 15 candles. Entry is the overlap of the recent support band and anchored VWAP band; stop is below support by `0.25 * ATR`; target 1 is the nearest swing resistance preserving reward/risk 2.0; target 2 is the prior high. Apply quantity-step floor rounding and the `0.05%` 24-hour volume cap. Return exact veto codes for score, risk, coverage, missing structure, overextension, liquidity, and reward/risk.

```python
RISK_FRACTIONS = {"conservative": 0.005, "balanced": 0.01, "aggressive": 0.02}


def risk_quantity(equity: float, fraction: float, entry: float, stop: float) -> float:
    distance = abs(entry - stop)
    if distance <= 0:
        raise ValueError("entry and stop must differ")
    return equity * fraction / distance
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `conda run -n polybob python -m pytest tests/unit/test_altcoin_trade_plan.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add libs/crypto/discovery/trade_plan.py tests/unit/test_altcoin_trade_plan.py
git commit -m "feat: add altcoin trade plans"
```

## Task 6: Discovery Service, Caching, and API Routes

**Files:**
- Create: `libs/crypto/discovery/service.py`
- Modify: `apps/api/main.py`
- Test: `tests/test_altcoin_discovery_service.py`
- Test: `tests/test_api_altcoin_discovery.py`

- [ ] **Step 1: Write failing degradation and API tests**

```python
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from apps.api import main
from libs.crypto.discovery.models import AlphaToken, DiscoverySnapshot, FuturesContract, ProviderHealth
from libs.crypto.discovery.service import AltcoinDiscoveryService


class FakeAlphaProvider:
    async def list_alpha_tokens(self, chain_id: str):
        if chain_id == "8453":
            raise TimeoutError("connect timeout")
        if chain_id == "56":
            return [AlphaToken(chain_id="56", contract_address="0xabc", symbol="VELVET", is_alpha=True)]
        return []


class FakeFuturesProvider:
    async def list_perpetuals(self):
        return [FuturesContract(symbol="VELVETUSDT", base_asset="VELVET", quote_asset="USDT", status="TRADING")]


class UnavailableDiscoveryService:
    async def get_snapshot(self):
        return DiscoverySnapshot(
            status="unavailable",
            observed_at=datetime.now(timezone.utc),
            candidates=[],
            source_health={"binance_alpha": ProviderHealth(status="unavailable", provider="binance_alpha")},
        )


@pytest.mark.asyncio
async def test_one_chain_failure_keeps_other_chains_visible():
    service = AltcoinDiscoveryService(
        alpha_provider=FakeAlphaProvider(),
        futures_provider=FakeFuturesProvider(),
        chain_ids=("1", "56", "8453", "CT_501"),
    )
    snapshot = await service.refresh()
    assert snapshot.status == "degraded"
    assert snapshot.chain_health["8453"].status == "unavailable"
    assert any(item.chain_id == "56" for item in snapshot.candidates)


def test_list_route_does_not_return_false_success_when_unavailable(monkeypatch):
    monkeypatch.setattr(main, "altcoin_discovery", UnavailableDiscoveryService())
    response = TestClient(main.app).get("/api/crypto/altcoin-discovery")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["candidates"] == []
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n polybob python -m pytest tests/test_altcoin_discovery_service.py tests/test_api_altcoin_discovery.py -q`

Expected: service imports or routes fail because they do not exist.

- [ ] **Step 3: Implement service orchestration**

The service owns one `httpx.AsyncClient`, a refresh lock, snapshot timestamps, and caches keyed by provider/asset. `refresh()` fetches all four Alpha chains and futures exchange info concurrently, builds the universe, fetches batch futures market data, computes evidence and scores, and atomically swaps the last successful snapshot. Detail enrichment loads dynamic token, DEX, chain, funding, open-interest, and K-line evidence only for the selected asset.

Use monotonic TTLs: universe 300 seconds, market 10 seconds, K-lines 900 seconds, futures features 300 seconds, chain evidence 600 seconds, detail 300 seconds. A stale snapshot remains available with `status="degraded"`; no snapshot plus unavailable core providers yields HTTP 503.

- [ ] **Step 4: Add lifecycle and routes**

Add `altcoin_discovery: AltcoinDiscoveryService | None`, initialize it without blocking full startup, close its client during shutdown, and expose:

```python
@app.get("/api/crypto/altcoin-discovery")
async def get_altcoin_discovery():
    service = require_altcoin_discovery()
    snapshot = await service.get_snapshot()
    if snapshot.status == "unavailable":
        return JSONResponse(status_code=503, content=snapshot.model_dump(mode="json"))
    return snapshot


@app.get("/api/crypto/altcoin-discovery/status")
async def get_altcoin_discovery_status():
    return require_altcoin_discovery().get_status()


@app.get("/api/crypto/altcoin-discovery/{asset_id:path}")
async def get_altcoin_discovery_detail(asset_id: str):
    detail = await require_altcoin_discovery().get_detail(asset_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="asset not found")
    return detail
```

- [ ] **Step 5: Run service and API tests and verify GREEN**

Run: `conda run -n polybob python -m pytest tests/test_altcoin_discovery_service.py tests/test_api_altcoin_discovery.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add libs/crypto/discovery/service.py apps/api/main.py tests/test_altcoin_discovery_service.py tests/test_api_altcoin_discovery.py
git commit -m "feat: expose altcoin discovery API"
```

## Task 7: Frontend Contract, Navigation, and Routes

**Files:**
- Create: `apps/dashboard/domain/altcoinDiscovery/workbench.ts`
- Create: `apps/dashboard/domain/altcoinDiscovery/workbench.test.ts`
- Create: `apps/dashboard/app/crypto/page.tsx`
- Create: `apps/dashboard/app/crypto/altcoin-discovery/page.tsx`
- Modify: `apps/dashboard/components/PrimaryNav.tsx`

- [ ] **Step 1: Write failing strict-parser tests**

```typescript
import { describe, expect, it } from 'vitest';
import { parseAltcoinDiscovery } from './workbench';

describe('altcoin discovery contract', () => {
  it('preserves three horizons and no-plan vetoes', () => {
    const parsed = parseAltcoinDiscovery({
      status: 'degraded',
      observed_at: '2026-06-27T12:00:00Z',
      candidates: [{
        asset_id: '56:0xabc', chain_id: '56', symbol: 'VELVET', futures_symbol: 'VELVETUSDT',
        price: 1.45, market_cap: 1450000000, coverage: 0.68, confidence: 0.7,
        pump_potential: { '7d': 72, '30d': 75, '90d': 65 },
        cashout_risk: { '7d': 48, '30d': 50, '90d': 55 },
        status: 'data_insufficient', vetoes: ['COVERAGE_BELOW_MINIMUM'], trade_plans: {},
      }],
      source_health: {},
    });
    expect(parsed.candidates[0].pumpPotential['30d']).toBe(75);
    expect(parsed.candidates[0].tradePlans['30d']).toBeUndefined();
    expect(parsed.candidates[0].vetoes).toContain('COVERAGE_BELOW_MINIMUM');
  });

  it('never invents candidates for malformed payloads', () => {
    expect(parseAltcoinDiscovery({ status: 'ok' }).candidates).toEqual([]);
  });
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd apps/dashboard && npm test -- domain/altcoinDiscovery/workbench.test.ts`

Expected: module resolution fails because the domain file does not exist.

- [ ] **Step 3: Implement parser and bilingual display dictionaries**

Define exact types for `Horizon`, `CandidateStatus`, `SourceHealth`, `TradePlan`, `PositionSize`, and `AltcoinDiscoveryWorkbench`. Parse numbers only when finite, preserve unknown status as unavailable, and never synthesize prices, scores, plans, or source success.

- [ ] **Step 4: Add Crypto navigation and server routes**

Insert `{ href: '/crypto', label: { en: 'Crypto', zh: '加密货币' } }` after Polymarket. The Crypto index describes its submodules operationally and links to Altcoin Discovery. The discovery route performs one server fetch with `cache: 'no-store'`, a 15-second timeout, and an explicit unavailable payload on API failure.

- [ ] **Step 5: Run parser tests and build**

Run: `cd apps/dashboard && npm test -- domain/altcoinDiscovery/workbench.test.ts && npm run build`

Expected: parser tests pass and Next.js lists `/crypto` and `/crypto/altcoin-discovery` in build output.

- [ ] **Step 6: Commit**

```bash
git add apps/dashboard/domain/altcoinDiscovery apps/dashboard/app/crypto apps/dashboard/components/PrimaryNav.tsx
git commit -m "feat: add crypto discovery routes"
```

## Task 8: Responsive Discovery Workbench

**Files:**
- Create: `apps/dashboard/components/AltcoinDiscoveryWorkspace.tsx`
- Modify: `apps/dashboard/app/crypto/altcoin-discovery/page.tsx`
- Modify: `apps/dashboard/app/globals.css`
- Test: `apps/dashboard/domain/altcoinDiscovery/workbench.test.ts`

- [ ] **Step 1: Extend tests for ordering and core conclusion**

```typescript
import {
  buildCoreConclusion,
  sortCandidates,
  type AltcoinCandidate,
} from './workbench';

function candidate(overrides: Partial<AltcoinCandidate>): AltcoinCandidate {
  return {
    assetId: '56:0xabc',
    chainId: '56',
    symbol: 'TEST',
    futuresSymbol: 'TESTUSDT',
    price: 1,
    marketCap: 1_000_000,
    coverage: 0.8,
    confidence: 0.8,
    pumpPotential: { '7d': 50, '30d': 50, '90d': 50 },
    cashoutRisk: { '7d': 50, '30d': 50, '90d': 50 },
    status: 'watch',
    vetoes: [],
    tradePlans: {},
    ...overrides,
  };
}

it('orders executable candidates before watches and vetoes', () => {
  const ordered = sortCandidates([
    candidate({ symbol: 'C', status: 'vetoed' }),
    candidate({ symbol: 'A', status: 'trade_eligible' }),
    candidate({ symbol: 'B', status: 'watch' }),
  ], '30d');
  expect(ordered.map((item) => item.symbol)).toEqual(['A', 'B', 'C']);
});

it('names the exact blocker when no trade plan exists', () => {
  expect(buildCoreConclusion(candidate({
    status: 'data_insufficient',
    vetoes: ['COVERAGE_BELOW_MINIMUM'],
  }), 'zh')).toContain('数据覆盖率');
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd apps/dashboard && npm test -- domain/altcoinDiscovery/workbench.test.ts`

Expected: missing exported helpers fail the tests.

- [ ] **Step 3: Implement the list/detail workbench**

The component must provide:

- one first-row core conclusion plus pump potential, cash-out risk, coverage, and freshness;
- horizon segmented control, chain/status filters, search, refresh, and provider-health button;
- a stable-width candidate table with chain, price, market cap, three horizon scores, risk, coverage, and status;
- selected detail with entry range, structural stop, targets, reward/risk, conservative/balanced/aggressive sizes, vetoes, score decomposition, and source lineage;
- no-plan text that names each blocking code;
- a mobile list/detail segmented view and sticky selected summary;
- bilingual labels driven by `useLanguage()`.

Use semantic buttons and existing `.panel`/`.metric-panel` primitives. Keep radii at 8px or below for new workbench surfaces. Do not add a hero, marketing copy, nested cards, decorative gradients, or fake chart data.

- [ ] **Step 4: Add polling without refresh storms**

Use `usePolling()` at 10 seconds for the list. Selection fetches detail once and aborts the previous request on change. Hidden tabs pause polling. A failed refresh keeps the previous snapshot, changes source health to stale/unavailable, and displays the failure without clearing the table.

- [ ] **Step 5: Run frontend tests and build**

Run: `cd apps/dashboard && npm test && npm run build`

Expected: all Vitest tests pass and the production build succeeds without TypeScript errors.

- [ ] **Step 6: Commit**

```bash
git add apps/dashboard/components/AltcoinDiscoveryWorkspace.tsx apps/dashboard/app/crypto/altcoin-discovery/page.tsx apps/dashboard/app/globals.css apps/dashboard/domain/altcoinDiscovery
git commit -m "feat: build altcoin discovery workbench"
```

## Task 9: Full Verification and Live Browser Acceptance

**Files:**
- Modify only files proven necessary by failing verification.
- Record: `docs/altcoin-discovery-verification.md`

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
conda run -n polybob python -m pytest \
  tests/test_discovery_networking.py \
  tests/test_altcoin_providers.py \
  tests/unit/test_altcoin_universe.py \
  tests/unit/test_altcoin_scoring.py \
  tests/unit/test_altcoin_trade_plan.py \
  tests/test_altcoin_discovery_service.py \
  tests/test_api_altcoin_discovery.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the complete backend suite**

Run: `conda run -n polybob python -m pytest -q`

Expected: all project tests pass; only pre-existing explicitly skipped tests may remain skipped.

- [ ] **Step 3: Run complete frontend verification**

Run: `cd apps/dashboard && npm test && npm run build`

Expected: all tests pass and the build succeeds.

- [ ] **Step 4: Restart the production-mode local stack**

Stop the current `start-all.sh` session cleanly, then run `./start-all.sh`. Confirm API health on `http://127.0.0.1:18000/` and dashboard health on `http://127.0.0.1:13001/crypto/altcoin-discovery`.

- [ ] **Step 5: Verify live provider evidence**

Request the list and status endpoints. Verify:

- Alpha count is non-zero on each current chain when the provider reports tokens;
- every trade-visible row has Alpha evidence and a live USDⓈ-M mapping;
- no candidate contains a source value labeled observed when its provider failed;
- source health shows the detected proxy without credentials;
- a selected candidate detail contains real timestamps and source lineage;
- 7-day, 30-day, and 90-day scores are present only when coverage permits;
- all three risk modes share the same structural entry and stop.

- [ ] **Step 6: Verify desktop and mobile UI in the in-app browser**

At `1440x900` and `390x844`, verify navigation, filters, list/detail switching, selected candidate, source-health drilldown, Chinese/English switching, horizontal overflow, sticky summary, and no element overlap. Confirm the browser console has no errors and failed network requests are explained by the UI.

- [ ] **Step 7: Write the verification record**

Record commands, pass counts, live chain counts, source statuses, browser viewport results, and any residual external-provider limitations in `docs/altcoin-discovery-verification.md`. Do not call the feature complete if any acceptance criterion lacks direct evidence.

- [ ] **Step 8: Commit verification-only fixes and record**

```bash
git add docs/altcoin-discovery-verification.md
git commit -m "test: verify altcoin discovery end to end"
```
