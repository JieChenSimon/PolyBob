export type Horizon = '7d' | '30d' | '90d';
export type CandidateStatus = 'trade_eligible' | 'watch' | 'data_insufficient' | 'vetoed';
export type WorkbenchStatus = 'ok' | 'degraded' | 'unavailable';

export function isLiveSnapshot(snapshot: { status: WorkbenchStatus; stale: boolean }): boolean {
  return snapshot.status === 'ok' && !snapshot.stale;
}

export function snapshotBadge(
  snapshot: { status: WorkbenchStatus; stale: boolean },
): 'live' | 'degraded' | 'stale' | 'unavailable' {
  if (snapshot.stale) return 'stale';
  if (snapshot.status === 'unavailable') return 'unavailable';
  if (snapshot.status === 'degraded') return 'degraded';
  return 'live';
}

export function formatObservedAt(value: string | null): string {
  if (!value) return '—';
  const timestamp = new Date(value);
  if (!Number.isFinite(timestamp.getTime())) return '—';
  const shanghai = new Date(timestamp.getTime() + 8 * 60 * 60 * 1000);
  return `${shanghai.toISOString().slice(0, 19).replace('T', ' ')} CST`;
}

export interface HorizonScore {
  value: number | null;
  coverage: number;
  contributions: Record<string, number>;
}

export interface PositionSize {
  riskFraction: number;
  quantity: number | null;
  notionalUsd: number | null;
  maxLossUsd: number | null;
}

export interface TradePlan {
  eligible: boolean;
  entryLow: number | null;
  entryHigh: number | null;
  stop: number | null;
  target1: number | null;
  target2: number | null;
  rewardRisk: number | null;
  vetoes: string[];
  positionSizes: Record<string, PositionSize>;
}

export interface Evidence {
  name: string;
  value: unknown;
  status: string;
  provider: string;
  field: string | null;
  observedAt: string | null;
  detail: string | null;
}

export interface SourceHealth {
  status: string;
  provider: string;
  message: string | null;
  endpoint: string | null;
  lastSuccessAt: string | null;
  lastFailureAt: string | null;
  failureCategory: string | null;
  retryable: boolean | null;
}

export interface AltcoinCandidate {
  assetId: string;
  chainId: string;
  contractAddress: string;
  symbol: string;
  futuresSymbol: string | null;
  mappingStatus: 'unique' | 'ambiguous' | 'unmatched';
  price: number | null;
  marketCap: number | null;
  liquidity: number | null;
  volume24h: number | null;
  chipConcentrationPercent: number | null;
  coverage: number;
  confidence: number;
  pumpPotential: Partial<Record<Horizon, HorizonScore>>;
  cashoutRisk: Partial<Record<Horizon, HorizonScore>>;
  status: CandidateStatus;
  vetoes: string[];
  tradePlans: Partial<Record<Horizon, TradePlan>>;
  evidence: Evidence[];
}

export interface AltcoinDiscoveryWorkbench {
  status: WorkbenchStatus;
  observedAt: string | null;
  stale: boolean;
  candidates: AltcoinCandidate[];
  sourceHealth: Record<string, SourceHealth>;
  chainHealth: Record<string, SourceHealth>;
  universeCounts: Record<string, number>;
}

export interface BreakoutPick {
  candidate: AltcoinCandidate;
  score: number;
  reasons: string[];
  blockers: string[];
}

export interface WorkbenchLeaders {
  actionable: AltcoinCandidate | null;
  highestPotential: AltcoinCandidate | null;
}

export interface CandidatePage<T> {
  items: T[];
  page: number;
  pageSize: number;
  totalPages: number;
  totalItems: number;
}

export function paginateCandidates<T>(items: T[], requestedPage: number, pageSize = 30): CandidatePage<T> {
  const safePageSize = Math.max(1, Math.floor(pageSize));
  const totalPages = Math.max(1, Math.ceil(items.length / safePageSize));
  const page = Math.min(totalPages, Math.max(1, Math.floor(requestedPage) || 1));
  const start = (page - 1) * safePageSize;
  return {
    items: items.slice(start, start + safePageSize),
    page,
    pageSize: safePageSize,
    totalPages,
    totalItems: items.length,
  };
}

