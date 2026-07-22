import { NextRequest, NextResponse } from 'next/server';
import { providerFetch } from '../../../../lib/providerFetch';

export const dynamic = 'force-dynamic';

interface NasdaqQuotePayload {
  data?: {
    symbol?: string;
    primaryData?: {
      lastSalePrice?: string;
      percentageChange?: string;
      lastTradeTimestamp?: string;
      isRealTime?: boolean;
      volume?: string;
    };
    marketStatus?: string;
  };
}

interface FinnhubQuotePayload {
  c?: number;
  d?: number;
  dp?: number;
  pc?: number;
  t?: number;
}

interface AlpacaBarsPayload {
  bars?: Record<string, { c?: number; t?: string }>;
}

type QuoteProvider = 'nasdaq' | 'finnhub' | 'alpaca-iex';
type QuoteMode = QuoteProvider | 'multi';
type ExtendedQuoteProvider = QuoteProvider | 'sina' | 'mixed';
type QuoteScope = 'active' | 'batch';
type DataStatus = 'realtime' | 'delayed' | 'stale' | 'last_close' | 'unknown';

interface QuoteSource {
  provider: QuoteProvider;
  price: number | null;
  lastTradeTimestamp: string | null;
  dataStatus: DataStatus;
  error?: string;
}

interface Quote {
  symbol: string;
  price: number | null;
  dayChangePct: number | null;
  lastTradeTimestamp: string | null;
  isRealTime: boolean;
  dataStatus: DataStatus;
  marketStatus: string | null;
  provider: ExtendedQuoteProvider;
  primaryProvider?: QuoteProvider;
  sources?: QuoteSource[];
  verifiedSourceCount?: number;
  sourceSpreadPct?: number | null;
  error?: string;
}

const maxSymbols = 140;
const concurrency = 8;
// Client batch refetchInterval is 60s; keep the server TTL slightly above it
// (poll + 10s) so steady pollers hit a warm cache instead of a just-expired one.
const usQuoteCacheTtlMs = 70_000;
const usActiveQuoteCacheTtlMs = 8_000;
const chinaQuoteCacheTtlMs = 15_000;
const chinaActiveQuoteCacheTtlMs = 4_000;
const finnhubRateWindowMs = 60_000;
const finnhubRequestLimit = parseRequestLimit(process.env.POLYBOB_FINNHUB_REQUESTS_PER_MINUTE);
const nasdaqHeaders = {
  accept: 'application/json, text/plain, */*',
  'accept-language': 'en-US,en;q=0.9',
  origin: 'https://www.nasdaq.com',
  referer: 'https://www.nasdaq.com/',
  'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
};

const quoteCache = new Map<string, { expiresAt: number; quote?: Quote; promise?: Promise<Quote> }>();
const finnhubRequestTimes: number[] = [];

export async function GET(request: NextRequest) {
  const symbols = (request.nextUrl.searchParams.get('symbols') || '')
    .split(',')
    .map((symbol) => symbol.trim().toUpperCase())
    .filter(Boolean)
    .slice(0, maxSymbols);

  const provider = resolveProvider(request.nextUrl.searchParams.get('provider'));
  const scope = request.nextUrl.searchParams.get('scope') === 'active' ? 'active' : 'batch';
  const usCacheTtlMs = scope === 'active' ? usActiveQuoteCacheTtlMs : usQuoteCacheTtlMs;
  const chinaCacheTtlMs = scope === 'active' ? chinaActiveQuoteCacheTtlMs : chinaQuoteCacheTtlMs;

  if (symbols.length === 0) {
    return NextResponse.json({ quotes: [], provider, timestamp: new Date().toISOString() });
  }

  const usSymbols = symbols.filter((symbol) => !isChinaSymbol(symbol));
  const chinaSymbols = symbols.filter(isChinaSymbol);
  const [usQuotes, chinaQuotes] = await Promise.all([
    usSymbols.length ? fetchQuotes(usSymbols, provider, usCacheTtlMs, scope) : Promise.resolve([]),
    chinaSymbols.length ? fetchSinaQuotes(chinaSymbols, chinaCacheTtlMs, scope) : Promise.resolve([]),
  ]);
  const quotes = [...usQuotes, ...chinaQuotes];

  return NextResponse.json({
    quotes,
    provider: resolveResponseProvider(quotes, provider),
    scope,
    timestamp: new Date().toISOString(),
  });
}

