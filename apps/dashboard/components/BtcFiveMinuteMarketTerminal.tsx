'use client';

import { useMemo } from 'react';
import { type BtcFiveMinuteWorkbench } from '@/domain/btcFiveMinute/workbench';
import { useLanguage } from '@/lib/i18n';
import FreshnessBadge from '@/components/ui/FreshnessBadge';
import StatusBadge, { statusTone } from '@/components/ui/StatusBadge';

export interface TerminalPoint {
  timestamp: number;
  price: number | null;
  upProbability: number | null;
}

const labels = {
  zh: {
    title: 'Bitcoin Up or Down - 5分钟',
    subtitle: 'Polymarket BTC 5分钟涨跌主窗口',
    targetPrice: '目标价格',
    currentPrice: '实时价格',
    fastestSource: '最快源',
    upProbability: 'Up 概率',
    window: '窗口',
    expiry: '剩余',
    source: '数据源',
    conclusion: '核心结论',
    action: '动作',
    candidate: '候选方向',
    entry: '候选进场价',
    maxEntry: '最高限价',
    decision: '入场判断',
    ev: 'EV',
    kelly: 'Kelly仓位',
    spread: '价差',
    depth: '深度',
    up: 'Up',
    down: 'Down',
    noData: '等待真实盘口',
    notAvailable: '不可用',
    official: '官方窗口',
    clob: 'CLOB分析',
    rules: '规则',
  },
  en: {
    title: 'Bitcoin Up or Down - 5m',
    subtitle: 'Polymarket BTC five-minute main market window',
    targetPrice: 'Price to Beat',
    currentPrice: 'Live Price',
    fastestSource: 'Fastest Source',
    upProbability: 'Up Probability',
    window: 'Window',
    expiry: 'Expiry',
    source: 'Source',
    conclusion: 'Core Conclusion',
    action: 'Action',
    candidate: 'Candidate',
    entry: 'Candidate Entry',
    maxEntry: 'Max Entry',
    decision: 'Entry',
    ev: 'EV',
    kelly: 'Kelly Size',
    spread: 'Spread',
    depth: 'Depth',
    up: 'Up',
    down: 'Down',
    noData: 'Waiting for real order book',
    notAvailable: 'N/A',
    official: 'Official',
    clob: 'CLOB',
    rules: 'Rules',
  },
};

