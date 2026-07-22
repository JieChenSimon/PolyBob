export type BtcFiveMinuteAction = 'no_trade' | 'watch_up' | 'watch_down' | 'paper_intent';
export type BtcFiveMinuteOutcomeLabel = 'UP' | 'DOWN';

export interface BtcFiveMinuteLevel {
  price: number;
  size: number;
}

export interface BtcFiveMinuteOutcome {
  token_id: string | null;
  is_real_orderbook: boolean;
  best_bid: number | null;
  best_ask: number | null;
  spread: number | null;
  bid_depth_top3: number | null;
  ask_depth_top3: number | null;
  candidate_entry_price: number | null;
  estimated_edge: number | null;
  model_probability: number | null;
  entry_analysis: BtcFiveMinuteEntryAnalysis | null;
  levels: {
    bids: BtcFiveMinuteLevel[];
    asks: BtcFiveMinuteLevel[];
  };
}

export interface BtcFiveMinuteWorkbench {
  source: string;
  action: BtcFiveMinuteAction;
  recommended_outcome: BtcFiveMinuteOutcomeLabel | null;
  reason_codes: string[];
  slug: string | null;
  seconds_to_expiry: number | null;
  target_price: BtcFiveMinutePricePoint | null;
  final_price: BtcFiveMinutePricePoint | null;
  btc_reference: BtcFiveMinuteBtcReference | null;
  error?: string;
  error_diagnosis?: BtcFiveMinuteErrorDiagnosis;
  data_health: BtcFiveMinuteDataHealth;
  entry_optimizer: BtcFiveMinuteEntryOptimizer | null;
  outcomes: Record<BtcFiveMinuteOutcomeLabel, BtcFiveMinuteOutcome>;
  isTradable: boolean;
  coreConclusion: string;
}

export type BtcFiveMinuteHealthStatus = 'ok' | 'degraded' | 'unavailable' | 'unknown';

export interface BtcFiveMinuteHealthLayer {
  status: BtcFiveMinuteHealthStatus;
  provider: string | null;
  message: string;
  action: string | null;
  endpoint: string | null;
}

export interface BtcFiveMinuteDataHealth {
  polymarket_market: BtcFiveMinuteHealthLayer;
  polymarket_orderbook: BtcFiveMinuteHealthLayer;
  btc_reference: BtcFiveMinuteHealthLayer;
  target_price: BtcFiveMinuteHealthLayer;
}

export type BtcFiveMinuteEntryDecision = 'enter' | 'watch' | 'avoid' | 'no_trade';

export interface BtcFiveMinuteEntryBand {
  enter_below: number | null;
  watch_below: number | null;
  avoid_above: number | null;
}

export interface BtcFiveMinuteEntryAnalysis {
  entry_decision: BtcFiveMinuteEntryDecision;
  entry_price: number | null;
  max_acceptable_price: number | null;
  win_probability: number | null;
  expected_value: number | null;
  cost_penalty: number | null;
  kelly_fraction: number | null;
  entry_band: BtcFiveMinuteEntryBand;
  risk_notes: string[];
}

export interface BtcFiveMinuteEntryOptimizer {
  decision: BtcFiveMinuteEntryDecision;
  recommended_outcome: BtcFiveMinuteOutcomeLabel | null;
  core_conclusion: string;
  max_acceptable_price?: number | null;
  kelly_fraction?: number | null;
  expected_value?: number | null;
  win_probability?: number | null;
}

export interface BtcFiveMinutePricePoint {
  source: string;
  price: number;
  field?: string;
}

export interface BtcFiveMinuteBtcReference {
  source: string;
  symbol: string | null;
  price: number | null;
  timestamp?: string;
  received_at?: string;
  provider_timestamp?: string | null;
  round_trip_ms?: number | null;
  staleness_ms?: number | null;
  latency_quality?: string;
  sources: BtcFiveMinuteBtcReferenceSource[];
}

export interface BtcFiveMinuteBtcReferenceSource {
  source: string;
  symbol: string | null;
  status: string;
  selected: boolean;
  price: number | null;
  provider_timestamp?: string | null;
  received_at?: string;
  round_trip_ms?: number | null;
  staleness_ms?: number | null;
  latency_quality?: string;
  error?: string;
}

export interface BtcFiveMinuteErrorDiagnosis {
  category: string;
  responsibility: string;
  provider: string | null;
  endpoint: string | null;
  retryable: boolean;
  likely_cause: string;
  user_action: string;
  technical_detail: string;
}