export const STATUS_LABELS: Record<CandidateStatus, { zh: string; en: string }> = {
  trade_eligible: { zh: '可执行', en: 'Actionable' },
  watch: { zh: '观察', en: 'Watch' },
  data_insufficient: { zh: '数据不足', en: 'Data insufficient' },
  vetoed: { zh: '已否决', en: 'Vetoed' },
};

export const VETO_LABELS: Record<string, { zh: string; en: string }> = {
  INVALID_SYMBOL: { zh: '标的符号无效', en: 'Invalid symbol' },
  AMBIGUOUS_SYMBOL_MAPPING: { zh: '同名合约映射不唯一', en: 'Ambiguous contract mapping' },
  NO_LIVE_USDT_PERPETUAL: { zh: '没有交易中的 USDT 永续合约', en: 'No live USDT perpetual' },
  BINANCE_TOKEN_BLACKLISTED: { zh: 'Binance 标记为黑名单代币', en: 'Token is blacklisted by Binance' },
  PUMP_POTENTIAL_BELOW_MINIMUM: { zh: '爆拉潜力未达门槛', en: 'Pump potential below threshold' },
  CASHOUT_RISK_ABOVE_MAXIMUM: { zh: '兑现风险超过上限', en: 'Cash-out risk above maximum' },
  COVERAGE_BELOW_MINIMUM: { zh: '数据覆盖率不足', en: 'Evidence coverage below minimum' },
  LIQUIDITY_BELOW_MINIMUM: { zh: '流动性不足', en: 'Liquidity below minimum' },
  VOLUME_BELOW_MINIMUM: { zh: '24 小时成交额不足', en: '24h volume below minimum' },
  INSUFFICIENT_CANDLES: { zh: '历史 K 线不足', en: 'Insufficient candle history' },
  INVALID_VOLATILITY_STRUCTURE: { zh: '波动结构无效', en: 'Invalid volatility structure' },
  NO_STRUCTURAL_ENTRY: { zh: '没有形成结构性入场区间', en: 'No structural entry zone' },
  PRICE_OVEREXTENDED: { zh: '现价偏离入场区间过远', en: 'Price is overextended' },
  REWARD_RISK_BELOW_MINIMUM: { zh: '风险收益比低于 2:1', en: 'Reward/risk below 2:1' },
};

const HORIZONS: Horizon[] = ['7d', '30d', '90d'];
const CANDIDATE_STATUSES = new Set<CandidateStatus>([
  'trade_eligible',
  'watch',
  'data_insufficient',
  'vetoed',
]);

export function parseAltcoinDiscovery(raw: unknown): AltcoinDiscoveryWorkbench {
  if (!isRecord(raw) || !Array.isArray(raw.candidates)) {
    return unavailableWorkbench();
  }

  const status = raw.status === 'ok' || raw.status === 'degraded'
    ? raw.status
    : 'unavailable';
  return {
    status,
    observedAt: asString(raw.observed_at),
    stale: raw.stale === true,
    candidates: raw.candidates.map(parseCandidate).filter(isCandidate),
    sourceHealth: parseHealthMap(raw.source_health),
    chainHealth: parseHealthMap(raw.chain_health),
    universeCounts: parseNumberMap(raw.universe_counts),
  };
}

export function parseAltcoinCandidate(raw: unknown): AltcoinCandidate | null {
  return parseCandidate(raw);
}

export function sortCandidates(
  candidates: AltcoinCandidate[],
  horizon: Horizon,
): AltcoinCandidate[] {
  const order: Record<CandidateStatus, number> = {
    trade_eligible: 0,
    watch: 1,
    data_insufficient: 2,
    vetoed: 3,
  };
  return [...candidates].sort((left, right) => {
    const statusDifference = order[left.status] - order[right.status];
    if (statusDifference !== 0) {
      return statusDifference;
    }
    const leftScore = left.pumpPotential[horizon]?.value ?? -1;
    const rightScore = right.pumpPotential[horizon]?.value ?? -1;
    return rightScore - leftScore || left.symbol.localeCompare(right.symbol);
  });
}

