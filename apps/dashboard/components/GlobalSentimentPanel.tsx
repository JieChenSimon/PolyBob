'use client';

import { useQuery } from '@tanstack/react-query';
import ErrorState from '@/components/ui/ErrorState';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

interface IndexQuote {
  key: string;
  name: string;
  price: number;
  change: number;
  change_pct: number;
}

interface RiskAppetite {
  date: string;
  limit_up_count: number;
  regime: 'hot' | 'warm' | 'cold';
}

interface Gauge {
  index: string;
  date: string;
  value: number;
  label: string;
}

interface SentimentPayload {
  gauges: Gauge[];
  global_indices: IndexQuote[];
  a_share_risk_appetite: RiskAppetite | null;
  timestamp: string;
  global_error?: string;
  a_share_error?: string;
}

const GAUGE_META: Record<string, { zh: string; en: string; max: number }> = {
  crypto_fear_greed: { zh: '加密恐惧贪婪', en: 'Crypto Fear & Greed', max: 100 },
  vix: { zh: 'VIX 恐慌指数', en: 'VIX', max: 50 },
  gold_oil_ratio: { zh: '金油比', en: 'Gold/Oil Ratio', max: 60 },
};

const LABEL_TEXT: Record<string, { zh: string; en: string }> = {
  extreme_fear: { zh: '极度恐惧', en: 'extreme fear' },
  fear: { zh: '恐惧', en: 'fear' },
  neutral: { zh: '中性', en: 'neutral' },
  greed: { zh: '贪婪', en: 'greed' },
  extreme_greed: { zh: '极度贪婪', en: 'extreme greed' },
  complacent: { zh: '自满', en: 'complacent' },
  calm: { zh: '平静', en: 'calm' },
  elevated: { zh: '升高', en: 'elevated' },
  panic: { zh: '恐慌', en: 'panic' },
  stress: { zh: '压力', en: 'stress' },
  elevated_ratio: { zh: '偏高', en: 'elevated' },
  normal: { zh: '正常', en: 'normal' },
  risk_on: { zh: '风险偏好', en: 'risk-on' },
};

/** Fear reads cool (sky), greed/panic read hot (rose) — same scale both ways. */
const LABEL_STYLE: Record<string, string> = {
  extreme_fear: 'bg-sky-100 text-sky-800 border-sky-300',
  fear: 'bg-sky-50 text-sky-700 border-sky-200',
  neutral: 'bg-stone-100 text-stone-600 border-stone-200',
  greed: 'bg-amber-50 text-amber-700 border-amber-200',
  extreme_greed: 'bg-rose-50 text-rose-700 border-rose-200',
  complacent: 'bg-sky-50 text-sky-700 border-sky-200',
  calm: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  elevated: 'bg-amber-50 text-amber-700 border-amber-200',
  panic: 'bg-rose-50 text-rose-700 border-rose-200',
  stress: 'bg-rose-50 text-rose-700 border-rose-200',
  normal: 'bg-stone-100 text-stone-600 border-stone-200',
  risk_on: 'bg-emerald-50 text-emerald-700 border-emerald-200',
};

const REGIME_STYLE: Record<string, string> = {
  hot: 'bg-rose-50 text-rose-700 border-rose-200',
  warm: 'bg-amber-50 text-amber-700 border-amber-200',
  cold: 'bg-sky-50 text-sky-700 border-sky-200',
};

function regimeLabel(regime: string, zh: boolean): string {
  const map: Record<string, { zh: string; en: string }> = {
    hot: { zh: '火热', en: 'hot' },
    warm: { zh: '温和', en: 'warm' },
    cold: { zh: '冷淡', en: 'cold' },
  };
  return zh ? (map[regime]?.zh ?? regime) : (map[regime]?.en ?? regime);
}

/**
 * Global indices plus the A-share limit-up count (the standard speculative
 * risk-appetite thermometer). Presented as market context only: stratifying the
 * dragon-tiger reversal edge by this reading showed no significant difference
 * (p = 0.30), so the panel deliberately does not imply it is a trading switch.
 */
