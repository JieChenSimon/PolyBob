# PolyBob Order Book Platform and Analysis Plan

## Core Conclusion

Order book analysis should be built first as a trustworthy market-data platform, not as a chart widget. The current PolyBob code can show a shallow Polymarket book summary, but it does not yet have reliable order-book reconstruction, replay, gap detection, or source entitlement gates.

For equities, the current free providers are not enough for real order-book analysis:

- US equities: current Nasdaq, Finnhub, and Alpaca paths provide quotes, trades, or bars, not true L2 depth in the running product.
- A-shares: the current Sina path is not a production-grade order-book source and is not wired as a reliable depth feed.
- Polymarket: REST and WebSocket CLOB data make this the best first target, but the local reducer must handle snapshots, incremental updates, data freshness, and resync before conclusions become trustworthy.
- Futu: remains a researched future option. Do not enable it until the operator is ready to keep OpenD running and a live entitlement probe confirms depth, sessions, symbols, and quota.

The first user-facing conclusion should be narrow and defensible: current visible liquidity is usable, expensive, or unreliable, with evidence from spread, depth, imbalance, estimated book-walk cost, and data quality.

Do not let order-book signals directly claim long-term investment value, market manipulation, or guaranteed price direction.

## Current PolyBob Gaps

| Area | Current state | Required change |
| --- | --- | --- |
| Event schema | OrderbookTick has bids/asks but no provider, venue, event type, sequence, receive time, checksum, or quality state. | Add canonical BookEvent and BookState contracts. |
| Snapshot/update logic | Polymarket book is parsed; price_change is ignored. No gap recovery. | Implement snapshot plus incremental reducer with resync. |
| BBO validation | Code takes the first bid/ask after float parsing. | Sort by price, merge duplicate levels, reject invalid/crossed books. |
| Time semantics | Missing timestamps are replaced with local UTC time. | Keep missing exchange/provider timestamps as null and downgrade quality. |
| Event bus | In-memory publish waits for all handlers, with no backpressure. | Use bounded queues and per-instrument single-writer book rebuilders. |
| Frontend | Markets page polls every 15 seconds and receives only feature summaries. | Use REST snapshot plus WebSocket coalesced updates for the selected symbol. |
| Persistence | No raw order-book log or deterministic replay. | Store raw events and periodic book snapshots for replay and regression tests. |
| Equity data | Current free quote feeds do not provide reliable L2 depth. | Add provider capability gates and disable depth analysis when unsupported. |

## Data Capability Rules

Every provider must declare capability before it can power order-book UI:

| Capability | Meaning | UI behavior |
| --- | --- | --- |
| NONE | No bid/ask or depth. | Hide order-book analysis; show source does not support it. |
| L1 | BBO or latest quote only. | Show spread, BBO size, freshness, basic microprice if sizes exist. |
| L2_AGGREGATED | Multi-level price/size depth. | Enable depth, imbalance, book-walk cost, slope, resiliency. |
| L3_MBO | Order-level events. | Enable queue/order-lifetime research only in lab mode. |

Required metadata: provider, venue, instrument, coverage, book_level, session, exchange_ts, provider_ts, receive_ts, monotonic_receive_ts, sequence or explicit no_sequence_available, and integrity_status.

If a source does not expose reliable sequence or checksum data, it can still be used as an atomic snapshot source, but it cannot support order-flow or cancel-rate claims.

## Architecture

~~~text
Venue adapters
  -> bounded raw event queues
  -> per-instrument sequencer/rebuilder
  -> canonical book state + quality state
  -> append-only raw log and periodic snapshots
  -> microstructure feature engine
  -> hot cache
  -> REST snapshot + WebSocket fanout
  -> focused UI for active/favorite symbols
~~~

Important implementation rules:

- One backend connection per provider, then fan out to browser clients.
- One single writer per venue plus instrument book.
- Active symbol gets highest priority; favorites and strategy symbols are second priority.
- UI updates should be coalesced to 10-20 Hz instead of rendering every event.
- Raw event queues must not silently drop canonical book events. Overflow means mark the book stale and resync.
- UI queues may drop intermediate states if the latest version is preserved.
- Store prices as integer ticks where possible, not floating-point book keys.

## Analysis Metrics

### P0: Build First

These are useful with reliable L1 or Polymarket CLOB reconstruction:

- data source, venue, session, freshness, and integrity status
- bid, ask, mid, spread, spread bps
- BBO size
- L1 imbalance
- microprice and microprice deviation from mid
- crossed, locked, stale, and gap detection
- core conclusion: usable, expensive, or unreliable

### P1: Enable After Reliable L2

These require trustworthy multi-level depth:

- top 5 and top 10 cumulative depth
- cumulative depth inside 5, 10, and 25 bps bands
- multi-level imbalance
- depth concentration
- visible book-walk VWAP for configured order sizes
- estimated visible slippage and remaining unfilled amount
- liquidity slope
- 1, 5, and 30 second order-flow imbalance, only when update semantics allow it
- resiliency: time for spread, depth, or microprice to return to baseline

### P2: Lab Only

These need richer event history or L3 data:

- queue position estimates
- order add/cancel/execute intensity
- order lifetime
- fleeting-liquidity patterns
- layering-like patterns
- cross-venue depth dispersion

