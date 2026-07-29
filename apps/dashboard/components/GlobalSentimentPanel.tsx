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

interface SentimentPayload {
  global_indices: IndexQuote[];
  a_share_risk_appetite: RiskAppetite | null;
  timestamp: string;
  global_error?: string;
  a_share_error?: string;
}

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
