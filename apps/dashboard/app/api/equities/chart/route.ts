import { NextRequest, NextResponse } from 'next/server';
import { providerFetch } from '../../../../lib/providerFetch';

export const dynamic = 'force-dynamic';

type Market = 'US' | 'CN';
type ChartMode = 'premarket' | 'regular' | 'afterhours' | 'all_intraday' | 'overnight' | '5d' | 'day' | 'week' | 'month' | 'quarter' | 'year';
type TradingSession = 'premarket' | 'regular' | 'afterhours' | 'overnight' | 'all' | 'cash';

interface ChartPoint {
  timestamp: number;
  label: string;
  price: number;
  volume: number | null;
  session: TradingSession;
}

interface DailyBar {
  date: string;
  close: number;
  volume: number | null;
}

interface NasdaqChartPayload {
  data?: {
    timeAsOf?: string;
    lastSalePrice?: string;
    previousClose?: string;
    chart?: Array<{
      x?: number;
      y?: number;
      z?: {
        dateTime?: string;
        value?: string;
      };
    }>;
  };
}

interface NasdaqHistoricalPayload {
  data?: {
    tradesTable?: {
      rows?: Array<{ date?: string; close?: string; volume?: string }>;
    };
  };
}

interface TencentMinutePayload {
  data?: Record<string, {
    data?: {
      date?: string;
      data?: string[];
    };
  }>;
}

interface TencentKlinePayload {
  data?: Record<string, {
    qfqday?: string[][];
    day?: string[][];
  }>;
}

interface ChartPayload {
  symbol: string;
  market: Market;
  mode: ChartMode;
  provider: 'nasdaq-chart' | 'nasdaq-historical' | 'tencent-minute' | 'tencent-kline';
  asOf: string | null;
  currency: 'USD' | 'CNY';
  sessionInfo: {
    label: string;
    description: string;
    timezone: string;
  };
  points: ChartPoint[];
}

const nasdaqHeaders = {
  accept: 'application/json, text/plain, */*',
  'accept-language': 'en-US,en;q=0.9',
  origin: 'https://www.nasdaq.com',
  referer: 'https://www.nasdaq.com/',
  'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
};

const chartCache = new Map<string, { expiresAt: number; payload?: ChartPayload; promise?: Promise<ChartPayload> }>();
const intradayTtlMs = 20_000;
const historicalTtlMs = 10 * 60_000;

export async function GET(request: NextRequest) {
  const symbol = (request.nextUrl.searchParams.get('symbol') || '').trim().toUpperCase();
  const mode = normalizeMode(request.nextUrl.searchParams.get('mode'));
  const market = isChinaSymbol(symbol) ? 'CN' : 'US';

  if (!symbol) {
    return NextResponse.json({ error: 'symbol is required' }, { status: 400 });
  }

  try {
    const key = `${market}:${symbol}:${mode}`;
    const ttlMs = isIntradayMode(mode) ? intradayTtlMs : historicalTtlMs;
    const payload = await fetchChartWithCache(key, ttlMs, () => (
      market === 'CN' ? buildChinaChart(symbol, mode) : buildUsChart(symbol, mode)
    ));

    return NextResponse.json(payload);
  } catch (error) {
    return NextResponse.json({
      symbol,
      mode,
      error: error instanceof Error ? error.message : 'failed to fetch chart',
    }, { status: 502 });
  }
}

async function fetchChartWithCache(
  key: string,
  ttlMs: number,
  loader: () => Promise<ChartPayload>,
): Promise<ChartPayload> {
  const now = Date.now();
  const cached = chartCache.get(key);
  if (cached?.payload && cached.expiresAt > now) {
    return cached.payload;
  }
  if (cached?.promise) {
    return cached.promise;
  }

  const promise = loader()
    .then((payload) => {
      chartCache.set(key, {
        expiresAt: Date.now() + ttlMs,
        payload,
      });
      return payload;
    })
    .catch((error) => {
      chartCache.delete(key);
      throw error;
    });

  chartCache.set(key, { expiresAt: now + ttlMs, promise });
  return promise;
}

async function buildUsChart(symbol: string, mode: ChartMode): Promise<ChartPayload> {
  if (isIntradayMode(mode)) {
    const intraday = await fetchNasdaqIntraday(symbol);
    const points = mode === 'all_intraday'
      ? intraday.points.filter((point) => point.session !== 'overnight')
      : intraday.points.filter((point) => point.session === mode);

    return {
      symbol,
      market: 'US',
      mode,
      provider: 'nasdaq-chart',
      asOf: intraday.asOf,
      currency: 'USD',
      sessionInfo: usSessionInfo(mode),
      points,
    };
  }

  const bars = await fetchNasdaqDailyBars(symbol, historyLookbackDays(mode));
  const points = aggregateBars(bars, mode).map((bar) => ({
    timestamp: new Date(`${bar.date}T00:00:00Z`).getTime(),
    label: bar.date,
    price: bar.close,
    volume: bar.volume,
    session: 'cash' as const,
  }));

  return {
    symbol,
    market: 'US',
    mode,
    provider: 'nasdaq-historical',
    asOf: bars.at(-1)?.date || null,
    currency: 'USD',
    sessionInfo: usSessionInfo(mode),
    points,
  };
}

