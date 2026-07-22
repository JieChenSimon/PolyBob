export type OrderBookCapability = 'QUOTE_ONLY' | 'L1_BBO' | 'L1_5_DEPTH' | 'L2_DEPTH';

export interface OrderBookLevel {
  price: number;
  size: number;
  level: number;
}

export interface OrderBookSnapshot {
  symbol: string;
  provider: string;
  source: string;
  capability: OrderBookCapability;
  isRealOrderBook: boolean;
  timestamp: string;
  lastPrice: number | null;
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
  bidDepth: number;
  askDepth: number;
  spread: number | null;
  spreadBps: number | null;
  depthImbalance: number | null;
  conclusion: string;
  error?: string;
}

export interface EastmoneyBidAskItem {
  item: string;
  value: unknown;
}

export interface EastmoneyPush2Payload {
  data?: Record<string, unknown> | null;
}

export function toEastmoneySecId(symbol: string): string | null {
  const normalized = symbol.trim().toUpperCase();
  const [code, suffix] = normalized.split('.');
  if (!/^\d{6}$/.test(code || '')) {
    return null;
  }
  if (suffix === 'SH') {
    return `1.${code}`;
  }
  if (suffix === 'SZ' || suffix === 'BJ') {
    return `0.${code}`;
  }
  return null;
}

export function resolveOrderBookCapability(symbol: string): OrderBookCapability {
  return toEastmoneySecId(symbol) ? 'L1_5_DEPTH' : 'QUOTE_ONLY';
}

export function parseEastmoneyBidAskItems(
  symbol: string,
  rows: EastmoneyBidAskItem[],
  now = new Date(),
): OrderBookSnapshot {
  const values = new Map<string, number>();
  for (const row of rows) {
    const value = Number(row.value);
    if (Number.isFinite(value)) {
      values.set(row.item, value);
    }
  }

  const bids = parseLevels(values, 'buy');
  const asks = parseLevels(values, 'sell');
  validateFiveLevelBook(bids, asks);

  const bidDepth = sumDepth(bids);
  const askDepth = sumDepth(asks);
  const bestBid = bids[0]?.price ?? null;
  const bestAsk = asks[0]?.price ?? null;
  const mid = bestBid !== null && bestAsk !== null ? (bestBid + bestAsk) / 2 : null;
  const spread = bestBid !== null && bestAsk !== null ? roundPrice(bestAsk - bestBid) : null;
  const spreadBps = spread !== null && mid && mid > 0 ? (spread / mid) * 10_000 : null;
  const totalDepth = bidDepth + askDepth;
  const depthImbalance = totalDepth > 0 ? (bidDepth - askDepth) / totalDepth : null;

  return {
    symbol: symbol.trim().toUpperCase(),
    provider: 'eastmoney-akshare-shape',
    source: 'Eastmoney quote shape',
    capability: 'L1_5_DEPTH',
    isRealOrderBook: false,
    timestamp: now.toISOString(),
    lastPrice: values.get('最新') ?? null,
    bids,
    asks,
    bidDepth,
    askDepth,
    spread,
    spreadBps,
    depthImbalance,
    conclusion: buildFiveLevelConclusion(spreadBps, depthImbalance),
  };
}

export function parseEastmoneyPush2Bbo(
  symbol: string,
  payload: EastmoneyPush2Payload,
  now = new Date(),
): OrderBookSnapshot {
  const data = payload.data;
  if (!data) {
    throw new Error('Eastmoney returned no quote data');
  }

  const bestBid = parseEastmoneyScaledPrice(data.f19);
  const bidSize = parseEastmoneyLotSize(data.f20);
  const bestAsk = parseEastmoneyScaledPrice(data.f17);
  const askSize = parseEastmoneyLotSize(data.f18);
  const lastPrice = parseEastmoneyScaledPrice(data.f43);

  if (bestBid === null || bestAsk === null || bidSize === null || askSize === null) {
    throw new Error('Eastmoney BBO fields are incomplete');
  }
  if (bestBid >= bestAsk) {
    throw new Error('Eastmoney BBO is crossed or locked');
  }

  const bids = [{ price: bestBid, size: bidSize, level: 1 }];
  const asks = [{ price: bestAsk, size: askSize, level: 1 }];
  const bidDepth = sumDepth(bids);
  const askDepth = sumDepth(asks);
  const mid = (bestBid + bestAsk) / 2;
  const spread = roundPrice(bestAsk - bestBid);
  const spreadBps = mid > 0 ? (spread / mid) * 10_000 : null;
  const totalDepth = bidDepth + askDepth;
  const depthImbalance = totalDepth > 0 ? (bidDepth - askDepth) / totalDepth : null;

  return {
    symbol: symbol.trim().toUpperCase(),
    provider: 'eastmoney',
    source: 'Eastmoney push2 quote API',
    capability: 'L1_BBO',
    isRealOrderBook: false,
    timestamp: now.toISOString(),
    lastPrice,
    bids,
    asks,
    bidDepth,
    askDepth,
    spread,
    spreadBps,
    depthImbalance,
    conclusion: buildBboConclusion(spreadBps, depthImbalance),
  };
}

