'use client';

import { useEffect, useState } from 'react';
import { API_BASE } from '@/lib/config';
import { StrategyInstance, StrategyIntent, StrategyTemplate } from '@/lib/types';

export default function StrategyCatalog() {
  const [strategies, setStrategies] = useState<StrategyTemplate[]>([]);
  const [instances, setInstances] = useState<StrategyInstance[]>([]);
  const [intents, setIntents] = useState<StrategyIntent[]>([]);
  const [pairSnapshots, setPairSnapshots] = useState<Array<{
    pair_id: string;
    spread_bps: number;
    net_edge_bps: number | null;
    opportunity_side: string | null;
  }>>([]);
  const [pairUniverse, setPairUniverse] = useState<Array<{
    pair_id: string;
    left: { venue: string; symbol: string };
    right: { venue: string; symbol: string };
  }>>([]);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const [catalogResponse, instancesResponse, pairResponse, universeResponse] = await Promise.all([
        fetch(`${API_BASE}/api/strategies/catalog`),
        fetch(`${API_BASE}/api/strategies/instances`),
        fetch(`${API_BASE}/api/pairs/snapshots`),
        fetch(`${API_BASE}/api/pairs/universe`),
      ]);
      const intentsResponse = await fetch(`${API_BASE}/api/strategies/intents`);

      const catalogPayload = await catalogResponse.json();
      const instancesPayload = await instancesResponse.json();
      const pairPayload = await pairResponse.json();
      const universePayload = await universeResponse.json();
      const intentsPayload = await intentsResponse.json();

      setStrategies(Array.isArray(catalogPayload.strategies) ? catalogPayload.strategies : []);
      setInstances(Array.isArray(instancesPayload.instances) ? instancesPayload.instances : []);
      setIntents(Array.isArray(intentsPayload.intents) ? intentsPayload.intents : []);
      setPairSnapshots(Array.isArray(pairPayload.snapshots) ? pairPayload.snapshots : []);
      setPairUniverse(Array.isArray(universePayload.pairs) ? universePayload.pairs : []);
    } catch (error) {
      console.error('Failed to fetch strategies:', error);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const createInstance = async (strategyId: string) => {
    setBusyId(strategyId);
    try {
      await fetch(`${API_BASE}/api/strategies/instances`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy_id: strategyId, environment: 'paper' }),
      });
      await refresh();
    } finally {
      setBusyId(null);
    }
  };

  const operateInstance = async (
    instanceId: string,
    action: 'start' | 'stop' | 'delete',
  ) => {
    setBusyId(instanceId);
    try {
      if (action === 'delete') {
        await fetch(`${API_BASE}/api/strategies/instances/${instanceId}`, {
          method: 'DELETE',
        });
      } else {
        await fetch(`${API_BASE}/api/strategies/instances/${instanceId}/${action}`, {
          method: 'POST',
        });
      }
      await refresh();
    } finally {
      setBusyId(null);
    }
  };

  const createDemoIntent = async () => {
    setBusyId('demo-intent');
    try {
      await fetch(`${API_BASE}/api/strategies/intents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          strategy_id: 'spread_arbitrage_v1',
          rationale: 'manual cross-exchange spread',
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
      });
      await refresh();
    } finally {
      setBusyId(null);
    }
  };

  const submitIntent = async (intentId: string) => {
    setBusyId(intentId);
    try {
      await fetch(`${API_BASE}/api/strategies/intents/${intentId}/submit`, {
        method: 'POST',
      });
      await refresh();
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[1.2fr,0.8fr]">
      <div className="space-y-6">
        <div className="panel overflow-hidden">
          <div className="border-b border-stone-200/80 px-6 py-5 md:px-8">
            <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
              Strategy Templates
            </div>
            <p className="mt-1 text-sm text-stone-500">
              模板负责定义能力边界和参数基线，实例负责运行时状态和环境。
            </p>
          </div>

          <div className="space-y-4 px-4 py-4 md:px-6">
            {strategies.map((strategy) => (
              <div
                key={strategy.strategy_id}
                className="rounded-[24px] border border-stone-200 bg-white/80 p-5"
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
                  <InfoBlock label="Status" value={strategy.status} />
                  <InfoBlock label="Runtime Mode" value={strategy.runtime_mode} />
                </div>

                <div className="mt-4 grid gap-4 xl:grid-cols-2">
                  <KeyValuePanel title="Parameters" values={strategy.parameters} />
                  <KeyValuePanel title="Risk Limits" values={strategy.risk_limits} />
                </div>

                <div className="mt-5 flex justify-end">
                  <button
                    onClick={() => createInstance(strategy.strategy_id)}
                    disabled={busyId === strategy.strategy_id}
                    className="rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-50"
                  >
                    Create Paper Instance
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="space-y-6">
        <div className="panel overflow-hidden">
          <div className="border-b border-stone-200/80 px-6 py-5">
            <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
              Strategy Instances
            </div>
            <p className="mt-1 text-sm text-stone-500">
              这里已经是控制面，不再只看模板。后续会继续补版本、回测绑定和实例级性能。
            </p>
          </div>

          <div className="space-y-3 px-4 py-4">
            {instances.map((instance) => (
              <div
                key={instance.instance_id}
                className="rounded-[24px] border border-stone-200 bg-stone-50/80 p-4"
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
                    <span>Updated</span>
                    <span>{new Date(instance.updated_at).toLocaleString()}</span>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    onClick={() => operateInstance(instance.instance_id, 'start')}
                    disabled={instance.status === 'running' || busyId === instance.instance_id}
                    className="rounded-full bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                  >
                    Start
                  </button>
                  <button
                    onClick={() => operateInstance(instance.instance_id, 'stop')}
                    disabled={instance.status !== 'running' || busyId === instance.instance_id}
                    className="rounded-full bg-amber-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                  >
                    Stop
                  </button>
                  <button
                    onClick={() => operateInstance(instance.instance_id, 'delete')}
                    disabled={busyId === instance.instance_id}
                    className="rounded-full bg-rose-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="metric-panel">
          <div className="text-xs font-medium uppercase tracking-[0.14em] text-stone-500">
            Strategy Center Direction
          </div>
          <div className="mt-4 space-y-3 text-sm leading-6 text-stone-600">
            <p>现在模板和实例已经分开，后续才能继续接参数版本、回测结果和执行结果。</p>
            <p>套利家族会建立在这个控制面上，而不是继续绕过 manager 直接 hardcode 到 API。</p>
          </div>
        </div>

        <div className="panel overflow-hidden">
          <div className="border-b border-stone-200/80 px-6 py-5">
            <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
              Pair Universe
            </div>
            <p className="mt-1 text-sm text-stone-500">
              当前自动套利策略加载的 pair universe。新增标的对优先改配置，不再改业务代码。
            </p>
          </div>

          <div className="space-y-3 px-4 py-4">
            {pairUniverse.length ? (
              pairUniverse.map((pair) => (
                <div key={pair.pair_id} className="rounded-[24px] border border-stone-200 bg-stone-50/80 p-4">
                  <div className="mono text-sm text-stone-900">{pair.pair_id}</div>
                  <div className="mt-2 text-sm text-stone-600">
                    {pair.left.venue}:{pair.left.symbol} ↔ {pair.right.venue}:{pair.right.symbol}
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                No pair universe loaded.
              </div>
            )}
          </div>
        </div>

        <div className="panel overflow-hidden">
          <div className="border-b border-stone-200/80 px-6 py-5">
            <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
              Pair Snapshots
            </div>
            <p className="mt-1 text-sm text-stone-500">
              这是自动套利策略的输入层。启动 `spread_arbitrage_v1` 实例后，它会监听这里的 pair snapshot。
            </p>
          </div>

          <div className="space-y-3 px-4 py-4">
            {pairSnapshots.length ? (
              pairSnapshots.map((snapshot) => (
                <div key={snapshot.pair_id} className="rounded-[24px] border border-stone-200 bg-stone-50/80 p-4">
                  <div className="mono text-sm text-stone-900">{snapshot.pair_id}</div>
                  <div className="mt-2 grid gap-2 text-sm text-stone-600">
                    <div>spread: {snapshot.spread_bps?.toFixed?.(2) ?? snapshot.spread_bps} bps</div>
                    <div>net edge: {snapshot.net_edge_bps?.toFixed?.(2) ?? snapshot.net_edge_bps} bps</div>
                    <div>side: {snapshot.opportunity_side || '--'}</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                No pair snapshots yet.
              </div>
            )}
          </div>
        </div>

        <div className="panel overflow-hidden">
          <div className="border-b border-stone-200/80 px-6 py-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
                  Trade Intents
                </div>
                <p className="mt-1 text-sm text-stone-500">
                  intent 是策略和执行之间的桥。先创建，再提交到 basket executor。
                </p>
              </div>
              <button
                onClick={createDemoIntent}
                disabled={busyId === 'demo-intent'}
                className="rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                Create Demo Intent
              </button>
            </div>
          </div>

          <div className="space-y-3 px-4 py-4">
            {intents.length ? (
              intents.map((intent) => (
                <div key={intent.intent_id} className="rounded-[24px] border border-stone-200 bg-stone-50/80 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="mono text-sm text-stone-900">{intent.intent_id}</div>
                      <div className="mt-1 text-xs text-stone-500">
                        {intent.strategy_id} / edge {intent.expected_edge_bps}bps / confidence {intent.confidence}
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
                      Submit To Execution
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                No intents yet.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function InfoBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-stone-50 px-4 py-3">
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
    <div className="rounded-2xl border border-stone-200 bg-stone-50/70 p-4">
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