async function fetchNasdaqIntraday(symbol: string): Promise<{ asOf: string | null; points: ChartPoint[] }> {
  const url = `https://api.nasdaq.com/api/quote/${encodeURIComponent(symbol)}/chart?assetclass=stocks`;
  const response = await providerFetch(url, {
    headers: nasdaqHeaders,
    cache: 'no-store',
  });

  if (!response.ok) {
    throw new Error(`Nasdaq chart HTTP ${response.status}`);
  }

  const payload = (await response.json()) as NasdaqChartPayload;
  const points = (payload.data?.chart || [])
    .map((item): ChartPoint | null => {
      const timestamp = typeof item.x === 'number' ? item.x : null;
      const price = typeof item.y === 'number' ? item.y : parseMoney(item.z?.value);
      if (!timestamp || price === null) {
        return null;
      }
      return {
        timestamp,
        label: item.z?.dateTime || formatEtTime(timestamp),
        price,
        volume: null,
        session: classifyUsSession(item.z?.dateTime, timestamp),
      };
    })
    .filter((point): point is ChartPoint => point !== null);

  return {
    asOf: payload.data?.timeAsOf || null,
    points,
  };
}

async function fetchNasdaqDailyBars(symbol: string, lookbackDays: number): Promise<DailyBar[]> {
  const toDate = new Date();
  const fromDate = new Date(toDate);
  fromDate.setDate(fromDate.getDate() - lookbackDays);
  const url = `https://api.nasdaq.com/api/quote/${encodeURIComponent(symbol)}/historical?assetclass=stocks&fromdate=${formatDate(fromDate)}&todate=${formatDate(toDate)}&limit=9999`;

  const response = await providerFetch(url, {
    headers: nasdaqHeaders,
    cache: 'no-store',
  });

  if (!response.ok) {
    throw new Error(`Nasdaq historical HTTP ${response.status}`);
  }

  const payload = (await response.json()) as NasdaqHistoricalPayload;
  return (payload.data?.tradesTable?.rows || [])
    .map((row) => ({
      date: normalizeNasdaqDate(row.date),
      close: parseMoney(row.close),
      volume: parseVolume(row.volume),
    }))
    .filter((bar): bar is DailyBar => Boolean(bar.date) && bar.close !== null)
    .reverse();
}

async function buildChinaChart(symbol: string, mode: ChartMode): Promise<ChartPayload> {
  if (isIntradayMode(mode)) {
    const points = await fetchTencentMinute(symbol);
    return {
      symbol,
      market: 'CN',
      mode,
      provider: 'tencent-minute',
      asOf: points.at(-1)?.label || null,
      currency: 'CNY',
      sessionInfo: chinaSessionInfo(mode),
      points,
    };
  }

  const bars = await fetchTencentDailyBars(symbol, historyLookbackDays(mode));
  const points = aggregateBars(bars, mode).map((bar) => ({
    timestamp: new Date(`${bar.date}T15:00:00+08:00`).getTime(),
    label: bar.date,
    price: bar.close,
    volume: bar.volume,
    session: 'cash' as const,
  }));

  return {
    symbol,
    market: 'CN',
    mode,
    provider: 'tencent-kline',
    asOf: bars.at(-1)?.date || null,
    currency: 'CNY',
    sessionInfo: chinaSessionInfo(mode),
    points,
  };
}

async function fetchTencentMinute(symbol: string): Promise<ChartPoint[]> {
  const tencentSymbol = toTencentSymbol(symbol);
  if (!tencentSymbol) {
    throw new Error('unsupported A-share symbol');
  }

  const url = `https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=${encodeURIComponent(tencentSymbol)}`;
  const response = await providerFetch(url, {
    headers: {
      accept: 'application/json, text/plain, */*',
      referer: 'https://gu.qq.com/',
      'user-agent': 'Mozilla/5.0',
    },
    cache: 'no-store',
  });

  if (!response.ok) {
    throw new Error(`Tencent minute HTTP ${response.status}`);
  }

  const payload = (await response.json()) as TencentMinutePayload;
  const data = payload.data?.[tencentSymbol]?.data;
  const rows = data?.data || [];
  const tradeDate = normalizeTencentDate(data?.date) || latestWeekdayDateInShanghai();
  return rows
    .map((row): ChartPoint | null => {
      const [hhmm, priceText, volumeText] = row.split(' ');
      const price = Number(priceText);
      if (!hhmm || !Number.isFinite(price)) {
        return null;
      }
      const hour = hhmm.slice(0, 2);
      const minute = hhmm.slice(2, 4);
      return {
        timestamp: new Date(`${tradeDate}T${hour}:${minute}:00+08:00`).getTime(),
        label: `${hour}:${minute}`,
        price,
        volume: Number.isFinite(Number(volumeText)) ? Number(volumeText) : null,
        session: 'regular' as const,
      };
    })
    .filter((point): point is ChartPoint => point !== null);
}