export function parseEastmoneyPush2FiveLevel(
  symbol: string,
  payload: EastmoneyPush2Payload,
  now = new Date(),
): OrderBookSnapshot {
  const data = payload.data;
  if (!data) {
    throw new Error('Eastmoney returned no quote data');
  }

  const snapshot = parseEastmoneyBidAskItems(symbol, [
    { item: 'sell_5', value: data.f31 },
    { item: 'sell_5_vol', value: lotValue(data.f32) },
    { item: 'sell_4', value: data.f33 },
    { item: 'sell_4_vol', value: lotValue(data.f34) },
    { item: 'sell_3', value: data.f35 },
    { item: 'sell_3_vol', value: lotValue(data.f36) },
    { item: 'sell_2', value: data.f37 },
    { item: 'sell_2_vol', value: lotValue(data.f38) },
    { item: 'sell_1', value: data.f39 },
    { item: 'sell_1_vol', value: lotValue(data.f40) },
    { item: 'buy_1', value: data.f19 },
    { item: 'buy_1_vol', value: lotValue(data.f20) },
    { item: 'buy_2', value: data.f17 },
    { item: 'buy_2_vol', value: lotValue(data.f18) },
    { item: 'buy_3', value: data.f15 },
    { item: 'buy_3_vol', value: lotValue(data.f16) },
    { item: 'buy_4', value: data.f13 },
    { item: 'buy_4_vol', value: lotValue(data.f14) },
    { item: 'buy_5', value: data.f11 },
    { item: 'buy_5_vol', value: lotValue(data.f12) },
    { item: '最新', value: data.f43 },
  ], now);

  return {
    ...snapshot,
    provider: 'eastmoney',
    source: 'Eastmoney push2 five-level quote API',
  };
}

export function buildUnavailableOrderBook(symbol: string, error: string): OrderBookSnapshot {
  return {
    symbol: symbol.trim().toUpperCase(),
    provider: 'none',
    source: 'none',
    capability: 'QUOTE_ONLY',
    isRealOrderBook: false,
    timestamp: new Date().toISOString(),
    lastPrice: null,
    bids: [],
    asks: [],
    bidDepth: 0,
    askDepth: 0,
    spread: null,
    spreadBps: null,
    depthImbalance: null,
    conclusion: '当前没有可验证盘口数据，只能显示报价，不输出订单簿结论。',
    error,
  };
}

function lotValue(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed * 100 : value;
}

function parseEastmoneyScaledPrice(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return roundPrice(parsed / 100);
}

function parseEastmoneyLotSize(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return null;
  }
  return parsed * 100;
}

function parseLevels(values: Map<string, number>, side: 'buy' | 'sell'): OrderBookLevel[] {
  const levels: OrderBookLevel[] = [];
  for (let level = 1; level <= 5; level += 1) {
    const price = values.get(`${side}_${level}`);
    const size = values.get(`${side}_${level}_vol`);
    if (price !== undefined && size !== undefined && price > 0 && size >= 0) {
      levels.push({ price, size, level });
    }
  }
  return levels;
}

function validateFiveLevelBook(bids: OrderBookLevel[], asks: OrderBookLevel[]) {
  if (bids.length === 0 || asks.length === 0) {
    throw new Error('five-level order book is missing bid or ask levels');
  }
  if ((bids[0]?.price ?? 0) >= (asks[0]?.price ?? 0)) {
    throw new Error('five-level order book is crossed or locked');
  }
  for (let index = 1; index < bids.length; index += 1) {
    if (bids[index].price > bids[index - 1].price) {
      throw new Error('bid levels are not sorted from best to worst');
    }
  }
  for (let index = 1; index < asks.length; index += 1) {
    if (asks[index].price < asks[index - 1].price) {
      throw new Error('ask levels are not sorted from best to worst');
    }
  }
}

function sumDepth(levels: OrderBookLevel[]) {
  return levels.reduce((total, level) => total + level.size, 0);
}

function roundPrice(value: number) {
  return Math.round(value * 10000) / 10000;
}

function buildFiveLevelConclusion(spreadBps: number | null, depthImbalance: number | null) {
  if (spreadBps === null || depthImbalance === null) {
    return '五档盘口数据不完整，暂不输出盘口结论。';
  }
  if (spreadBps > 30) {
    return '五档盘口显示价差偏宽，追价成本较高。';
  }
  if (depthImbalance > 0.25) {
    return '五档盘口显示买盘明显强于卖盘，短线支撑偏强。';
  }
  if (depthImbalance < -0.25) {
    return '五档盘口显示卖盘明显强于买盘，短线追价需谨慎。';
  }
  return '五档盘口相对均衡，暂未显示明显单边压力。';
}

function buildBboConclusion(spreadBps: number | null, depthImbalance: number | null) {
  if (spreadBps === null || depthImbalance === null) {
    return '当前只有买一卖一数据，盘口结论受限。';
  }
  if (spreadBps > 30) {
    return '买一卖一价差偏宽，当前追价成本较高。';
  }
  if (depthImbalance > 0.3) {
    return '买一卖一显示买盘较强，但这不是完整五档订单簿。';
  }
  if (depthImbalance < -0.3) {
    return '买一卖一显示卖盘较强，但这不是完整五档订单簿。';
  }
  return '买一卖一相对均衡；当前不是完整订单簿，只能作为盘口线索。';
}
