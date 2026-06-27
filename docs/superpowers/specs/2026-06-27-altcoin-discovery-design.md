# PolyBob Altcoin Discovery Design

## Objective

Add a first-class `Crypto` module to PolyBob with an `Altcoin Discovery` submodule. The submodule must discover research candidates from the live intersection of Binance Alpha and actively traded Binance USDⓈ-M perpetual contracts, evaluate them over 7-day, 30-day, and 90-day horizons, and expose both a research ranking and risk-sized trade plans.

Production responses must contain only observed or derived real data. Missing evidence is represented as unavailable and reduces coverage; it is never replaced by fabricated values, static recommendations, or silent zeroes.

## Product Boundary

The first release supports research and paper decision support. It does not submit live exchange orders.

The module has two outputs:

1. A ranked research watchlist with evidence, source freshness, coverage, vetoes, pump-potential scores, and cash-out-risk scores.
2. A trade plan for candidates that pass every eligibility gate, including an entry zone, structural stop, targets, reward/risk ratio, invalidation reason, and position limits for 0.5%, 1%, and 2% account-risk modes.

The UI must not describe inferred concentration or historical behavior as proof that a specific market maker or project team will pump a token. It presents observable evidence and labels behavioral conclusions as model inferences.

## Universe

The universe is recalculated from live provider responses. An asset is eligible for ranking only when all of the following are true:

- the Binance Alpha response includes the `Alpha` community-recognition tag;
- a Binance USDⓈ-M symbol has `contractType=PERPETUAL`, `status=TRADING`, and `quoteAsset=USDT`;
- the Alpha token and futures base asset can be mapped uniquely;
- the token is not blacklisted by the Binance Web3 metadata response.

Exact case-insensitive symbol matches are accepted. Symbol normalization uses Unicode NFC plus case folding; it never drops non-ASCII characters, and an empty normalized key is rejected. Contract multiplier symbols such as `1000*`, `1000000*`, and `1M*` are accepted only through an explicit normalizer and only when one Alpha token maps to one futures symbol. Duplicate symbols, multiple chain contracts, or multiple possible futures matches remain visible as `mapping_ambiguous` and are ineligible for a trade plan until disambiguated.

The current Binance Web3 Alpha provider supports Ethereum (`1`), BNB Chain (`56`), Base (`8453`), and Solana (`CT_501`). These are the complete first-release chain set. Chain coverage is provider-driven so a newly announced Alpha chain can be added as an adapter without changing the scoring domain.

## Architecture

### Backend Units

- `libs/crypto/discovery/models.py`: typed provider observations, evidence, candidates, scores, trade plans, and source-health records.
- `libs/crypto/discovery/providers/binance_alpha.py`: paginated Alpha ranking, token metadata, dynamic token facts, K-lines, and smart-money rank ingestion.
- `libs/crypto/discovery/providers/binance_futures.py`: exchange metadata, ticker, K-lines, funding, open interest, and long/short observations.
- `libs/crypto/discovery/providers/dex_screener.py`: DEX pair price, liquidity, volume, and pair-age evidence.
- `libs/crypto/discovery/providers/evm.py`: Ethereum, BNB Chain, and Base RPC evidence adapters.
- `libs/crypto/discovery/providers/solana.py`: Solana RPC evidence adapter.
- `libs/crypto/discovery/universe.py`: deterministic Alpha/futures intersection and ambiguity handling.
- `libs/crypto/discovery/scoring.py`: evidence normalization, horizon-specific dual-axis scoring, coverage, and vetoes.
- `libs/crypto/discovery/trade_plan.py`: structural entry, stop, target, reward/risk, and three risk-mode position limits.
- `libs/crypto/discovery/service.py`: concurrent refresh orchestration, TTL caches, stale-while-revalidate behavior, and source diagnostics.
- `libs/networking.py`: outbound proxy resolution and shared network-error classification.

The existing FastAPI app owns the service lifecycle and exposes read-only discovery endpoints. Provider code does not import FastAPI or dashboard types.

