# Altcoin Discovery Verification

Verified on 2026-06-28.

## Scope

- Binance Alpha tokens across Ethereum, BSC, Base, and Solana.
- Unique Binance Alpha and current USD-M symbol intersections only.
- Real Binance Alpha OHLCV for 7d, 30d, and 90d dual-axis scoring.
- Three risk modes in every generated structural trade plan.
- No fabricated price, funding, open-interest, account equity, or position quantity.

## Live Data Evidence

- Binance Alpha returned 308 tokens: Ethereum 19, BSC 239, Base 25, Solana 25.
- Binance Futures REST returned HTTP 451 from the current network.
- Official USD-M WebSocket API ticker.price returned current prices for 683 symbols.
- PolyBob retained 633 canonical USDT symbols after excluding dated delivery symbols and other quote assets.
- The unique Alpha intersection contained 128 candidates.
- Because ticker.price does not include contractType, the Futures source and snapshot are marked degraded with websocket_api_inferred_perpetual.
- Historical OHLCV comes from the official Binance Alpha alpha-trade/klines endpoint.

## Performance

- Before: approximately 19 seconds and 668 KB for a full list response.
- After: 7-18 ms and 118 KB for cached list summaries.
- Full evidence and trade plans are fetched only for the selected candidate.
- Expired successful snapshots return immediately while refresh runs in the background.

## Automated Verification

- Backend: conda run -n polybob python -m pytest -q, 189 passed and 2 skipped.
- Dashboard: npm test, 31 passed.
- Dashboard: npm run build, Next.js production build succeeded.

The two skipped tests are explicitly opt-in live-provider checks.

## Browser Verification

- Desktop viewport: no page-level horizontal overflow and no clipped controls.
- Mobile viewport 390x844: no page-level horizontal overflow and no clipped controls.
- Verified search, detail loading, source-health disclosure, bilingual switching, and mobile list/detail switching.
- Browser console after the hydration fix: zero errors and zero warnings.

## Safety Boundary

The module is a research workbench, not an execution guarantee. Missing Futures funding, open interest, portfolio equity, or other required evidence remains unavailable and reduces coverage. A candidate is not promoted to a trade plan when its configured gates fail.
