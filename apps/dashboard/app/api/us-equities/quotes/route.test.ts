import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe('US equity quote route', () => {
  it('uses Finnhub with a server-side token and maps a fresh quote', async () => {
    vi.stubEnv('FINNHUB_API_KEY', 'test-token');
    vi.stubEnv('POLYBOB_US_EQUITY_QUOTE_PROVIDER', 'finnhub');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      c: 212.42,
      dp: 1.25,
      pc: 209.8,
      t: Math.floor(Date.now() / 1000),
    }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const { GET } = await import('./route');

    const response = await GET(new NextRequest('http://localhost/api/us-equities/quotes?symbols=NVDA'));
    const payload = await response.json();

    expect(fetchMock).toHaveBeenCalledWith(
      'https://finnhub.io/api/v1/quote?symbol=NVDA',
      expect.objectContaining({
        headers: expect.objectContaining({ 'X-Finnhub-Token': 'test-token' }),
      }),
    );
    expect(payload.provider).toBe('finnhub');
    expect(payload.quotes[0]).toMatchObject({
      symbol: 'NVDA',
      price: 212.42,
      dayChangePct: 1.25,
      isRealTime: true,
      dataStatus: 'realtime',
      provider: 'finnhub',
    });
  });

  it('queries Finnhub and Nasdaq together and exposes cross-source verification', async () => {
    vi.stubEnv('FINNHUB_API_KEY', 'test-token');
    vi.stubEnv('POLYBOB_US_EQUITY_QUOTE_PROVIDER', 'multi');
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.startsWith('https://finnhub.io/')) {
        return Promise.resolve(new Response(JSON.stringify({
          c: 88.6,
          dp: 2.2,
          t: Math.floor(Date.now() / 1000),
        }), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify({
        data: {
          symbol: 'AAOI',
          primaryData: {
            lastSalePrice: '$88.50',
            percentageChange: '2.10%',
            lastTradeTimestamp: 'Jun 23, 2026',
            isRealTime: false,
          },
          marketStatus: 'Closed',
        },
      }), { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);
    const { GET } = await import('./route');

    const response = await GET(new NextRequest('http://localhost/api/us-equities/quotes?symbols=AAOI'));
    const payload = await response.json();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith('https://finnhub.io/'))).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith('https://api.nasdaq.com/'))).toBe(true);
    expect(payload.provider).toBe('mixed');
    expect(payload.quotes[0]).toMatchObject({
      symbol: 'AAOI',
      price: 88.6,
      provider: 'mixed',
      primaryProvider: 'finnhub',
      verifiedSourceCount: 2,
    });
    expect(payload.quotes[0].sourceSpreadPct).toBeCloseTo(0.1129, 3);
    expect(payload.quotes[0].sources).toEqual(expect.arrayContaining([
      expect.objectContaining({ provider: 'finnhub', price: 88.6 }),
      expect.objectContaining({ provider: 'nasdaq', price: 88.5 }),
    ]));
  });

  it('stops calling Finnhub when the local request budget is exhausted', async () => {
    vi.stubEnv('FINNHUB_API_KEY', 'test-token');
    vi.stubEnv('POLYBOB_US_EQUITY_QUOTE_PROVIDER', 'multi');
    vi.stubEnv('POLYBOB_FINNHUB_REQUESTS_PER_MINUTE', '1');
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.startsWith('https://finnhub.io/')) {
        return Promise.resolve(new Response(JSON.stringify({
          c: 200,
          dp: 0.5,
          t: Math.floor(Date.now() / 1000),
        }), { status: 200 }));
      }
      const symbol = url.includes('/AAPL/') ? 'AAPL' : 'MSFT';
      return Promise.resolve(new Response(JSON.stringify({
        data: {
          symbol,
          primaryData: {
            lastSalePrice: symbol === 'AAPL' ? '$199.90' : '$500.00',
            percentageChange: '0.20%',
            lastTradeTimestamp: 'Jun 23, 2026',
            isRealTime: false,
          },
          marketStatus: 'Closed',
        },
      }), { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);
    const { GET } = await import('./route');

    const response = await GET(new NextRequest('http://localhost/api/us-equities/quotes?symbols=AAPL,MSFT'));
    const payload = await response.json();

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith('https://finnhub.io/'))).toHaveLength(1);
    expect(payload.provider).toBe('mixed');
    expect(payload.quotes).toEqual(expect.arrayContaining([
      expect.objectContaining({ symbol: 'AAPL', provider: 'mixed', verifiedSourceCount: 2 }),
      expect.objectContaining({ symbol: 'MSFT', provider: 'mixed', verifiedSourceCount: 1 }),
    ]));
  });

  it('keeps active quote cache separate from slower batch refreshes', async () => {
    vi.stubEnv('POLYBOB_US_EQUITY_QUOTE_PROVIDER', 'nasdaq');
    let price = 100;
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
      data: {
        symbol: 'AAOI',
        primaryData: {
          lastSalePrice: `$${price++}`,
          percentageChange: '0.10%',
          lastTradeTimestamp: 'Jun 23, 2026',
          isRealTime: false,
        },
        marketStatus: 'Closed',
      },
    }), { status: 200 })));
    vi.stubGlobal('fetch', fetchMock);
    const { GET } = await import('./route');

    const batchResponse = await GET(new NextRequest('http://localhost/api/us-equities/quotes?symbols=AAOI&scope=batch'));
    const activeResponse = await GET(new NextRequest('http://localhost/api/us-equities/quotes?symbols=AAOI&scope=active'));
    const batchPayload = await batchResponse.json();
    const activePayload = await activeResponse.json();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(batchPayload.quotes[0].price).toBe(100);
    expect(activePayload.quotes[0].price).toBe(101);
  });
});