export default function GlobalSentimentPanel() {
  const { language } = useLanguage();
  const zh = language === 'zh';

  const query = useQuery<SentimentPayload>({
    queryKey: ['market-sentiment'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/market-sentiment`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return (await response.json()) as SentimentPayload;
    },
    refetchInterval: 60_000,
    staleTime: 45_000,
  });

  const indices = query.data?.global_indices ?? [];
  const appetite = query.data?.a_share_risk_appetite ?? null;
  const gauges = query.data?.gauges ?? [];

  return (
    <section
      aria-label={zh ? '全球市场情绪' : 'Global market sentiment'}
      className="panel mb-6 overflow-hidden"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-200 px-5 py-4">
        <div>
          <div className="eyebrow">{zh ? '环球投资情绪' : 'Global Sentiment'}</div>
          <h2 className="mt-0.5 text-lg font-bold tracking-[-0.02em] text-stone-900">
            {zh ? '全球指数 · A股风险偏好' : 'World Indices · A-share Risk Appetite'}
          </h2>
        </div>
        {appetite ? (
          <span
            className={`rounded-full border px-3 py-1 text-xs font-medium ${
              REGIME_STYLE[appetite.regime] ?? REGIME_STYLE.cold
            }`}
          >
            {zh ? '涨停 ' : 'Limit-ups '}
            <span className="font-mono font-semibold">{appetite.limit_up_count}</span>
            {' · '}
            {regimeLabel(appetite.regime, zh)}
          </span>
        ) : null}
      </div>

      {query.isError ? (
        <ErrorState
          className="m-5"
          title={zh ? '情绪数据加载失败' : 'Failed to load sentiment'}
          message={zh ? '无法连接 PolyBob API。' : 'Cannot reach the PolyBob API.'}
          onRetry={() => void query.refetch()}
          retryLabel={zh ? '重试' : 'Retry'}
        />
      ) : null}

      {gauges.length > 0 ? (
        <ul className="grid grid-cols-2 gap-3 lg:grid-cols-3 border-b border-stone-200 px-5 py-4">
          {gauges.map((gauge) => {
            const meta = GAUGE_META[gauge.index];
            const pct = Math.min(100, Math.max(0, (gauge.value / (meta?.max ?? 100)) * 100));
            return (
              <li key={gauge.index} className="rounded-lg border border-stone-200 p-3">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-xs font-medium text-stone-500">
                    {meta ? (zh ? meta.zh : meta.en) : gauge.index}
                  </span>
                  <span className="font-mono text-lg font-bold text-stone-900">
                    {gauge.value.toFixed(gauge.index === 'crypto_fear_greed' ? 0 : 2)}
                  </span>
                </div>
                <div
                  className="mt-2 h-1.5 overflow-hidden rounded-full bg-stone-100"
                  role="img"
                  aria-label={`${gauge.index} ${gauge.value}`}
                >
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-sky-400 via-amber-400 to-rose-500"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span
                  className={`mt-2 inline-block rounded border px-1.5 py-0.5 text-[10px] font-medium ${
                    LABEL_STYLE[gauge.label] ?? LABEL_STYLE.neutral
                  }`}
                >
                  {LABEL_TEXT[gauge.label] ? (zh ? LABEL_TEXT[gauge.label].zh : LABEL_TEXT[gauge.label].en) : gauge.label}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}

      {!query.isError && indices.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-stone-400" aria-live="polite">
          {query.isLoading ? (zh ? '加载中…' : 'Loading…') : (zh ? '暂无数据' : 'No data')}
        </div>
      ) : (
        <ul className="grid grid-cols-2 divide-x divide-y divide-stone-100 md:grid-cols-3 lg:grid-cols-5">
          {indices.map((index) => {
            const up = index.change_pct >= 0;
            return (
              <li key={index.key} className="px-4 py-3">
                <div className="truncate text-[11px] uppercase tracking-wide text-stone-400">
                  {index.name}
                </div>
                <div className="mt-0.5 font-mono text-[15px] font-semibold text-stone-900">
                  {index.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </div>
                <div
                  className={`mt-0.5 font-mono text-xs font-medium ${
                    up ? 'text-emerald-600' : 'text-rose-600'
                  }`}
                >
                  {up ? '▲' : '▼'} {index.change_pct >= 0 ? '+' : ''}
                  {index.change_pct.toFixed(2)}%
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <p className="border-t border-stone-200 px-5 py-2.5 text-[11px] leading-5 text-stone-500">
        {zh
          ? '说明:涨停数是 A 股投机情绪温度计。实测按其分层对龙虎榜反转策略的效果差异不显著(p=0.30),故此处仅作环境参考,不作为交易开关。'
          : 'Note: the limit-up count is A-share speculative appetite. Stratifying the dragon-tiger reversal edge by it showed no significant difference (p = 0.30), so this is context only — not a trading switch.'}
      </p>
    </section>
  );
}
