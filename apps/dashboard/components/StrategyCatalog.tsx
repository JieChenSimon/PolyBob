'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { API_BASE } from '@/lib/config';
import ErrorState from '@/components/ui/ErrorState';
import { useLanguage } from '@/lib/i18n';
import { requireSuccessfulMutation } from '@/lib/mutationResponse';
import { StrategyInstance, StrategyIntent, StrategyTemplate } from '@/lib/types';
import DataTrustBar from '@/components/ui/DataTrustBar';

interface PairSnapshot {
  pair_id: string;
  spread_bps: number;
  net_edge_bps: number | null;
  opportunity_side: string | null;
}

interface PairUniverseEntry {
  pair_id: string;
  left: { venue: string; symbol: string };
  right: { venue: string; symbol: string };
}

interface CapabilityRow {
  capability_id: string;
  state: 'available' | 'disabled' | 'degraded' | 'unknown' | 'blocked';
  truth: string;
  missing?: string[];
}

interface PromotionEvidenceRecord {
  strategy: string;
  instrument: string;
  approved: boolean;
  role: 'trade' | 'avoid';
  failed: string[];
  t_stat: number | null;
  t_hurdle: number | null;
  n: number | null;
  n_clusters: number | null;
  cluster_by: string;
  evidence_end: string | null;
  evidence_age_days: number | null;
  max_evidence_age_days: number | null;
  evidence_expired: boolean;
  pit_status: string;
}

interface PromotionBoardPayload {
  records?: PromotionEvidenceRecord[];
}

const STRATEGY_QUERY_PREFIX = ['strategies', 'catalog-workspace'] as const;
const STRATEGY_REFETCH_MS = 15_000;
const STRATEGY_STALE_MS = 12_000;

async function fetchList<T>(path: string, listKey: string, signal: AbortSignal | undefined): Promise<T[]> {
  const response = await fetch(`${API_BASE}${path}`, { signal });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const payload = await response.json();
  return Array.isArray(payload[listKey]) ? payload[listKey] : [];
}

function useStrategyQuery<T>(key: string, path: string, listKey: string) {
  return useQuery<T[]>({
    queryKey: [...STRATEGY_QUERY_PREFIX, key],
    queryFn: ({ signal }) => fetchList<T>(path, listKey, signal),
    refetchInterval: STRATEGY_REFETCH_MS,
    staleTime: STRATEGY_STALE_MS,
  });
}