### API Surface

- `GET /api/crypto/altcoin-discovery`: source health, refresh time, universe counts, filters, and ranked candidate summaries.
- `GET /api/crypto/altcoin-discovery/{asset_id}`: complete evidence, raw source fields, horizon scores, vetoes, and trade plans for one chain-specific contract.
- `GET /api/crypto/altcoin-discovery/status`: provider availability, freshness, latency, last success, last failure classification, and remediation text.

`asset_id` is chain-specific and combines chain ID with contract address. Symbol alone is never a primary key.

### Frontend Units

- `app/crypto/page.tsx`: Crypto module entry and operational summary.
- `app/crypto/altcoin-discovery/page.tsx`: Altcoin Discovery route.
- `components/AltcoinDiscoveryWorkspace.tsx`: list/detail workbench and responsive interaction.
- `domain/altcoinDiscovery/workbench.ts`: API types, parsing, display state, and bilingual labels.

The primary navigation gains `Crypto / 加密货币`. The Crypto page exposes `Altcoin Discovery / 山寨币发现` as a submodule rather than adding another unrelated top-level route.

## Data Sources

The primary sources are:

- Binance Skills Hub documented Web3 endpoints for Alpha rank, token search, static metadata, dynamic market facts, K-lines, smart-money inflow, and address performance;
- Binance USDⓈ-M public REST endpoints for exchange information, market price, K-lines, funding, open interest, and participant ratios;
- DEX Screener public token-pair endpoints for independent DEX liquidity and volume evidence;
- chain RPC methods for contract supply, balances, token-holder concentration, and transfer history where public RPC capability permits;
- free registered explorer or RPC APIs as optional evidence enrichers.

Every observation includes `provider`, `field`, `observed_at`, `received_at`, `freshness`, `status`, and the original value. Derived evidence also records its input observation IDs.

Provider capabilities are enforced per chain rather than inferred from a successful undocumented request. The current official Binance Skills Hub client allows smart-money inflow on BNB Chain, Base, and Solana, but not Ethereum. An Ethereum response observed by calling the upstream route directly is not used as authoritative evidence until the official client capability matrix includes that chain. The missing Ethereum feature reduces evidence coverage and is visible in source health.

Binance Web3 and standard Binance hosts are not directly reachable on the current machine without the configured macOS proxy, while `data-api.binance.vision` is reachable directly. `libs/networking.py` therefore resolves outbound proxy settings in this order:

1. `POLYBOB_OUTBOUND_PROXY`;
2. `HTTPS_PROXY` or `ALL_PROXY`;
3. enabled macOS HTTPS proxy from `scutil --proxy` when running on Darwin;
4. direct connection.

The status endpoint distinguishes DNS, connect timeout, TLS timeout, proxy refusal, HTTP 403, HTTP 418/429, HTTP 5xx, malformed payload, and schema mismatch. Credentials embedded in proxy URLs are never returned to the UI or logs.

## Refresh and Performance

- Alpha pages and futures exchange metadata: 5-minute TTL.
- Batch market snapshots: 10-second TTL.
- Daily K-lines and horizon features: 15-minute TTL.
- funding and open-interest history: 5-minute TTL.
- chain and holder evidence: 10-minute TTL.
- token detail enrichment: loaded on selection and cached for 5 minutes.

Refreshes use bounded concurrency, per-provider timeouts, retry only for transient errors, and per-key request coalescing. The list endpoint serves the last successful snapshot with an explicit stale badge while a background refresh runs. It never blocks every page request on a full multi-chain scan.

## Evidence Model

Each feature is normalized to `[0, 1]`. Missing inputs are excluded from the weighted numerator and denominator. Coverage is the sum of observed feature weights divided by all expected feature weights. Confidence combines source quality, freshness, mapping confidence, and feature coverage.

### Floor and Washout

