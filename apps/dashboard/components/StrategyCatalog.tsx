'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { API_BASE } from '@/lib/config';
import ErrorState from '@/components/ui/ErrorState';
import { useLanguage } from '@/lib/i18n';
import { requireSuccessfulMutation } from '@/lib/mutationResponse';
import { StrategyInstance, StrategyIntent, StrategyTemplate } from '@/lib/types';

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
  const strategies = catalogQuery.data ?? [];
  const instances = instancesQuery.data ?? [];
  const intents = intentsQuery.data ?? [];
  const pairSnapshots = pairSnapshotsQuery.data ?? [];
  const pairUniverse = pairUniverseQuery.data ?? [];

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
            {strategies.map((strategy) => (
              <div
                key={strategy.strategy_id}
                className="rounded-lg border border-stone-200 bg-white p-5"
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-lg font-semibold text-stone-900">{strategy.name}</div>
                    <div className="mt-1 text-sm text-stone-500">{strategy.description}</div>
                  </div>
                  <span className="rounded-full bg-stone-100 px-3 py-1 text-xs font-medium text-stone-600">
                    {strategy.family}
                  </span>
                </div>

                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <InfoBlock label={zh ? '状态' : 'Status'} value={strategy.status} />
                  <InfoBlock label={zh ? '运行模式' : 'Runtime Mode'} value={strategy.runtime_mode} />
                </div>

                <div className="mt-4 grid gap-4 xl:grid-cols-2">
                  <KeyValuePanel title={zh ? '参数' : 'Parameters'} values={strategy.parameters} />
                  <KeyValuePanel title={zh ? '风险限制' : 'Risk Limits'} values={strategy.risk_limits} />
                </div>

                <div className="mt-5 flex justify-end">
                  <button
                    onClick={() => createInstance(strategy.strategy_id)}
                    disabled={busyId === strategy.strategy_id}
                    className="rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-50"
                  >
                    {zh ? '创建 Paper 实例' : 'Create Paper Instance'}
                  </button>
                </div>
              </div>
            ))}
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
                ? '这里是策略运行控制面：实例能启动、停止、删除，并与 intent 队列衔接。'
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
                    <div className="text-sm font-semibold text-stone-900">{instance.name}</div>
                    <div className="mt-1 text-xs text-stone-500">
                      {instance.strategy_id} / {instance.environment}
                    </div>
                  </div>
                  <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-stone-700">
                    {instance.status}
                  </span>
                </div>

                <div className="mt-4 grid gap-2 text-sm text-stone-600">
                  <div className="flex items-center justify-between gap-3">
                    <span className="mono text-stone-500">instance_id</span>
                    <span className="mono text-right text-stone-800">{instance.instance_id}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span>{zh ? '更新时间' : 'Updated'}</span>
                    <span>{new Date(instance.updated_at).toLocaleString()}</span>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
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
                </div>
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
                      disabled={intent.status === 'submitted' || busyId === intent.intent_id}
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
              disabled={busyId === 'lab-intent'}
              className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {busyId === 'lab-intent'
                ? (zh ? '创建中' : 'Creating')
                : (zh ? '创建实验 Intent' : 'Create Lab Intent')}
            </button>
          </div>
        </div>
      </div>
    </div>
    </>
  );
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
