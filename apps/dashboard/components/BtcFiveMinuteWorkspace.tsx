'use client';

import { type BtcFiveMinuteOutcome, type BtcFiveMinuteWorkbench } from '@/domain/btcFiveMinute/workbench';
import { useLanguage } from '@/lib/i18n';

const labels = {
  zh: {
    loading: '正在读取真实盘口...',
    core: '核心结论',
    source: '数据源',
    action: '动作',
    recommended: '候选方向',
    window: '窗口',
    expiry: '剩余',
    reference: 'BTC参考价',
    referenceSources: 'BTC实时价源',
    dataHealth: '数据健康检查',
    marketMeta: '市场元数据',
    orderBook: 'CLOB盘口',
    targetLayer: '目标价',
    status: '状态',
    latency: '延迟',
    selected: '已选',
    target: '目标价',
    reasons: '原因',
    error: '错误',
    diagnosis: '问题判断',
    category: '类别',
    responsibility: '责任侧',
    provider: '数据方',
    endpoint: '接口',
    likelyCause: '可能原因',
    userAction: '建议动作',
    technicalDetail: '技术细节',
    up: '上涨 UP',
    down: '下跌 DOWN',
    bestBid: '最佳买价',
    bestAsk: '最佳卖价',
    spread: '价差',
    bidDepth: '买盘深度',
    askDepth: '卖盘深度',
    entry: '候选进场价',
    decision: '入场判断',
    maxEntry: '最高限价',
    enterBelow: '可入场价',
    watchBelow: '观察价',
    avoidAbove: '禁止追价',
    edge: '估计边际',
    ev: 'EV',
    kelly: 'Kelly仓位',
    probability: '模型概率',
    bids: '买盘',
    asks: '卖盘',
    notAvailable: '不可用',
    realBook: '真实盘口',
    notRealBook: '无真实盘口',
  },
  en: {
    loading: 'Loading real order book...',
    core: 'Core Conclusion',
    source: 'Source',
    action: 'Action',
    recommended: 'Candidate',
    window: 'Window',
    expiry: 'Expiry',
    reference: 'BTC Reference',
    referenceSources: 'BTC Price Sources',
    dataHealth: 'Data Health',
    marketMeta: 'Market Metadata',
    orderBook: 'CLOB Order Book',
    targetLayer: 'Target Price',
    status: 'Status',
    latency: 'Latency',
    selected: 'Selected',
    target: 'Target',
    reasons: 'Reasons',
    error: 'Error',
    diagnosis: 'Diagnosis',
    category: 'Category',
    responsibility: 'Responsibility',
    provider: 'Provider',
    endpoint: 'Endpoint',
    likelyCause: 'Likely Cause',
    userAction: 'Suggested Action',
    technicalDetail: 'Technical Detail',
    up: 'Up',
    down: 'Down',
    bestBid: 'Best Bid',
    bestAsk: 'Best Ask',
    spread: 'Spread',
    bidDepth: 'Bid Depth',
    askDepth: 'Ask Depth',
    entry: 'Candidate Entry',
    decision: 'Entry Decision',
    maxEntry: 'Max Entry',
    enterBelow: 'Enter Below',
    watchBelow: 'Watch Below',
    avoidAbove: 'Avoid Above',
    edge: 'Estimated Edge',
    ev: 'EV',
    kelly: 'Kelly Size',
    probability: 'Model Probability',
    bids: 'Bids',
    asks: 'Asks',
    notAvailable: 'N/A',
    realBook: 'Real Book',
    notRealBook: 'No Real Book',
  },
};