function resolveProvider(requestedProvider: string | null): QuoteMode {
  if (requestedProvider === 'multi' || requestedProvider === 'finnhub' || requestedProvider === 'alpaca-iex' || requestedProvider === 'nasdaq') {
    return requestedProvider;
  }

  const configuredProvider = process.env.POLYBOB_US_EQUITY_QUOTE_PROVIDER;
  if (configuredProvider === 'multi' || configuredProvider === 'finnhub' || configuredProvider === 'alpaca-iex' || configuredProvider === 'nasdaq') {
    return configuredProvider;
  }
  return 'multi';
}

async function fetchQuotes(symbols: string[], provider: QuoteMode, ttlMs: number, scope: QuoteScope) {
  if (provider === 'multi') {
    return fetchMultiSourceQuotes(symbols, ttlMs, scope);
  }
  if (provider === 'alpaca-iex') {
    return fetchAlpacaIexQuotes(symbols);
  }

  const results: Quote[] = [];

  for (let index = 0; index < symbols.length; index += concurrency) {
    const batch = symbols.slice(index, index + concurrency);
    const batchResults = await Promise.all(
      batch.map((symbol) => fetchQuoteWithCache(`${scope}:${provider}:${symbol}`, ttlMs, () => (
        provider === 'finnhub' ? fetchFinnhubQuote(symbol) : fetchNasdaqQuote(symbol)
      ))),
    );
    results.push(...batchResults);
  }

  return results;
}

async function fetchMultiSourceQuotes(symbols: string[], ttlMs: number, scope: QuoteScope): Promise<Quote[]> {
  const alpacaPromise = hasAlpacaCredentials()
    ? fetchAlpacaIexQuotes(symbols)
    : Promise.resolve([]);
  const sourceQuotes = new Map<string, Quote[]>();

  for (let index = 0; index < symbols.length; index += concurrency) {
    const batch = symbols.slice(index, index + concurrency);
    await Promise.all(batch.map(async (symbol) => {
      const requests: Array<Promise<Quote>> = [
        fetchQuoteWithCache(`${scope}:nasdaq:${symbol}`, ttlMs, () => fetchNasdaqQuote(symbol)),
      ];
      if (process.env.FINNHUB_API_KEY) {
        requests.push(fetchQuoteWithCache(`${scope}:finnhub:${symbol}`, ttlMs, () => fetchFinnhubQuote(symbol)));
      }
      sourceQuotes.set(symbol, await Promise.all(requests));
    }));
  }

  const alpacaQuotes = await alpacaPromise;
  for (const quote of alpacaQuotes) {
    sourceQuotes.set(quote.symbol, [...(sourceQuotes.get(quote.symbol) || []), quote]);
  }

  return symbols.map((symbol) => aggregateQuotes(symbol, sourceQuotes.get(symbol) || []));
}

async function fetchNasdaqQuote(symbol: string): Promise<Quote> {
  const url = `https://api.nasdaq.com/api/quote/${encodeURIComponent(symbol)}/info?assetclass=stocks`;

  try {
    const response = await providerFetch(url, {
      headers: nasdaqHeaders,
      cache: 'no-store',
    });

    if (!response.ok) {
      return emptyQuote(symbol, 'nasdaq', `HTTP ${response.status}`);
    }

    const payload = (await response.json()) as NasdaqQuotePayload;
    const primaryData = payload.data?.primaryData;

    return {
      symbol: payload.data?.symbol?.toUpperCase() || symbol,
      price: parseMoney(primaryData?.lastSalePrice),
      dayChangePct: parsePercent(primaryData?.percentageChange),
      lastTradeTimestamp: primaryData?.lastTradeTimestamp || null,
      isRealTime: primaryData?.isRealTime === true,
      dataStatus: primaryData?.isRealTime === true ? 'realtime' : 'delayed',
      marketStatus: payload.data?.marketStatus || null,
      provider: 'nasdaq',
    };
  } catch (error) {
    return emptyQuote(symbol, 'nasdaq', error instanceof Error ? error.message : 'quote fetch failed');
  }
}

