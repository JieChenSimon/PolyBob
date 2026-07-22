import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe('equity order book route', () => {
  it('returns A-share real five-level depth from Eastmoney when AkShare is disabled', async () => {
    vi.stubEnv('POLYBOB_DISABLE_AKSHARE_ORDERBOOK', '1');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      data: {
        f57: '000001',
        f58: '平安银行',
        f43: 10.45,
        f39: 10.45,
        f40: 2339,
        f37: 10.46,
        f38: 16084,
        f35: 10.47,
        f36: 14891,
        f33: 10.48,
        f34: 10357,
        f31: 10.49,
        f32: 11471,
        f19: 10.44,
        f20: 3690,
        f17: 10.43,
        f18: 8359,
        f15: 10.42,
        f16: 6016,
        f13: 10.41,
        f14: 7381,
        f11: 10.4,
        f12: 13019,
      },
    }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const { GET } = await import('./route');

    const response = await GET(new NextRequest('http://localhost/api/equities/order-book?symbol=000001.SZ'));
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('push2.eastmoney.com/api/qt/stock/get'),
      expect.objectContaining({ cache: 'no-store' }),
    );
    expect(payload).toMatchObject({
      symbol: '000001.SZ',
      provider: 'eastmoney',
      capability: 'L1_5_DEPTH',
      isRealOrderBook: false,
      lastPrice: 10.45,
    });
    expect(payload.bids).toEqual(expect.arrayContaining([{ price: 10.44, size: 369000, level: 1 }]));
    expect(payload.asks).toEqual(expect.arrayContaining([{ price: 10.45, size: 233900, level: 1 }]));
    expect(payload.bids).toHaveLength(5);
    expect(payload.asks).toHaveLength(5);
  });

  it('uses Eastmoney first by default instead of spawning the AkShare subprocess', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      data: {
        f57: '000001',
        f58: '平安银行',
        f43: 10.45,
        f39: 10.45,
        f40: 2339,
        f37: 10.46,
        f38: 16084,
        f35: 10.47,
        f36: 14891,
        f33: 10.48,
        f34: 10357,
        f31: 10.49,
        f32: 11471,
        f19: 10.44,
        f20: 3690,
        f17: 10.43,
        f18: 8359,
        f15: 10.42,
        f16: 6016,
        f13: 10.41,
        f14: 7381,
        f11: 10.4,
        f12: 13019,
      },
    }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const { GET } = await import('./route');

    const response = await GET(new NextRequest('http://localhost/api/equities/order-book?symbol=000001.SZ'));
    const payload = await response.json();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(payload).toMatchObject({
      symbol: '000001.SZ',
      provider: 'eastmoney',
      capability: 'L1_5_DEPTH',
    });
  });

  it('does not fabricate US order book when IBKR is unavailable', async () => {
    const { GET } = await import('./route');

    const response = await GET(new NextRequest('http://localhost/api/equities/order-book?symbol=AAOI'));
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload).toMatchObject({
      symbol: 'AAOI',
      provider: 'none',
      capability: 'QUOTE_ONLY',
      isRealOrderBook: false,
      bids: [],
      asks: [],
    });
    expect(payload.error).toContain('IBKR');
  });

  it('reuses a short-lived order-book cache for repeated selected symbols', async () => {
    vi.stubEnv('POLYBOB_DISABLE_AKSHARE_ORDERBOOK', '1');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      data: {
        f57: '000001',
        f58: '平安银行',
        f43: 10.45,
        f39: 10.45,
        f40: 2339,
        f37: 10.46,
        f38: 16084,
        f35: 10.47,
        f36: 14891,
        f33: 10.48,
        f34: 10357,
        f31: 10.49,
        f32: 11471,
        f19: 10.44,
        f20: 3690,
        f17: 10.43,
        f18: 8359,
        f15: 10.42,
        f16: 6016,
        f13: 10.41,
        f14: 7381,
        f11: 10.4,
        f12: 13019,
      },
    }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const { GET } = await import('./route');

    await GET(new NextRequest('http://localhost/api/equities/order-book?symbol=000001.SZ'));
    await GET(new NextRequest('http://localhost/api/equities/order-book?symbol=000001.SZ'));

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('returns A-share five-level depth from AkShare subprocess output when available', async () => {
    vi.stubEnv('POLYBOB_AKSHARE_ORDERBOOK_FIXTURE', JSON.stringify([
      { item: 'sell_1', value: 10.45 },
      { item: 'sell_1_vol', value: 233900 },
      { item: 'sell_2', value: 10.46 },
      { item: 'sell_2_vol', value: 1608400 },
      { item: 'sell_3', value: 10.47 },
      { item: 'sell_3_vol', value: 1489100 },
      { item: 'sell_4', value: 10.48 },
      { item: 'sell_4_vol', value: 1035700 },
      { item: 'sell_5', value: 10.49 },
      { item: 'sell_5_vol', value: 1147100 },
      { item: 'buy_1', value: 10.44 },
      { item: 'buy_1_vol', value: 369000 },
      { item: 'buy_2', value: 10.43 },
      { item: 'buy_2_vol', value: 835900 },
      { item: 'buy_3', value: 10.42 },
      { item: 'buy_3_vol', value: 601600 },
      { item: 'buy_4', value: 10.41 },
      { item: 'buy_4_vol', value: 738100 },
      { item: 'buy_5', value: 10.4 },
      { item: 'buy_5_vol', value: 1301900 },
      { item: '最新', value: 10.45 },
    ]));
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { GET } = await import('./route');

    const response = await GET(new NextRequest('http://localhost/api/equities/order-book?symbol=000001.SZ'));
    const payload = await response.json();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(payload).toMatchObject({
      symbol: '000001.SZ',
      capability: 'L1_5_DEPTH',
      bids: expect.arrayContaining([{ price: 10.44, size: 369000, level: 1 }]),
      asks: expect.arrayContaining([{ price: 10.45, size: 233900, level: 1 }]),
    });
    expect(payload.bids).toHaveLength(5);
    expect(payload.asks).toHaveLength(5);
  });
});
