'use client';

import { useQuery } from '@tanstack/react-query';
import VerdictBanner from '@/components/VerdictBanner';
import ForecastLabPanel from '@/components/ForecastLabPanel';
import { domainForSymbol, instrumentHref } from '@/lib/instrument';
import dynamic from 'next/dynamic';
import { useRouter, useSearchParams } from 'next/navigation';
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  buildTechnicalAdvice,
  type TechnicalAdvice,
} from '@/domain/equities/advice';
import {
  buildBatchQuoteSymbols,
  paginateEquities,
} from '@/domain/equities/pagination';
import { Language, useLanguage } from '@/lib/i18n';

// The recharts-based chart is loaded lazily so recharts stays out of the
// first-load bundle. The placeholder fills the fixed-height chart container
// (h-[320px]) to avoid layout shift.
const EquityPriceChart = dynamic(() => import('./EquityPriceChart'), {
  ssr: false,
  loading: () => <div className="h-full" />,
});

type Market = 'US' | 'CN';
type ChartMode = 'premarket' | 'regular' | 'afterhours' | 'all_intraday' | 'overnight' | '5d' | 'day' | 'week' | 'month' | 'quarter' | 'year';

interface QuotePayload {
  quotes: Array<{
    symbol: string;
    price: number | null;
    dayChangePct: number | null;
    lastTradeTimestamp: string | null;
    isRealTime: boolean;
    dataStatus?: 'realtime' | 'delayed' | 'stale' | 'last_close' | 'unknown';
    marketStatus: string | null;
    provider: 'nasdaq' | 'finnhub' | 'alpaca-iex' | 'sina' | 'mixed';
    primaryProvider?: 'nasdaq' | 'finnhub' | 'alpaca-iex';
    sources?: Array<{
      provider: 'nasdaq' | 'finnhub' | 'alpaca-iex';
      price: number | null;
      lastTradeTimestamp: string | null;
      dataStatus: 'realtime' | 'delayed' | 'stale' | 'last_close' | 'unknown';
      error?: string;
    }>;
    verifiedSourceCount?: number;
    sourceSpreadPct?: number | null;
    error?: string;
  }>;
  provider: 'nasdaq' | 'finnhub' | 'alpaca-iex' | 'sina' | 'mixed';
  scope?: 'active' | 'batch';
  timestamp: string;
}

interface QuoteState {
  bySymbol: Record<string, QuotePayload['quotes'][number]>;
  provider: 'nasdaq' | 'finnhub' | 'alpaca-iex' | 'sina' | 'mixed';
  timestamp: string | null;
  loading: boolean;
  error: string | null;
}

interface TechnicalState {
  symbol: string | null;
  loading: boolean;
  error: string | null;
  provider: string | null;
  asOf: string | null;
  latestClose: number | null;
  movingAverages: {
    ma20: number | null;
    ma50: number | null;
    ma200: number | null;
  } | null;
  trend: {
    aboveMa20: boolean | null;
    aboveMa50: boolean | null;
    aboveMa200: boolean | null;
  } | null;
}

interface ChartPayload {
  symbol: string;
  market: Market;
  mode: ChartMode;
  provider: string;
  asOf: string | null;
  currency: 'USD' | 'CNY';
  sessionInfo: {
    label: string;
    description: string;
    timezone: string;
  };
  points: Array<{
    timestamp: number;
    label: string;
    price: number;
    volume: number | null;
    session: 'premarket' | 'regular' | 'afterhours' | 'overnight' | 'all' | 'cash';
  }>;
}

interface ChartState {
  symbol: string | null;
  mode: ChartMode;
  loading: boolean;
  error: string | null;
  payload: ChartPayload | null;
}

interface OrderBookLevel {
  price: number;
  size: number;
  level: number;
}