async function fetchFinnhubQuote(symbol: string): Promise<Quote> {
  const token = process.env.FINNHUB_API_KEY;
  if (!token) {
    return emptyQuote(symbol, 'finnhub', 'FINNHUB_API_KEY is not configured');
  }

  if (!reserveFinnhubRequest()) {
    return emptyQuote(symbol, 'finnhub', `Finnhub ${finnhubRequestLimit}/minute request budget reached`);
  }

  const url = `https://finnhub.io/api/v1/quote?symbol=${encodeURIComponent(symbol)}`;

  try {
    const response = await providerFetch(url, {
      headers: {
        accept: 'application/json',
        'X-Finnhub-Token': token,
      },
      cache: 'no-store',
    }, 5_000);
    if (!response.ok) {
      return emptyQuote(symbol, 'finnhub', `Finnhub HTTP ${response.status}`);
    }

    const payload = (await response.json()) as FinnhubQuotePayload;
    const price = typeof payload.c === 'number' && payload.c > 0 ? payload.c : null;
    if (price === null) {
      return emptyQuote(symbol, 'finnhub', 'Finnhub returned no current price');
    }

    const dataStatus = classifyUsTimestampFreshness(payload.t ? payload.t * 1000 : null);
    return {
      symbol,
      price,
      dayChangePct: typeof payload.dp === 'number'
        ? payload.dp
        : calculateChangePct(price, payload.pc),
      lastTradeTimestamp: payload.t ? new Date(payload.t * 1000).toISOString() : null,
      isRealTime: dataStatus === 'realtime',
      dataStatus,
      marketStatus: 'US',
      provider: 'finnhub',
    };
  } catch (error) {
    return emptyQuote(symbol, 'finnhub', error instanceof Error ? `Finnhub ${error.message}` : 'Finnhub quote fetch failed');
  }
}

function reserveFinnhubRequest(now = Date.now()) {
  while (finnhubRequestTimes.length && finnhubRequestTimes[0] <= now - finnhubRateWindowMs) {
    finnhubRequestTimes.shift();
  }
  if (finnhubRequestTimes.length >= finnhubRequestLimit) {
    return false;
  }
  finnhubRequestTimes.push(now);
  return true;
}

function hasAlpacaCredentials() {
  return Boolean(process.env.ALPACA_API_KEY_ID && process.env.ALPACA_API_SECRET_KEY);
}

function aggregateQuotes(symbol: string, quotes: Quote[]): Quote {
  const available = quotes.filter((quote) => quote.price !== null);
  if (available.length === 0) {
    const errors = quotes.map((quote) => quote.error).filter(Boolean).join('; ');
    return {
      ...emptyQuote(symbol, 'mixed', errors || 'No configured quote source returned a price'),
      sources: quotes.map(toQuoteSource),
      verifiedSourceCount: 0,
      sourceSpreadPct: null,
    };
  }

  const primary = [...available].sort(compareQuotePriority)[0];
  const prices = available.map((quote) => quote.price as number);
  const minimum = Math.min(...prices);
  const maximum = Math.max(...prices);
  const midpoint = (minimum + maximum) / 2;

  return {
    ...primary,
    provider: 'mixed',
    primaryProvider: primary.provider as QuoteProvider,
    sources: quotes.map(toQuoteSource),
    verifiedSourceCount: available.length,
    sourceSpreadPct: available.length > 1 && midpoint > 0 ? ((maximum - minimum) / midpoint) * 100 : null,
    error: undefined,
  };
}

function toQuoteSource(quote: Quote): QuoteSource {
  return {
    provider: quote.provider as QuoteProvider,
    price: quote.price,
    lastTradeTimestamp: quote.lastTradeTimestamp,
    dataStatus: quote.dataStatus,
    ...(quote.error ? { error: quote.error } : {}),
  };
}

