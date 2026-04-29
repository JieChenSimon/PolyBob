'use client';

import { useEffect, useState } from 'react';
import { API_BASE } from '@/lib/config';

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
  const [data, setData] = useState<ExecutionStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const fetchExecution = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/execution/status`);
      const payload = await response.json();
      setData(payload);
    } catch (error) {
      console.error('Failed to fetch execution status:', error);
    }
  };

  useEffect(() => {
    fetchExecution();
    const interval = window.setInterval(fetchExecution, 5000);
    return () => window.clearInterval(interval);
  }, []);

  const submitDemoBasket = async () => {
    setSubmitting(true);
    try {
      await fetch(`${API_BASE}/api/execution/baskets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parent_intent_id: 'manual_demo_spread',
          legs: [
            {
              venue: 'binance',
              symbol: 'BTCUSDT',
              side: 'buy',
              quantity: 0.01,
              limit_price: 65000,
            },
            {
              venue: 'hyperliquid',
              symbol: 'BTC',
              side: 'sell',
              quantity: 0.01,
              limit_price: 65010,
            },
          ],
        }),
      });
      await fetchExecution();
    } finally {
      setSubmitting(false);
    }
  };

  const cancelBasket = async (basketId: string) => {
    await fetch(`${API_BASE}/api/execution/baskets/${basketId}/cancel`, {
      method: 'POST',
    });
    await fetchExecution();
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[0.95fr,1.05fr]">
      <div className="grid gap-6">
        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            Execution Desk
          </div>
          <p className="mt-2 text-sm leading-6 text-stone-500">
            核心执行路径是 intent、risk check、basket 和 paper 记录。BTC demo auto trader 属于 lab，
            默认关闭，需要 ENABLE_LAB_AUTO_TRADER=true 才会启动。
          </p>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <Metric
              title="Lab Auto Trader"
              value={data?.status.enabled === false ? 'Disabled' : data?.status.running ? 'Running' : 'Stopped'}
            />
            <Metric title="Position" value={`${data?.status.position?.toFixed(4) || '0.0000'} BTC`} />
            <Metric title="Total Value" value={`$${data?.status.total_value?.toFixed(2) || '0.00'}`} />
            <Metric title="PnL" value={`${data?.status.pnl?.toFixed(2) || '0.00'} (${data?.status.pnl_pct?.toFixed(2) || '0.00'}%)`} />
          </div>
          <div className="mt-5 flex justify-end">
            <button
              onClick={submitDemoBasket}
              disabled={submitting}
              className="rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              Submit Paper Basket
            </button>
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            Basket Summary
          </div>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <Metric title="Intent Count" value={String(data?.intents.length || 0)} />
            <Metric title="Basket Count" value={String(data?.baskets.length || 0)} />
            <Metric
              title="Residual Legs"
              value={String(data?.baskets.reduce((sum, basket) => sum + basket.metrics.residual_legs, 0) || 0)}
            />
          </div>
        </div>
      </div>

      <div className="grid gap-6">
        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            Intent Queue
          </div>
          <p className="mt-2 text-sm text-stone-500">
            这一层用来解释 basket 从哪里来。后续真实套利策略会先写 intent，再交给执行编排器。
          </p>
          <div className="mt-5 space-y-3">
            {data?.intents?.length ? (
              data.intents.map((intent) => (
                <div key={intent.intent_id} className="rounded-2xl border border-stone-200 bg-stone-50 px-4 py-3">
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
                  <div className="mt-2 text-xs text-stone-500">basket: {intent.basket_id || '--'}</div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                No intents yet.
              </div>
            )}
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            Basket Execution
          </div>
          <p className="mt-2 text-sm text-stone-500">
            多腿执行已经有了最小骨架。后续这里会补 ack、fill、补腿和净敞口回放。
          </p>
          <div className="mt-5 space-y-3">
            {data?.baskets?.length ? (
              data.baskets.map((basket) => (
                <div key={basket.basket_id} className="rounded-2xl border border-stone-200 bg-stone-50 px-4 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="mono text-sm text-stone-900">{basket.basket_id}</div>
                      <div className="mt-1 text-xs text-stone-500">{basket.status}</div>
                    </div>
                    <button
                      onClick={() => cancelBasket(basket.basket_id)}
                      className="rounded-full bg-amber-600 px-3 py-1.5 text-xs font-medium text-white"
                    >
                      Cancel
                    </button>
                  </div>

                  <div className="mt-3 grid gap-2 text-sm text-stone-600 sm:grid-cols-2">
                    <div>submitted: {basket.metrics.submitted_legs}</div>
                    <div>rejected: {basket.metrics.rejected_legs}</div>
                    <div>cancelled: {basket.metrics.cancelled_legs}</div>
                    <div>residual: {basket.metrics.residual_legs}</div>
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
              <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                No baskets yet.
              </div>
            )}
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            Recent Trades
          </div>
          <div className="mt-5 space-y-3">
            {data?.performance.trades?.length ? (
              data.performance.trades.map((trade, index) => (
                <div key={index} className="rounded-2xl border border-stone-200 bg-stone-50 px-4 py-3 text-sm text-stone-700">
                  {JSON.stringify(trade)}
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                No trades yet.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
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
