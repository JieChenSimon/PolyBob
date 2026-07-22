import { NextRequest, NextResponse } from 'next/server';
import { providerFetch } from '../../../../lib/providerFetch';

export const dynamic = 'force-dynamic';

interface Bar {
  date: string;
  close: number;
}

interface NasdaqHistoricalPayload {
  data?: {
    tradesTable?: {
      rows?: Array<{ date?: string; close?: string }>;
    };
  };
}

interface TencentKlinePayload {
  data?: Record<string, {
    qfqday?: string[][];
    day?: string[][];
  }>;
}

interface TechnicalPayload {
  symbol: string;
  provider: 'nasdaq-historical' | 'tencent-kline';
  asOf: string | null;
  latestClose: number | null;
  movingAverages: {
    ma20: number | null;
    ma50: number | null;
    ma200: number | null;
  };
  trend: {
    aboveMa20: boolean | null;
    aboveMa50: boolean | null;
    aboveMa200: boolean | null;
  } | null;
  bars: number;
}

const nasdaqHeaders = {
  accept: 'application/json, text/plain, */*',
  'accept-language': 'en-US,en;q=0.9',
  origin: 'https://www.nasdaq.com',
  referer: 'https://www.nasdaq.com/',
  'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
};
const technicalCache = new Map<string, { expiresAt: number; payload?: TechnicalPayload; promise?: Promise<TechnicalPayload> }>();
const usTechnicalCacheTtlMs = 30 * 60_000;
const chinaTechnicalCacheTtlMs = 5 * 60_000;

export async function GET(request: NextRequest) {
  const symbol = (request.nextUrl.searchParams.get('symbol') || '').trim().toUpperCase();

  if (!symbol) {
    return NextResponse.json({ error: 'symbol is required' }, { status: 400 });
  }

  try {
    const isChina = isChinaSymbol(symbol);
    const payload = await fetchTechnicalsWithCache(
      symbol,
      isChina ? chinaTechnicalCacheTtlMs : usTechnicalCacheTtlMs,
      () => buildTechnicalPayload(symbol, isChina),
    );

    return NextResponse.json(payload);
  } catch (error) {
    return NextResponse.json({
      symbol,
      error: error instanceof Error ? error.message : 'failed to fetch technicals',
    }, { status: 502 });
  }
}

async function buildTechnicalPayload(symbol: string, isChina: boolean): Promise<TechnicalPayload> {
  const bars = isChina ? await fetchChinaBars(symbol) : await fetchNasdaqBars(symbol);
  const closes = bars.map((bar) => bar.close).filter((value) => Number.isFinite(value));
  const latestClose = closes.at(-1) ?? null;
  const movingAverages = {
    ma20: averageLast(closes, 20),
    ma50: averageLast(closes, 50),
    ma200: averageLast(closes, 200),
  };

  return {
    symbol,
    provider: isChina ? 'tencent-kline' : 'nasdaq-historical',
    asOf: bars.at(-1)?.date || null,
    latestClose,
    movingAverages,
    trend: latestClose ? {
      aboveMa20: movingAverages.ma20 !== null ? latestClose >= movingAverages.ma20 : null,
      aboveMa50: movingAverages.ma50 !== null ? latestClose >= movingAverages.ma50 : null,
      aboveMa200: movingAverages.ma200 !== null ? latestClose >= movingAverages.ma200 : null,
    } : null,
    bars: bars.length,
  };
}

async function fetchTechnicalsWithCache(
  symbol: string,
  ttlMs: number,
  loader: () => Promise<TechnicalPayload>,
): Promise<TechnicalPayload> {
  const now = Date.now();
  const cached = technicalCache.get(symbol);
  if (cached?.payload && cached.expiresAt > now) {
    return cached.payload;
  }
  if (cached?.promise) {
    return cached.promise;
  }

  const promise = loader()
    .then((payload) => {
      technicalCache.set(symbol, {
        expiresAt: Date.now() + ttlMs,
        payload,
      });
      return payload;
    })
    .catch((error) => {
      technicalCache.delete(symbol);
      throw error;
    });

  technicalCache.set(symbol, { expiresAt: now + ttlMs, promise });
  return promise;
}

async function fetchNasdaqBars(symbol: string): Promise<Bar[]> {
  const toDate = new Date();
  const fromDate = new Date(toDate);
  fromDate.setDate(fromDate.getDate() - 430);
  const url = `https://api.nasdaq.com/api/quote/${encodeURIComponent(symbol)}/historical?assetclass=stocks&fromdate=${formatNasdaqDate(fromDate)}&todate=${formatNasdaqDate(toDate)}&limit=9999`;

  const response = await providerFetch(url, {
    headers: nasdaqHeaders,
    cache: 'no-store',
  });

  if (!response.ok) {
    throw new Error(`Nasdaq historical HTTP ${response.status}`);
  }

  const payload = (await response.json()) as NasdaqHistoricalPayload;
  const rows = payload.data?.tradesTable?.rows || [];
  return rows
    .map((row) => ({ date: row.date || '', close: parseMoney(row.close) }))
    .filter((bar): bar is Bar => Boolean(bar.date) && bar.close !== null)
    .reverse();
}

async function fetchChinaBars(symbol: string): Promise<Bar[]> {
  const tencentSymbol = toTencentSymbol(symbol);
  if (!tencentSymbol) {
    throw new Error('unsupported A-share symbol');
  }

  const url = `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=${encodeURIComponent(tencentSymbol)},day,,,300,qfq`;
  const response = await providerFetch(url, {
    headers: {
      accept: 'application/json, text/plain, */*',
      referer: 'https://gu.qq.com/',
      'user-agent': 'Mozilla/5.0',
    },
    cache: 'no-store',
  });

  if (!response.ok) {
    throw new Error(`Tencent kline HTTP ${response.status}`);
  }

  const payload = await response.json() as TencentKlinePayload;
  const rows = payload.data?.[tencentSymbol]?.qfqday || payload.data?.[tencentSymbol]?.day || [];
  return rows
    .map((row) => ({ date: row[0], close: Number(row[2]) }))
    .filter((bar) => Boolean(bar.date) && Number.isFinite(bar.close));
}

function averageLast(values: number[], window: number) {
  if (values.length < window) {
    return null;
  }
  const slice = values.slice(-window);
  return Number((slice.reduce((sum, value) => sum + value, 0) / window).toFixed(2));
}

function formatNasdaqDate(value: Date) {
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${value.getFullYear()}-${month}-${day}`;
}

function parseMoney(value: string | undefined) {
  if (!value || value === 'N/A') {
    return null;
  }
  const numeric = Number(value.replace(/[$,]/g, ''));
  return Number.isFinite(numeric) ? numeric : null;
}

function isChinaSymbol(symbol: string) {
  return symbol.endsWith('.SH') || symbol.endsWith('.SZ') || symbol.endsWith('.BJ');
}

function toTencentSymbol(symbol: string) {
  const [code, suffix] = symbol.split('.');
  if (!code || !suffix) {
    return null;
  }
  if (suffix === 'SH') {
    return `sh${code}`;
  }
  if (suffix === 'SZ') {
    return `sz${code}`;
  }
  return null;
}