async function fetchTencentDailyBars(symbol: string, lookbackDays: number): Promise<DailyBar[]> {
  const tencentSymbol = toTencentSymbol(symbol);
  if (!tencentSymbol) {
    throw new Error('unsupported A-share symbol');
  }

  const count = Math.min(1000, Math.max(120, lookbackDays));
  const url = `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=${encodeURIComponent(tencentSymbol)},day,,,${count},qfq`;
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

  const payload = (await response.json()) as TencentKlinePayload;
  const rows = payload.data?.[tencentSymbol]?.qfqday || payload.data?.[tencentSymbol]?.day || [];
  return rows
    .map((row) => ({
      date: row[0],
      close: Number(row[2]),
      volume: Number.isFinite(Number(row[5])) ? Number(row[5]) : null,
    }))
    .filter((bar): bar is DailyBar => Boolean(bar.date) && Number.isFinite(bar.close));
}

function aggregateBars(bars: DailyBar[], mode: ChartMode): DailyBar[] {
  if (mode === '5d') {
    return bars.slice(-5);
  }
  if (mode === 'day') {
    return bars.slice(-120);
  }

  const grouped = new Map<string, DailyBar>();
  for (const bar of bars) {
    const key = aggregateKey(bar.date, mode);
    const current = grouped.get(key);
    grouped.set(key, {
      date: bar.date,
      close: bar.close,
      volume: (current?.volume || 0) + (bar.volume || 0),
    });
  }

  const values = Array.from(grouped.values());
  if (mode === 'week') {
    return values.slice(-80);
  }
  if (mode === 'month') {
    return values.slice(-60);
  }
  if (mode === 'quarter') {
    return values.slice(-40);
  }
  return values.slice(-20);
}

function aggregateKey(date: string, mode: ChartMode) {
  const [year, monthText, dayText] = date.split('-');
  const month = Number(monthText);
  const day = Number(dayText);
  if (mode === 'week') {
    const week = Math.ceil((day + new Date(Number(year), month - 1, 1).getDay()) / 7);
    return `${year}-${monthText}-W${week}`;
  }
  if (mode === 'month') {
    return `${year}-${monthText}`;
  }
  if (mode === 'quarter') {
    return `${year}-Q${Math.ceil(month / 3)}`;
  }
  return year;
}

function classifyUsSession(label: string | undefined, timestamp: number): TradingSession {
  const minutes = labelMinutes(label) ?? etMinutes(timestamp);
  if (minutes >= 4 * 60 && minutes < 9 * 60 + 30) {
    return 'premarket';
  }
  if (minutes >= 9 * 60 + 30 && minutes < 16 * 60) {
    return 'regular';
  }
  if (minutes >= 16 * 60 && minutes < 20 * 60) {
    return 'afterhours';
  }
  return 'overnight';
}

function labelMinutes(label: string | undefined) {
  if (!label) {
    return null;
  }
  const match = label.match(/(\d{1,2}):(\d{2})\s*(AM|PM)?/i);
  if (!match) {
    return null;
  }
  let hour = Number(match[1]);
  const minute = Number(match[2]);
  const meridiem = match[3]?.toUpperCase();
  if (meridiem === 'PM' && hour !== 12) {
    hour += 12;
  }
  if (meridiem === 'AM' && hour === 12) {
    hour = 0;
  }
  return hour * 60 + minute;
}

function etMinutes(timestamp: number) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(new Date(timestamp));
  const hour = Number(parts.find((part) => part.type === 'hour')?.value || 0);
  const minute = Number(parts.find((part) => part.type === 'minute')?.value || 0);
  return hour * 60 + minute;
}

