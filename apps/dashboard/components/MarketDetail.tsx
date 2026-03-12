'use client';

import { useEffect, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { DashboardMarket } from '@/app/page';

interface MarketDetailProps {
  market: DashboardMarket | null;
}

type Point = {
  time: string;
  value: number;
};

function formatMetric(value: number | null | undefined, digits: number) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '--';
  }

  return value.toFixed(digits);
}

function formatTime(value: string | null | undefined) {
  if (!value) {
    return '--';
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return '--';
  }

  return parsed.toLocaleString('en-GB', {
    hour12: false,
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function MarketDetail({ market }: MarketDetailProps) {
  const [priceHistory, setPriceHistory] = useState<Point[]>([]);
  const [spreadHistory, setSpreadHistory] = useState<Point[]>([]);

  useEffect(() => {
    setPriceHistory([]);
    setSpreadHistory([]);
  }, [market?.market_id]);

  useEffect(() => {
    if (!market?.features) {
      return;
    }

    const time = new Date().toLocaleTimeString('en-GB', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });

    setPriceHistory((previous) => {
      const next = [...previous, { time, value: market.features!.mid_price }];
      return next.slice(-24);
    });

    setSpreadHistory((previous) => {
      const next = [...previous, { time, value: market.features!.spread_bps }];
      return next.slice(-24);
    });
  }, [market?.features]);

  if (!market) {
    return (
      <section className="panel flex min-h-[720px] items-center justify-center px-8 py-10">
        <div className="max-w-xl text-center">
          <span className="eyebrow">How To Use</span>
          <h2 className="mt-5 text-3xl font-bold tracking-[-0.05em] text-stone-900">
            先从左侧选一个市场
          </h2>
          <div className="mt-4 space-y-3 text-sm leading-6 text-stone-600">
            <p>1. 先看问题是不是你理解的事件。</p>
            <p>2. 再看 liquidity 和 spread，判断这个市场是否“值得继续看”。</p>
            <p>3. 最后再用右侧的盘口和变化图判断它当前是平稳、偏宽还是异常。</p>
          </div>
        </div>
      </section>
    );
  }

  const features = market.features;
  const spreadState =
    !features
      ? 'waiting'
      : features.spread_bps > 500
        ? 'Spread very wide'
        : features.spread_bps > 150
          ? 'Spread needs watching'
          : 'Spread looks healthy';

  return (
    <section className="panel min-h-[720px] overflow-hidden">
      <div className="border-b border-stone-200/80 px-6 py-6 md:px-8">
        <span className="eyebrow">Selected Market</span>
        <div className="mt-4 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="max-w-3xl">
            <h2 className="text-3xl font-bold tracking-[-0.05em] text-stone-900">
              {market.question}
            </h2>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-stone-100 px-3 py-1 text-stone-600">
                {market.category || 'Uncategorized'}
              </span>
              <span className="rounded-full bg-stone-100 px-3 py-1 text-stone-600">
                Liquidity {formatMetric(market.liquidity_score, 1)}
              </span>
              <span className="rounded-full bg-stone-100 px-3 py-1 text-stone-600">
                {spreadState}
              </span>
            </div>
          </div>

          <div className="grid gap-2 text-xs text-stone-500 md:text-right">
            <div className="mono">Market ID: {market.market_id}</div>
            <div className="mono">Asset ID: {market.primary_asset_id || '--'}</div>
            <div>Ends: {formatTime(market.end_time)}</div>
          </div>
        </div>
      </div>

      <div className="grid gap-6 px-6 py-6 md:px-8">
        {!features ? (
          <div className="rounded-[24px] border border-dashed border-stone-200 bg-stone-50 px-6 py-10 text-center text-sm text-stone-500">
            这个市场已经进了 watchlist，但特征还没准备好。通常再等几秒，等首次 book 快照和实时更新到达后就会显示。
          </div>
        ) : (
          <>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="Mid Price" value={formatMetric(features.mid_price, 4)} tone="cyan" />
              <MetricCard label="Spread" value={`${formatMetric(features.spread_bps, 1)} bps`} tone={features.spread_bps > 150 ? 'amber' : 'emerald'} />
              <MetricCard label="Depth Imbalance" value={formatMetric(features.depth_imbalance, 3)} tone={Math.abs(features.depth_imbalance) > 0.5 ? 'amber' : 'stone'} />
              <MetricCard label="Trade Intensity (1m)" value={formatMetric(features.trade_intensity_1m, 0)} tone="stone" />
            </div>

            <div className="grid gap-6 xl:grid-cols-[1.15fr,0.85fr]">
              <div className="grid gap-6">
                <ChartCard
                  title="Mid Price Trend"
                  subtitle="The last 24 updates for the selected market"
                >
                  <ResponsiveContainer width="100%" height={240}>
                    <AreaChart data={priceHistory}>
                      <defs>
                        <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#1481ba" stopOpacity={0.35} />
                          <stop offset="100%" stopColor="#1481ba" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="#e7dfd3" strokeDasharray="4 4" />
                      <XAxis dataKey="time" tick={{ fill: '#7a6d60', fontSize: 11 }} />
                      <YAxis tick={{ fill: '#7a6d60', fontSize: 11 }} domain={['auto', 'auto']} />
                      <Tooltip
                        contentStyle={{
                          borderRadius: 18,
                          border: '1px solid #e7dfd3',
                          backgroundColor: '#fffaf2',
                        }}
                      />
                      <Area type="monotone" dataKey="value" stroke="#1481ba" strokeWidth={2} fill="url(#priceFill)" />
                    </AreaChart>
                  </ResponsiveContainer>
                </ChartCard>

                <ChartCard
                  title="Spread History"
                  subtitle="Higher spread means worse execution conditions"
                >
                  <ResponsiveContainer width="100%" height={220}>
                    <LineChart data={spreadHistory}>
                      <CartesianGrid stroke="#e7dfd3" strokeDasharray="4 4" />
                      <XAxis dataKey="time" tick={{ fill: '#7a6d60', fontSize: 11 }} />
                      <YAxis tick={{ fill: '#7a6d60', fontSize: 11 }} />
                      <Tooltip
                        contentStyle={{
                          borderRadius: 18,
                          border: '1px solid #e7dfd3',
                          backgroundColor: '#fffaf2',
                        }}
                      />
                      <Line type="monotone" dataKey="value" stroke="#b45309" strokeWidth={2.5} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </ChartCard>
              </div>

              <div className="grid gap-6">
                <div className="metric-panel">
                  <div className="text-xs font-medium uppercase tracking-[0.14em] text-stone-500">
                    Order Book Snapshot
                  </div>
                  <div className="mt-4 grid gap-4">
                    <BookSide
                      label="Bid"
                      price={formatMetric(features.bid_price, 4)}
                      size={formatMetric(features.bid_size, 2)}
                      tone="emerald"
                    />
                    <BookSide
                      label="Ask"
                      price={formatMetric(features.ask_price, 4)}
                      size={formatMetric(features.ask_size, 2)}
                      tone="rose"
                    />
                  </div>
                </div>

                <div className="metric-panel">
                  <div className="text-xs font-medium uppercase tracking-[0.14em] text-stone-500">
                    How To Read This
                  </div>
                  <div className="mt-4 space-y-4 text-sm leading-6 text-stone-600">
                    <p>
                      <strong className="text-stone-900">Mid price</strong> tells you where the market currently sits.
                    </p>
                    <p>
                      <strong className="text-stone-900">Spread</strong> tells you how expensive it is to enter or exit quickly.
                    </p>
                    <p>
                      <strong className="text-stone-900">Depth imbalance</strong> shows whether bid or ask size dominates right now.
                    </p>
                    <p>
                      If spread is very wide, this market may be interesting to monitor but poor for immediate execution.
                    </p>
                  </div>
                </div>

                <div className="metric-panel">
                  <div className="text-xs font-medium uppercase tracking-[0.14em] text-stone-500">
                    Activity
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
                    <MiniMetric label="Volume (1m)" value={formatMetric(features.volume_1m, 2)} />
                    <MiniMetric label="Trade count (1m)" value={formatMetric(features.trade_intensity_1m, 0)} />
                    <MiniMetric label="Updated" value={formatTime(features.timestamp)} />
                    <MiniMetric label="Slug" value={market.slug || '--'} mono />
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function MetricCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: 'cyan' | 'amber' | 'emerald' | 'stone';
}) {
  const toneMap = {
    cyan: 'text-sky-700 bg-sky-50',
    amber: 'text-amber-700 bg-amber-50',
    emerald: 'text-emerald-700 bg-emerald-50',
    stone: 'text-stone-700 bg-stone-50',
  };

  return (
    <div className="metric-panel">
      <div className="text-xs font-medium uppercase tracking-[0.14em] text-stone-500">{label}</div>
      <div className={`mt-3 inline-flex rounded-2xl px-4 py-3 text-2xl font-bold tracking-[-0.04em] ${toneMap[tone]}`}>
        {value}
      </div>
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="metric-panel">
      <div>
        <div className="text-lg font-semibold tracking-[-0.03em] text-stone-900">{title}</div>
        <div className="mt-1 text-sm text-stone-500">{subtitle}</div>
      </div>
      <div className="mt-5">{children}</div>
    </div>
  );
}

function BookSide({
  label,
  price,
  size,
  tone,
}: {
  label: string;
  price: string;
  size: string;
  tone: 'emerald' | 'rose';
}) {
  return (
    <div className={`rounded-[20px] border px-4 py-4 ${tone === 'emerald' ? 'border-emerald-200 bg-emerald-50' : 'border-rose-200 bg-rose-50'}`}>
      <div className={`text-sm font-semibold ${tone === 'emerald' ? 'text-emerald-700' : 'text-rose-700'}`}>{label} side</div>
      <div className="mt-3 grid grid-cols-2 gap-4 text-sm">
        <div>
          <div className="text-stone-500">Price</div>
          <div className="mt-1 font-semibold text-stone-900">{price}</div>
        </div>
        <div>
          <div className="text-stone-500">Size</div>
          <div className="mt-1 font-semibold text-stone-900">{size}</div>
        </div>
      </div>
    </div>
  );
}

function MiniMetric({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded-2xl bg-stone-50 px-4 py-3">
      <div className="text-xs uppercase tracking-[0.12em] text-stone-500">{label}</div>
      <div className={`mt-2 text-sm font-semibold text-stone-900 ${mono ? 'mono' : ''}`}>{value}</div>
    </div>
  );
}