const emptyOutcome: BtcFiveMinuteOutcome = {
  token_id: null,
  is_real_orderbook: false,
  best_bid: null,
  best_ask: null,
  spread: null,
  bid_depth_top3: null,
  ask_depth_top3: null,
  candidate_entry_price: null,
  estimated_edge: null,
  model_probability: null,
  entry_analysis: null,
  levels: { bids: [], asks: [] },
};

export function parseBtcFiveMinuteWorkbench(raw: unknown): BtcFiveMinuteWorkbench {
  const payload = isRecord(raw) ? raw : {};
  const source = asString(payload.source) || 'unavailable';
  const action = normalizeAction(payload.action);
  const recommended = normalizeOutcome(payload.recommended_outcome);
  const reasonCodes = Array.isArray(payload.reason_codes)
    ? payload.reason_codes.map(String)
    : [];
  const outcomesRaw = isRecord(payload.outcomes) ? payload.outcomes : {};
  const outcomes = {
    UP: parseOutcome(outcomesRaw.UP),
    DOWN: parseOutcome(outcomesRaw.DOWN),
  };
  const isTradable = source === 'polymarket_clob'
    && action !== 'no_trade'
    && Boolean(recommended)
    && outcomes.UP.is_real_orderbook
    && outcomes.DOWN.is_real_orderbook;

  const btcReference = parseBtcReference(payload.btc_reference);
  const errorDiagnosis = parseErrorDiagnosis(payload.error_diagnosis);
  return {
    source,
    action,
    recommended_outcome: recommended,
    reason_codes: reasonCodes,
    slug: asString(payload.slug),
    seconds_to_expiry: asNumber(payload.seconds_to_expiry),
    target_price: parsePricePoint(payload.target_price),
    final_price: parsePricePoint(payload.final_price),
    btc_reference: btcReference,
    error: asString(payload.error) || undefined,
    error_diagnosis: errorDiagnosis,
    data_health: parseDataHealth(payload.data_health, {
      source,
      outcomes,
      btcReference,
      targetPrice: parsePricePoint(payload.target_price),
      errorDiagnosis,
    }),
    entry_optimizer: parseEntryOptimizer(payload.entry_optimizer),
    outcomes,
    isTradable,
    coreConclusion: buildCoreConclusion(action, recommended, reasonCodes, isTradable, parseEntryOptimizer(payload.entry_optimizer)),
  };
}

function parseDataHealth(
  raw: unknown,
  fallback: {
    source: string;
    outcomes: Record<BtcFiveMinuteOutcomeLabel, BtcFiveMinuteOutcome>;
    btcReference: BtcFiveMinuteBtcReference | null;
    targetPrice: BtcFiveMinutePricePoint | null;
    errorDiagnosis?: BtcFiveMinuteErrorDiagnosis;
  },
): BtcFiveMinuteDataHealth {
  const payload = isRecord(raw) ? raw : {};
  const bothBooks = fallback.outcomes.UP.is_real_orderbook && fallback.outcomes.DOWN.is_real_orderbook;
  const btcOk = typeof fallback.btcReference?.price === 'number';
  const targetOk = typeof fallback.targetPrice?.price === 'number';
  return {
    polymarket_market: parseHealthLayer(payload.polymarket_market, {
      status: fallback.source === 'polymarket_clob' ? 'ok' : 'unavailable',
      provider: fallback.errorDiagnosis?.provider || 'Polymarket Gamma',
      message: fallback.errorDiagnosis?.technical_detail || (fallback.source === 'polymarket_clob' ? 'Active market resolved.' : 'Active market unavailable.'),
      action: fallback.errorDiagnosis?.user_action || null,
      endpoint: fallback.errorDiagnosis?.endpoint || null,
    }),
    polymarket_orderbook: parseHealthLayer(payload.polymarket_orderbook, {
      status: bothBooks ? 'ok' : 'unavailable',
      provider: 'Polymarket CLOB',
      message: bothBooks ? 'UP and DOWN real order books loaded.' : 'Real order book unavailable.',
      action: bothBooks ? null : '先确认 Polymarket 市场元数据和 token id 是否可用。',
      endpoint: null,
    }),
    btc_reference: parseHealthLayer(payload.btc_reference, {
      status: btcOk ? 'ok' : 'unavailable',
      provider: fallback.btcReference?.source || 'Binance / OKX / Coinbase',
      message: btcOk ? 'BTC reference available.' : 'BTC reference unavailable.',
      action: btcOk ? null : '检查 BTC 行情源网络连接。',
      endpoint: null,
    }),
    target_price: parseHealthLayer(payload.target_price, {
      status: targetOk ? 'ok' : 'unavailable',
      provider: fallback.targetPrice?.source || 'Polymarket event/page',
      message: targetOk ? 'Target price available.' : 'Target price unavailable.',
      action: targetOk ? null : '检查 Polymarket Gamma eventMetadata 或页面目标价解析。',
      endpoint: null,
    }),
  };
}