P2 outputs must be labelled as research. They must not accuse spoofing or market manipulation.

## UI and UX Positioning

The order-book page should be a dense trading workbench, not a generic report. The top region should show one conclusion:

- Liquidity: usable
- Execution cost: high
- Data quality: stale
- Depth unavailable for this provider

Recommended layout:

1. Header: symbol/market, session, source, freshness, integrity status.
2. Core conclusion strip: one sentence with severity and invalidation reason.
3. Live book ladder: bid/ask depth, cumulative size, spread, selected order size.
4. Execution cost panel: book-walk cost for small/medium/custom size.
5. Pressure panel: imbalance, microprice deviation, OFI if valid.
6. Reliability panel: source, sequence/gap state, latency, last resync.
7. Historical micro chart: spread, depth, microprice deviation over the current session.

For unsupported equities, the UI should explicitly say: Current provider has no verified order-book depth. PolyBob is showing quote data only and will not produce order-book conclusions.

## Current Low-Cost Equity Delivery

The active equity implementation deliberately uses a low-cost, best-effort path without pretending it is official full-depth market data:

- A-shares use real Eastmoney/AkShare same-source five-level bid/ask fields and are exposed as `L1_5_DEPTH`.
- If the real five-level request fails, A-shares return unavailable. Do not fall back to BBO, candles, latest price, or inferred depth as a substitute for盘口.
- US equities without IBKR market depth credentials return `QUOTE_ONLY`. The UI must show that no verified order-book source is configured.
- IBKR remains the preferred future US equity depth source, but it is no longer a default dependency because the current operator does not have an IBKR account.
- Futu remains deferred and must not be used as a default route because it requires keeping OpenD running.

This path is intentionally not exchange-grade L2. The product can use it for盘口线索, spread, BBO or five-level imbalance, and short-horizon liquidity warnings. It must not label it as consolidated depth, NBBO depth, or full order book.

## Non-Goals

- Do not synthesize order books from last price, bars, or candles.
- Do not combine asynchronous providers into a fake consolidated L2 book.
- Do not call IEX-only or single-provider depth NBBO unless the feed proves it.
- Do not infer hidden liquidity, dark-pool activity, or trader identity.
- Do not classify spoofing as fact.
- Do not output precise execution-quality conclusions without bid/ask depth.
- Do not let order-book metrics decide long-term holding quality by themselves.

## Validation Gates

Before this becomes a core feature:

1. Replay real Polymarket book plus price_change streams and reconcile final book against REST snapshots.
2. Verify best_bid equals max(bids) and best_ask equals min(asks) for every event.
3. Inject duplicate, missing, out-of-order, and delayed messages.
4. Confirm stale/gap states block analysis output.
5. Persist raw events and prove deterministic replay produces identical final book hashes.
6. Measure adapter-to-UI latency and render frequency.
7. Run provider entitlement probes for any future equity depth source.
8. Add UI tests for unsupported provider, stale data, live data, and resync.

Initial SLO targets:

| Metric | Target |
| --- | ---: |
| Adapter receive to canonical event | P99 <= 5 ms |
| Canonical event to in-memory book update | P99 <= 10 ms |
| Book update to feature calculation | P99 <= 15 ms |
| Backend receive to browser visible | P95 <= 100 ms, P99 <= 250 ms |
| Gap detection for active symbol | <= 100 ms or next message |
| Gap resync | P95 <= 2 s |
| UI update rate | 10-20 Hz coalesced |
| Replay determinism | 100% identical final book hash |

## Delivery Sequence

1. Add provider capability gates and disable unsupported equity order-book conclusions.
2. Define canonical BookEvent, BookState, and BookQuality schemas.
3. Implement Polymarket snapshot plus update reducer, including price_change.
4. Add bounded queues and per-instrument single-writer rebuilders.
5. Persist raw events and periodic snapshots for replay.
6. Add P0 features and the single core conclusion.
7. Add REST snapshot plus WebSocket fanout for selected markets.
8. Build the order-book workbench UI for Polymarket first.
9. Add L2 metrics only after source-specific reconstruction tests pass.
10. Revisit Futu or another authorized equity depth source later via explicit entitlement probe.

## References

- Polymarket CLOB market channel: https://docs.polymarket.com/developers/CLOB/websocket/market-channel
- Polymarket CLOB order book: https://docs.polymarket.com/developers/CLOB/clients/methods-public/get-order-book
- Binance local order book reconstruction pattern: https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams#how-to-manage-a-local-order-book-correctly
- Nasdaq TotalView: https://www.nasdaq.com/solutions/nasdaq-totalview
- Nasdaq TotalView-ITCH specification: https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHspecification.pdf
- NYSE Integrated Feed: https://www.nyse.com/market-data/real-time/integrated-feed
- SEC Market Data Infrastructure rule: https://www.sec.gov/files/rules/final/2020/34-90610.pdf
- Cont, Kukanov, Stoikov, Price Impact of Order Book Events: https://doi.org/10.1093/jjfinec/nbt003
- Stoikov, Micro-Price: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2970694
- Parquet file format: https://parquet.apache.org/docs/file-format/
