import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import {
  buildUnavailableOrderBook,
  parseEastmoneyBidAskItems,
  parseEastmoneyPush2FiveLevel,
  toEastmoneySecId,
} from '../../../../domain/equities/orderBook';

export const dynamic = 'force-dynamic';

const execFileAsync = promisify(execFile);
const orderBookCacheTtlMs = 3_000;
const orderBookCache = new Map<string, { expiresAt: number; payload: unknown }>();

const eastmoneyFields = [
  'f11',
  'f12',
  'f13',
  'f14',
  'f15',
  'f16',
  'f17',
  'f18',
  'f19',
  'f20',
  'f31',
  'f32',
  'f33',
  'f34',
  'f35',
  'f36',
  'f37',
  'f38',
  'f39',
  'f40',
  'f43',
  'f57',
  'f58',
].join(',');

export async function GET(request: NextRequest) {
  const symbol = (request.nextUrl.searchParams.get('symbol') || '').trim().toUpperCase();
  if (!symbol) {
    return NextResponse.json(
      buildUnavailableOrderBook('', 'symbol is required'),
      { status: 400 },
    );
  }

  const secid = toEastmoneySecId(symbol);
  if (!secid) {
    return NextResponse.json(buildUnavailableOrderBook(
      symbol,
      'IBKR market depth is not configured and no free US equity order-book source is enabled',
    ));
  }

  const cacheKey = `order-book:${symbol}`;
  const cached = orderBookCache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) {
    return NextResponse.json(cached.payload);
  }

  try {
    const fixtureSnapshot = await fetchAkshareOrderBook(symbol, { fixtureOnly: true });
    if (fixtureSnapshot) {
      cacheOrderBook(cacheKey, fixtureSnapshot);
      return NextResponse.json(fixtureSnapshot);
    }

    const response = await fetch(
      `https://push2.eastmoney.com/api/qt/stock/get?secid=${encodeURIComponent(secid)}&fields=${eastmoneyFields}`,
      {
        headers: {
          accept: 'application/json, text/plain, */*',
          referer: 'https://quote.eastmoney.com/',
          'user-agent': 'Mozilla/5.0',
        },
        cache: 'no-store',
        signal: AbortSignal.timeout(5_000),
      },
    );

    if (!response.ok) {
      const fallbackSnapshot = await fetchAkshareOrderBook(symbol);
      if (fallbackSnapshot) {
        cacheOrderBook(cacheKey, fallbackSnapshot);
        return NextResponse.json(fallbackSnapshot);
      }
      // Cache the failure too, so a down provider does not trigger the
      // AkShare subprocess fallback on every poll within the TTL window.
      const unavailable = buildUnavailableOrderBook(symbol, `Eastmoney HTTP ${response.status}`);
      cacheOrderBook(cacheKey, unavailable);
      return NextResponse.json(unavailable);
    }

    const payload = await response.json();
    const snapshot = parseEastmoneyPush2FiveLevel(symbol, payload);
    cacheOrderBook(cacheKey, snapshot);
    return NextResponse.json(snapshot);
  } catch (error) {
    const fallbackSnapshot = await fetchAkshareOrderBook(symbol);
    if (fallbackSnapshot) {
      cacheOrderBook(cacheKey, fallbackSnapshot);
      return NextResponse.json(fallbackSnapshot);
    }
    // Cache the failure too, so a down provider does not trigger the
    // AkShare subprocess fallback on every poll within the TTL window.
    const unavailable = buildUnavailableOrderBook(
      symbol,
      error instanceof Error ? `Real five-level order book unavailable: ${error.message}` : 'Real five-level order book unavailable',
    );
    cacheOrderBook(cacheKey, unavailable);
    return NextResponse.json(unavailable);
  }
}

function cacheOrderBook(cacheKey: string, payload: unknown) {
  orderBookCache.set(cacheKey, {
    expiresAt: Date.now() + orderBookCacheTtlMs,
    payload,
  });
}

async function fetchAkshareOrderBook(symbol: string, options: { fixtureOnly?: boolean } = {}) {
  if (process.env.POLYBOB_DISABLE_AKSHARE_ORDERBOOK === '1') {
    return null;
  }

  const fixture = process.env.POLYBOB_AKSHARE_ORDERBOOK_FIXTURE;
  if (fixture) {
    return parseEastmoneyBidAskItems(symbol, JSON.parse(fixture));
  }

  if (options.fixtureOnly || process.env.POLYBOB_ENABLE_AKSHARE_ORDERBOOK !== '1') {
    return null;
  }

  const code = symbol.split('.')[0];
  if (!/^\d{6}$/.test(code)) {
    return null;
  }

  const python = process.env.POLYBOB_AKSHARE_PYTHON || 'python3';
  const script = [
    'import json, sys',
    'import akshare as ak',
    'df = ak.stock_bid_ask_em(symbol=sys.argv[1])',
    'print(df.to_json(orient="records", force_ascii=False))',
  ].join('; ');

  try {
    const { stdout } = await execFileAsync(python, ['-c', script, code], {
      timeout: 6_000,
      maxBuffer: 1024 * 1024,
    });
    const rows = JSON.parse(stdout);
    return parseEastmoneyBidAskItems(symbol, rows);
  } catch {
    return null;
  }
}