export function buildBreakoutWatchlist(
  candidates: AltcoinCandidate[],
  horizon: Horizon,
  language: 'zh' | 'en',
  limit = 5,
): BreakoutPick[] {
  return candidates
    .flatMap((candidate) => {
      const potential = candidate.pumpPotential[horizon]?.value;
      if (candidate.status === 'vetoed' || potential === null || potential === undefined || potential < 65) {
        return [];
      }
      const risk = candidate.cashoutRisk[horizon]?.value ?? 55;
      const plan = candidate.tradePlans[horizon];
      const score = potential - risk * 0.35 + candidate.coverage * 20 + (candidate.status === 'trade_eligible' || plan?.eligible ? 12 : 0);
      return [{
        candidate,
        score,
        reasons: breakoutReasons(candidate, horizon, language),
        blockers: breakoutBlockers(candidate, horizon, language),
      } satisfies BreakoutPick];
    })
    .sort((left, right) => right.score - left.score || left.candidate.symbol.localeCompare(right.candidate.symbol))
    .slice(0, limit);
}

export function buildWorkbenchLeaders(
  candidates: AltcoinCandidate[],
  horizon: Horizon,
): WorkbenchLeaders {
  const sorted = sortCandidates(candidates, horizon);
  const actionable = sorted.find((candidate) => (
    candidate.status === 'trade_eligible' || candidate.tradePlans[horizon]?.eligible
  )) ?? null;
  const highestPotential = [...candidates]
    .filter((candidate) => candidate.status !== 'vetoed')
    .sort((left, right) => (
      (right.pumpPotential[horizon]?.value ?? -1) - (left.pumpPotential[horizon]?.value ?? -1)
      || left.symbol.localeCompare(right.symbol)
    ))[0] ?? null;
  return { actionable, highestPotential };
}

export function buildCoreConclusion(
  candidate: AltcoinCandidate,
  horizon: Horizon,
  language: 'zh' | 'en',
): string {
  const plan = candidate.tradePlans[horizon];
  if (
    plan?.eligible
    && plan.entryLow !== null
    && plan.entryHigh !== null
  ) {
    return language === 'zh'
      ? `${candidate.symbol} ${horizon} 通过门槛；观察入场区间 ${formatPrice(plan.entryLow)}–${formatPrice(plan.entryHigh)}。`
      : `${candidate.symbol} passes the ${horizon} gates; watch entry ${formatPrice(plan.entryLow)}–${formatPrice(plan.entryHigh)}.`;
  }

  const codes = [...candidate.vetoes, ...(plan?.vetoes ?? [])];
  const labels = [...new Set(codes)].map((code) => (
    VETO_LABELS[code]?.[language] ?? code
  ));
  if (labels.length > 0) {
    return language === 'zh'
      ? `暂不生成交易计划：${labels.join('；')}。`
      : `No trade plan: ${labels.join('; ')}.`;
  }
  return language === 'zh'
    ? '当前仅观察，尚未同时通过潜力、风险和结构价位门槛。'
    : 'Watch only: potential, risk, and structural-price gates are not all satisfied.';
}

const CONTRIBUTION_LABELS: Record<string, { zh: string; en: string }> = {
  floor: { zh: '市值/价格位置接近底部', en: 'Market-cap and price location are near the floor' },
  washout: { zh: '洗盘后量能和波动收敛', en: 'Volume and volatility show washout compression' },
  control: { zh: '筹码集中度偏高', en: 'Holder concentration is elevated' },
  accumulation: { zh: '链上/买盘吸筹信号较强', en: 'Onchain or buy-side accumulation is strong' },
  historical_operator_strength: { zh: '历史上出现过快速拉升', en: 'History shows fast rally ability' },
  futures_squeeze: { zh: '合约端存在挤压条件', en: 'Futures positioning supports a squeeze setup' },
};