function compareQuotePriority(left: Quote, right: Quote) {
  const statusRank: Record<DataStatus, number> = {
    realtime: 5,
    delayed: 4,
    last_close: 3,
    stale: 2,
    unknown: 1,
  };
  const statusDifference = statusRank[right.dataStatus] - statusRank[left.dataStatus];
  if (statusDifference !== 0) {
    return statusDifference;
  }
  const timeDifference = parseQuoteTimestamp(right.lastTradeTimestamp) - parseQuoteTimestamp(left.lastTradeTimestamp);
  if (timeDifference !== 0) {
    return timeDifference;
  }
  const providerRank: Record<QuoteProvider, number> = { finnhub: 3, 'alpaca-iex': 2, nasdaq: 1 };
  return providerRank[right.provider as QuoteProvider] - providerRank[left.provider as QuoteProvider];
}

function parseQuoteTimestamp(value: string | null) {
  if (!value) {
    return 0;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

async function fetchAlpacaIexQuotes(symbols: string[]): Promise<Quote[]> {
  const apiKey = process.env.ALPACA_API_KEY_ID;
  const secretKey = process.env.ALPACA_API_SECRET_KEY;
  if (!apiKey || !secretKey) {
    return symbols.map((symbol) => emptyQuote(symbol, 'alpaca-iex', 'ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY are not configured'));
  }

  const url = `https://data.alpaca.markets/v2/stocks/bars/latest?symbols=${encodeURIComponent(symbols.join(','))}&feed=iex`;

  try {
    const response = await providerFetch(url, {
      headers: {
        accept: 'application/json',
        'APCA-API-KEY-ID': apiKey,
        'APCA-API-SECRET-KEY': secretKey,
      },
      cache: 'no-store',
    });

    if (!response.ok) {
      return symbols.map((symbol) => emptyQuote(symbol, 'alpaca-iex', `HTTP ${response.status}`));
    }

    const payload = (await response.json()) as AlpacaBarsPayload;
    return symbols.map((symbol) => {
      const bar = payload.bars?.[symbol];
      return {
        symbol,
        price: typeof bar?.c === 'number' ? bar.c : null,
        dayChangePct: null,
        lastTradeTimestamp: bar?.t || null,
        isRealTime: false,
        dataStatus: bar?.t ? 'delayed' : 'unknown',
        marketStatus: 'IEX',
        provider: 'alpaca-iex',
        ...(bar ? {} : { error: 'No IEX bar returned' }),
      };
    });
  } catch (error) {
    return symbols.map((symbol) => emptyQuote(symbol, 'alpaca-iex', error instanceof Error ? error.message : 'quote fetch failed'));
  }
}

async function fetchSinaQuotes(symbols: string[], ttlMs: number, scope: QuoteScope): Promise<Quote[]> {
  return Promise.all(
    symbols.map((symbol) => fetchQuoteWithCache(`${scope}:sina:${symbol}`, ttlMs, () => fetchSinaQuote(symbol))),
  );
}

async function fetchQuoteWithCache(key: string, ttlMs: number, loader: () => Promise<Quote>): Promise<Quote> {
  const now = Date.now();
  const cached = quoteCache.get(key);
  if (cached?.quote && cached.expiresAt > now) {
    return cached.quote;
  }
  if (cached?.promise) {
    return cached.promise;
  }

  const promise = loader()
    .then((quote) => {
      quoteCache.set(key, {
        expiresAt: Date.now() + ttlMs,
        quote,
      });
      return quote;
    })
    .catch((error) => {
      quoteCache.delete(key);
      throw error;
    });

  quoteCache.set(key, { expiresAt: now + ttlMs, promise });
  return promise;
}

async function fetchSinaQuote(symbol: string): Promise<Quote> {
  const sinaSymbol = toSinaSymbol(symbol);
  if (!sinaSymbol) {
    return emptyQuote(symbol, 'sina', 'Unsupported A-share symbol');
  }
  const url = `https://hq.sinajs.cn/list=${encodeURIComponent(sinaSymbol)}`;

  try {
    const response = await providerFetch(url, {
      headers: {
        referer: 'https://finance.sina.com.cn',
        'user-agent': 'Mozilla/5.0',
      },
      cache: 'no-store',
    });
    if (!response.ok) {
      return emptyQuote(symbol, 'sina', `HTTP ${response.status}`);
    }

    const raw = Buffer.from(await response.arrayBuffer()).toString('latin1');
    const data = raw.match(/="([^"]*)"/)?.[1]?.split(',') || [];
    const previousClose = Number(data[2]);
    const price = Number(data[3]);
    const tradeDate = data[30];
    const tradeTime = data[31];
    const dayChangePct = price !== null && previousClose && previousClose > 0
      ? ((price - previousClose) / previousClose) * 100
      : null;
    const lastTradeTimestamp = tradeDate && tradeTime ? `${tradeDate} ${tradeTime}` : null;
    const dataStatus = classifyChinaTradeDate(tradeDate);

    return {
      symbol,
      price: Number.isFinite(price) ? price : null,
      dayChangePct,
      lastTradeTimestamp,
      isRealTime: dataStatus === 'realtime',
      dataStatus,
      marketStatus: 'CN',
      provider: 'sina',
    };
  } catch (error) {
    return emptyQuote(symbol, 'sina', error instanceof Error ? error.message : 'quote fetch failed');
  }
}

function emptyQuote(symbol: string, provider: ExtendedQuoteProvider, error: string): Quote {
  return {
    symbol,
    price: null,
    dayChangePct: null,
    lastTradeTimestamp: null,
    isRealTime: false,
    dataStatus: 'unknown',
    marketStatus: null,
    provider,
    error,
  };
}

function classifyUsTimestampFreshness(timestampMs: number | null): DataStatus {
  if (!timestampMs || !Number.isFinite(timestampMs)) {
    return 'unknown';
  }
  const ageMs = Date.now() - timestampMs;
  if (ageMs <= 2 * 60_000) {
    return 'realtime';
  }
  if (!isUsRegularSession() && ageMs <= 7 * 24 * 60 * 60_000) {
    return 'last_close';
  }
  return 'stale';
}

function isUsRegularSession(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(now);
  const weekday = parts.find((part) => part.type === 'weekday')?.value;
  if (weekday === 'Sat' || weekday === 'Sun') {
    return false;
  }
  const hour = Number(parts.find((part) => part.type === 'hour')?.value);
  const minute = Number(parts.find((part) => part.type === 'minute')?.value);
  const minutes = hour * 60 + minute;
  return minutes >= 9 * 60 + 30 && minutes < 16 * 60;
}

function calculateChangePct(price: number, previousClose: number | undefined) {
  if (typeof previousClose !== 'number' || previousClose <= 0) {
    return null;
  }
  return ((price - previousClose) / previousClose) * 100;
}

function parseRequestLimit(value: string | undefined) {
  const parsed = Number(value || 55);
  if (!Number.isFinite(parsed)) {
    return 55;
  }
  return Math.min(60, Math.max(1, Math.floor(parsed)));
}

function resolveResponseProvider(quotes: Quote[], requestedProvider: QuoteMode): ExtendedQuoteProvider {
  if (quotes.length === 0) {
    return requestedProvider === 'multi' ? 'mixed' : requestedProvider;
  }
  const providers = new Set(quotes.map((quote) => quote.provider));
  return providers.size === 1 ? quotes[0].provider : 'mixed';
}

function classifyChinaTradeDate(tradeDate: string | undefined): DataStatus {
  if (!tradeDate) {
    return 'unknown';
  }
  return tradeDate === latestWeekdayDateInShanghai() ? 'realtime' : 'stale';
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

function isChinaSymbol(symbol: string) {
  return symbol.endsWith('.SH') || symbol.endsWith('.SZ') || symbol.endsWith('.BJ');
}

function toSinaSymbol(symbol: string) {
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

function parseMoney(value: string | undefined) {
  if (!value || value === 'N/A') {
    return null;
  }

  const numeric = Number(value.replace(/[$,]/g, ''));
  return Number.isFinite(numeric) ? numeric : null;
}

function parsePercent(value: string | undefined) {
  if (!value || value === 'N/A') {
    return null;
  }

  const numeric = Number(value.replace(/[%,]/g, ''));
  return Number.isFinite(numeric) ? numeric : null;
}