function parseHealthLayer(raw: unknown, fallback: BtcFiveMinuteHealthLayer): BtcFiveMinuteHealthLayer {
  if (!isRecord(raw)) {
    return fallback;
  }
  return {
    status: normalizeHealthStatus(raw.status) || fallback.status,
    provider: asString(raw.provider) || fallback.provider,
    message: asString(raw.message) || fallback.message,
    action: asString(raw.action) || fallback.action,
    endpoint: asString(raw.endpoint) || fallback.endpoint,
  };
}

function parseEntryOptimizer(raw: unknown): BtcFiveMinuteEntryOptimizer | null {
  if (!isRecord(raw)) {
    return null;
  }
  const decision = normalizeEntryDecision(raw.decision);
  const coreConclusion = asString(raw.core_conclusion);
  if (!decision || !coreConclusion) {
    return null;
  }
  return {
    decision,
    recommended_outcome: normalizeOutcome(raw.recommended_outcome),
    core_conclusion: coreConclusion,
    max_acceptable_price: asNumber(raw.max_acceptable_price),
    kelly_fraction: asNumber(raw.kelly_fraction),
    expected_value: asNumber(raw.expected_value),
    win_probability: asNumber(raw.win_probability),
  };
}

function parsePricePoint(raw: unknown): BtcFiveMinutePricePoint | null {
  if (!isRecord(raw)) {
    return null;
  }
  const source = asString(raw.source);
  const price = asNumber(raw.price);
  if (!source || price === null) {
    return null;
  }
  return {
    source,
    price,
    field: asString(raw.field) || undefined,
  };
}

function parseBtcReference(raw: unknown): BtcFiveMinuteBtcReference | null {
  if (!isRecord(raw)) {
    return null;
  }
  return {
    source: asString(raw.source) || 'unavailable',
    symbol: asString(raw.symbol),
    price: asNumber(raw.price),
    timestamp: asString(raw.timestamp) || undefined,
    received_at: asString(raw.received_at) || undefined,
    provider_timestamp: asString(raw.provider_timestamp),
    round_trip_ms: asNumber(raw.round_trip_ms),
    staleness_ms: asNumber(raw.staleness_ms),
    latency_quality: asString(raw.latency_quality) || undefined,
    sources: Array.isArray(raw.sources)
      ? raw.sources.map(parseBtcReferenceSource).filter((source): source is BtcFiveMinuteBtcReferenceSource => source !== null)
      : [],
  };
}

function parseBtcReferenceSource(raw: unknown): BtcFiveMinuteBtcReferenceSource | null {
  if (!isRecord(raw)) {
    return null;
  }
  return {
    source: asString(raw.source) || 'unknown',
    symbol: asString(raw.symbol),
    status: asString(raw.status) || 'unknown',
    selected: raw.selected === true,
    price: asNumber(raw.price),
    provider_timestamp: asString(raw.provider_timestamp),
    received_at: asString(raw.received_at) || undefined,
    round_trip_ms: asNumber(raw.round_trip_ms),
    staleness_ms: asNumber(raw.staleness_ms),
    latency_quality: asString(raw.latency_quality) || undefined,
    error: asString(raw.error) || undefined,
  };
}

export function buildUnavailableBtcFiveMinuteWorkbench(error: unknown): BtcFiveMinuteWorkbench {
  return parseBtcFiveMinuteWorkbench({
    source: 'unavailable',
    action: 'no_trade',
    recommended_outcome: null,
    reason_codes: ['WORKBENCH_UNAVAILABLE'],
    error: error instanceof Error ? error.message : String(error),
    error_diagnosis: {
      category: 'local_api',
      responsibility: 'browser_to_polybob_api',
      provider: 'PolyBob API',
      endpoint: null,
      retryable: true,
      likely_cause: '浏览器无法连接本机 PolyBob API。常见原因是 API 没启动、端口不对、跨域配置异常，或本机网络拦截 localhost 请求。',
      user_action: '确认 API 正在运行，并检查 NEXT_PUBLIC_API_BASE_URL / POLYBOB_API_PORT 是否指向正确端口。',
      technical_detail: error instanceof Error ? error.message : String(error),
    },
  });
}