export default function BtcFiveMinuteMarketTerminal({
  workbench,
  history,
}: {
  workbench: BtcFiveMinuteWorkbench | null;
  history: TerminalPoint[];
}) {
  const { language } = useLanguage();
  const t = labels[language];

  const price = typeof workbench?.btc_reference?.price === 'number' ? workbench.btc_reference.price : null;
  const targetPrice = workbench?.target_price?.price ?? null;
  const upMid = midpoint(workbench?.outcomes.UP.best_bid ?? null, workbench?.outcomes.UP.best_ask ?? null);
  const downMid = midpoint(workbench?.outcomes.DOWN.best_bid ?? null, workbench?.outcomes.DOWN.best_ask ?? null);
  const priceChange = useMemo(() => {
    const first = history.find((point) => point.price !== null)?.price ?? null;
    if (first === null || price === null) {
      return null;
    }
    return price - first;
  }, [history, price]);

  const btcRef = workbench?.btc_reference ?? null;
  const health = workbench?.data_health ?? null;
  const refAgeMs = btcRef?.staleness_ms ?? btcRef?.round_trip_ms ?? null;

  return (
    <section
      aria-label={language === 'zh' ? 'BTC 5 分钟涨跌盘口终端' : 'BTC five-minute up/down order-book terminal'}
      className="overflow-hidden rounded-xl border border-stone-200 bg-white shadow-[0_1px_2px_rgba(28,25,23,0.04)]"
    >
      <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr),360px]">
        <div className="min-w-0 border-b border-stone-200 p-5 lg:border-b-0 lg:border-r">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div className="flex min-w-0 gap-4">
              <div
                aria-hidden
                className="grid h-14 w-14 shrink-0 place-items-center rounded-xl bg-amber-500 text-3xl font-bold text-white"
              >
                ₿
              </div>
              <div className="min-w-0">
                <div className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">
                  {t.subtitle}
                </div>
                <h2 className="mt-1 text-2xl font-bold text-stone-900 md:text-3xl">
                  {t.title}
                </h2>
                <div className="mono mt-2 truncate text-xs text-stone-500">
                  {workbench?.slug || t.noData}
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {btcRef ? (
                    <FreshnessBadge
                      source={btcRef.source}
                      ageMs={refAgeMs}
                      status={health?.btc_reference?.status ?? undefined}
                      language={language}
                    />
                  ) : null}
                  {health?.polymarket_orderbook ? (
                    <StatusBadge tone={statusTone(health.polymarket_orderbook.status)}>
                      {language === 'zh' ? '盘口' : 'Book'} · {health.polymarket_orderbook.status}
                    </StatusBadge>
                  ) : null}
                </div>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <Segment active>{t.clob}</Segment>
              <Segment>{t.official}</Segment>
              <Segment>{t.rules}</Segment>
            </div>
          </div>

          <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <DarkMetric
              label={t.targetPrice}
              value={targetPrice === null ? t.notAvailable : `$${targetPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
              subValue={workbench?.target_price?.source || t.notAvailable}
            />
            <DarkMetric
              label={t.currentPrice}
              value={price === null ? t.notAvailable : `$${price.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
              accent={priceChange === null ? undefined : priceChange >= 0 ? 'up' : 'down'}
              subValue={formatBtcReferenceTag(workbench) || formatPriceDistance(price, targetPrice)}
            />
            <DarkMetric
              label={t.upProbability}
              value={upMid === null ? t.notAvailable : `${Math.round(upMid * 100)}%`}
              accent="up"
              subValue={downMid === null ? undefined : `Down ${Math.round(downMid * 100)}%`}
            />
            <DarkMetric
              label={t.expiry}
              value={formatSeconds(workbench?.seconds_to_expiry ?? null, t.notAvailable)}
              subValue={workbench?.source || t.notAvailable}
            />
          </div>

          <div className="mt-5 h-[260px] rounded-lg border border-stone-200 bg-white p-4">
            <MarketLineChart points={history} emptyText={t.noData} />
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <TimeChip active label={workbench?.seconds_to_expiry === null ? t.window : '5分钟'} />
            <TimeChip label="15分钟" />
            <TimeChip label="1小时" />
            <TimeChip label="1天" />
          </div>
        </div>

        <aside className="grid content-start gap-4 p-5">
          <div className={`rounded-xl border px-4 py-4 ${
            workbench?.isTradable ? 'border-emerald-300 bg-emerald-50' : 'border-amber-300 bg-amber-50'
          }`}>
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">
              {t.conclusion}
            </div>
            <div className="mt-2 text-xl font-bold leading-8 text-stone-900">
              {workbench?.coreConclusion || t.noData}
            </div>
            <div className="mt-3 grid gap-2 text-sm">
              <AsideRow label={t.decision} value={workbench?.entry_optimizer?.decision || t.notAvailable} />
              <AsideRow label={t.action} value={workbench?.action || t.notAvailable} />
              <AsideRow label={t.candidate} value={workbench?.recommended_outcome || t.notAvailable} />
              <AsideRow label={t.maxEntry} value={formatPrice(workbench?.entry_optimizer?.max_acceptable_price ?? null)} />
              <AsideRow label={t.ev} value={formatSigned(workbench?.entry_optimizer?.expected_value ?? null)} />
              <AsideRow label={t.kelly} value={formatPercent(workbench?.entry_optimizer?.kelly_fraction ?? null)} />
              <AsideRow label={t.window} value={workbench?.slug || t.notAvailable} />
            </div>
          </div>

          <OutcomeTradeCard label={t.up} tone="up" workbench={workbench} outcome="UP" t={t} />
          <OutcomeTradeCard label={t.down} tone="down" workbench={workbench} outcome="DOWN" t={t} />
        </aside>
      </div>
    </section>
  );
}

