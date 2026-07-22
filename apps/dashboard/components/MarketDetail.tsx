'use client';

import dynamic from 'next/dynamic';
import { useEffect, useState } from 'react';
import { useLanguage } from '@/lib/i18n';
import { DashboardMarket } from '@/lib/types';
import FreshnessBadge from '@/components/ui/FreshnessBadge';

interface MarketDetailProps {
  market: DashboardMarket | null;
}

type Point = {
  time: string;
  value: number;
};

// Charts are loaded lazily so recharts stays out of the first-load bundle.
// Placeholders match the chart heights (240 / 220) to avoid layout shift.
const PriceTrendChart = dynamic(
  () => import('./MarketDetailCharts').then((mod) => mod.PriceTrendChart),
  { ssr: false, loading: () => <div style={{ height: 240 }} /> },
);
const SpreadHistoryChart = dynamic(
  () => import('./MarketDetailCharts').then((mod) => mod.SpreadHistoryChart),
  { ssr: false, loading: () => <div style={{ height: 220 }} /> },
);

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
  const { language } = useLanguage();
  const zh = language === 'zh';
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
      <section className="panel flex min-h-[360px] items-center justify-center px-8 py-10 xl:min-h-[720px]">
        <div className="max-w-xl text-center">
          <span className="eyebrow">{zh ? '等待选择' : 'No Market Selected'}</span>
          <h2 className="mt-5 text-3xl font-bold text-stone-900">
            {zh ? '选择一个市场查看实时盘口' : 'Select a market to review live features'}
          </h2>
          <p className="mt-4 text-sm leading-6 text-stone-600">
            {zh
              ? '这里会显示所选市场的中间价、价差、盘口深度、会话内走势和活跃度。'
              : 'This pane shows mid price, spread, book depth, session trend, and activity for the selected market.'}
          </p>
        </div>
      </section>
    );
  }

  const features = market.features;
  const spreadState =
    !features
      ? 'waiting'
      : features.spread_bps > 500
        ? (zh ? '价差很宽' : 'Spread very wide')
        : features.spread_bps > 150
          ? (zh ? '价差需要关注' : 'Spread needs watching')
          : (zh ? '价差健康' : 'Spread looks healthy');

  return (
    <section className="panel min-h-[520px] overflow-hidden xl:min-h-[720px]">
      <div className="border-b border-stone-200 px-6 py-6 md:px-8">
        <span className="eyebrow">{zh ? '已选市场' : 'Selected Market'}</span>
        <div className="mt-4 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="max-w-3xl">
            <h2 className="text-2xl font-bold text-stone-900 md:text-3xl">
              {market.question}
            </h2>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-stone-100 px-3 py-1 text-stone-600">
                {market.category || (zh ? '未分类' : 'Uncategorized')}
              </span>
              <span className="rounded-full bg-stone-100 px-3 py-1 text-stone-600">
                {zh ? '流动性' : 'Liquidity'} {formatMetric(market.liquidity_score, 1)}
              </span>
              <span className="rounded-full bg-stone-100 px-3 py-1 text-stone-600">
                {spreadState}
              </span>
            </div>
          </div>

          <div className="grid gap-2 text-xs text-stone-500 md:justify-items-end md:text-right">
            {features ? (
              <FreshnessBadge
                source="Polymarket"
                timestamp={features.timestamp}
                freshMs={20_000}
                staleMs={60_000}
                language={zh ? 'zh' : 'en'}
              />
            ) : null}
            <div className="mono">{zh ? '市场 ID' : 'Market ID'}: {market.market_id}</div>
            <div className="mono">{zh ? '资产 ID' : 'Asset ID'}: {market.primary_asset_id || '--'}</div>
            <div>{zh ? '结束' : 'Ends'}: {formatTime(market.end_time)}</div>
          </div>
        </div>
      </div>

      <div className="grid gap-6 px-6 py-6 md:px-8">
        {!features ? (
          <div className="rounded-lg border border-dashed border-stone-200 bg-stone-50 px-6 py-10 text-center text-sm text-stone-500">
            {zh
              ? '这个市场已经进了观察列表，但特征还没准备好。通常再等几秒，等首次盘口快照和实时更新到达后就会显示。'
              : 'This market is on the watchlist, but features are not ready yet. Wait for the first book snapshot and realtime update.'}
          </div>
        ) : (
          <>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard label={zh ? '中间价' : 'Mid Price'} value={formatMetric(features.mid_price, 4)} tone="cyan" />
              <MetricCard label={zh ? '价差' : 'Spread'} value={`${formatMetric(features.spread_bps, 1)} bps`} tone={features.spread_bps > 150 ? 'amber' : 'emerald'} />
              <MetricCard label={zh ? '深度偏斜' : 'Depth Imbalance'} value={formatMetric(features.depth_imbalance, 3)} tone={Math.abs(features.depth_imbalance) > 0.5 ? 'amber' : 'stone'} />
              <MetricCard label={zh ? '交易强度(1m)' : 'Trade Intensity (1m)'} value={formatMetric(features.trade_intensity_1m, 0)} tone="stone" />
            </div>

            <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr),minmax(0,0.85fr)]">
              <div className="grid gap-6">
                <ChartCard
                  title={zh ? '中间价趋势' : 'Mid Price Trend'}
                  subtitle={zh ? '浏览器本次会话最近 24 次更新，不是完整历史 K 线' : 'Last 24 updates in this browser session, not full historical candles'}
                >
                  <PriceTrendChart data={priceHistory} />
                </ChartCard>

                <ChartCard
                  title={zh ? '价差历史' : 'Spread History'}
                  subtitle={zh ? '浏览器本次会话内的价差变化，用于观察即时执行环境' : 'Session-only spread changes for current execution conditions'}
                >
                  <SpreadHistoryChart data={spreadHistory} />
                </ChartCard>
              </div>

              <div className="grid gap-6">
                <div className="metric-panel">
                  <div className="text-xs font-medium uppercase tracking-[0.14em] text-stone-500">
                    {zh ? '盘口快照' : 'Order Book Snapshot'}
                  </div>
                  <div className="mt-4 grid gap-4">
                    <BookSide
                      label={zh ? '买盘' : 'Bid'}
                      price={formatMetric(features.bid_price, 4)}
                      size={formatMetric(features.bid_size, 2)}
                      tone="emerald"
                      zh={zh}
                    />
                    <BookSide
                      label={zh ? '卖盘' : 'Ask'}
                      price={formatMetric(features.ask_price, 4)}
                      size={formatMetric(features.ask_size, 2)}
                      tone="rose"
                      zh={zh}
                    />
                  </div>
                </div>

                <div className="metric-panel">
                  <div className="text-xs font-medium uppercase tracking-[0.14em] text-stone-500">
                    {zh ? '执行观察' : 'Execution Read'}
                  </div>
                  <div className="mt-4 space-y-4 text-sm leading-6 text-stone-600">
                    {zh ? (
                      <>
                        <p><strong className="text-stone-900">位置：</strong>中间价表示市场当前大致位置。</p>
                        <p><strong className="text-stone-900">成本：</strong>价差越宽，快速进出场成本越高。</p>
                        <p><strong className="text-stone-900">压力：</strong>深度偏斜显示买盘或卖盘哪边占优。</p>
                        <p>价差过宽时保留观察，不进入立即执行。</p>
                      </>
                    ) : (
                      <>
                        <p><strong className="text-stone-900">Position:</strong> mid price shows where the market currently sits.</p>
                        <p><strong className="text-stone-900">Cost:</strong> wider spread makes quick entry or exit more expensive.</p>
                        <p><strong className="text-stone-900">Pressure:</strong> depth imbalance shows which side dominates.</p>
                        <p>When spread is too wide, keep it on watch instead of immediate execution.</p>
                      </>
                    )}
                  </div>
                </div>

                <div className="metric-panel">
                  <div className="text-xs font-medium uppercase tracking-[0.14em] text-stone-500">
                    {zh ? '活跃度' : 'Activity'}
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
                    <MiniMetric label={zh ? '成交量(1m)' : 'Volume (1m)'} value={formatMetric(features.volume_1m, 2)} />
                    <MiniMetric label={zh ? '成交次数(1m)' : 'Trade count (1m)'} value={formatMetric(features.trade_intensity_1m, 0)} />
                    <MiniMetric label={zh ? '更新时间' : 'Updated'} value={formatTime(features.timestamp)} />
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
      <div className={`mt-3 inline-flex max-w-full rounded-lg px-4 py-3 text-xl font-bold md:text-2xl ${toneMap[tone]}`}>
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
  zh,
}: {
  label: string;
  price: string;
  size: string;
  tone: 'emerald' | 'rose';
  zh: boolean;
}) {
  return (
    <div className={`rounded-lg border px-4 py-4 ${tone === 'emerald' ? 'border-emerald-200 bg-emerald-50' : 'border-rose-200 bg-rose-50'}`}>
      <div className={`text-sm font-semibold ${tone === 'emerald' ? 'text-emerald-700' : 'text-rose-700'}`}>{zh ? label : `${label} side`}</div>
      <div className="mt-3 grid grid-cols-2 gap-4 text-sm">
        <div>
          <div className="text-stone-500">{zh ? '价格' : 'Price'}</div>
          <div className="mt-1 font-semibold text-stone-900">{price}</div>
        </div>
        <div>
          <div className="text-stone-500">{zh ? '数量' : 'Size'}</div>
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
    <div className="rounded-lg bg-stone-50 px-4 py-3">
      <div className="text-xs uppercase tracking-[0.12em] text-stone-500">{label}</div>
      <div className={`mt-2 text-sm font-semibold text-stone-900 ${mono ? 'mono' : ''}`}>{value}</div>
    </div>
  );
}