export default function StrategyCatalog() {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const queryClient = useQueryClient();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const catalogQuery = useStrategyQuery<StrategyTemplate>('catalog', '/api/strategies/catalog', 'strategies');
  const instancesQuery = useStrategyQuery<StrategyInstance>('instances', '/api/strategies/instances', 'instances');
  const intentsQuery = useStrategyQuery<StrategyIntent>('intents', '/api/strategies/intents', 'intents');
  const pairSnapshotsQuery = useStrategyQuery<PairSnapshot>('pair-snapshots', '/api/pairs/snapshots', 'snapshots');
  const pairUniverseQuery = useStrategyQuery<PairUniverseEntry>('pair-universe', '/api/pairs/universe', 'pairs');
  const capabilityQuery = useQuery<{ rows?: CapabilityRow[] }>({
    queryKey: ['workbench-capabilities'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/capabilities`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    staleTime: 20_000,
    refetchInterval: 30_000,
  });
  const promotionBoardQuery = useQuery<PromotionBoardPayload>({
    queryKey: ['promotion-board'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/strategies/promotion-board`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    staleTime: 240_000,
    refetchInterval: 300_000,
  });
  const strategies = catalogQuery.data ?? [];
  const instances = instancesQuery.data ?? [];
  const intents = intentsQuery.data ?? [];
  const pairSnapshots = pairSnapshotsQuery.data ?? [];
  const pairUniverse = pairUniverseQuery.data ?? [];
  const capabilities = capabilityQuery.data?.rows ?? [];
  const promotionByStrategy = new Map((promotionBoardQuery.data?.records ?? []).map((record) => [record.strategy, record]));
  const strategyRuntime = capabilities.find((row) => row.capability_id === 'strategy_runtime');
  const paperExecution = capabilities.find((row) => row.capability_id === 'paper_execution');
  const strategyActionsBlocked = capabilityQuery.isError || !capabilityQuery.data || strategyRuntime?.state !== 'available';
  const executionActionsBlocked = capabilityQuery.isError || !capabilityQuery.data || paperExecution?.state !== 'available';
  const capabilityReason = capabilityQuery.isError
    ? (zh ? '能力矩阵不可用；为避免误操作，策略控制动作已暂时禁用。' : 'Capability matrix is unavailable; strategy controls are disabled to avoid unsafe actions.')
    : strategyRuntime?.truth || (zh ? '策略运行能力当前未开放。' : 'Strategy runtime is not currently enabled.');

  const refetchStrategyState = () =>
    queryClient.invalidateQueries({ queryKey: STRATEGY_QUERY_PREFIX });

  const createInstance = async (strategyId: string) => {
    setBusyId(strategyId);
    setMutationError(null);
    try {
      await requireSuccessfulMutation(fetch(`${API_BASE}/api/strategies/instances`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy_id: strategyId, environment: 'paper' }),
      }));
      await refetchStrategyState();
    } catch (error) {
      setMutationError(error instanceof Error ? error.message : 'unknown error');
    } finally {
      setBusyId(null);
    }
  };

  const operateInstance = async (
    instanceId: string,
    action: 'start' | 'stop' | 'delete',
  ) => {
    setBusyId(instanceId);
    setMutationError(null);
    try {
      const request = action === 'delete'
        ? fetch(`${API_BASE}/api/strategies/instances/${instanceId}`, {
          method: 'DELETE',
        })
        : fetch(`${API_BASE}/api/strategies/instances/${instanceId}/${action}`, {
          method: 'POST',
        });
      await requireSuccessfulMutation(request);
      await refetchStrategyState();
    } catch (error) {
      setMutationError(error instanceof Error ? error.message : 'unknown error');
    } finally {
      setBusyId(null);
    }
  };

  const createLabIntent = async () => {
    setBusyId('lab-intent');
    setMutationError(null);
    try {
      await requireSuccessfulMutation(fetch(`${API_BASE}/api/strategies/intents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          strategy_id: 'spread_arbitrage_v1',
          rationale: 'manual lab cross-exchange spread check',
          expected_edge_bps: 18,
          confidence: 0.72,
          metadata: {
            mode: 'cross_exchange',
          },
          legs: [
            {
              venue: 'binance',
              symbol: 'BTCUSDT',
              side: 'buy',
              quantity: 0.01,
              limit_price: 65000,
              role: 'hedge',
            },
            {
              venue: 'hyperliquid',
              symbol: 'BTC',
              side: 'sell',
              quantity: 0.01,
              limit_price: 65010,
              role: 'primary',
            },
          ],
        }),
      }));
      await refetchStrategyState();
    } catch (error) {
      setMutationError(error instanceof Error ? error.message : 'unknown error');
    } finally {
      setBusyId(null);
    }
  };

  const submitIntent = async (intentId: string) => {
    setBusyId(intentId);
    setMutationError(null);
    try {
      await requireSuccessfulMutation(fetch(`${API_BASE}/api/strategies/intents/${intentId}/submit`, {
        method: 'POST',
      }));
      await refetchStrategyState();
    } catch (error) {
      setMutationError(error instanceof Error ? error.message : 'unknown error');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
    {catalogQuery.isError ? (
      <ErrorState
        className="mb-5"
        title={zh ? '策略目录加载失败' : 'Failed to load the strategy catalog'}
        message={zh ? '无法连接 PolyBob API，模板与实例暂时为空。' : 'Cannot reach the PolyBob API; templates and instances are empty for now.'}
        onRetry={() => void catalogQuery.refetch()}
        retryLabel={zh ? '重试' : 'Retry'}
      />
    ) : null}
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr),minmax(0,0.8fr)]">
      <div className="space-y-6">
        <div className="grid gap-3 md:grid-cols-2">
          <DataTrustBar
            source={zh ? '能力矩阵' : 'Capability Matrix'}
            state={strategyRuntime?.state ?? (capabilityQuery.isError ? 'unknown' : 'unknown')}
            reason={capabilityReason}
          />
          <DataTrustBar
            source={zh ? '模拟执行能力' : 'Paper Execution'}
            state={paperExecution?.state ?? (capabilityQuery.isError ? 'unknown' : 'unknown')}
            reason={paperExecution?.truth ?? (zh ? '执行能力状态未知。' : 'Execution capability state is unknown.')}
          />
          <DataTrustBar
            source={zh ? '权威晋级板' : 'Promotion Board'}
            state={promotionBoardQuery.isError ? 'unknown' : promotionBoardQuery.data ? 'available' : 'unknown'}
            reason={promotionBoardQuery.isError
              ? (zh ? '无法读取权威晋级板；策略配置中的收益自述不会被当作证据。' : 'The authoritative promotion board is unavailable; configuration claims are not treated as evidence.')
              : (zh ? '以真实历史研究、聚类推断、样本外与 PIT 门禁作为策略有效性的唯一依据。' : 'Real-history research, clustered inference, out-of-sample checks, and PIT gates are the sole evidence of strategy validity.')}
          />
        </div>
        <div className="panel overflow-hidden">
          <div className="border-b border-stone-200 px-6 py-5 md:px-8">
            <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
              {zh ? '策略模板' : 'Strategy Templates'}
            </div>
            <p className="mt-1 text-sm text-stone-500">
              {zh
                ? '模板定义能力边界、参数基线和风险限制；实例负责运行时状态和 paper 环境。'
                : 'Templates define capability boundaries, parameter baselines, and risk limits; instances own runtime state and paper environment.'}
            </p>
          </div>
          {mutationError ? (
            <div className="border-b border-rose-100 bg-rose-50 px-6 py-2 text-xs text-rose-700">
              {zh ? '操作失败，请重试。' : 'Action failed. Try again.'} {mutationError}
            </div>
          ) : null}

          <div className="space-y-4 px-4 py-4 md:px-6">
            {strategies.map((strategy) => {
              const promotion = promotionByStrategy.get(strategy.strategy_id);
              return (
              <div
                key={strategy.strategy_id}
                className="rounded-lg border border-stone-200 bg-white p-5"
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-lg font-semibold text-stone-900">{displayStrategyName(strategy, zh)}</div>
                    <div className="mt-1 text-sm text-stone-500">{displayStrategyDescription(strategy, zh, promotion, Boolean(promotionBoardQuery.data))}</div>
                  </div>
                  <span className="rounded-full bg-stone-100 px-3 py-1 text-xs font-medium text-stone-600">
                    {strategy.family}
                  </span>
                </div>

                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <InfoBlock label={zh ? '状态' : 'Status'} value={displayStrategyState(strategy.status, zh)} />
                  <InfoBlock label={zh ? '运行模式' : 'Runtime Mode'} value={displayStrategyState(strategy.runtime_mode, zh)} />
                  <InfoBlock label={zh ? '产品状态' : 'Product Status'} value={displayStrategyState(strategy.product_status ?? 'research', zh)} />
                  <InfoBlock label={zh ? '基本面/证据/PIT' : 'Fundamental / Evidence / PIT'} value={promotion ? promotionEvidenceState(promotion, zh) : `${strategy.fundamental_evidence ?? 'UNKNOWN'} / ${strategy.evidence_status ?? 'UNKNOWN'} / ${strategy.pit_status ?? 'UNKNOWN'}`} />
                </div>

                {promotion ? <PromotionEvidencePanel record={promotion} zh={zh} /> : null}

                {strategy.basic_evidence ? (
                  <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                    <div className="font-semibold">{zh ? '质量过滤后研究证据' : 'Quality-filtered research evidence'}</div>
                    <div className="mt-1">{zh ? '基本面/质量过滤：' : 'Quality filters: '}{Array.isArray(strategy.basic_evidence.quality_filters) ? strategy.basic_evidence.quality_filters.join(', ') : 'UNKNOWN'}</div>
                    <div className="mt-1">{zh ? '未知字段：' : 'Unknown fields: '}{strategy.unknown_fields?.join(', ') || 'UNKNOWN'}</div>
                    <div className="mt-1 font-semibold">{zh ? '禁止交易：证据状态或 PIT 未知' : 'No trading: evidence or PIT is UNKNOWN'}</div>
                  </div>
                ) : null}

                <div className="mt-4 grid gap-4 xl:grid-cols-2">
                  <KeyValuePanel title={zh ? '参数' : 'Parameters'} values={strategy.parameters} />
                  <KeyValuePanel title={zh ? '风险限制' : 'Risk Limits'} values={strategy.risk_limits} />
                </div>

                {strategyActionsBlocked ? (
                  <div className="mt-5 border-l-2 border-amber-400 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
                    {zh ? '当前仅展示研究模板。策略运行能力尚未获准，因此不会提供创建实例操作。' : 'This research template is view-only. Strategy runtime is not approved, so instance creation is unavailable.'}
                  </div>
                ) : <div className="mt-5 flex justify-end">
                  <button
                    onClick={() => createInstance(strategy.strategy_id)}
                    disabled={strategy.runtime_mode !== 'paper_ready' || strategy.trade_permission !== true || busyId === strategy.strategy_id}
                    title={zh ? '未通过 Promotion/PIT 门禁，禁止创建运行实例。' : 'Promotion/PIT gates are not passed; instance creation is disabled.'}
                    className="rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-50"
                  >
                    {zh ? '创建 Paper 实例' : 'Create Paper Instance'}
                  </button>
                </div>}
              </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="space-y-6">
        <div className="panel overflow-hidden">
          <div className="border-b border-stone-200 px-6 py-5">
            <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
              {zh ? '策略实例' : 'Strategy Instances'}
            </div>
            <p className="mt-1 text-sm text-stone-500">
              {zh
                ? (strategyActionsBlocked ? '当前只读展示策略实例与证据边界；运行控制将在能力获准后提供。' : '这里是策略运行控制面：实例能启动、停止、删除，并与 intent 队列衔接。')
                : 'This is the strategy runtime control plane: instances can start, stop, delete, and feed the intent queue.'}
            </p>
          </div>

          <div className="space-y-3 px-4 py-4">
            {instances.map((instance) => (
              <div
                key={instance.instance_id}
                className="rounded-lg border border-stone-200 bg-stone-50 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-stone-900">{displayInstanceName(instance, zh)}</div>
                    <div className="mt-1 text-xs text-stone-500">
                      {zh ? `策略：${displayStrategyId(instance.strategy_id)} · 环境：${displayEnvironment(instance.environment)}` : `${instance.strategy_id} / ${instance.environment}`}
                    </div>
                  </div>
                  <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-stone-700">
                    {displayInstanceStatus(instance.status, zh)}
                  </span>
                </div>

                <div className="mt-4 grid gap-2 text-sm text-stone-600">
                  <div className="flex items-center justify-between gap-3">
                    <span>{zh ? '更新时间' : 'Updated'}</span>
                    <span>{new Date(instance.updated_at).toLocaleString()}</span>
                  </div>
                  <details className="text-xs text-stone-500">
                    <summary className="cursor-pointer hover:text-sky-700">{zh ? '技术标识（排障用）' : 'Technical ID'}</summary>
                    <div className="mono mt-1 break-all text-[11px]">{instance.instance_id}</div>
                  </details>
                </div>

                {strategyActionsBlocked ? (
                  <div className="mt-4 border-l-2 border-amber-400 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
                    {zh ? '当前为只读研究实例；策略运行能力未获准，不能启动、停止或删除。' : 'This is a read-only research instance; strategy runtime is not approved, so controls are unavailable.'}
                  </div>
                ) : <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    onClick={() => operateInstance(instance.instance_id, 'start')}
                    disabled={instance.status === 'running' || busyId === instance.instance_id}
                    className="rounded-full bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                  >
                    {zh ? '启动' : 'Start'}
                  </button>
                  <button
                    onClick={() => operateInstance(instance.instance_id, 'stop')}
                    disabled={instance.status !== 'running' || busyId === instance.instance_id}
                    className="rounded-full bg-amber-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                  >
                    {zh ? '停止' : 'Stop'}
                  </button>
                  <button
                    onClick={() => operateInstance(instance.instance_id, 'delete')}
                    disabled={busyId === instance.instance_id}
                    className="rounded-full bg-rose-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                  >
                    {zh ? '删除' : 'Delete'}
                  </button>
                </div>}
              </div>
            ))}
          </div>
        </div>

        <div className="metric-panel">
          <div className="text-xs font-medium uppercase tracking-[0.14em] text-stone-500">
            {zh ? '策略中心定位' : 'Strategy Center Role'}
          </div>
          <div className="mt-4 space-y-3 text-sm leading-6 text-stone-600">
            <p>
              {zh
                ? '这里负责把模板、实例、信号输入、intent 和执行结果串起来，避免策略逻辑绕过控制面。'
                : 'This page connects templates, instances, signal inputs, intents, and execution outcomes so strategy logic does not bypass the control plane.'}
            </p>
          </div>
        </div>

        <div className="panel overflow-hidden">
          <div className="border-b border-stone-200 px-6 py-5">
            <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
              {zh ? '交易对宇宙' : 'Pair Universe'}
            </div>
            <p className="mt-1 text-sm text-stone-500">
              {zh
                ? '当前策略实例可读取的交易对配置。新增标的对优先改配置，不改业务代码。'
                : 'Pair configuration available to strategy instances. Add pairs through config instead of business code.'}
            </p>
          </div>

          <div className="space-y-3 px-4 py-4">
            {pairUniverse.length ? (
              pairUniverse.map((pair) => (
                <div key={pair.pair_id} className="rounded-lg border border-stone-200 bg-stone-50 p-4">
                  <div className="mono text-sm text-stone-900">{pair.pair_id}</div>
                  <div className="mt-2 text-sm text-stone-600">
                    {pair.left.venue}:{pair.left.symbol} ↔ {pair.right.venue}:{pair.right.symbol}
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                {zh ? '暂无交易对配置。' : 'No pair universe loaded.'}
              </div>
            )}
          </div>
        </div>

        <div className="panel overflow-hidden">
          <div className="border-b border-stone-200 px-6 py-5">
            <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
              {zh ? '交易对快照' : 'Pair Snapshots'}
            </div>
            <p className="mt-1 text-sm text-stone-500">
              {zh
                ? '这是策略的信号输入层。运行中的实例会读取这里的价差、净边际和机会方向。'
                : 'This is the strategy signal input layer. Running instances read spread, net edge, and opportunity side here.'}
            </p>
          </div>

          <div className="space-y-3 px-4 py-4">
            {pairSnapshots.length ? (
              pairSnapshots.map((snapshot) => (
                <div key={snapshot.pair_id} className="rounded-lg border border-stone-200 bg-stone-50 p-4">
                  <div className="mono text-sm text-stone-900">{snapshot.pair_id}</div>
                  <div className="mt-2 grid gap-2 text-sm text-stone-600">
                    <div>{zh ? '价差' : 'spread'}: {snapshot.spread_bps?.toFixed?.(2) ?? snapshot.spread_bps} bps</div>
                    <div>{zh ? '净边际' : 'net edge'}: {snapshot.net_edge_bps?.toFixed?.(2) ?? snapshot.net_edge_bps} bps</div>
                    <div>{zh ? '方向' : 'side'}: {snapshot.opportunity_side || '--'}</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                {zh ? '暂无交易对快照。' : 'No pair snapshots yet.'}
              </div>
            )}
          </div>
        </div>

        <div className="panel overflow-hidden">
          <div className="border-b border-stone-200 px-6 py-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
                  {zh ? '交易意图' : 'Trade Intents'}
                </div>
                <p className="mt-1 text-sm text-stone-500">
                  {zh
                    ? 'intent 是策略和执行之间的桥。策略生成后再提交到 basket executor。'
                    : 'Intents bridge strategy and execution. Strategies create them before submission to the basket executor.'}
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-3 px-4 py-4">
            {intents.length ? (
              intents.map((intent) => (
                <div key={intent.intent_id} className="rounded-lg border border-stone-200 bg-stone-50 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="mono text-sm text-stone-900">{intent.intent_id}</div>
                      <div className="mt-1 text-xs text-stone-500">
                        {intent.strategy_id} / {zh ? '边际' : 'edge'} {intent.expected_edge_bps}bps / {zh ? '置信度' : 'confidence'} {intent.confidence}
                      </div>
                    </div>
                    <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-stone-700">
                      {intent.status}
                    </span>
                  </div>

                  <div className="mt-3 text-sm text-stone-600">{intent.rationale}</div>
                  {intent.error ? (
                    <div className="mt-2 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700">
                      {intent.error}
                    </div>
                  ) : null}
                  <div className="mt-4 space-y-2">
                    {intent.legs.map((leg) => (
                      <div key={leg.leg_id} className="rounded-xl bg-white px-3 py-2 text-sm text-stone-700">
                        {leg.role} / {leg.venue} / {leg.symbol} / {leg.side} / {leg.quantity}
                      </div>
                    ))}
                  </div>

                  <div className="mt-4 flex justify-end">
                    <button
                      onClick={() => submitIntent(intent.intent_id)}
                      disabled={executionActionsBlocked || intent.status === 'submitted' || busyId === intent.intent_id}
                      title={executionActionsBlocked ? (paperExecution?.truth ?? undefined) : undefined}
                      className="rounded-full bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                    >
                      {zh ? '提交到执行' : 'Submit To Execution'}
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                {zh ? '暂无交易意图。' : 'No intents yet.'}
              </div>
            )}
          </div>
        </div>

        <div className="panel overflow-hidden">
          <div className="border-b border-stone-200 px-6 py-5">
            <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
              {zh ? '实验区：手动 Intent' : 'Lab: Manual Intent'}
            </div>
            <p className="mt-1 text-sm text-stone-500">
              {zh
                ? '仅用于验证 intent 到 basket 的链路，不代表真实策略信号，也不进入默认核心结论。'
                : 'Only validates the intent-to-basket path. It is not a live strategy signal and is excluded from the default core conclusion.'}
            </p>
          </div>
          <div className="px-4 py-4">
            <button
              onClick={createLabIntent}
              disabled={executionActionsBlocked || busyId === 'lab-intent'}
              title={executionActionsBlocked ? (paperExecution?.truth ?? undefined) : undefined}
              className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {busyId === 'lab-intent'
                ? (zh ? '创建中' : 'Creating')
                : (zh ? '创建实验 Intent' : 'Create Lab Intent')}
            </button>
            {executionActionsBlocked ? (
              <p className="mt-3 text-xs leading-5 text-stone-500">
                {zh ? '当前为只读观察：能力矩阵未开放 Paper 执行，实验 Intent 不会被创建。' : 'Read-only observation: paper execution is not enabled in the capability matrix, so lab intents cannot be created.'}
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
    </>
  );
}

function displayInstanceStatus(value: string, zh: boolean) {
  if (!zh) return value;
  return ({
    running: '运行中',
    stopped: '已停止',
    paused: '已暂停',
    created: '已创建',
    failed: '失败',
  } as Record<string, string>)[value.toLowerCase()] || value;
}

function displayStrategyState(value: string | null | undefined, zh: boolean) {
  if (!zh) return value || 'UNKNOWN';
  return ({
    template: '模板',
    research: '研究中',
    paper_ready: '可进行模拟盘验证',
    blocked: '已阻断',
    disabled: '已关闭',
    unknown: '未知',
  } as Record<string, string>)[(value || 'unknown').toLowerCase()] || value || '未知';
}

function displayStrategyName(strategy: StrategyTemplate, zh: boolean) {
  if (!zh) return strategy.name;
  return ({
    ai_enhanced_prediction_v1: 'AI 增强预测策略 V1',
    altcoin_retail_crowding: '山寨币散户拥挤度策略',
    spread_arbitrage_v1: '跨市场价差策略 V1',
  } as Record<string, string>)[strategy.strategy_id] || strategy.name;
}

function displayStrategyDescription(
  strategy: StrategyTemplate,
  zh: boolean,
  promotion: PromotionEvidenceRecord | undefined,
  promotionBoardLoaded: boolean,
) {
  if (promotion) {
    return zh
      ? '此策略的有效性以权威晋级板为准；配置中的历史收益描述不作为当前可交易证据。'
      : 'The authoritative promotion board determines this strategy’s validity; historical returns in configuration are not current trade evidence.';
  }
  if (!promotionBoardLoaded) {
    return zh
      ? '权威晋级板当前不可读取；任何配置中的历史收益或胜率均未被验证，不能作为策略有效性或交易依据。'
      : 'The authoritative promotion board is unavailable; historical returns or win rates in configuration are unverified and cannot support a strategy or trade decision.';
  }
  if (!zh) return strategy.description;
  return ({
    ai_enhanced_prediction_v1: '研究型预测策略模板；尚未获得真实交易或模拟盘运行授权。',
    altcoin_retail_crowding: '研究型拥挤度策略模板；尚未获得真实交易或模拟盘运行授权。',
    spread_arbitrage_v1: '研究型跨市场价差模板；尚未获得真实交易或模拟盘运行授权。',
  } as Record<string, string>)[strategy.strategy_id] || strategy.description;
}

function promotionEvidenceState(record: PromotionEvidenceRecord, zh: boolean) {
  if (record.approved && record.role === 'trade' && !record.evidence_expired) {
    return zh ? '已通过 / PIT 已验证 / 可开仓' : 'passed / PIT verified / tradable';
  }
  if (record.approved && record.role === 'avoid' && !record.evidence_expired) {
    return zh ? '回避过滤器 / 不开仓' : 'avoidance filter / no trade';
  }
  return zh ? `未通过 / PIT ${record.pit_status || 'UNKNOWN'} / 禁止交易` : `not promoted / PIT ${record.pit_status || 'UNKNOWN'} / no trade`;
}

function PromotionEvidencePanel({ record, zh }: { record: PromotionEvidenceRecord; zh: boolean }) {
  const permitted = record.approved && record.role === 'trade' && !record.evidence_expired;
  const avoidOnly = record.approved && record.role === 'avoid' && !record.evidence_expired;
  const tone = permitted ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : avoidOnly ? 'border-sky-200 bg-sky-50 text-sky-900' : 'border-rose-200 bg-rose-50 text-rose-900';
  return (
    <div className={`mt-4 rounded-md border px-3 py-3 text-xs leading-5 ${tone}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <strong>{zh ? '权威研究结论' : 'Authoritative research verdict'}</strong>
        <span>{permitted ? (zh ? '可开仓' : 'TRADE PERMITTED') : avoidOnly ? (zh ? '仅回避' : 'AVOID ONLY') : (zh ? '禁止交易' : 'NO TRADE')}</span>
      </div>
      <div className="mt-2 grid gap-x-4 gap-y-1 sm:grid-cols-2">
        <span>{zh ? '聚类 t 值' : 'Clustered t'}: <b>{formatEvidenceNumber(record.t_stat)}{record.t_hurdle !== null ? ` / ${record.t_hurdle.toFixed(2)}` : ''}</b></span>
        <span>{zh ? '独立单元' : 'Independent units'}: <b>{record.n_clusters ?? '—'}{record.cluster_by ? ` (${record.cluster_by})` : ''}</b></span>
        <span>{zh ? '原始样本' : 'Raw observations'}: <b>{record.n?.toLocaleString() ?? '—'}</b></span>
        <span>{zh ? 'PIT 状态' : 'PIT status'}: <b>{record.pit_status || 'UNKNOWN'}</b></span>
      </div>
      {record.evidence_end ? <div className="mt-1.5">{zh ? '证据截至' : 'Evidence through'}: <b>{record.evidence_end}</b>{record.evidence_age_days !== null && record.max_evidence_age_days ? ` · ${record.evidence_age_days}/${record.max_evidence_age_days} ${zh ? '天' : 'days'}` : ''}{record.evidence_expired ? (zh ? '（已过期）' : ' (expired)') : ''}</div> : null}
      {record.failed.length ? <div className="mt-1.5">{zh ? '未通过原因' : 'Gate failures'}: {record.failed.join(' · ')}</div> : null}
    </div>
  );
}

function formatEvidenceNumber(value: number | null) {
  return value === null || value === undefined || !Number.isFinite(value) ? '—' : value.toFixed(2);
}

function displayStrategyId(strategyId: string) {
  return ({
    ai_enhanced_prediction_v1: 'AI 增强预测 V1',
    altcoin_retail_crowding: '山寨币散户拥挤度',
    spread_arbitrage_v1: '跨市场价差 V1',
  } as Record<string, string>)[strategyId] || strategyId;
}

function displayInstanceName(instance: StrategyInstance, zh: boolean) {
  if (!zh) return instance.name;
  const suffix = instance.name.split('/').slice(1).join('/').trim();
  return `${displayStrategyId(instance.strategy_id)}${suffix ? ` / ${suffix}` : ''}`;
}

function displayEnvironment(value: string) {
  return value === 'paper' ? '模拟盘' : value;
}

function InfoBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-stone-50 px-4 py-3">
      <div className="text-xs uppercase tracking-[0.12em] text-stone-500">{label}</div>
      <div className="mt-2 text-sm font-semibold text-stone-900">{value}</div>
    </div>
  );
}

function KeyValuePanel({
  title,
  values,
}: {
  title: string;
  values: Record<string, number | string | boolean | null>;
}) {
  return (
    <div className="rounded-lg border border-stone-200 bg-stone-50 p-4">
      <div className="text-xs font-medium uppercase tracking-[0.12em] text-stone-500">
        {title}
      </div>
      <div className="mt-3 space-y-2">
        {Object.entries(values).map(([key, value]) => (
          <div key={key} className="flex items-center justify-between gap-4 text-sm">
            <span className="mono text-stone-500">{key}</span>
            <span className="font-medium text-stone-900">{String(value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