- inverse market-cap percentile within the eligible universe;
- drawdown from the trailing 180-day high;
- distance from the trailing 90-day low;
- 14-day realized-volatility compression relative to the prior 60 days;
- volume contraction followed by non-price-expanding accumulation.

Low market cap is an opportunity input, not proof that an asset cannot fall further.

### Control and Accumulation

- top-10 holder percentage after known burn, bridge, LP, and exchange addresses are excluded when labels exist;
- developer, insider, sniper, bundle, KOL, and professional-holder percentages from observed provider fields;
- smart-money net inflow percentile;
- buy/sell volume imbalance;
- holder-count change when historical observations exist;
- concentration change rather than concentration level alone.

Concentration can raise pump potential. Developer and insider concentration also raises cash-out risk. The two effects are shown separately and never netted into one opaque score.

### Historical Operator Inference

- maximum rolling 7-day and 30-day return over the trailing 180 days;
- speed and volume expansion of prior rallies;
- retracement from the most recent qualifying rally;
- stabilization after retracement;
- repeat rally count.

This feature is labeled `historical_operator_strength`; it is not presented as identification of a real-world market maker.

### Futures Squeeze

- funding-rate percentile and sign;
- open-interest change versus price change;
- global and top-trader long/short ratios;
- basis or premium;
- volume and realized-volatility expansion.

The squeeze score rewards conditions such as rising open interest with stable price and non-crowded long positioning. Extremely positive funding and crowded longs increase cash-out risk.

## Scores

Component scores are `floor`, `washout`, `control`, `accumulation`, `historical_operator_strength`, `futures_squeeze`, and `liquidity_quality`.

Pump-potential weights:

| Component | 7 days | 30 days | 90 days |
|---|---:|---:|---:|
| floor | 10% | 20% | 25% |
| washout | 15% | 20% | 15% |
| control | 20% | 15% | 15% |
| accumulation | 20% | 25% | 25% |
| historical operator strength | 10% | 15% | 20% |
| futures squeeze | 25% | 5% | 0% |

Cash-out risk is horizon-specific and combines developer/insider concentration, adverse exchange or smart-money flows, audit risk, low liquidity, abnormal turnover, crowded futures positioning, and known unlock evidence. Missing unlock evidence reduces coverage rather than asserting that no unlock exists.

Scores are rounded only for display. Sorting uses full-precision values. The API returns component values and weights so every score is explainable.

## Vetoes and Eligibility

A candidate is research-visible but trade-ineligible when any of these conditions applies:

- ambiguous token-to-futures mapping;
- stale Binance market data;
- score coverage below 70%;
- critical Binance audit risk or blacklist flag;
- liquidity below USD 500,000;
- trailing 24-hour volume below USD 1,000,000;
- observed developer or insider transfer to an exchange above 1% of circulating supply in 24 hours;
- unlocked or removable LP representing more than 50% of usable liquidity when that evidence is available;
- no valid structural stop or reward/risk below 2.0;
- current price more than 1.5 daily ATR above the proposed entry-zone ceiling.

Thresholds are configuration values returned by the API and displayed in Settings. Changing a threshold does not mutate historical observations.

## Trade Plan

A trade plan is generated independently for each horizon only when pump potential is at least 70, cash-out risk is at most 45, coverage is at least 70%, and no veto is active.

- Entry zone: overlap of a recent support cluster, anchored VWAP area, and no more than 0.5 ATR above support.
- Structural stop: below the support/invalidation level with an ATR buffer; it is not a fixed arbitrary percentage.
- Target 1: nearest material resistance that preserves reward/risk of at least 2.0.
- Target 2: prior swing high or measured range expansion.
- Position size: `account_equity * risk_fraction / abs(entry_mid - stop)` converted to contracts.
- Liquidity cap: the smaller of risk-derived size and 0.05% of trailing 24-hour USD volume.
- Risk modes: `conservative=0.5%`, `balanced=1%`, `aggressive=2%` account loss at the structural stop.