export default function BtcFiveMinuteWorkspace({
  workbench,
  lastUpdated,
}: {
  workbench: BtcFiveMinuteWorkbench | null;
  lastUpdated: string | null;
}) {
  const { language } = useLanguage();
  const t = labels[language];

  if (!workbench) {
    return (
      <section className="panel px-5 py-8 text-sm font-medium text-stone-600">
        {t.loading}
      </section>
    );
  }

  return (
    <div className="grid gap-5">
      <section className={`panel overflow-hidden border-l-4 px-5 py-5 ${
        workbench.isTradable ? 'border-emerald-500' : 'border-amber-500'
      }`}>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">
              {t.core}
            </div>
            <h2 className="mt-2 text-2xl font-bold text-stone-950 md:text-3xl">
              {workbench.coreConclusion}
            </h2>
            <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
              <StatusPill label={t.source} value={workbench.source} />
              <StatusPill label={t.action} value={workbench.action} />
              <StatusPill label={t.recommended} value={workbench.recommended_outcome || t.notAvailable} />
            </div>
          </div>
          <div className="grid min-w-[240px] gap-2 text-sm text-stone-600">
            <MetaRow label={t.window} value={workbench.slug || t.notAvailable} />
            <MetaRow label={t.expiry} value={formatSeconds(workbench.seconds_to_expiry, t.notAvailable)} />
            <MetaRow label={t.target} value={formatPriceValue(workbench.target_price?.price ?? null, t.notAvailable)} />
            <MetaRow label={t.reference} value={formatBtcReference(workbench, t.notAvailable)} />
            <MetaRow label="Updated" value={lastUpdated || t.notAvailable} />
          </div>
        </div>
        {(workbench.reason_codes.length > 0 || workbench.error) && (
          <div className="mt-4 grid gap-2 text-sm">
            {workbench.reason_codes.length > 0 && (
              <div className="rounded-lg bg-amber-50 px-3 py-2 font-medium text-amber-900">
                {t.reasons}: {workbench.reason_codes.join(', ')}
              </div>
            )}
            {workbench.error && (
              <div className="rounded-lg bg-rose-50 px-3 py-2 font-medium text-rose-900">
                {t.error}: {workbench.error}
              </div>
            )}
            {workbench.error_diagnosis && (
              <div className="rounded-lg border border-rose-100 bg-white px-3 py-3 text-stone-700">
                <div className="mb-2 text-xs font-bold uppercase tracking-[0.12em] text-rose-700">
                  {t.diagnosis}
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                  <MetaRow label={t.category} value={workbench.error_diagnosis.category} />
                  <MetaRow label={t.responsibility} value={workbench.error_diagnosis.responsibility} />
                  <MetaRow label={t.provider} value={workbench.error_diagnosis.provider || t.notAvailable} />
                  <MetaRow label={t.endpoint} value={workbench.error_diagnosis.endpoint || t.notAvailable} />
                </div>
                <div className="mt-3 grid gap-2">
                  <DiagnosisText label={t.likelyCause} value={workbench.error_diagnosis.likely_cause} />
                  <DiagnosisText label={t.userAction} value={workbench.error_diagnosis.user_action} />
                  <DiagnosisText label={t.technicalDetail} value={workbench.error_diagnosis.technical_detail || workbench.error || t.notAvailable} mono />
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      <DataHealthPanel workbench={workbench} t={t} />

      <BtcReferenceSources workbench={workbench} t={t} />

      <section className="grid gap-5 xl:grid-cols-2">
        <OutcomePanel title={t.up} outcome={workbench.outcomes.UP} tone="emerald" t={t} />
        <OutcomePanel title={t.down} outcome={workbench.outcomes.DOWN} tone="rose" t={t} />
      </section>
    </div>
  );
}

function DataHealthPanel({ workbench, t }: { workbench: BtcFiveMinuteWorkbench; t: typeof labels.zh }) {
  const layers = [
    { key: 'polymarket_market', title: t.marketMeta, layer: workbench.data_health.polymarket_market },
    { key: 'polymarket_orderbook', title: t.orderBook, layer: workbench.data_health.polymarket_orderbook },
    { key: 'btc_reference', title: t.reference, layer: workbench.data_health.btc_reference },
    { key: 'target_price', title: t.targetLayer, layer: workbench.data_health.target_price },
  ];
  return (
    <section className="panel overflow-hidden">
      <header className="border-b border-stone-200 px-5 py-4">
        <h3 className="text-lg font-bold text-stone-950">{t.dataHealth}</h3>
      </header>
      <div className="grid gap-3 px-5 py-4 lg:grid-cols-4">
        {layers.map(({ key, title, layer }) => (
          <div key={key} className={`rounded-lg border px-3 py-3 text-sm ${healthTone(layer.status)}`}>
            <div className="flex items-start justify-between gap-2">
              <div className="font-bold text-stone-950">{title}</div>
              <span className="mono rounded bg-white/70 px-2 py-0.5 text-xs font-bold uppercase">
                {layer.status}
              </span>
            </div>
            <div className="mono mt-1 truncate text-xs text-stone-600">{layer.provider || t.notAvailable}</div>
            <div className="mt-2 leading-5 text-stone-700">{layer.message}</div>
            {layer.action && (
              <div className="mt-2 rounded-md bg-white/70 px-2 py-2 text-xs leading-5 text-stone-700">
                {layer.action}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function BtcReferenceSources({ workbench, t }: { workbench: BtcFiveMinuteWorkbench; t: typeof labels.zh }) {
  const sources = workbench.btc_reference?.sources ?? [];
  if (sources.length === 0) {
    return null;
  }

  return (
    <section className="panel overflow-hidden">
      <header className="flex items-center justify-between gap-3 border-b border-stone-200 px-5 py-4">
        <div>
          <h3 className="text-lg font-bold text-stone-950">{t.referenceSources}</h3>
          <p className="mono mt-1 text-xs text-stone-500">
            {workbench.btc_reference?.source || t.notAvailable} · {formatLatency(workbench.btc_reference?.staleness_ms ?? workbench.btc_reference?.round_trip_ms ?? null, t.notAvailable)}
          </p>
        </div>
      </header>
      <div className="grid gap-2 px-5 py-4">
        {sources.map((source) => (
          <div
            key={source.source}
            className={`grid gap-2 rounded-lg border px-3 py-3 text-sm md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,0.8fr)_minmax(0,0.8fr)] ${
              source.selected ? 'border-emerald-200 bg-emerald-50' : 'border-stone-200 bg-stone-50'
            }`}
          >
            <div className="min-w-0">
              <div className="font-bold text-stone-900">{source.source}</div>
              <div className="mono truncate text-xs text-stone-500">{source.symbol || t.notAvailable}</div>
            </div>
            <div className="mono font-semibold text-stone-900">{formatPriceValue(source.price, t.notAvailable)}</div>
            <div className="text-stone-600">{t.status}: <span className="mono">{source.status}</span></div>
            <div className="text-stone-600">{t.latency}: <span className="mono">{formatLatency(source.staleness_ms ?? source.round_trip_ms, t.notAvailable)}</span></div>
          </div>
        ))}
      </div>
    </section>
  );
}

function OutcomePanel({
  title,
  outcome,
  tone,
  t,
}: {
  title: string;
  outcome: BtcFiveMinuteOutcome;
  tone: 'emerald' | 'rose';
  t: typeof labels.zh;
}) {
  const toneClass = tone === 'emerald' ? 'text-emerald-700 bg-emerald-50' : 'text-rose-700 bg-rose-50';

  return (
    <article className="panel overflow-hidden">
      <header className="flex items-center justify-between gap-3 border-b border-stone-200 px-5 py-4">
        <div className="min-w-0">
          <h3 className="text-xl font-bold text-stone-950">{title}</h3>
          <p className="mono mt-1 truncate text-xs text-stone-500">{outcome.token_id || t.notAvailable}</p>
        </div>
        <span className={`shrink-0 rounded-md px-2.5 py-1 text-xs font-bold ${toneClass}`}>
          {outcome.is_real_orderbook ? t.realBook : t.notRealBook}
        </span>
      </header>

      <div className="grid gap-3 px-5 py-4 sm:grid-cols-2 lg:grid-cols-3">
        <Metric label={t.bestBid} value={formatPrice(outcome.best_bid, t.notAvailable)} />
        <Metric label={t.bestAsk} value={formatPrice(outcome.best_ask, t.notAvailable)} />
        <Metric label={t.spread} value={formatPrice(outcome.spread, t.notAvailable)} />
        <Metric label={t.bidDepth} value={formatSize(outcome.bid_depth_top3, t.notAvailable)} />
        <Metric label={t.askDepth} value={formatSize(outcome.ask_depth_top3, t.notAvailable)} />
        <Metric label={t.entry} value={formatPrice(outcome.candidate_entry_price, t.notAvailable)} strong />
        <Metric label={t.decision} value={outcome.entry_analysis?.entry_decision || t.notAvailable} strong />
        <Metric label={t.maxEntry} value={formatPrice(outcome.entry_analysis?.max_acceptable_price ?? null, t.notAvailable)} />
        <Metric label={t.edge} value={formatPercent(outcome.estimated_edge, t.notAvailable)} />
        <Metric label={t.ev} value={formatSigned(outcome.entry_analysis?.expected_value ?? null, t.notAvailable)} />
        <Metric label={t.kelly} value={formatPercent(outcome.entry_analysis?.kelly_fraction ?? null, t.notAvailable)} />
        <Metric label={t.probability} value={formatPercent(outcome.model_probability, t.notAvailable)} />
      </div>

      {outcome.entry_analysis && (
        <div className="grid gap-3 border-t border-stone-200 px-5 py-4 sm:grid-cols-3">
          <Metric label={t.enterBelow} value={formatPrice(outcome.entry_analysis.entry_band.enter_below, t.notAvailable)} strong />
          <Metric label={t.watchBelow} value={formatPrice(outcome.entry_analysis.entry_band.watch_below, t.notAvailable)} />
          <Metric label={t.avoidAbove} value={formatPrice(outcome.entry_analysis.entry_band.avoid_above, t.notAvailable)} />
        </div>
      )}

      <div className="grid gap-4 border-t border-stone-200 px-5 py-4 md:grid-cols-2">
        <BookSide title={t.bids} levels={outcome.levels.bids} empty={t.notAvailable} />
        <BookSide title={t.asks} levels={outcome.levels.asks} empty={t.notAvailable} />
      </div>
    </article>
  );
}

function BookSide({ title, levels, empty }: { title: string; levels: { price: number; size: number }[]; empty: string }) {
  return (
    <div className="min-w-0">
      <div className="mb-2 text-xs font-bold uppercase tracking-[0.12em] text-stone-500">{title}</div>
      <div className="grid gap-1">
        {levels.slice(0, 6).map((level) => (
          <div key={`${level.price}-${level.size}`} className="grid grid-cols-2 rounded-md bg-stone-50 px-3 py-2 mono text-xs">
            <span>{formatPrice(level.price, empty)}</span>
            <span className="text-right text-stone-600">{formatSize(level.size, empty)}</span>
          </div>
        ))}
        {levels.length === 0 && <div className="rounded-md bg-stone-50 px-3 py-2 text-sm text-stone-500">{empty}</div>}
      </div>
    </div>
  );
}

function Metric({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="metric-panel">
      <div className="text-xs font-semibold uppercase tracking-[0.1em] text-stone-500">{label}</div>
      <div className={`mono mt-1 text-lg ${strong ? 'font-bold text-stone-950' : 'font-semibold text-stone-800'}`}>
        {value}
      </div>
    </div>
  );
}

function StatusPill({ label, value }: { label: string; value: string }) {
  return (
    <span className="rounded-md border border-stone-200 bg-stone-50 px-2.5 py-1 text-stone-700">
      {label}: <span className="mono text-stone-950">{value}</span>
    </span>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[88px,minmax(0,1fr)] gap-3">
      <span className="font-semibold text-stone-500">{label}</span>
      <span className="mono truncate text-right text-stone-900">{value}</span>
    </div>
  );
}

function DiagnosisText({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="grid gap-1">
      <span className="text-xs font-semibold uppercase tracking-[0.1em] text-stone-500">{label}</span>
      <span className={`${mono ? 'mono' : ''} break-words text-sm leading-6 text-stone-800`}>{value}</span>
    </div>
  );
}

function formatPrice(value: number | null, empty: string) {
  return value === null ? empty : value.toFixed(3);
}

function formatPriceValue(value: number | null, empty: string) {
  return value === null ? empty : `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function formatLatency(value: number | null | undefined, empty: string) {
  return typeof value === 'number' ? `${value}ms` : empty;
}

function formatPercent(value: number | null, empty: string) {
  return value === null ? empty : `${(value * 100).toFixed(1)}%`;
}

function formatSigned(value: number | null, empty: string) {
  return value === null ? empty : `${value >= 0 ? '+' : ''}${value.toFixed(4)}`;
}

function formatSize(value: number | null, empty: string) {
  return value === null ? empty : value.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function formatSeconds(value: number | null, empty: string) {
  return value === null ? empty : `${Math.max(0, Math.round(value))}s`;
}

function formatBtcReference(workbench: BtcFiveMinuteWorkbench, empty: string) {
  const price = workbench.btc_reference?.price;
  return typeof price === 'number' ? `$${price.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : empty;
}

function healthTone(status: string) {
  if (status === 'ok') {
    return 'border-emerald-200 bg-emerald-50';
  }
  if (status === 'degraded') {
    return 'border-amber-200 bg-amber-50';
  }
  return 'border-rose-200 bg-rose-50';
}