function parseErrorDiagnosis(raw: unknown): BtcFiveMinuteErrorDiagnosis | undefined {
  if (!isRecord(raw)) {
    return undefined;
  }
  return {
    category: asString(raw.category) || 'unknown',
    responsibility: asString(raw.responsibility) || 'unknown',
    provider: asString(raw.provider),
    endpoint: asString(raw.endpoint),
    retryable: raw.retryable !== false,
    likely_cause: asString(raw.likely_cause) || '暂时无法判断具体失败来源。',
    user_action: asString(raw.user_action) || '稍后重试；如果持续出现，请保留技术细节继续排查。',
    technical_detail: asString(raw.technical_detail) || '',
  };
}

function parseOutcome(raw: unknown): BtcFiveMinuteOutcome {
  if (!isRecord(raw)) {
    return { ...emptyOutcome, levels: { bids: [], asks: [] } };
  }
  return {
    token_id: asString(raw.token_id),
    is_real_orderbook: raw.is_real_orderbook === true,
    best_bid: asNumber(raw.best_bid),
    best_ask: asNumber(raw.best_ask),
    spread: asNumber(raw.spread),
    bid_depth_top3: asNumber(raw.bid_depth_top3),
    ask_depth_top3: asNumber(raw.ask_depth_top3),
    candidate_entry_price: asNumber(raw.candidate_entry_price),
    estimated_edge: asNumber(raw.estimated_edge),
    model_probability: asNumber(raw.model_probability),
    entry_analysis: parseEntryAnalysis(raw.entry_analysis),
    levels: {
      bids: parseLevels(isRecord(raw.levels) ? raw.levels.bids : null),
      asks: parseLevels(isRecord(raw.levels) ? raw.levels.asks : null),
    },
  };
}

function parseEntryAnalysis(raw: unknown): BtcFiveMinuteEntryAnalysis | null {
  if (!isRecord(raw)) {
    return null;
  }
  const decision = normalizeEntryDecision(raw.entry_decision);
  if (!decision) {
    return null;
  }
  const band = isRecord(raw.entry_band) ? raw.entry_band : {};
  return {
    entry_decision: decision,
    entry_price: asNumber(raw.entry_price),
    max_acceptable_price: asNumber(raw.max_acceptable_price),
    win_probability: asNumber(raw.win_probability),
    expected_value: asNumber(raw.expected_value),
    cost_penalty: asNumber(raw.cost_penalty),
    kelly_fraction: asNumber(raw.kelly_fraction),
    entry_band: {
      enter_below: asNumber(band.enter_below),
      watch_below: asNumber(band.watch_below),
      avoid_above: asNumber(band.avoid_above),
    },
    risk_notes: Array.isArray(raw.risk_notes) ? raw.risk_notes.map(String) : [],
  };
}

function parseLevels(raw: unknown): BtcFiveMinuteLevel[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .map((level) => {
      if (!isRecord(level)) {
        return null;
      }
      const price = asNumber(level.price);
      const size = asNumber(level.size);
      return price === null || size === null ? null : { price, size };
    })
    .filter((level): level is BtcFiveMinuteLevel => level !== null);
}

function buildCoreConclusion(
  action: BtcFiveMinuteAction,
  recommended: BtcFiveMinuteOutcomeLabel | null,
  reasonCodes: string[],
  isTradable: boolean,
  entryOptimizer: BtcFiveMinuteEntryOptimizer | null,
) {
  if (entryOptimizer?.core_conclusion) {
    return entryOptimizer.core_conclusion;
  }
  if (!isTradable || action === 'no_trade') {
    return reasonCodes.length ? '真实盘口不可用，跳过交易。' : '当前没有足够边际，跳过交易。';
  }
  return `当前候选方向：${recommended}，仅作为 paper intent 观察。`;
}

function normalizeAction(value: unknown): BtcFiveMinuteAction {
  return value === 'watch_up' || value === 'watch_down' || value === 'paper_intent'
    ? value
    : 'no_trade';
}

function normalizeOutcome(value: unknown): BtcFiveMinuteOutcomeLabel | null {
  return value === 'UP' || value === 'DOWN' ? value : null;
}

function normalizeEntryDecision(value: unknown): BtcFiveMinuteEntryDecision | null {
  return value === 'enter' || value === 'watch' || value === 'avoid' || value === 'no_trade'
    ? value
    : null;
}

function normalizeHealthStatus(value: unknown): BtcFiveMinuteHealthStatus | null {
  return value === 'ok' || value === 'degraded' || value === 'unavailable' || value === 'unknown'
    ? value
    : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