Account equity is read from PolyBob's portfolio ledger or an explicit user-entered risk-capital value. The value is blank by default when neither source exists. In that state the plan still exposes structural prices and all three risk percentages, but contract quantities remain unavailable rather than assuming a fictional account balance.

The plan returns a range, not a promise of execution. Fees, funding, estimated slippage, and contract quantity filters are included in the displayed risk estimate.

No win probability is shown until a leakage-safe rolling backtest has calibrated the score against forward 7-day, 30-day, and 90-day outcomes. Until then, the UI displays score, evidence coverage, and realized reward/risk only.

## User Experience

The desktop workbench uses a dense list/detail layout:

1. First row: one core conclusion, selected horizon pump potential, cash-out risk, and data coverage.
2. Toolbar: horizon, chain, status, risk mode, search, refresh, and source health.
3. Left pane: ranked candidates ordered by `trade eligible`, `watch`, `data insufficient`, then `vetoed`.
4. Right pane: selected asset trade plan, three risk-mode position limits, score decomposition, evidence, vetoes, and source lineage.

The detail pane never shows entry, stop, or target placeholders as configured values. When no plan is valid it shows the exact blocking conditions.

On mobile, list and detail become segmented views with a sticky selected-asset summary. Tables scroll horizontally only where column preservation is necessary. Chinese and English labels cover navigation, filters, empty states, errors, score components, source states, and trade-plan fields.

## Failure Handling

- One provider or chain failure degrades only affected evidence and candidates.
- The list remains available from the last successful snapshot with source-specific stale state.
- A provider schema change is reported as `schema_mismatch`, includes the missing field path, and suppresses dependent scores.
- Rate limits honor `Retry-After` and do not trigger immediate retry storms.
- A complete lack of live Alpha or futures universe data returns an unavailable state, never an empty successful list.
- API errors include likely cause, affected provider, diagnostic evidence, and an actionable remediation message.

## Testing

Backend tests follow TDD and cover:

- Alpha pagination across all four current chains;
- exact, multiplier, duplicate, and ambiguous futures mappings;
- Unicode symbols, empty normalized keys, and non-ASCII futures symbols;
- missing evidence and coverage renormalization;
- 7-day, 30-day, and 90-day weight selection;
- concentration increasing both potential and risk through separate paths;
- every veto and trade-plan gate;
- structural entry/stop/target calculations and all three risk modes;
- proxy resolution and network-error classification;
- stale-while-revalidate and per-provider degradation;
- API success, degraded, unavailable, and schema-mismatch contracts.

Provider contract fixtures are captured from real responses, minimized, and labeled with source and capture time. They are test evidence, not production fallback data. Optional live smoke tests verify current provider schemas but are excluded from the deterministic default suite.

Frontend tests cover parsing, bilingual labels, status ordering, no-plan explanations, and risk-mode calculations. Browser acceptance checks desktop and mobile layouts, route navigation, empty/degraded states, responsive behavior, network requests, and console errors.

Required final verification:

- `conda run -n polybob python -m pytest -q`;
- `npm test` in `apps/dashboard`;
- `npm run build` in `apps/dashboard`;
- live API smoke test through the detected outbound proxy;
- in-app browser verification of `/crypto` and `/crypto/altcoin-discovery` at desktop and mobile viewport widths.

## Acceptance Criteria

- Every ranked row proves both Alpha membership and a live Binance USDⓈ-M perpetual mapping.
- Ethereum, BNB Chain, Base, and Solana are queried and expose independent source health.
- Every candidate exposes 7-day, 30-day, and 90-day pump-potential, cash-out-risk, coverage, and confidence outputs when sufficient evidence exists.
- High concentration is visible in both opportunity and risk explanations.
- Eligible candidates expose conservative, balanced, and aggressive trade plans from the same structural levels.
- Missing or stale data cannot become a fabricated score, recommendation, price, or successful empty state.
- The UI presents one core conclusion before supporting detail and remains usable at desktop and mobile widths.
- All required automated, build, live-data, and browser checks pass.
