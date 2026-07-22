import { describe, expect, it } from 'vitest';
import {
  buildUnavailableOrderBook,
  parseEastmoneyBidAskItems,
  parseEastmoneyPush2FiveLevel,
  resolveOrderBookCapability,
  toEastmoneySecId,
} from './orderBook';

describe('equity order book domain', () => {
  it('maps A-share symbols to Eastmoney secids', () => {
    expect(toEastmoneySecId('000001.SZ')).toBe('0.000001');
    expect(toEastmoneySecId('600519.SH')).toBe('1.600519');
    expect(toEastmoneySecId('835185.BJ')).toBe('0.835185');
  });

  it('parses Eastmoney/AkShare-style five-level bid and ask items', () => {
    const book = parseEastmoneyBidAskItems('000001.SZ', [
      { item: 'sell_5', value: 10.49 },
      { item: 'sell_5_vol', value: 1147100 },
      { item: 'sell_4', value: 10.48 },
      { item: 'sell_4_vol', value: 1035700 },
      { item: 'sell_3', value: 10.47 },
      { item: 'sell_3_vol', value: 1489100 },
      { item: 'sell_2', value: 10.46 },
      { item: 'sell_2_vol', value: 1608400 },
      { item: 'sell_1', value: 10.45 },
      { item: 'sell_1_vol', value: 233900 },
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
    ], new Date('2026-06-24T02:30:00.000Z'));

    expect(book).toMatchObject({
      symbol: '000001.SZ',
      provider: 'eastmoney-akshare-shape',
      source: 'Eastmoney quote shape',
      capability: 'L1_5_DEPTH',
      isRealOrderBook: false,
      lastPrice: 10.45,
      spread: 0.01,
      depthImbalance: expect.any(Number),
      conclusion: expect.stringContaining('五档盘口'),
    });
    expect(book.bids).toHaveLength(5);
    expect(book.asks).toHaveLength(5);
    expect(book.bids[0]).toEqual({ price: 10.44, size: 369000, level: 1 });
    expect(book.asks[0]).toEqual({ price: 10.45, size: 233900, level: 1 });
    expect(book.bidDepth).toBe(3846500);
    expect(book.askDepth).toBe(5514200);
    expect(book.depthImbalance).toBeCloseTo(-0.1782, 4);
  });

  it('rejects malformed five-level snapshots instead of fabricating depth', () => {
    expect(() => parseEastmoneyBidAskItems('000001.SZ', [
      { item: 'sell_1', value: 10.45 },
      { item: 'sell_1_vol', value: 233900 },
      { item: 'buy_1', value: 10.46 },
      { item: 'buy_1_vol', value: 369000 },
    ])).toThrow(/crossed/);
  });

  it('parses Eastmoney push2 five-level fields using the AkShare verified mapping', () => {
    const book = parseEastmoneyPush2FiveLevel('000001.SZ', {
      data: {
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
    }, new Date('2026-06-24T02:30:00.000Z'));

    expect(book).toMatchObject({
      symbol: '000001.SZ',
      provider: 'eastmoney',
      source: 'Eastmoney push2 five-level quote API',
      capability: 'L1_5_DEPTH',
      lastPrice: 10.45,
    });
    expect(book.bids).toHaveLength(5);
    expect(book.asks).toHaveLength(5);
    expect(book.bids[0]).toEqual({ price: 10.44, size: 369000, level: 1 });
    expect(book.asks[0]).toEqual({ price: 10.45, size: 233900, level: 1 });
  });

  it('exposes unsupported US symbols as quote-only without IBKR credentials', () => {
    const book = buildUnavailableOrderBook('AAOI', 'ibkr is not configured');

    expect(book).toMatchObject({
      symbol: 'AAOI',
      provider: 'none',
      capability: 'QUOTE_ONLY',
      isRealOrderBook: false,
      bids: [],
      asks: [],
      error: 'ibkr is not configured',
    });
    expect(resolveOrderBookCapability('AAOI')).toBe('QUOTE_ONLY');
  });
});
