'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { API_BASE } from '@/lib/config';
import ErrorState from '@/components/ui/ErrorState';
import { useLanguage } from '@/lib/i18n';
import { requireSuccessfulMutation } from '@/lib/mutationResponse';
import { formatNumber, formatSigned } from '@/lib/format';

interface ExecutionStatus {
  status: {
    running: boolean;
    enabled?: boolean;
    mode?: string;
    capital: number;
    total_value: number;
    pnl: number;
    pnl_pct: number;
    position: number;
  };
  performance: {
    total_trades: number;
    win_rate: number;
    trades: Array<Record<string, unknown>>;
  };
  intents: Array<{
    intent_id: string;
    strategy_id: string;
    status: string;
    basket_id: string | null;
    expected_edge_bps: number;
    confidence: number;
  }>;
  baskets: Array<{
    basket_id: string;
    status: string;
    metrics: {
      submitted_legs: number;
      cancelled_legs: number;
      rejected_legs: number;
      residual_legs: number;
    };
    legs: Array<{
      leg_id: string;
      venue: string;
      symbol: string;
      side: string;
      quantity: number;
      status: string;
    }>;
  }>;
}

export default function ExecutionWorkspace() {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const [mutationError, setMutationError] = useState<string | null>(null);

  const executionQuery = useQuery<ExecutionStatus>({
    queryKey: ['execution', 'status'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/execution/status`, { signal });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.json();
    },
    refetchInterval: 10_000,
    staleTime: 8_000,
  });
  const data = executionQuery.data ?? null;

  const cancelBasket = async (basketId: string) => {
    setMutationError(null);
    try {
      await requireSuccessfulMutation(fetch(`${API_BASE}/api/execution/baskets/${basketId}/cancel`, {
        method: 'POST',
      }));
      await executionQuery.refetch();
    } catch (error) {
      setMutationError(error instanceof Error ? error.message : 'unknown error');
    }
  };

  return (
    <>
    {executionQuery.isError ? (
      <ErrorState
        className="mb-5"
        title={zh ? '执行数据加载失败' : 'Failed to load execution state'}
        message={zh ? '无法连接 PolyBob API，以下为占位数值。' : 'Cannot reach the PolyBob API; placeholders are shown below.'}
        onRetry={() => void executionQuery.refetch()}
        retryLabel={zh ? '重试' : 'Retry'}
      />
    ) : null}
    <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr),minmax(0,1.05fr)]">
      <div className="grid gap-6">
        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            {zh ? '执行台' : 'Execution Desk'}
          </div>
          <p className="mt-2 text-sm leading-6 text-stone-500">
            {zh
              ? '核心路径只展示策略意图、风险检查、basket 状态和 paper 执行记录。实验性手动样例被单独隔离，不参与默认判断。'
              : 'The core path focuses on strategy intents, risk checks, basket state, and paper execution records. Experimental manual samples are isolated from the default decision flow.'}
          </p>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <Metric title={zh ? '执行模式' : 'Execution Mode'} value={formatMode(data?.status.mode, zh)} />
            <Metric title={zh ? '持仓' : 'Position'} value={`${formatNumber(data?.status.position, 4)} BTC`} />
            <Metric title={zh ? '总资产' : 'Total Value'} value={data?.status ? `$${formatNumber(data.status.total_value, 2)}` : '--'} />
            <Metric title={zh ? '盈亏' : 'PnL'} value={data?.status ? `${formatSigned(data.status.pnl, 2)} (${formatNumber(data.status.pnl_pct, 2)}%)` : '--'} />
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            {zh ? 'Basket 汇总' : 'Basket Summary'}
          </div>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <Metric title={zh ? '意图数量' : 'Intent Count'} value={data ? String(data.intents.length) : 'UNKNOWN'} />
            <Metric title={zh ? 'Basket 数量' : 'Basket Count'} value={data ? String(data.baskets.length) : 'UNKNOWN'} />
            <Metric
              title={zh ? '残余腿' : 'Residual Legs'}
              value={data ? String(data.baskets.reduce((sum, basket) => sum + basket.metrics.residual_legs, 0)) : 'UNKNOWN'}
            />
            <Metric
              title={zh ? '拒绝腿' : 'Rejected Legs'}
              value={data ? String(data.baskets.reduce((sum, basket) => sum + basket.metrics.rejected_legs, 0)) : 'UNKNOWN'}
            />
          </div>
        </div>

        <div className="panel p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
                {zh ? '实验区：手动 Paper Basket' : 'Lab: Manual Paper Basket'}
              </div>
              <p className="mt-2 text-sm leading-6 text-stone-500">
                {zh
                  ? '这里只用于验证 basket executor 和取消链路。它不是策略建议，也不会作为核心结论展示。'
                  : 'This only validates basket executor and cancel flow. It is not a strategy recommendation and is excluded from the core conclusion.'}
              </p>
            </div>
            <span className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-xs font-medium text-amber-800">
              {zh ? 'Lab Paper Execution 默认关闭' : 'Lab paper execution is disabled by default'}
            </span>
          </div>
          {mutationError ? (
            <div className="mt-4 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700">
              {zh ? '操作失败，请重试。' : 'Action failed. Try again.'} {mutationError}
            </div>
          ) : null}
        </div>
      </div>

      <div className="grid gap-6">
        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            {zh ? '意图队列' : 'Intent Queue'}
          </div>
          <p className="mt-2 text-sm text-stone-500">
            {zh
              ? '这一层解释 basket 从哪里来：策略先生成 intent，再由执行编排器提交并记录结果。'
              : 'This layer shows where baskets come from: strategies create intents, then the executor submits and records them.'}
          </p>
          <div className="mt-5 space-y-3">
            {data?.intents?.length ? (
              data.intents.map((intent) => (
                <div key={intent.intent_id} className="rounded-lg border border-stone-200 bg-stone-50 px-4 py-3">
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
                  <div className="mt-2 text-xs text-stone-500">{zh ? 'basket' : 'basket'}: {intent.basket_id || '--'}</div>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                {zh ? '暂无意图。' : 'No intents yet.'}
              </div>
            )}
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            {zh ? 'Basket 执行' : 'Basket Execution'}
          </div>
          <p className="mt-2 text-sm text-stone-500">
            {zh
              ? '多腿执行状态在这里复核：提交、拒绝、取消和残余腿都应能追踪。'
              : 'Review multi-leg execution here: submitted, rejected, cancelled, and residual legs must stay traceable.'}
          </p>
          <div className="mt-5 space-y-3">
            {data?.baskets?.length ? (
              data.baskets.map((basket) => (
                <div key={basket.basket_id} className="rounded-lg border border-stone-200 bg-stone-50 px-4 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="mono text-sm text-stone-900">{basket.basket_id}</div>
                      <div className="mt-1 text-xs text-stone-500">{basket.status}</div>
                    </div>
                    <button
                      onClick={() => cancelBasket(basket.basket_id)}
                      className="rounded-full bg-amber-600 px-3 py-1.5 text-xs font-medium text-white"
                    >
                      {zh ? '取消' : 'Cancel'}
                    </button>
                  </div>

                  <div className="mt-3 grid gap-2 text-sm text-stone-600 sm:grid-cols-2">
                    <div>{zh ? '已提交' : 'submitted'}: {basket.metrics.submitted_legs}</div>
                    <div>{zh ? '已拒绝' : 'rejected'}: {basket.metrics.rejected_legs}</div>
                    <div>{zh ? '已取消' : 'cancelled'}: {basket.metrics.cancelled_legs}</div>
                    <div>{zh ? '残余' : 'residual'}: {basket.metrics.residual_legs}</div>
                  </div>

                  <div className="mt-4 space-y-2">
                    {basket.legs.map((leg) => (
                      <div key={leg.leg_id} className="rounded-xl bg-white px-3 py-2 text-sm text-stone-700">
                        {leg.venue} / {leg.symbol} / {leg.side} / {leg.quantity} / {leg.status}
                      </div>
                    ))}
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                {zh ? '暂无 basket。' : 'No baskets yet.'}
              </div>
            )}
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            {zh ? '最近成交' : 'Recent Trades'}
          </div>
          <div className="mt-5 space-y-3">
            {data?.performance.trades?.length ? (
              data.performance.trades.map((trade, index) => (
                <div key={index} className="rounded-lg border border-stone-200 bg-stone-50 px-4 py-3 text-sm text-stone-700">
                  {JSON.stringify(trade)}
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                {zh ? '暂无成交。' : 'No trades yet.'}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
    </>
  );
}

function Metric({ title, value }: { title: string; value: string }) {
  return (
    <div className="metric-panel">
      <div className="text-xs uppercase tracking-[0.12em] text-stone-500">{title}</div>
      <div className="mt-2 text-xl font-bold tracking-[-0.04em] text-stone-900">{value}</div>
    </div>
  );
}

function formatMode(mode: string | undefined, zh: boolean) {
  if (!mode) {
    return zh ? '未知' : 'unknown';
  }

  if (mode === 'paper') {
    return zh ? 'Paper 模拟' : 'paper';
  }

  return mode;
}
