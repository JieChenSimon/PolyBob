export type Market = 'US' | 'CN';

export interface QuoteForAdvice {
  price: number | null;
}

export interface TechnicalsForAdvice {
  latestClose: number | null;
  movingAverages: {
    ma20: number | null;
    ma50: number | null;
    ma200: number | null;
  } | null;
}

export interface ChartForAdvice {
  symbol: string | null;
  points: Array<{ price: number }>;
}

export interface TechnicalAdvice {
  action: 'add' | 'hold' | 'trim' | 'risk_trim' | 'wait' | 'unavailable';
  headline: string;
  rationale: string;
  currentPrice: number | null;
  addLow: number | null;
  addHigh: number | null;
  trimLow: number | null;
  trimHigh: number | null;
  support: number | null;
  resistance: number | null;
  volatilityBand: number | null;
}

export interface AdviceText {
  unavailableHeadline: string;
  unavailableRationale: string;
  holdHeadline: string;
  holdRationale: string;
  riskTrimHeadline: string;
  riskTrimRationale: string;
  trimHeadline: string;
  trimRationale: string;
  addHeadline: string;
  addRationale: string;
  waitHeadline: string;
  waitRationale: string;
}

export function buildTechnicalAdvice({
  quote,
  technicals,
  chart,
  selectedSymbol,
  text,
}: {
  quote: QuoteForAdvice | undefined;
  technicals: TechnicalsForAdvice;
  chart: ChartForAdvice | null;
  selectedSymbol: string;
  market: Market;
  text: AdviceText;
}): TechnicalAdvice {
  const currentPrice = finiteOrNull(quote?.price) ?? finiteOrNull(technicals.latestClose);
  if (currentPrice === null) {
    return {
      action: 'unavailable',
      headline: text.unavailableHeadline,
      rationale: text.unavailableRationale,
      currentPrice: null,
      addLow: null,
      addHigh: null,
      trimLow: null,
      trimHigh: null,
      support: null,
      resistance: null,
      volatilityBand: null,
    };
  }

  const ma = technicals.movingAverages;
  const points = chart?.symbol === selectedSymbol ? chart.points : [];
  const prices = points.map((point) => point.price).filter(Number.isFinite);
  const chartLow = prices.length ? Math.min(...prices) : null;
  const chartHigh = prices.length ? Math.max(...prices) : null;
  const volatilityBand = estimateVolatilityBand(currentPrice, prices);
  const supportCandidates = [
    finiteOrNull(ma?.ma20),
    finiteOrNull(ma?.ma50),
    finiteOrNull(ma?.ma200),
    chartLow,
  ].filter((value): value is number => value !== null && value <= currentPrice);
  const resistanceCandidates = [
    finiteOrNull(ma?.ma20),
    finiteOrNull(ma?.ma50),
    finiteOrNull(ma?.ma200),
    chartHigh,
  ].filter((value): value is number => value !== null && value >= currentPrice);

  const support = supportCandidates.length
    ? nearestBelowOrEqual(supportCandidates, currentPrice)
    : currentPrice - volatilityBand;
  const resistance = resistanceCandidates.length
    ? nearestAboveOrEqual(resistanceCandidates, currentPrice)
    : currentPrice + volatilityBand * 1.6;
  const addCenter = Math.min(currentPrice - volatilityBand * 0.35, support + volatilityBand * 0.15);
  const trimCenter = Math.max(currentPrice + volatilityBand * 0.55, resistance - volatilityBand * 0.15);
  const addLow = Math.max(0.01, addCenter - volatilityBand * 0.45);
  const addHigh = Math.max(addLow, addCenter + volatilityBand * 0.35);
  const trimLow = Math.max(currentPrice, trimCenter - volatilityBand * 0.3);
  const trimHigh = Math.max(trimLow, trimCenter + volatilityBand * 0.45);
  const above20 = ma?.ma20 !== null && ma?.ma20 !== undefined ? currentPrice >= ma.ma20 : null;
  const above50 = ma?.ma50 !== null && ma?.ma50 !== undefined ? currentPrice >= ma.ma50 : null;
  const above200 = ma?.ma200 !== null && ma?.ma200 !== undefined ? currentPrice >= ma.ma200 : null;
  const extensionFromMa20 = ma?.ma20 ? (currentPrice - ma.ma20) / ma.ma20 : 0;
  const nearSupport = currentPrice <= addHigh + volatilityBand * 0.3;
  const nearResistance = currentPrice >= trimLow - volatilityBand * 0.3;

  let action: TechnicalAdvice['action'] = 'hold';
  let headline = text.holdHeadline;
  let rationale = text.holdRationale;

  if (above200 === false || (above20 === false && above50 === false)) {
    action = 'risk_trim';
    headline = text.riskTrimHeadline;
    rationale = text.riskTrimRationale;
  } else if (extensionFromMa20 > 0.08 || nearResistance) {
    action = 'trim';
    headline = text.trimHeadline;
    rationale = text.trimRationale;
  } else if ((above20 || above50) && nearSupport) {
    action = 'add';
    headline = text.addHeadline;
    rationale = text.addRationale;
  } else {
    action = 'wait';
    headline = text.waitHeadline;
    rationale = text.waitRationale;
  }

  return {
    action,
    headline,
    rationale,
    currentPrice,
    addLow: roundPrice(addLow),
    addHigh: roundPrice(addHigh),
    trimLow: roundPrice(trimLow),
    trimHigh: roundPrice(trimHigh),
    support: roundPrice(support),
    resistance: roundPrice(resistance),
    volatilityBand: roundPrice(volatilityBand),
  };
}

function nearestBelowOrEqual(values: number[], currentPrice: number) {
  const below = values.filter((value) => value <= currentPrice);
  return below.length ? Math.max(...below) : Math.min(...values);
}

function nearestAboveOrEqual(values: number[], currentPrice: number) {
  const above = values.filter((value) => value >= currentPrice);
  return above.length ? Math.min(...above) : Math.max(...values);
}

export function estimateVolatilityBand(currentPrice: number, prices: number[]) {
  if (prices.length >= 3) {
    const low = Math.min(...prices);
    const high = Math.max(...prices);
    const rangeBand = Math.max((high - low) * 0.25, currentPrice * 0.006);
    return Math.max(rangeBand, currentPrice * 0.012);
  }
  return currentPrice * 0.025;
}

function finiteOrNull(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function roundPrice(value: number) {
  return Number(value.toFixed(value >= 100 ? 2 : 3));
}