function OutcomeTradeCard({
  label,
  tone,
  workbench,
  outcome,
  t,
}: {
  label: string;
  tone: 'up' | 'down';
  workbench: BtcFiveMinuteWorkbench | null;
  outcome: 'UP' | 'DOWN';
  t: typeof labels.zh;
}) {
  const data = workbench?.outcomes[outcome] ?? null;
  const probability = midpoint(data?.best_bid ?? null, data?.best_ask ?? null);
  const toneClass = tone === 'up'
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : 'border-rose-200 bg-rose-50 text-rose-700';

  return (
    <div className={`rounded-xl border px-4 py-4 ${toneClass}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="text-lg font-bold">{label}</div>
        <div className="mono text-2xl font-bold">
          {probability === null ? '--' : `${Math.round(probability * 100)}%`}
        </div>
      </div>
      <div className="mt-3 grid gap-2 text-sm text-stone-700">
        <AsideRow label="Bid / Ask" value={`${formatPrice(data?.best_bid ?? null)} / ${formatPrice(data?.best_ask ?? null)}`} />
        <AsideRow label={t.spread} value={formatPrice(data?.spread ?? null)} />
        <AsideRow label={t.depth} value={`${formatSize(data?.bid_depth_top3 ?? null)} / ${formatSize(data?.ask_depth_top3 ?? null)}`} />
        <AsideRow label={t.entry} value={formatPrice(data?.candidate_entry_price ?? null)} />
        <AsideRow label={t.decision} value={data?.entry_analysis?.entry_decision || '--'} />
        <AsideRow label={t.maxEntry} value={formatPrice(data?.entry_analysis?.max_acceptable_price ?? null)} />
        <AsideRow label={t.ev} value={formatSigned(data?.entry_analysis?.expected_value ?? null)} />
        <AsideRow label={t.kelly} value={formatPercent(data?.entry_analysis?.kelly_fraction ?? null)} />
      </div>
    </div>
  );
}

function MarketLineChart({ points, emptyText }: { points: TerminalPoint[]; emptyText: string }) {
  const valid = points.filter((point) => point.price !== null) as Array<TerminalPoint & { price: number }>;
  if (valid.length < 2) {
    return (
      <div className="grid h-full place-items-center text-sm font-medium text-stone-400">
        {emptyText}
      </div>
    );
  }

  const width = 820;
  const height = 220;
  const min = Math.min(...valid.map((point) => point.price));
  const max = Math.max(...valid.map((point) => point.price));
  const span = Math.max(1, max - min);
  const path = valid.map((point, index) => {
    const x = (index / Math.max(1, valid.length - 1)) * width;
    const y = height - ((point.price - min) / span) * (height - 24) - 12;
    return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(' ');
  const last = valid[valid.length - 1];
  const lastY = height - ((last.price - min) / span) * (height - 24) - 12;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" role="img" aria-label="BTC reference price chart">
      {[0.25, 0.5, 0.75].map((ratio) => (
        <line
          key={ratio}
          x1="0"
          x2={width}
          y1={height * ratio}
          y2={height * ratio}
          stroke="#e7e5e4"
          strokeDasharray="6 8"
        />
      ))}
      <path d={path} fill="none" stroke="#d97706" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={width - 2} cy={lastY} r="5" fill="#d97706" />
      <text x={width - 8} y={lastY - 10} textAnchor="end" fill="#57534e" fontSize="12">
        ${last.price.toLocaleString(undefined, { maximumFractionDigits: 0 })}
      </text>
    </svg>
  );
}

function DarkMetric({
  label,
  value,
  subValue,
  accent,
}: {
  label: string;
  value: string;
  subValue?: string;
  accent?: 'up' | 'down';
}) {
  const accentClass = accent === 'up' ? 'text-emerald-600' : accent === 'down' ? 'text-rose-600' : 'text-stone-900';
  return (
    <div className="rounded-lg border border-stone-200 bg-white px-4 py-3">
      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-stone-400">{label}</div>
      <div className={`mono mt-2 text-2xl font-bold ${accentClass}`}>{value}</div>
      {subValue && <div className="mono mt-1 text-xs text-stone-400">{subValue}</div>}
    </div>
  );
}

function AsideRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[110px,minmax(0,1fr)] gap-3">
      <span className="text-stone-400">{label}</span>
      <span className="mono truncate text-right font-semibold text-stone-900">{value}</span>
    </div>
  );
}

function Segment({ children, active = false }: { children: string; active?: boolean }) {
  return (
    <span className={`rounded-full px-3 py-1.5 text-xs font-bold ${
      active ? 'bg-stone-900 text-white' : 'bg-stone-100 text-stone-500'
    }`}>
      {children}
    </span>
  );
}

function TimeChip({ label, active = false }: { label: string; active?: boolean }) {
  return (
    <span className={`rounded-full px-3 py-2 text-sm font-semibold ${
      active ? 'bg-stone-900 text-white' : 'bg-stone-100 text-stone-500'
    }`}>
      {label}
    </span>
  );
}

function midpoint(bid: number | null, ask: number | null) {
  if (bid === null || ask === null) {
    return null;
  }
  return (bid + ask) / 2;
}

function formatPrice(value: number | null) {
  return value === null ? '--' : value.toFixed(3);
}

function formatSize(value: number | null) {
  return value === null ? '--' : value.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function formatSigned(value: number | null) {
  return value === null ? '--' : `${value >= 0 ? '+' : ''}${value.toFixed(4)}`;
}

function formatPercent(value: number | null) {
  return value === null ? '--' : `${(value * 100).toFixed(2)}%`;
}

function formatSeconds(value: number | null, empty: string) {
  return value === null ? empty : `${Math.max(0, Math.round(value))}s`;
}

function formatPriceDistance(price: number | null, targetPrice: number | null) {
  if (price === null || targetPrice === null) {
    return undefined;
  }
  const distance = price - targetPrice;
  return `${distance >= 0 ? '+' : ''}${distance.toFixed(2)} vs target`;
}

function formatBtcReferenceTag(workbench: BtcFiveMinuteWorkbench | null) {
  const reference = workbench?.btc_reference;
  if (!reference || reference.price === null) {
    return undefined;
  }
  const latency = reference.staleness_ms ?? reference.round_trip_ms;
  const latencyLabel = latency === null || latency === undefined ? 'latency n/a' : `${latency}ms`;
  return `${reference.source} · ${latencyLabel}`;
}