function breakoutReasons(candidate: AltcoinCandidate, horizon: Horizon, language: 'zh' | 'en'): string[] {
  const potential = candidate.pumpPotential[horizon]?.value;
  const risk = candidate.cashoutRisk[horizon]?.value;
  const plan = candidate.tradePlans[horizon];
  const reasons: string[] = [];

  if (potential !== null && potential !== undefined) {
    reasons.push(language === 'zh'
      ? `爆拉潜力 ${potential.toFixed(1)}，进入精选观察阈值。`
      : `Pump potential is ${potential.toFixed(1)}, above the spotlight threshold.`);
  }
  if (risk !== null && risk !== undefined) {
    reasons.push(language === 'zh'
      ? `兑现风险 ${risk.toFixed(1)}，用于约束入场质量。`
      : `Cash-out risk is ${risk.toFixed(1)}, used as an entry-quality guard.`);
  }
  reasons.push(language === 'zh'
    ? `数据覆盖率 ${(candidate.coverage * 100).toFixed(0)}%，未覆盖项不会被补值。`
    : `Evidence coverage is ${(candidate.coverage * 100).toFixed(0)}%; missing fields are not imputed.`);

  const contributions = candidate.pumpPotential[horizon]?.contributions ?? {};
  Object.entries(contributions)
    .sort((left, right) => right[1] - left[1])
    .slice(0, 3)
    .forEach(([name, value]) => {
      const label = CONTRIBUTION_LABELS[name]?.[language] ?? name;
      reasons.push(language === 'zh'
        ? `${label}，贡献 ${value.toFixed(1)} 分。`
        : `${label}, contributing ${value.toFixed(1)} points.`);
    });

  if (plan?.eligible && plan.entryLow !== null && plan.entryLow !== undefined && plan.entryHigh !== null && plan.entryHigh !== undefined) {
    reasons.push(language === 'zh'
      ? `已形成观察入场区间 ${formatPrice(plan.entryLow)}–${formatPrice(plan.entryHigh)}。`
      : `A watch entry zone is available at ${formatPrice(plan.entryLow)}-${formatPrice(plan.entryHigh)}.`);
  }
  return reasons;
}

function breakoutBlockers(candidate: AltcoinCandidate, horizon: Horizon, language: 'zh' | 'en'): string[] {
  const plan = candidate.tradePlans[horizon];
  const codes = [...new Set([...candidate.vetoes, ...(plan?.vetoes ?? [])])];
  const blockers = codes.map((code) => VETO_LABELS[code]?.[language] ?? code);
  if (candidate.status === 'data_insufficient' && blockers.length === 0) {
    blockers.push(language === 'zh' ? '数据不足，不能转成执行计划。' : 'Data is insufficient; not converted into an execution plan.');
  }
  if (candidate.status !== 'trade_eligible' && !plan?.eligible && blockers.length === 0) {
    blockers.push(language === 'zh'
      ? '仅作为观察候选，尚未同时通过潜力、风险和结构价位门槛。'
      : 'Watch only; potential, risk, and structural-price gates are not all satisfied.');
  }
  return blockers;
}

function formatPrice(value: number): string {
  if (Math.abs(value) >= 1) {
    return value.toLocaleString('en-US', { maximumFractionDigits: 4 });
  }
  return value.toLocaleString('en-US', { maximumSignificantDigits: 6 });
}

function parseCandidate(raw: unknown): AltcoinCandidate | null {
  if (!isRecord(raw)) {
    return null;
  }
  const assetId = asString(raw.asset_id);
  const chainId = asString(raw.chain_id);
  const contractAddress = asString(raw.contract_address);
  const symbol = asString(raw.symbol);
  if (!assetId || !chainId || !contractAddress || !symbol) {
    return null;
  }
  const status = asString(raw.status);
  const mappingStatus = asString(raw.mapping_status);
  return {
    assetId,
    chainId,
    contractAddress,
    symbol,
    futuresSymbol: asString(raw.futures_symbol),
    mappingStatus: mappingStatus === 'unique' || mappingStatus === 'ambiguous'
      ? mappingStatus
      : 'unmatched',
    price: asNumber(raw.price),
    marketCap: asNumber(raw.market_cap),
    liquidity: asNumber(raw.liquidity),
    volume24h: asNumber(raw.volume_24h),
    chipConcentrationPercent: asNumber(raw.chip_concentration_percent),
    coverage: asNumber(raw.coverage) ?? 0,
    confidence: asNumber(raw.confidence) ?? 0,
    pumpPotential: parseHorizonScores(raw.pump_potential),
    cashoutRisk: parseHorizonScores(raw.cashout_risk),
    status: CANDIDATE_STATUSES.has(status as CandidateStatus)
      ? status as CandidateStatus
      : 'data_insufficient',
    vetoes: parseStrings(raw.vetoes),
    tradePlans: parseTradePlans(raw.trade_plans),
    evidence: parseEvidence(raw.evidence),
  };
}