interface OrderBookPayload {
  symbol: string;
  provider: string;
  source: string;
  capability: 'QUOTE_ONLY' | 'L1_BBO' | 'L1_5_DEPTH' | 'L2_DEPTH';
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

interface OrderBookState {
  symbol: string | null;
  loading: boolean;
  error: string | null;
  payload: OrderBookPayload | null;
}

interface EquitySeed {
  symbol: string;
  name: string;
  sector: string;
  universe?: 'Nasdaq-100' | 'Personal';
  market?: Market;
  aliases?: string[];
}

type EquityObservation = Required<Pick<EquitySeed, 'symbol' | 'name' | 'sector' | 'market'>> & {
  universe: 'Nasdaq-100' | 'Personal';
  aliases?: string[];
};

const nasdaq100Universe: EquitySeed[] = [
  { symbol: 'AAPL', name: 'Apple', sector: 'Technology Hardware' },
  { symbol: 'ABNB', name: 'Airbnb', sector: 'Consumer Services' },
  { symbol: 'ADBE', name: 'Adobe', sector: 'Software' },
  { symbol: 'ADI', name: 'Analog Devices', sector: 'Semiconductors' },
  { symbol: 'ADP', name: 'Automatic Data Processing', sector: 'Business Services' },
  { symbol: 'ADSK', name: 'Autodesk', sector: 'Software' },
  { symbol: 'AEP', name: 'American Electric Power', sector: 'Utilities' },
  { symbol: 'ALNY', name: 'Alnylam Pharmaceuticals', sector: 'Biotechnology' },
  { symbol: 'AMAT', name: 'Applied Materials', sector: 'Semiconductor Equipment' },
  { symbol: 'AMD', name: 'Advanced Micro Devices', sector: 'Semiconductors' },
  { symbol: 'AMGN', name: 'Amgen', sector: 'Biotechnology' },
  { symbol: 'AMZN', name: 'Amazon', sector: 'Consumer Discretionary' },
  { symbol: 'APP', name: 'AppLovin', sector: 'Software' },
  { symbol: 'ARM', name: 'Arm Holdings', sector: 'Semiconductors' },
  { symbol: 'ASML', name: 'ASML Holding', sector: 'Semiconductor Equipment' },
  { symbol: 'AVGO', name: 'Broadcom', sector: 'Semiconductors' },
  { symbol: 'AXON', name: 'Axon Enterprise', sector: 'Industrials' },
  { symbol: 'BKNG', name: 'Booking Holdings', sector: 'Consumer Services' },
  { symbol: 'BKR', name: 'Baker Hughes', sector: 'Energy' },
  { symbol: 'CCEP', name: 'Coca-Cola Europacific Partners', sector: 'Consumer Staples' },
  { symbol: 'CDNS', name: 'Cadence Design Systems', sector: 'Software' },
  { symbol: 'CEG', name: 'Constellation Energy', sector: 'Utilities' },
  { symbol: 'CHTR', name: 'Charter Communications', sector: 'Telecommunications' },
  { symbol: 'CMCSA', name: 'Comcast', sector: 'Telecommunications' },
  { symbol: 'COST', name: 'Costco Wholesale', sector: 'Consumer Staples' },
  { symbol: 'CPRT', name: 'Copart', sector: 'Industrials' },
  { symbol: 'CRWD', name: 'CrowdStrike', sector: 'Software' },
  { symbol: 'CSCO', name: 'Cisco Systems', sector: 'Networking' },
  { symbol: 'CSGP', name: 'CoStar Group', sector: 'Real Estate Data' },
  { symbol: 'CSX', name: 'CSX', sector: 'Transportation' },
  { symbol: 'CTAS', name: 'Cintas', sector: 'Business Services' },
  { symbol: 'CTSH', name: 'Cognizant', sector: 'IT Services' },
  { symbol: 'DASH', name: 'DoorDash', sector: 'Consumer Services' },
  { symbol: 'DDOG', name: 'Datadog', sector: 'Software' },
  { symbol: 'DXCM', name: 'Dexcom', sector: 'Medical Devices' },
  { symbol: 'EA', name: 'Electronic Arts', sector: 'Interactive Entertainment' },
  { symbol: 'EXC', name: 'Exelon', sector: 'Utilities' },
  { symbol: 'FANG', name: 'Diamondback Energy', sector: 'Energy' },
  { symbol: 'FAST', name: 'Fastenal', sector: 'Industrials' },
  { symbol: 'FER', name: 'Ferrovial', sector: 'Infrastructure' },
  { symbol: 'FTNT', name: 'Fortinet', sector: 'Cybersecurity' },
  { symbol: 'GEHC', name: 'GE HealthCare', sector: 'Health Care Equipment' },
  { symbol: 'GILD', name: 'Gilead Sciences', sector: 'Biotechnology' },
  { symbol: 'GOOG', name: 'Alphabet Class C', sector: 'Communication Services' },
  { symbol: 'GOOGL', name: 'Alphabet Class A', sector: 'Communication Services' },
  { symbol: 'HON', name: 'Honeywell', sector: 'Industrials' },
  { symbol: 'IDXX', name: 'IDEXX Laboratories', sector: 'Health Care' },
  { symbol: 'INSM', name: 'Insmed', sector: 'Biotechnology' },
  { symbol: 'INTC', name: 'Intel', sector: 'Semiconductors' },
  { symbol: 'INTU', name: 'Intuit', sector: 'Software' },
  { symbol: 'ISRG', name: 'Intuitive Surgical', sector: 'Medical Devices' },
  { symbol: 'KDP', name: 'Keurig Dr Pepper', sector: 'Consumer Staples' },
  { symbol: 'KHC', name: 'Kraft Heinz', sector: 'Consumer Staples' },
  { symbol: 'KLAC', name: 'KLA', sector: 'Semiconductor Equipment' },
  { symbol: 'LIN', name: 'Linde', sector: 'Materials' },
  { symbol: 'LRCX', name: 'Lam Research', sector: 'Semiconductor Equipment' },
  { symbol: 'MAR', name: 'Marriott International', sector: 'Consumer Services' },
  { symbol: 'MCHP', name: 'Microchip Technology', sector: 'Semiconductors' },
  { symbol: 'MDLZ', name: 'Mondelez International', sector: 'Consumer Staples' },
  { symbol: 'MELI', name: 'MercadoLibre', sector: 'Consumer Discretionary' },
  { symbol: 'META', name: 'Meta Platforms', sector: 'Communication Services' },
  { symbol: 'MNST', name: 'Monster Beverage', sector: 'Consumer Staples' },
  { symbol: 'MPWR', name: 'Monolithic Power Systems', sector: 'Semiconductors' },
  { symbol: 'MRVL', name: 'Marvell Technology', sector: 'Semiconductors' },
  { symbol: 'MSFT', name: 'Microsoft', sector: 'Software' },
  { symbol: 'MSTR', name: 'MicroStrategy', sector: 'Software' },
  { symbol: 'MU', name: 'Micron Technology', sector: 'Semiconductors' },
  { symbol: 'NFLX', name: 'Netflix', sector: 'Communication Services' },
  { symbol: 'NVDA', name: 'NVIDIA', sector: 'Semiconductors' },
  { symbol: 'NXPI', name: 'NXP Semiconductors', sector: 'Semiconductors' },
  { symbol: 'ODFL', name: 'Old Dominion Freight Line', sector: 'Transportation' },
  { symbol: 'ORLY', name: "O'Reilly Automotive", sector: 'Consumer Discretionary' },
  { symbol: 'PANW', name: 'Palo Alto Networks', sector: 'Cybersecurity' },
  { symbol: 'PAYX', name: 'Paychex', sector: 'Business Services' },
  { symbol: 'PCAR', name: 'PACCAR', sector: 'Industrials' },
  { symbol: 'PDD', name: 'PDD Holdings', sector: 'Consumer Discretionary' },
  { symbol: 'PEP', name: 'PepsiCo', sector: 'Consumer Staples' },
  { symbol: 'PLTR', name: 'Palantir Technologies', sector: 'Software' },
  { symbol: 'PYPL', name: 'PayPal', sector: 'Financial Technology' },
  { symbol: 'QCOM', name: 'Qualcomm', sector: 'Semiconductors' },
  { symbol: 'REGN', name: 'Regeneron Pharmaceuticals', sector: 'Biotechnology' },
  { symbol: 'ROP', name: 'Roper Technologies', sector: 'Software' },
  { symbol: 'ROST', name: 'Ross Stores', sector: 'Consumer Discretionary' },
  { symbol: 'SBUX', name: 'Starbucks', sector: 'Consumer Discretionary' },
  { symbol: 'SHOP', name: 'Shopify', sector: 'Software' },
  { symbol: 'SNDK', name: 'Sandisk', sector: 'Data Storage' },
  { symbol: 'SNPS', name: 'Synopsys', sector: 'Software' },
  { symbol: 'STX', name: 'Seagate Technology', sector: 'Data Storage' },
  { symbol: 'TMUS', name: 'T-Mobile US', sector: 'Telecommunications' },
  { symbol: 'TRI', name: 'Thomson Reuters', sector: 'Information Services' },
  { symbol: 'TSLA', name: 'Tesla', sector: 'Autos' },
  { symbol: 'TTWO', name: 'Take-Two Interactive', sector: 'Interactive Entertainment' },
  { symbol: 'TXN', name: 'Texas Instruments', sector: 'Semiconductors' },
  { symbol: 'VRSK', name: 'Verisk Analytics', sector: 'Data Analytics' },
  { symbol: 'VRTX', name: 'Vertex Pharmaceuticals', sector: 'Biotechnology' },
  { symbol: 'WBD', name: 'Warner Bros. Discovery', sector: 'Communication Services' },
  { symbol: 'WDAY', name: 'Workday', sector: 'Software' },
  { symbol: 'WDC', name: 'Western Digital', sector: 'Data Storage' },
  { symbol: 'WMT', name: 'Walmart', sector: 'Consumer Staples' },
  { symbol: 'XEL', name: 'Xcel Energy', sector: 'Utilities' },
  { symbol: 'ZS', name: 'Zscaler', sector: 'Cybersecurity' },
];

const personalWatchlist: EquitySeed[] = [
  { symbol: 'AAOI', name: 'Applied Optoelectronics', sector: 'Optical Components', universe: 'Personal' },
];

const aShareUniverse: EquitySeed[] = [
  { symbol: '600519.SH', name: '贵州茅台', sector: '白酒', universe: 'Personal', market: 'CN' },
  { symbol: '000858.SZ', name: '五粮液', sector: '白酒', universe: 'Personal', market: 'CN' },
  { symbol: '300750.SZ', name: '宁德时代', sector: '新能源', universe: 'Personal', market: 'CN' },
  { symbol: '002594.SZ', name: '比亚迪', sector: '新能源车', universe: 'Personal', market: 'CN' },
  { symbol: '600036.SH', name: '招商银行', sector: '银行', universe: 'Personal', market: 'CN' },
  { symbol: '601318.SH', name: '中国平安', sector: '保险', universe: 'Personal', market: 'CN' },
  { symbol: '600900.SH', name: '长江电力', sector: '公用事业', universe: 'Personal', market: 'CN' },
  { symbol: '600276.SH', name: '恒瑞医药', sector: '医药', universe: 'Personal', market: 'CN' },
  { symbol: '601899.SH', name: '紫金矿业', sector: '有色金属', universe: 'Personal', market: 'CN' },
  { symbol: '600460.SH', name: '士兰微', sector: '半导体', universe: 'Personal', market: 'CN', aliases: ['兰士微', '士兰微电子', 'Silan'] },
  { symbol: '688008.SH', name: '澜起科技', sector: '半导体', universe: 'Personal', market: 'CN', aliases: ['兰起科技', 'Montage'] },
  { symbol: '510300.SH', name: '沪深300ETF', sector: '宽基ETF', universe: 'Personal', market: 'CN' },
];

const observations: EquityObservation[] = [
  ...nasdaq100Universe.map((seed) => ({ ...seed, market: 'US' as const, universe: 'Nasdaq-100' as const })),
  ...personalWatchlist.map((seed) => ({ ...seed, market: 'US' as const, universe: 'Personal' as const })),
  ...aShareUniverse.map((seed) => ({ ...seed, market: seed.market ?? 'CN', universe: seed.universe ?? 'Personal' })) as EquityObservation[],
];

const sourceNote = 'Coverage: Nasdaq-100, personal US names such as AAOI, and selected A-share watchlist names. Nasdaq list checked Jun 10, 2026.';
const sourceNoteZh = '覆盖范围：Nasdaq-100、AAOI 等个人美股观察池，以及精选 A 股观察池。Nasdaq 清单核对日期：2026-06-10。';
const favoritesStorageKey = 'polybob-us-equity-favorites';

const uiText = {
  zh: {
    terminal: '股票行情观察台',
    lab: 'PolyBob 股票观察 / REAL-ONLY',
    coverage: '覆盖范围',
    watchlist: '行情观察池',
    favorites: '收藏',
    all: '全部',
    category: '分类',
    market: '市场',
    usMarket: '美股',
    cnMarket: 'A股',
    search: '搜索代码、公司、行业',
    noMatch: '没有匹配的股票。',
    favoriteOnly: '只看收藏',
    addFavorite: '收藏',
    removeFavorite: '已收藏',
    observationOnly: '仅行情观察',
    noAdvice: '技术观察建议',
    technicalAdvice: '技术加减仓观察',
    coreConclusion: '核心结论',
    addZone: '加仓观察区',
    trimZone: '减仓观察区',
    support: '支撑参考',
    resistance: '压力参考',
    volatilityBand: '波动缓冲',
    modelBasis: '依据实时价、走势图、均线和波动区间；成本价不参与加减仓价格计算。',
    adviceUnavailable: '真实价格不足，暂不生成观察区间。',
    portfolioNotConfigured: '组合未配置',
    quote: '真实行情',
    movingAverages: '真实均线',
    technicalSource: '技术数据',
    provider: '来源',
    primaryProvider: '主报价源',
    sourceCheck: '多源校验',
    sourceAligned: '价格一致',
    sourceWatch: '存在价差',
    sourceDivergent: '价差异常',
    singleSource: '仅单源有效',
    last: '最新价',
    dayPct: '日涨跌',
    marketStatus: '市场状态',
    timestamp: '时间',
    delayed: '延迟',
    realtime: '实时',
    stale: '旧数据',
    lastClose: '休市最后数据',
    unknownFreshness: '来源未确认',
    loadingData: '行情加载中',
    dataError: '行情失败',
    ma20: '20日均线',
    ma50: '50日均线',
    ma200: '200日均线',
    asOf: '日期',
    latestClose: '最新收盘',
    chart: '走势图',
    chartLoading: '走势图加载中',
    chartNoData: '没有可用走势图数据',
    chartSource: '图表来源',
    chartAsOf: '图表时间',
    orderBook: '盘口线索',
    orderBookCapability: '盘口能力',
    orderBookSource: '盘口来源',
    orderBookFreshness: '盘口时间',
    bid: '买盘',
    ask: '卖盘',
    spread: '价差',
    spreadBps: '价差bps',
    depthImbalance: '盘口不平衡',
    noRealOrderBook: '真实五档 / 非完整L2',
    realOrderBook: '真实订单簿',
    premarket: '盘前报价',
    regular: '盘中报价',
    afterhours: '盘后报价',
    allIntraday: '全部分时',
    overnight: '夜盘',
    fiveDay: '5日',
    dayK: '日K',
    weekK: '周K',
    monthK: '月K',
    quarterK: '季K',
    yearK: '年K',
    price: '价格',
    volume: '成交量',
    usSessionNote: '美股常规盘为 9:30-16:00 ET，盘前 4:00-9:30 ET，盘后 16:00-20:00 ET；夜盘通常依赖券商/ATS，免费源可能没有覆盖。',
    cnSessionNote: 'A 股通常为 9:30-11:30、13:00-15:00 北京时间，没有美股式盘前、盘后和夜盘。',
    above: '高于均线',
    below: '低于均线',
    unavailable: '无真实数据',
    configured: '已连接',
    notConfigured: '未配置',
    personal: '自选',
    nasdaq100: '纳指100',
    realOnlyRule: '本页使用真实 quote、真实走势图和真实 moving averages 生成技术观察价。未接入真实组合时，不生成目标仓位、胜率、Sharpe、估值或盈利风险。',
    unavailableHeadline: '数据不足',
    unavailableRationale: '真实实时价或最新收盘价不可用，暂不计算技术观察区间。',
    holdHeadline: '持有观察',
    holdRationale: '实时价处在支撑和压力之间，暂以观察为主。',
    riskTrimHeadline: '风控减仓',
    riskTrimRationale: '实时价低于关键均线组合，趋势结构偏弱，优先降低风险暴露。',
    trimHeadline: '逢高减仓',
    trimRationale: '实时价相对短期均线或分时高点偏离较大，适合把减仓观察价放在压力区附近。',
    addHeadline: '回踩加仓',
    addRationale: '实时价接近支撑区且中短期趋势未破坏，加仓观察价应围绕支撑和波动缓冲设置。',
    waitHeadline: '等待触发',
    waitRationale: '实时价尚未接近加仓支撑或减仓压力，等待价格进入观察区再动作。',
  },
  en: {
    terminal: 'Equity Quote Monitor',
    lab: 'PolyBob Equity Watch / REAL-ONLY',
    coverage: 'Coverage',
    watchlist: 'Quote Watchlist',
    favorites: 'Favorites',
    all: 'All',
    category: 'Category',
    market: 'Market',
    usMarket: 'US',
    cnMarket: 'A-shares',
    search: 'Search symbol, company, sector',
    noMatch: 'No matching equity.',
    favoriteOnly: 'Favorites only',
    addFavorite: 'Favorite',
    removeFavorite: 'Favorited',
    observationOnly: 'Quote observation only',
    noAdvice: 'Technical levels',
    technicalAdvice: 'Technical add/trim watch',
    coreConclusion: 'Core conclusion',
    addZone: 'Add watch zone',
    trimZone: 'Trim watch zone',
    support: 'Support ref',
    resistance: 'Resistance ref',
    volatilityBand: 'Volatility band',
    modelBasis: 'Based on live price, chart, moving averages and volatility range. Cost basis is not used for add/trim levels.',
    adviceUnavailable: 'Insufficient real price data for watch levels.',
    portfolioNotConfigured: 'Portfolio not configured',
    quote: 'Real quote',
    movingAverages: 'Real moving averages',
    technicalSource: 'Technical data',
    provider: 'Provider',
    primaryProvider: 'Primary source',
    sourceCheck: 'Cross-source check',
    sourceAligned: 'Aligned',
    sourceWatch: 'Price gap',
    sourceDivergent: 'Divergent',
    singleSource: 'Single valid source',
    last: 'Last',
    dayPct: 'Day %',
    marketStatus: 'Market status',
    timestamp: 'Timestamp',
    delayed: 'Delayed',
    realtime: 'Realtime',
    stale: 'Stale',
    lastClose: 'Last close',
    unknownFreshness: 'Unverified',
    loadingData: 'Loading quotes',
    dataError: 'Quote error',
    ma20: '20D MA',
    ma50: '50D MA',
    ma200: '200D MA',
    asOf: 'As of',
    latestClose: 'Latest close',
    chart: 'Chart',
    chartLoading: 'Loading chart',
    chartNoData: 'No chart data',
    chartSource: 'Chart source',
    chartAsOf: 'Chart as of',
    orderBook: 'Book signal',
    orderBookCapability: 'Book capability',
    orderBookSource: 'Book source',
    orderBookFreshness: 'Book time',
    bid: 'Bid',
    ask: 'Ask',
    spread: 'Spread',
    spreadBps: 'Spread bps',
    depthImbalance: 'Depth imbalance',
    noRealOrderBook: 'Real 5-level / not full L2',
    realOrderBook: 'Real order book',
    premarket: 'Pre-market',
    regular: 'Regular',
    afterhours: 'After-hours',
    allIntraday: 'All intraday',
    overnight: 'Overnight',
    fiveDay: '5D',
    dayK: 'Day',
    weekK: 'Week',
    monthK: 'Month',
    quarterK: 'Quarter',
    yearK: 'Year',
    price: 'Price',
    volume: 'Volume',
    usSessionNote: 'US regular hours are 9:30-16:00 ET, pre-market is 4:00-9:30 ET, and after-hours is 16:00-20:00 ET. Overnight trading usually depends on broker/ATS coverage and may not be available from free sources.',
    cnSessionNote: 'A-shares usually trade 9:30-11:30 and 13:00-15:00 Beijing time, without US-style pre-market, after-hours, or overnight sessions.',
    above: 'Above MA',
    below: 'Below MA',
    unavailable: 'No real data',
    configured: 'Connected',
    notConfigured: 'Not configured',
    personal: 'Personal',
    nasdaq100: 'NDX',
    realOnlyRule: 'This page uses real quotes, real charts and real moving averages to generate technical watch levels. Without a real portfolio, it does not generate target weights, win rate, Sharpe, valuation, or earnings risk.',
    unavailableHeadline: 'Insufficient data',
    unavailableRationale: 'Real quote or latest close is unavailable, so technical watch levels are not calculated.',
    holdHeadline: 'Hold / Watch',
    holdRationale: 'Price is between support and resistance; observation is the primary action.',
    riskTrimHeadline: 'Risk trim',
    riskTrimRationale: 'Price is below the key moving-average stack, so reducing risk exposure takes priority.',
    trimHeadline: 'Trim into strength',
    trimRationale: 'Price is extended versus the short-term average or intraday high; trim levels should sit near resistance.',
    addHeadline: 'Add on pullback',
    addRationale: 'Price is near support while the short/mid-term trend is intact; add levels should sit around support plus a volatility buffer.',
    waitHeadline: 'Wait for trigger',
    waitRationale: 'Price has not reached the add support zone or trim resistance zone; wait until it enters a watch zone.',
  },
};

export default function USEquityAdvisor({
  symbol: symbolOverride,
  hideList = false,
}: {
  /** Pin the panel to one instrument (used by that instrument's own page). */
  symbol?: string;
  /** Hide the watchlist rail when the page is already about a single name. */
  hideList?: boolean;
} = {}) {
  const { language } = useLanguage();
  const text = uiText[language];
  // The URL is the page's single source of truth for which instrument is being
  // looked at. This used to be local state while VerdictBanner read ?symbol=,
  // so clicking AMD in this list left the verdict above still judging NVDA and
  // the wisdom panel below still judging NVDA — three panels, three answers,
  // one screen. The verdict now lives on the instrument's own route, and
  // selecting here navigates there.
  const searchParams = useSearchParams();
  const router = useRouter();
  const [mobileView, setMobileView] = useState<'detail' | 'list'>('detail');
  const selectedSymbol = (
    symbolOverride || searchParams?.get('symbol') || 'NVDA'
  ).toUpperCase();
  // Selecting a name stays on this page and swaps the detail panel, which is
  // what the quote, chart, moving averages, order book and technical read are
  // for. Navigating away on click removed all of that behind a page with only a
  // verdict on it — the selection UI and the detail UI belong together.
  const setSelectedSymbol = useCallback(
    (next: string) => {
      const clean = (next || '').trim().toUpperCase();
      if (!clean || clean === selectedSymbol) return;
      const params = new URLSearchParams(searchParams?.toString() ?? '');
      params.set('symbol', clean);
      router.replace(`?${params.toString()}`, { scroll: false });
      setMobileView('detail');
    },
    [router, searchParams, selectedSymbol],
  );
  const [query, setQuery] = useState('');
  const [selectedMarket, setSelectedMarket] = useState<Market>('US');
  const [selectedCategory, setSelectedCategory] = useState('All');
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [favorites, setFavorites] = useState<string[]>([]);
  const [chartMode, setChartMode] = useState<ChartMode>('all_intraday');
  const [page, setPage] = useState(1);
  const urlNamedSymbol = Boolean(symbolOverride || searchParams?.get('symbol'));

  const marketObservations = useMemo(() => {
    return observations.filter((item) => item.market === selectedMarket);
  }, [selectedMarket]);

  const categories = useMemo(() => {
    const values = Array.from(new Set(marketObservations.map((item) => item.sector))).sort();
    return ['All', ...values, 'Personal'];
  }, [marketObservations]);

  useEffect(() => {
    try {
      const storedFavorites = JSON.parse(window.localStorage.getItem(favoritesStorageKey) || '[]');
      if (Array.isArray(storedFavorites)) {
        setFavorites(storedFavorites.filter((item) => typeof item === 'string'));
      }
    } catch {
      setFavorites([]);
    }
  }, []);

  // Switching market (US ⇄ A-share) resets the view — but it must not overwrite
  // an instrument the URL explicitly asked for. This effect also runs on mount,
  // so it was stamping the first name of the default market over ?symbol=,
  // which is why opening a link to AMD landed on AAPL.
  const marketSwitchedOnce = useRef(false);
  useEffect(() => {
    setSelectedCategory('All');
    setChartMode('all_intraday');
    setPage(1);
    if (!marketSwitchedOnce.current) {
      marketSwitchedOnce.current = true;   // mount: honour the URL
      return;
    }
    if (urlNamedSymbol) return;
    const nextSymbol = observations.find((item) => item.market === selectedMarket)?.symbol || 'NVDA';
    setSelectedSymbol(nextSymbol);
  }, [selectedMarket, setSelectedSymbol, urlNamedSymbol]);

  const activeQuoteQuery = useQuery<QuotePayload>({
    queryKey: ['equities', 'quotes', 'active', selectedSymbol],
    queryFn: async ({ signal }) => {
      const response = await fetch(`/api/us-equities/quotes?scope=active&symbols=${encodeURIComponent(selectedSymbol)}`, {
        cache: 'no-store',
        signal,
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.json();
    },
    enabled: selectedSymbol.length > 0,
    refetchInterval: selectedMarket === 'CN' ? 5_000 : 8_000,
    staleTime: selectedMarket === 'CN' ? 4_000 : 7_000,
  });

  const filteredObservations = useMemo(() => {
    const normalizedQuery = query.trim().toUpperCase();
    return marketObservations.filter((item) => {
      if (favoritesOnly && !favorites.includes(item.symbol)) {
        return false;
      }
      if (selectedCategory === 'Personal' && item.universe !== 'Personal') {
        return false;
      }
      if (selectedCategory !== 'All' && selectedCategory !== 'Personal' && item.sector !== selectedCategory) {
        return false;
      }
      if (!normalizedQuery) {
        return true;
      }
      return buildSearchText(item).includes(normalizedQuery);
    });
  }, [favorites, favoritesOnly, marketObservations, query, selectedCategory]);

  const pagination = useMemo(
    () => paginateEquities(filteredObservations, page),
    [filteredObservations, page],
  );
  const batchQuoteSymbols = useMemo(
    () => buildBatchQuoteSymbols(pagination.items, selectedSymbol, favorites),
    [favorites, pagination.items, selectedSymbol],
  );

  useEffect(() => {
    setPage(1);
  }, [favoritesOnly, query, selectedCategory]);

  useEffect(() => {
    if (page !== pagination.page) {
      setPage(pagination.page);
    }
  }, [page, pagination.page]);

  const batchQuoteQuery = useQuery<QuotePayload>({
    queryKey: ['equities', 'quotes', 'batch', selectedMarket, batchQuoteSymbols],
    queryFn: async ({ signal }) => {
      const response = await fetch(`/api/us-equities/quotes?symbols=${encodeURIComponent(batchQuoteSymbols)}`, {
        cache: 'no-store',
        signal,
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.json();
    },
    refetchInterval: selectedMarket === 'CN' ? 30_000 : 60_000,
    staleTime: selectedMarket === 'CN' ? 25_000 : 55_000,
  });
  const quoteState = useMemo<QuoteState>(() => {
    const batch = batchQuoteQuery.data;
    const active = activeQuoteQuery.data;
    const quotes = [...(batch?.quotes ?? []), ...(active?.quotes ?? [])];
    return {
      bySymbol: Object.fromEntries(quotes.map((quote) => [quote.symbol, quote])),
      provider: active?.provider ?? batch?.provider ?? 'nasdaq',
      timestamp: active?.timestamp ?? batch?.timestamp ?? null,
      loading: batchQuoteQuery.isPending && activeQuoteQuery.isPending,
      error: batchQuoteQuery.error instanceof Error
        ? batchQuoteQuery.error.message
        : activeQuoteQuery.error instanceof Error ? activeQuoteQuery.error.message : null,
    };
  }, [activeQuoteQuery.data, activeQuoteQuery.error, activeQuoteQuery.isPending, batchQuoteQuery.data, batchQuoteQuery.error, batchQuoteQuery.isPending]);

  // Only snap to the first row when the URL named nothing. The watchlist is a
  // hardcoded Nasdaq-100 style universe, but the insider-cluster edge lives in
  // small and mid caps — SCTX, FSBC, CLBK are exactly the tickers it fires on
  // and none of them are in the list. Overriding an explicit ?symbol= with the
  // first list item meant clicking through from 今日机会 landed you on AAPL.
  useEffect(() => {
    if (urlNamedSymbol || filteredObservations.length === 0) {
      return;
    }
    if (!filteredObservations.some((item) => item.symbol === selectedSymbol)) {
      setSelectedSymbol(filteredObservations[0].symbol);
    }
  }, [filteredObservations, selectedSymbol, setSelectedSymbol, urlNamedSymbol]);

  // A symbol from the URL that is not in the watchlist is still a real
  // instrument: synthesise a minimal row for it so the quote, chart and
  // technicals can load rather than silently showing a different stock.
  const selected =
    marketObservations.find((item) => item.symbol === selectedSymbol)
    ?? (urlNamedSymbol
      ? ({
          symbol: selectedSymbol,
          name: selectedSymbol,
          // A-share codes are six digits; anything else is treated as US. Same
          // rule the wisdom endpoint uses to resolve a bare symbol.
          market: /^\d{6}/.test(selectedSymbol) ? 'CN' : 'US',
          sector: '',
          universe: 'Personal',
        } satisfies EquityObservation)
      : undefined)
    ?? marketObservations[0]
    ?? observations[0];
  const favoriteSet = useMemo(() => new Set(favorites), [favorites]);
  const selectedQuote = quoteState.bySymbol[selected.symbol];
  const technicalQuery = useQuery<Omit<TechnicalState, 'loading' | 'error'>>({
    queryKey: ['equities', 'technicals', selected.symbol],
    queryFn: async ({ signal }) => {
        const response = await fetch(`/api/equities/technicals?symbol=${encodeURIComponent(selected.symbol)}`, {
          cache: 'no-store',
          signal,
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
    },
    staleTime: 5 * 60_000,
  });
  const technicalState = useMemo<TechnicalState>(() => technicalQuery.data
    ? { ...technicalQuery.data, loading: false, error: null }
    : {
        symbol: selected.symbol,
        loading: technicalQuery.isPending,
        error: technicalQuery.error instanceof Error ? technicalQuery.error.message : null,
        provider: null,
        asOf: null,
        latestClose: null,
        movingAverages: null,
        trend: null,
      }, [selected.symbol, technicalQuery.data, technicalQuery.error, technicalQuery.isPending]);

  const effectiveMode = selected.market === 'CN' && chartMode === 'overnight' ? 'all_intraday' : chartMode;
  const chartQuery = useQuery<ChartPayload>({
    queryKey: ['equities', 'chart', selected.symbol, effectiveMode],
    queryFn: async ({ signal }) => {
        const response = await fetch(`/api/equities/chart?symbol=${encodeURIComponent(selected.symbol)}&mode=${encodeURIComponent(effectiveMode)}`, {
          cache: 'no-store',
          signal,
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
    },
    staleTime: effectiveMode === 'all_intraday' ? 15_000 : 60_000,
  });
  const chartState = useMemo<ChartState>(() => ({
    symbol: selected.symbol,
    mode: effectiveMode,
    loading: chartQuery.isPending,
    error: chartQuery.error instanceof Error ? chartQuery.error.message : null,
    payload: chartQuery.data ?? null,
  }), [chartQuery.data, chartQuery.error, chartQuery.isPending, effectiveMode, selected.symbol]);

  const orderBookQuery = useQuery<OrderBookPayload>({
    queryKey: ['equities', 'order-book', selected.symbol],
    queryFn: async ({ signal }) => {
      const response = await fetch(`/api/equities/order-book?symbol=${encodeURIComponent(selected.symbol)}`, {
        cache: 'no-store',
        signal,
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.json();
    },
    refetchInterval: selected.market === 'CN' ? 3_000 : 15_000,
    staleTime: selected.market === 'CN' ? 2_000 : 12_000,
  });
  const orderBookState = useMemo<OrderBookState>(() => ({
    symbol: selected.symbol,
    loading: orderBookQuery.isPending,
    error: orderBookQuery.error instanceof Error ? orderBookQuery.error.message : null,
    payload: orderBookQuery.data ?? null,
  }), [orderBookQuery.data, orderBookQuery.error, orderBookQuery.isPending, selected.symbol]);

  const toggleFavorite = useCallback((symbol: string) => {
    setFavorites((previous) => {
      const nextFavorites = previous.includes(symbol)
        ? previous.filter((item) => item !== symbol)
        : [...previous, symbol].sort();
      window.localStorage.setItem(favoritesStorageKey, JSON.stringify(nextFavorites));
      return nextFavorites;
    });
  }, []);

  const technicalAdvice = useMemo(() => {
    return buildTechnicalAdvice({
      quote: selectedQuote,
      technicals: technicalState.symbol === selected.symbol
        ? technicalState
        : { latestClose: null, movingAverages: null },
      chart: chartState.symbol === selected.symbol && chartState.payload
        ? { symbol: chartState.symbol, points: chartState.payload.points }
        : null,
      selectedSymbol: selected.symbol,
      market: selected.market,
      text,
    });
  }, [chartState, selected.market, selected.symbol, selectedQuote, technicalState, text]);

  return (
    <div className="w-full min-w-0 overflow-hidden rounded-md border border-stone-200 bg-white text-stone-900 shadow-[0_1px_2px_rgba(28,25,23,0.04)]">
      <TerminalHeader language={language} quoteState={quoteState} />

      {!hideList ? (
        <div className="grid grid-cols-2 border-t border-stone-200 bg-stone-50 p-1 lg:hidden">
          <button
            type="button"
            onClick={() => setMobileView('detail')}
            className={`rounded px-3 py-2 text-xs font-semibold ${mobileView === 'detail' ? 'bg-white text-sky-700 shadow-sm' : 'text-stone-500'}`}
          >
            {language === 'zh' ? `${selected.symbol} 详情` : `${selected.symbol} detail`}
          </button>
          <button
            type="button"
            onClick={() => setMobileView('list')}
            className={`rounded px-3 py-2 text-xs font-semibold ${mobileView === 'list' ? 'bg-white text-sky-700 shadow-sm' : 'text-stone-500'}`}
          >
            {language === 'zh' ? '股票池' : 'Watchlist'}
          </button>
        </div>
      ) : null}

      <div
        className={
          hideList
            ? 'border-t border-stone-200'
            : 'grid border-t border-stone-200 lg:grid-cols-[minmax(250px,280px),minmax(0,1fr)]'
        }
      >
        <div className={hideList ? 'hidden' : `${mobileView === 'list' ? 'block' : 'hidden'} lg:block`}>
          <ObservationRail
            categories={categories}
            favoriteSet={favoriteSet}
            favoritesOnly={favoritesOnly}
            filteredCount={filteredObservations.length}
            filteredObservations={pagination.items}
            language={language}
            page={pagination.page}
            query={query}
            quoteState={quoteState}
            selectedCategory={selectedCategory}
            selectedMarket={selectedMarket}
            selectedSymbol={selected.symbol}
            text={text}
            totalCount={observations.length}
            totalPages={pagination.totalPages}
            onCategoryChange={setSelectedCategory}
            onFavoritesOnlyChange={setFavoritesOnly}
            onMarketChange={setSelectedMarket}
            onPageChange={setPage}
            onQueryChange={setQuery}
            onSelect={setSelectedSymbol}
            onToggleFavorite={toggleFavorite}
          />
        </div>

        <section className={`${!hideList && mobileView === 'list' ? 'hidden' : 'block'} min-w-0 bg-white lg:block lg:border-l`}>
          <ForecastLabPanel
            key={`${selected.market}:${selected.symbol}`}
            symbol={selected.symbol}
            domain={selected.market === 'CN' ? 'a_share' : 'us_equity'}
          />
          <EquityDecisionHeader
            advice={technicalAdvice}
            favoriteSet={favoriteSet}
            verdictDomain={selected.market === 'CN' ? 'a_share' : 'us_equity'}
            item={selected}
            quote={selectedQuote}
            text={text}
            onToggleFavorite={toggleFavorite}
          />
          <EquityChartPanel
            chartMode={chartMode}
            chartState={chartState}
            item={selected}
            text={text}
            onChartModeChange={setChartMode}
          />
          <QuotePanel item={selected} quote={selectedQuote} quoteState={quoteState} text={text} />
          <OrderBookPanel item={selected} orderBookState={orderBookState} text={text} />
          <MovingAveragePanel item={selected} technicalState={technicalState} text={text} />
          <GuardrailPanel quoteState={quoteState} technicalState={technicalState} text={text} />
        </section>
      </div>
    </div>
  );
}

function TerminalHeader({
  language,
  quoteState,
}: {
  language: Language;
  quoteState: QuoteState;
}) {
  const text = uiText[language];
  const anyRealtime = Object.values(quoteState.bySymbol).some((quote) => quote.dataStatus === 'realtime');
  const quoteStatus = quoteState.error
    ? text.dataError
    : quoteState.loading
      ? text.loadingData
      : anyRealtime
        ? text.realtime
        : text.delayed;
  const providerStatus = `${quoteState.provider.toUpperCase()} ${quoteStatus}`;

  return (
    <header className="grid min-w-0 gap-3 bg-white px-4 py-3 md:grid-cols-[minmax(0,1fr),auto] md:items-center">
      <div className="min-w-0">
        <div className="mono text-[11px] font-semibold uppercase text-amber-600">
          {text.lab}
        </div>
        <div className="mt-1 text-lg font-semibold text-stone-900">
          {text.terminal}
        </div>
      </div>
      <div className="hidden min-w-0 grid-cols-3 gap-2 text-right md:grid">
        <TapeMetric label={text.quote} value={providerStatus} tone={quoteState.error ? 'red' : anyRealtime ? 'green' : 'amber'} />
        <TapeMetric label={text.noAdvice} value={text.configured} tone="cyan" />
        <TapeMetric label={text.portfolioNotConfigured} value={text.notConfigured} tone="amber" />
      </div>
    </header>
  );
}

function TapeMetric({ label, value, tone }: { label: string; value: string; tone: 'cyan' | 'amber' | 'red' | 'green' }) {
  const toneClass = {
    cyan: 'text-sky-700',
    amber: 'text-amber-600',
    red: 'text-rose-600',
    green: 'text-emerald-600',
  }[tone];

  return (
    <div className="min-w-0 rounded border border-stone-200 bg-stone-50 px-2 py-2 sm:px-3">
      <div className="mono text-[10px] uppercase text-stone-500">{label}</div>
      <div className={`mono mt-1 truncate text-xs font-semibold sm:text-sm ${toneClass}`}>{value}</div>
    </div>
  );
}

const ObservationRail = memo(function ObservationRail({
  categories,
  favoriteSet,
  favoritesOnly,
  filteredCount,
  filteredObservations,
  language,
  page,
  query,
  quoteState,
  selectedCategory,
  selectedMarket,
  selectedSymbol,
  text,
  totalCount,
  totalPages,
  onCategoryChange,
  onFavoritesOnlyChange,
  onMarketChange,
  onPageChange,
  onQueryChange,
  onSelect,
  onToggleFavorite,
}: {
  categories: string[];
  favoriteSet: Set<string>;
  favoritesOnly: boolean;
  filteredCount: number;
  filteredObservations: EquityObservation[];
  language: Language;
  page: number;
  query: string;
  quoteState: QuoteState;
  selectedCategory: string;
  selectedMarket: Market;
  selectedSymbol: string;
  text: typeof uiText.zh;
  totalCount: number;
  totalPages: number;
  onCategoryChange: (category: string) => void;
  onFavoritesOnlyChange: (favoritesOnly: boolean) => void;
  onMarketChange: (market: Market) => void;
  onPageChange: (page: number) => void;
  onQueryChange: (query: string) => void;
  onSelect: (symbol: string) => void;
  onToggleFavorite: (symbol: string) => void;
}) {
  return (
    <aside className="bg-white">
      <div className="border-b border-stone-200 px-3 py-3">
        <div className="mono text-[11px] font-semibold uppercase text-stone-500">{text.watchlist}</div>
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="mono text-[10px] uppercase text-amber-600">
            {text.coverage}
          </span>
          <span className="mono text-[10px] text-stone-500">
            {filteredCount}/{totalCount}
          </span>
        </div>
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={text.search}
          className="mono mt-3 w-full rounded border border-stone-200 bg-white px-3 py-2 text-xs text-stone-900 outline-none transition placeholder:text-stone-400 focus:border-sky-500"
        />
        <div className="mt-3">
          <div className="mono mb-2 text-[10px] uppercase text-stone-500">{text.market}</div>
          <div className="grid grid-cols-2 gap-2">
            {(['US', 'CN'] as Market[]).map((market) => {
              const active = market === selectedMarket;
              return (
                <button
                  key={market}
                  type="button"
                  onClick={() => onMarketChange(market)}
                  className={`rounded border px-2 py-2 text-xs font-semibold transition ${
                    active ? 'border-sky-500 bg-sky-50 text-sky-700' : 'border-stone-200 text-stone-600 hover:border-sky-400'
                  }`}
                >
                  {market === 'US' ? text.usMarket : text.cnMarket}
                </button>
              );
            })}
          </div>
        </div>
        <div className="mt-3 flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => onFavoritesOnlyChange(!favoritesOnly)}
            className={`rounded border px-2 py-1 text-[11px] font-semibold transition ${
              favoritesOnly ? 'border-sky-500 bg-sky-50 text-sky-700' : 'border-stone-200 text-stone-600 hover:border-sky-400'
            }`}
          >
            {text.favoriteOnly}
          </button>
          <span className="mono text-[10px] text-stone-500">{favoriteSet.size} {text.favorites}</span>
        </div>
        <div className="mt-3">
          <div className="mono mb-2 text-[10px] uppercase text-stone-500">{text.category}</div>
          <div className="flex max-h-28 flex-wrap gap-2 overflow-y-auto pr-1">
            {categories.map((category) => {
              const active = category === selectedCategory;
              return (
                <button
                  key={category}
                  type="button"
                  onClick={() => onCategoryChange(category)}
                  className={`rounded border px-2 py-1 text-[10px] font-semibold transition ${
                    active ? 'border-sky-500 bg-sky-50 text-sky-700' : 'border-stone-200 text-stone-600 hover:border-sky-500'
                  }`}
                >
                  {category === 'All' ? text.all : category === 'Personal' ? text.personal : category}
                </button>
              );
            })}
          </div>
        </div>
        <div className="mt-2 text-[11px] leading-4 text-stone-500">{language === 'zh' ? sourceNoteZh : sourceNote}</div>
      </div>
      <div className="divide-y divide-[#e7e5e4]">
        {filteredObservations.map((item) => {
          const active = item.symbol === selectedSymbol;
          const quote = quoteState.bySymbol[item.symbol];
          return (
            <div
              key={item.symbol}
              onClick={() => onSelect(item.symbol)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onSelect(item.symbol);
                }
              }}
              role="button"
              tabIndex={0}
              className={`grid w-full grid-cols-[76px,minmax(0,1fr)] gap-3 px-3 py-3 text-left transition ${
                active ? 'bg-stone-50' : 'hover:bg-stone-50'
              }`}
            >
              <div>
                <div className="mono text-base font-semibold text-stone-900">{item.symbol}</div>
                <div className={changeClass(quote?.dayChangePct)}>{formatOptionalPct(quote?.dayChangePct)}</div>
              </div>
              <div className="min-w-0 overflow-hidden">
                <div className="flex items-center justify-between gap-2">
                  <span className="rounded bg-sky-50 px-2 py-0.5 text-[11px] font-semibold text-sky-700">
                    {text.observationOnly}
                  </span>
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onToggleFavorite(item.symbol);
                    }}
                    className={`mono rounded px-2 py-0.5 text-[10px] ${
                      favoriteSet.has(item.symbol) ? 'bg-amber-50 text-amber-600' : 'bg-stone-50 text-stone-400'
                    }`}
                  >
                    {favoriteSet.has(item.symbol) ? '★' : '☆'}
                  </button>
                  <span className="mono hidden shrink-0 text-[11px] text-stone-500 min-[520px]:inline">
                    {formatOptionalMoney(quote?.price, item.market)}
                  </span>
                </div>
                <div className="mt-2 truncate text-xs text-stone-600">
                  {item.name} / {item.sector}
                </div>
                <div className="mono mt-1 text-[10px] uppercase text-stone-400">
                  {item.universe === 'Personal' ? text.personal : text.nasdaq100}
                </div>
              </div>
            </div>
          );
        })}
        {filteredObservations.length === 0 ? (
          <div className="px-3 py-8 text-sm text-stone-500">
            {text.noMatch}
          </div>
        ) : null}
      </div>
      {filteredCount > 0 ? (
        <div className="flex h-11 items-center justify-between border-t border-stone-200 px-3">
          <button
            type="button"
            aria-label={language === 'zh' ? '上一页' : 'Previous page'}
            title={language === 'zh' ? '上一页' : 'Previous page'}
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
            className="mono h-7 w-8 rounded border border-stone-200 text-sm text-stone-600 transition hover:border-sky-500 hover:text-sky-700 disabled:cursor-not-allowed disabled:opacity-30"
          >
            ←
          </button>
          <span className="mono text-[11px] text-stone-500">{page}/{totalPages}</span>
          <button
            type="button"
            aria-label={language === 'zh' ? '下一页' : 'Next page'}
            title={language === 'zh' ? '下一页' : 'Next page'}
            disabled={page >= totalPages}
            onClick={() => onPageChange(page + 1)}
            className="mono h-7 w-8 rounded border border-stone-200 text-sm text-stone-600 transition hover:border-sky-500 hover:text-sky-700 disabled:cursor-not-allowed disabled:opacity-30"
          >
            →
          </button>
        </div>
      ) : null}
    </aside>
  );
});

function EquityDecisionHeader({
  advice,
  favoriteSet,
  item,
  quote,
  verdictDomain,
  text,
  onToggleFavorite,
}: {
  advice: TechnicalAdvice;
  favoriteSet: Set<string>;
  item: EquityObservation;
  quote?: QuotePayload['quotes'][number];
  /** Which market's verdict rules apply to this name. */
  verdictDomain: string;
  text: typeof uiText.zh;
  onToggleFavorite: (symbol: string) => void;
}) {
  const actionTone = advice.action === 'add'
    ? 'good'
    : advice.action === 'trim' || advice.action === 'risk_trim'
      ? 'bad'
      : undefined;

  return (
    <section className="border-b border-stone-200 bg-white p-4 md:p-5">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr),minmax(340px,0.95fr)]">
        <div className="min-w-0 rounded border border-stone-200 bg-white p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="mono text-3xl font-semibold text-stone-900 sm:text-4xl">{item.symbol}</span>
                <span className="rounded bg-sky-50 px-2 py-1 text-xs font-semibold text-sky-700">
                  {item.market === 'US' ? text.usMarket : text.cnMarket}
                </span>
                <span className="rounded border border-stone-200 px-2 py-1 text-xs text-stone-600">
                  {item.universe === 'Personal' ? text.personal : text.nasdaq100}
                </span>
              </div>
              <div className="mt-2 truncate text-sm text-stone-600">{item.name} / {item.sector}</div>
            </div>
            <button
              type="button"
              onClick={() => onToggleFavorite(item.symbol)}
              className={`shrink-0 rounded border px-3 py-1.5 text-xs font-semibold ${
                favoriteSet.has(item.symbol) ? 'border-sky-500 bg-sky-50 text-sky-700' : 'border-stone-200 text-stone-600'
              }`}
            >
              {favoriteSet.has(item.symbol) ? `★ ${text.removeFavorite}` : `☆ ${text.addFavorite}`}
            </button>
          </div>

          {/*
            该标的的投资准则判定 — above the core conclusion on purpose.
            What follows below is a moving-average read: this project tested
            chart-pattern rules across 184 configurations and confirmed none of
            them, so 「逢高减仓」 is context, not evidence. The verdict is the
            part with a measured win rate and a sample size behind it, and the
            reader meets it first.
          */}
          <div className="mt-4">
            <VerdictBanner symbol={item.symbol} domain={verdictDomain} embedded compact />
          </div>

          <div className="mt-5 grid gap-4 sm:grid-cols-[minmax(0,1fr),auto] sm:items-end">
            <div>
              <div className="mono text-[10px] uppercase text-stone-500">{text.coreConclusion}</div>
              <div className={`mt-2 text-3xl font-semibold leading-tight ${actionTone === 'good' ? 'text-emerald-600' : actionTone === 'bad' ? 'text-rose-600' : 'text-stone-900'}`}>
                {advice.headline}
              </div>
            </div>
            <div className="sm:text-right">
              <div className="mono text-[10px] uppercase text-stone-500">{text.last}</div>
              <div className="mono mt-1 text-4xl font-semibold text-stone-900">{formatOptionalMoney(advice.currentPrice ?? quote?.price, item.market)}</div>
              <div className={changeClass(quote?.dayChangePct)}>{formatOptionalPct(quote?.dayChangePct)}</div>
            </div>
          </div>

          <p className="mt-4 max-w-3xl text-sm leading-6 text-stone-600">{advice.rationale}</p>
          <p className="mt-2 text-xs leading-5 text-stone-500">{text.modelBasis}</p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
          <div className="rounded border border-emerald-200 bg-emerald-50 p-4">
            <div className="mono text-[10px] uppercase text-emerald-600">{text.addZone}</div>
            <div className="mono mt-2 text-2xl font-semibold text-emerald-600">
              {formatPriceRange(advice.addLow, advice.addHigh, item.market)}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <MiniStat label={text.support} value={formatOptionalMoney(advice.support, item.market)} />
              <MiniStat label={text.volatilityBand} value={formatOptionalMoney(advice.volatilityBand, item.market)} />
            </div>
          </div>

          <div className="rounded border border-rose-200 bg-rose-50 p-4">
            <div className="mono text-[10px] uppercase text-rose-500">{text.trimZone}</div>
            <div className="mono mt-2 text-2xl font-semibold text-rose-600">
              {formatPriceRange(advice.trimLow, advice.trimHigh, item.market)}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <MiniStat label={text.resistance} value={formatOptionalMoney(advice.resistance, item.market)} />
              <MiniStat label={text.quote} value={formatDataStatus(quote?.dataStatus, text)} />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded border border-stone-200 bg-stone-50 px-2 py-2">
      <div className="mono text-[9px] uppercase text-stone-500">{label}</div>
      <div className="mono mt-1 truncate text-sm font-semibold text-stone-900">{value}</div>
    </div>
  );
}

const QuotePanel = memo(function QuotePanel({
  item,
  quote,
  quoteState,
  text,
}: {
  item: EquityObservation;
  quote?: QuotePayload['quotes'][number];
  quoteState: QuoteState;
  text: typeof uiText.zh;
}) {
  const status = quote ? formatDataStatus(quote.dataStatus, text) : quoteState.loading ? text.loadingData : text.unavailable;
  const sourceNames = quote?.sources
    ?.filter((source) => source.price !== null)
    .map((source) => source.provider.toUpperCase())
    .join(' + ');
  const sourceCheck = formatSourceCheck(quote, text);

  return (
    <section className="border-b border-stone-200 p-4 md:p-5">
      <PanelTitle title={text.quote} code="QUOTE" />
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        <TerminalStat label={text.last} value={formatOptionalMoney(quote?.price, item.market)} tone={quote?.price === null || !quote ? undefined : 'good'} />
        <TerminalStat label={text.dayPct} value={formatOptionalPct(quote?.dayChangePct)} tone={quote?.dayChangePct === undefined || quote?.dayChangePct === null ? undefined : quote.dayChangePct >= 0 ? 'good' : 'bad'} />
        <TerminalStat label={text.marketStatus} value={quote?.marketStatus ? `${quote.marketStatus} / ${status}` : status} />
        <TerminalStat label={text.timestamp} value={quote?.lastTradeTimestamp || quoteState.timestamp || '--'} />
        <TerminalStat label={text.primaryProvider} value={quote?.primaryProvider?.toUpperCase() || quote?.provider.toUpperCase() || '--'} />
        <TerminalStat label={text.sourceCheck} value={sourceNames ? `${sourceNames} / ${sourceCheck}` : sourceCheck} tone={sourceCheck === text.sourceAligned ? 'good' : undefined} />
      </div>
      {quote?.error || quoteState.error ? (
        <div className="mt-3 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-600">
          {quote?.error || quoteState.error}
        </div>
      ) : null}
    </section>
  );
});

const EquityChartPanel = memo(function EquityChartPanel({
  chartMode,
  chartState,
  item,
  text,
  onChartModeChange,
}: {
  chartMode: ChartMode;
  chartState: ChartState;
  item: EquityObservation;
  text: typeof uiText.zh;
  onChartModeChange: (mode: ChartMode) => void;
}) {
  const sessionOptions: Array<{ mode: ChartMode; label: string; disabled?: boolean }> = item.market === 'US'
    ? [
        { mode: 'premarket', label: text.premarket },
        { mode: 'regular', label: text.regular },
        { mode: 'afterhours', label: text.afterhours },
        { mode: 'all_intraday', label: text.allIntraday },
        { mode: 'overnight', label: text.overnight },
      ]
    : [
        { mode: 'all_intraday', label: text.regular },
        { mode: 'premarket', label: text.premarket, disabled: true },
        { mode: 'afterhours', label: text.afterhours, disabled: true },
        { mode: 'overnight', label: text.overnight, disabled: true },
      ];
  const rangeOptions: Array<{ mode: ChartMode; label: string }> = [
    { mode: '5d', label: text.fiveDay },
    { mode: 'day', label: text.dayK },
    { mode: 'week', label: text.weekK },
    { mode: 'month', label: text.monthK },
    { mode: 'quarter', label: text.quarterK },
    { mode: 'year', label: text.yearK },
  ];
  const points = chartState.payload?.points || [];
  const color = points.length > 1 && points[points.length - 1].price >= points[0].price ? '#059669' : '#e11d48';
  const note = item.market === 'US' ? text.usSessionNote : text.cnSessionNote;

  return (
    <section className="border-b border-stone-200 p-4 md:p-5">
      <PanelTitle title={text.chart} code="CHART" />
      <div className="mt-4 flex flex-wrap gap-2">
        {sessionOptions.map((option) => (
          <button
            key={option.mode}
            type="button"
            disabled={option.disabled}
            onClick={() => onChartModeChange(option.mode)}
            className={`rounded border px-3 py-2 text-xs font-semibold transition ${
              chartMode === option.mode
                ? 'border-sky-500 bg-sky-50 text-sky-700'
                : option.disabled
                  ? 'cursor-not-allowed border-stone-200 text-stone-400'
                  : 'border-stone-200 text-stone-600 hover:border-sky-400'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {rangeOptions.map((option) => (
          <button
            key={option.mode}
            type="button"
            onClick={() => onChartModeChange(option.mode)}
            className={`rounded border px-3 py-2 text-xs font-semibold transition ${
              chartMode === option.mode
                ? 'border-sky-500 bg-sky-50 text-sky-700'
                : 'border-stone-200 text-stone-600 hover:border-sky-500'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="mt-4 rounded border border-stone-200 bg-white p-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="mono text-[10px] uppercase text-stone-500">{chartState.payload?.sessionInfo.label || text.chart}</div>
            <div className="mt-1 text-sm text-stone-600">{chartState.payload?.sessionInfo.description || note}</div>
          </div>
          <div className="mono text-right text-[11px] text-stone-500">
            <div>{text.chartSource}: {chartState.payload?.provider || '--'}</div>
            <div>{text.chartAsOf}: {chartState.payload?.asOf || '--'}</div>
          </div>
        </div>

        <div className="mt-4 h-[320px] min-w-0">
          {chartState.loading ? (
            <div className="flex h-full items-center justify-center text-sm text-stone-500">{text.chartLoading}</div>
          ) : chartState.error ? (
            <div className="flex h-full items-center justify-center text-sm text-rose-600">{chartState.error}</div>
          ) : points.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-stone-500">{text.chartNoData}</div>
          ) : (
            <EquityPriceChart
              points={points}
              color={color}
              symbol={item.symbol}
              market={item.market}
              priceLabel={text.price}
              volumeLabel={text.volume}
            />
          )}
        </div>
      </div>

      <div className="mt-3 text-xs leading-5 text-stone-500">{note}</div>
    </section>
  );
});

const OrderBookPanel = memo(function OrderBookPanel({
  item,
  orderBookState,
  text,
}: {
  item: EquityObservation;
  orderBookState: OrderBookState;
  text: typeof uiText.zh;
}) {
  const payload = orderBookState.symbol === item.symbol ? orderBookState.payload : null;
  const quality = payload?.isRealOrderBook ? text.realOrderBook : text.noRealOrderBook;
  const capability = payload?.capability || (orderBookState.loading ? text.loadingData : 'QUOTE_ONLY');

  return (
    <section className="border-b border-stone-200 p-4 md:p-5">
      <PanelTitle title={text.orderBook} code="BOOK" />
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <TerminalStat label={text.orderBookCapability} value={`${capability} / ${quality}`} tone={payload?.capability === 'QUOTE_ONLY' ? 'bad' : undefined} />
        <TerminalStat label={text.orderBookSource} value={payload?.provider ? payload.provider.toUpperCase() : '--'} />
        <TerminalStat label={text.spread} value={formatOptionalMoney(payload?.spread, item.market)} />
        <TerminalStat label={text.depthImbalance} value={formatOptionalRatio(payload?.depthImbalance)} tone={imbalanceTone(payload?.depthImbalance)} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="rounded border border-emerald-200 bg-emerald-50 p-3">
          <div className="mono text-[10px] uppercase text-emerald-600">{text.bid}</div>
          <OrderBookLevels levels={payload?.bids || []} market={item.market} tone="bid" text={text} />
        </div>
        <div className="rounded border border-rose-200 bg-rose-50 p-3">
          <div className="mono text-[10px] uppercase text-rose-500">{text.ask}</div>
          <OrderBookLevels levels={payload?.asks || []} market={item.market} tone="ask" text={text} />
        </div>
      </div>
      <div className={`mt-3 rounded border px-3 py-2 text-sm leading-6 ${
        payload?.error || orderBookState.error
          ? 'border-rose-200 bg-rose-50 text-rose-600'
          : 'border-stone-200 bg-white text-stone-600'
      }`}
      >
        {orderBookState.loading
          ? text.loadingData
          : payload?.conclusion || orderBookState.error || text.unavailable}
      </div>
      <div className="mono mt-2 text-[10px] uppercase text-stone-500">
        {text.orderBookFreshness}: {payload?.timestamp || '--'} / {payload?.source || '--'}
      </div>
    </section>
  );
});

function OrderBookLevels({
  levels,
  market,
  tone,
  text,
}: {
  levels: OrderBookLevel[];
  market: Market;
  tone: 'bid' | 'ask';
  text: typeof uiText.zh;
}) {
  const visibleLevels = levels.slice(0, 5);
  if (visibleLevels.length === 0) {
    return (
      <div className="mt-2 grid grid-cols-2 gap-2">
        <MiniStat label={text.price} value="--" />
        <MiniStat label={text.volume} value="--" />
      </div>
    );
  }

  return (
    <div className="mt-2 overflow-hidden rounded border border-stone-200">
      <div className="grid grid-cols-[42px,minmax(0,1fr),minmax(0,1fr)] bg-stone-100 px-2 py-1 text-[10px] uppercase text-stone-500">
        <span>LVL</span>
        <span>{text.price}</span>
        <span className="text-right">{text.volume}</span>
      </div>
      <div className="divide-y divide-white/10">
        {visibleLevels.map((level) => (
          <div key={`${tone}-${level.level}`} className="grid grid-cols-[42px,minmax(0,1fr),minmax(0,1fr)] px-2 py-1.5">
            <span className="mono text-[11px] text-stone-500">{level.level}</span>
            <span className={`mono text-sm font-semibold ${tone === 'bid' ? 'text-emerald-600' : 'text-rose-600'}`}>
              {formatOptionalMoney(level.price, market)}
            </span>
            <span className="mono text-right text-sm text-stone-900">{formatCompactVolume(level.size)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MovingAveragePanel({
  item,
  technicalState,
  text,
}: {
  item: EquityObservation;
  technicalState: TechnicalState;
  text: typeof uiText.zh;
}) {
  const ma = technicalState.movingAverages;

  return (
    <section className="border-b border-stone-200 p-4 md:p-5 xl:border-b-0">
      <PanelTitle title={text.movingAverages} code="MA" />
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <TerminalStat label={text.latestClose} value={technicalState.loading ? '--' : formatOptionalMoney(technicalState.latestClose, item.market)} />
        <TerminalStat label={text.ma20} value={technicalState.loading ? '--' : formatOptionalMoney(ma?.ma20, item.market)} tone={maTone(technicalState.trend?.aboveMa20)} />
        <TerminalStat label={text.ma50} value={technicalState.loading ? '--' : formatOptionalMoney(ma?.ma50, item.market)} tone={maTone(technicalState.trend?.aboveMa50)} />
        <TerminalStat label={text.ma200} value={technicalState.loading ? '--' : formatOptionalMoney(ma?.ma200, item.market)} tone={maTone(technicalState.trend?.aboveMa200)} />
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <TrendStat label={text.ma20} value={technicalState.trend?.aboveMa20} text={text} />
        <TrendStat label={text.ma50} value={technicalState.trend?.aboveMa50} text={text} />
        <TrendStat label={text.ma200} value={technicalState.trend?.aboveMa200} text={text} />
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <TerminalStat label={text.asOf} value={technicalState.error ? text.unavailable : technicalState.asOf || '--'} />
        <TerminalStat label={text.provider} value={technicalState.provider || '--'} />
      </div>
      {technicalState.error ? (
        <div className="mt-3 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-600">
          {technicalState.error}
        </div>
      ) : null}
    </section>
  );
}

function GuardrailPanel({
  quoteState,
  technicalState,
  text,
}: {
  quoteState: QuoteState;
  technicalState: TechnicalState;
  text: typeof uiText.zh;
}) {
  return (
    <div className="grid border-t border-stone-200 bg-stone-50 lg:grid-cols-3">
      <section className="border-b border-stone-200 p-4 lg:border-b-0 lg:border-r">
        <PanelTitle title={text.portfolioNotConfigured} code="GATE" />
        <div className="mt-3 grid grid-cols-2 gap-2">
          <TerminalStat label={text.observationOnly} value={text.configured} tone="good" />
          <TerminalStat label={text.portfolioNotConfigured} value={text.notConfigured} tone="bad" />
        </div>
      </section>

      <section className="border-b border-stone-200 p-4 lg:border-b-0 lg:border-r">
        <PanelTitle title={text.provider} code="SRC" />
        <div className="mt-3 grid grid-cols-2 gap-2">
          <TerminalStat label={text.quote} value={quoteState.provider.toUpperCase()} />
          <TerminalStat label={text.technicalSource} value={technicalState.provider || '--'} />
        </div>
        <div className="mono mt-2 truncate text-[10px] text-stone-500">{quoteState.timestamp || '--'}</div>
      </section>

      <section className="p-4">
        <PanelTitle title="REAL" code="RULE" />
        <div className="mt-3 text-xs leading-5 text-stone-600">
          {text.realOnlyRule}
        </div>
      </section>
    </div>
  );
}

function PanelTitle({ title, code }: { title: string; code: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h3 className="text-sm font-semibold uppercase text-stone-700">{title}</h3>
      <span className="mono rounded border border-stone-200 px-2 py-0.5 text-[10px] text-stone-500">{code}</span>
    </div>
  );
}

function TerminalStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'good' | 'bad';
}) {
  const toneClass = tone === 'good' ? 'text-emerald-600' : tone === 'bad' ? 'text-rose-600' : 'text-stone-900';

  return (
    <div className="rounded border border-stone-200 bg-white px-3 py-3">
      <div className="mono text-[10px] uppercase text-stone-500">{label}</div>
      <div className={`mono mt-1 break-words text-lg font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function TrendStat({ label, value, text }: { label: string; value: boolean | null | undefined; text: typeof uiText.zh }) {
  const display = value === true ? text.above : value === false ? text.below : text.unavailable;
  return <TerminalStat label={label} value={display} tone={maTone(value)} />;
}

function buildSearchText(item: EquityObservation) {
  return [item.symbol, item.name, item.sector, ...(item.aliases || [])]
    .join(' ')
    .toUpperCase();
}

function formatOptionalPct(value: number | null | undefined) {
  return value === null || value === undefined ? '--' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function formatPriceRange(low: number | null, high: number | null, market: Market) {
  if (low === null || high === null) {
    return '--';
  }
  return `${formatOptionalMoney(low, market)} - ${formatOptionalMoney(high, market)}`;
}

function formatDataStatus(
  status: QuotePayload['quotes'][number]['dataStatus'] | undefined,
  text: typeof uiText.zh,
) {
  if (status === 'realtime') {
    return text.realtime;
  }
  if (status === 'delayed') {
    return text.delayed;
  }
  if (status === 'stale') {
    return text.stale;
  }
  if (status === 'last_close') {
    return text.lastClose;
  }
  return text.unknownFreshness;
}

function formatSourceCheck(
  quote: QuotePayload['quotes'][number] | undefined,
  text: typeof uiText.zh,
) {
  const validSources = quote?.verifiedSourceCount || 0;
  if (validSources < 2) {
    return text.singleSource;
  }
  const spread = quote?.sourceSpreadPct;
  if (spread === null || spread === undefined) {
    return text.singleSource;
  }
  const label = spread <= 0.25
    ? text.sourceAligned
    : spread <= 1
      ? text.sourceWatch
      : text.sourceDivergent;
  return `${label} ${spread.toFixed(2)}%`;
}

function formatOptionalMoney(value: number | null | undefined, market: Market) {
  if (value === null || value === undefined) {
    return '--';
  }
  const prefix = market === 'CN' ? '¥' : '$';
  return `${prefix}${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatCompactVolume(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '--';
  }
  if (value >= 100_000_000) {
    return `${(value / 100_000_000).toFixed(2)}亿`;
  }
  if (value >= 10_000) {
    return `${(value / 10_000).toFixed(2)}万`;
  }
  return value.toLocaleString();
}

function formatOptionalRatio(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '--';
  }
  return `${value > 0 ? '+' : ''}${value.toFixed(3)}`;
}

function imbalanceTone(value: number | null | undefined): 'good' | 'bad' | undefined {
  if (value === null || value === undefined) {
    return undefined;
  }
  if (value > 0.25) {
    return 'good';
  }
  if (value < -0.25) {
    return 'bad';
  }
  return undefined;
}

function maTone(value: boolean | null | undefined): 'good' | 'bad' | undefined {
  if (value === true) {
    return 'good';
  }
  if (value === false) {
    return 'bad';
  }
  return undefined;
}

function changeClass(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return 'mono mt-1 text-xs text-stone-500';
  }
  return `mono mt-1 text-xs ${value >= 0 ? 'text-emerald-600' : 'text-rose-600'}`;
}