function usSessionInfo(mode: ChartMode) {
  const descriptions: Record<ChartMode, { label: string; description: string; timezone: string }> = {
    premarket: {
      label: '盘前 / Pre-market',
      description: '4:00-9:30 ET。Nasdaq/NYSE 常见盘前窗口，流动性通常低于盘中。',
      timezone: 'America/New_York',
    },
    regular: {
      label: '盘中 / Regular',
      description: '9:30-16:00 ET。美股交易所常规交易时段。',
      timezone: 'America/New_York',
    },
    afterhours: {
      label: '盘后 / After-hours',
      description: '16:00-20:00 ET。电子交易网络撮合，流动性和价差风险更高。',
      timezone: 'America/New_York',
    },
    all_intraday: {
      label: '全部分时 / Extended intraday',
      description: '覆盖盘前、盘中和盘后可得数据；不同免费数据源覆盖可能不完整。',
      timezone: 'America/New_York',
    },
    overnight: {
      label: '夜盘 / Overnight',
      description: '20:00-4:00 ET 通常依赖券商或 ATS 的隔夜交易服务，不是所有股票和免费源都有数据。',
      timezone: 'America/New_York',
    },
    '5d': { label: '5日', description: '最近 5 个交易日收盘走势。', timezone: 'America/New_York' },
    day: { label: '日K', description: '日线收盘走势。', timezone: 'America/New_York' },
    week: { label: '周K', description: '周线聚合走势。', timezone: 'America/New_York' },
    month: { label: '月K', description: '月线聚合走势。', timezone: 'America/New_York' },
    quarter: { label: '季K', description: '季度聚合走势。', timezone: 'America/New_York' },
    year: { label: '年K', description: '年度聚合走势。', timezone: 'America/New_York' },
  };
  return descriptions[mode];
}

function chinaSessionInfo(mode: ChartMode) {
  if (isIntradayMode(mode)) {
    return {
      label: 'A股分时 / Regular',
      description: 'A 股通常为 9:30-11:30、13:00-15:00 北京时间；没有美股式盘前/盘后。',
      timezone: 'Asia/Shanghai',
    };
  }
  return {
    label: mode,
    description: 'A 股复权 K 线聚合走势。',
    timezone: 'Asia/Shanghai',
  };
}

function normalizeMode(value: string | null): ChartMode {
  const allowed: ChartMode[] = ['premarket', 'regular', 'afterhours', 'all_intraday', 'overnight', '5d', 'day', 'week', 'month', 'quarter', 'year'];
  return allowed.includes(value as ChartMode) ? value as ChartMode : 'all_intraday';
}

function isIntradayMode(mode: ChartMode) {
  return mode === 'premarket' || mode === 'regular' || mode === 'afterhours' || mode === 'all_intraday' || mode === 'overnight';
}

function historyLookbackDays(mode: ChartMode) {
  if (mode === '5d') return 20;
  if (mode === 'day') return 180;
  if (mode === 'week') return 540;
  if (mode === 'month') return 2200;
  if (mode === 'quarter') return 3650;
  return 7300;
}

function formatDate(value: Date) {
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${value.getFullYear()}-${month}-${day}`;
}

function formatEtTime(timestamp: number) {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(timestamp));
}

function parseMoney(value: string | undefined) {
  if (!value || value === 'N/A') {
    return null;
  }
  const numeric = Number(value.replace(/[$,]/g, ''));
  return Number.isFinite(numeric) ? numeric : null;
}

function normalizeNasdaqDate(value: string | undefined) {
  if (!value) {
    return '';
  }
  const slashMatch = value.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (!slashMatch) {
    return value;
  }
  const month = slashMatch[1].padStart(2, '0');
  const day = slashMatch[2].padStart(2, '0');
  return `${slashMatch[3]}-${month}-${day}`;
}

function normalizeTencentDate(value: string | undefined) {
  if (!value) {
    return '';
  }
  const compactMatch = value.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (compactMatch) {
    return `${compactMatch[1]}-${compactMatch[2]}-${compactMatch[3]}`;
  }
  return value.match(/^\d{4}-\d{2}-\d{2}$/) ? value : '';
}

function latestWeekdayDateInShanghai() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    weekday: 'short',
  }).formatToParts(new Date());
  const year = parts.find((part) => part.type === 'year')?.value || '';
  const month = parts.find((part) => part.type === 'month')?.value || '';
  const day = parts.find((part) => part.type === 'day')?.value || '';
  const weekday = parts.find((part) => part.type === 'weekday')?.value || '';
  const current = new Date(`${year}-${month}-${day}T12:00:00+08:00`);
  if (weekday === 'Sat') {
    current.setDate(current.getDate() - 1);
  } else if (weekday === 'Sun') {
    current.setDate(current.getDate() - 2);
  }
  return current.toISOString().slice(0, 10);
}

function parseVolume(value: string | undefined) {
  if (!value || value === 'N/A') {
    return null;
  }
  const numeric = Number(value.replace(/,/g, ''));
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
  if (suffix === 'BJ') {
    return null;
  }
  return null;
}