function parseHorizonScores(raw: unknown): Partial<Record<Horizon, HorizonScore>> {
  if (!isRecord(raw)) {
    return {};
  }
  const scores: Partial<Record<Horizon, HorizonScore>> = {};
  HORIZONS.forEach((horizon) => {
    const value = raw[horizon];
    if (!isRecord(value)) {
      return;
    }
    scores[horizon] = {
      value: asNumber(value.value),
      coverage: asNumber(value.coverage) ?? 0,
      contributions: parseNumberMap(value.contributions),
    };
  });
  return scores;
}

function parseTradePlans(raw: unknown): Partial<Record<Horizon, TradePlan>> {
  if (!isRecord(raw)) {
    return {};
  }
  const plans: Partial<Record<Horizon, TradePlan>> = {};
  HORIZONS.forEach((horizon) => {
    const value = raw[horizon];
    if (!isRecord(value)) {
      return;
    }
    plans[horizon] = {
      eligible: value.eligible === true,
      entryLow: asNumber(value.entry_low),
      entryHigh: asNumber(value.entry_high),
      stop: asNumber(value.stop),
      target1: asNumber(value.target_1),
      target2: asNumber(value.target_2),
      rewardRisk: asNumber(value.reward_risk),
      vetoes: parseStrings(value.vetoes),
      positionSizes: parsePositionSizes(value.position_sizes),
    };
  });
  return plans;
}

function parsePositionSizes(raw: unknown): Record<string, PositionSize> {
  if (!isRecord(raw)) {
    return {};
  }
  return Object.fromEntries(Object.entries(raw).flatMap(([key, value]) => {
    if (!isRecord(value)) {
      return [];
    }
    return [[key, {
      riskFraction: asNumber(value.risk_fraction) ?? 0,
      quantity: asNumber(value.quantity),
      notionalUsd: asNumber(value.notional_usd),
      maxLossUsd: asNumber(value.max_loss_usd),
    } satisfies PositionSize]];
  }));
}

function parseEvidence(raw: unknown): Evidence[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.flatMap((value) => {
    if (!isRecord(value) || !asString(value.name) || !asString(value.provider)) {
      return [];
    }
    return [{
      name: asString(value.name) as string,
      value: value.value,
      status: asString(value.status) || 'unavailable',
      provider: asString(value.provider) as string,
      field: asString(value.field),
      observedAt: asString(value.observed_at),
      detail: asString(value.detail),
    }];
  });
}

function parseHealthMap(raw: unknown): Record<string, SourceHealth> {
  if (!isRecord(raw)) {
    return {};
  }
  return Object.fromEntries(Object.entries(raw).flatMap(([key, value]) => {
    if (!isRecord(value) || !asString(value.provider)) {
      return [];
    }
    return [[key, {
      status: asString(value.status) || 'unavailable',
      provider: asString(value.provider) as string,
      message: asString(value.message),
      endpoint: asString(value.endpoint),
      lastSuccessAt: asString(value.last_success_at),
      lastFailureAt: asString(value.last_failure_at),
      failureCategory: asString(value.failure_category),
      retryable: typeof value.retryable === 'boolean' ? value.retryable : null,
    } satisfies SourceHealth]];
  }));
}

function parseNumberMap(raw: unknown): Record<string, number> {
  if (!isRecord(raw)) {
    return {};
  }
  return Object.fromEntries(Object.entries(raw).flatMap(([key, value]) => {
    const number = asNumber(value);
    return number === null ? [] : [[key, number]];
  }));
}

function parseStrings(raw: unknown): string[] {
  return Array.isArray(raw) ? raw.filter((value): value is string => typeof value === 'string') : [];
}

function unavailableWorkbench(): AltcoinDiscoveryWorkbench {
  return {
    status: 'unavailable',
    observedAt: null,
    stale: false,
    candidates: [],
    sourceHealth: {},
    chainHealth: {},
    universeCounts: {},
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isCandidate(value: AltcoinCandidate | null): value is AltcoinCandidate {
  return value !== null;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
