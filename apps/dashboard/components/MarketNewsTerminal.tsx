'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import ErrorState from '@/components/ui/ErrorState';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

type Direction = 'bullish' | 'bearish' | 'mixed' | 'neutral';

interface AssetImpact {
  asset_class: string;
  direction: Direction;
  confidence: number;
  rationale: string;
}

interface NewsItem {
  document_id: string;
  headline: string;
  summary: string;
  url: string;
  source: string;
  category: string | null;
  related: string[];
  published_at: string | null;
  captured_at: string;
  sentiment: Direction;
  analysis_engine: string;
  impacts: AssetImpact[];
}

interface NewsPayload {
  count: number;
  asset_classes: string[];
  filter: string | null;
  items: NewsItem[];
}

const ASSET_LABELS: Record<string, { zh: string; en: string }> = {
  us_equities: { zh: '股市', en: 'Equities' },
  crypto: { zh: '加密', en: 'Crypto' },
  gold: { zh: '黄金', en: 'Gold' },
  fx: { zh: '外汇', en: 'FX' },
  rates: { zh: '利率', en: 'Rates' },
  oil: { zh: '原油', en: 'Oil' },
};

const DIRECTION_STYLE: Record<Direction, string> = {
  bullish: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  bearish: 'bg-rose-50 text-rose-700 border-rose-200',
  mixed: 'bg-amber-50 text-amber-700 border-amber-200',
  neutral: 'bg-stone-100 text-stone-500 border-stone-200',
};

const DIRECTION_MARK: Record<Direction, string> = {
  bullish: '▲',
  bearish: '▼',
  mixed: '◆',
  neutral: '•',
};

function assetLabel(assetClass: string, zh: boolean): string {
  const entry = ASSET_LABELS[assetClass];
  if (!entry) return assetClass;
  return zh ? entry.zh : entry.en;
}

function directionLabel(direction: Direction, zh: boolean): string {
  const map: Record<Direction, { zh: string; en: string }> = {
    bullish: { zh: '利多', en: 'bullish' },
    bearish: { zh: '利空', en: 'bearish' },
    mixed: { zh: '中性偏波动', en: 'mixed' },
    neutral: { zh: '中性', en: 'neutral' },
  };
  return zh ? map[direction].zh : map[direction].en;
}

function relativeTime(iso: string | null, zh: boolean): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return zh ? '刚刚' : 'now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return zh ? `${minutes}分钟前` : `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return zh ? `${hours}小时前` : `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return zh ? `${days}天前` : `${days}d ago`;
}

export default function MarketNewsTerminal() {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const [assetFilter, setAssetFilter] = useState<string | null>(null);

  const newsQuery = useQuery<NewsPayload>({
    queryKey: ['market-news', assetFilter ?? 'all'],
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({ limit: '40' });
      if (assetFilter) params.set('asset_class', assetFilter);
      const response = await fetch(`${API_BASE}/api/market-news?${params.toString()}`, { signal });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return (await response.json()) as NewsPayload;
    },
    refetchInterval: 20_000,
    staleTime: 15_000,
  });

  const payload = newsQuery.data;
  const items = payload?.items ?? [];
  const assetClasses = payload?.asset_classes ?? Object.keys(ASSET_LABELS);

  return (
    <section className="panel mb-6 flex flex-col overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-200 px-5 py-4">
        <div>
          <div className="eyebrow">{zh ? '实时市场消息' : 'Market Wire'}</div>
          <h2 className="mt-0.5 text-lg font-bold tracking-[-0.02em] text-stone-900">
            {zh ? '新闻流 · 跨资产影响' : 'News Feed · Cross-Asset Impact'}
          </h2>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-stone-500">
          <span className={`inline-block h-2 w-2 rounded-full ${newsQuery.isFetching ? 'bg-emerald-400' : 'bg-stone-300'}`} />
          {zh ? '每 20 秒刷新' : 'refreshes every 20s'}
        </div>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-stone-200 px-5 py-3">
        <FilterChip active={assetFilter === null} onClick={() => setAssetFilter(null)}>
          {zh ? '全部' : 'All'}
        </FilterChip>
        {assetClasses.map((assetClass) => (
          <FilterChip
            key={assetClass}
            active={assetFilter === assetClass}
            onClick={() => setAssetFilter(assetClass)}
          >
            {assetLabel(assetClass, zh)}
          </FilterChip>
        ))}
      </div>

      {newsQuery.isError ? (
        <ErrorState
          className="m-5"
          title={zh ? '新闻加载失败' : 'Failed to load news'}
          message={
            zh
              ? '无法连接新闻服务，请确认 FINNHUB_API_KEY 已配置且 API 正在运行。'
              : 'Cannot reach the news service; check that FINNHUB_API_KEY is set and the API is running.'
          }
          onRetry={() => void newsQuery.refetch()}
          retryLabel={zh ? '重试' : 'Retry'}
        />
      ) : null}

      {!newsQuery.isError && items.length === 0 ? (
        <div className="px-5 py-10 text-center text-sm text-stone-400">
          {newsQuery.isLoading
            ? zh
              ? '加载市场消息中…'
              : 'Loading market wire…'
            : zh
              ? '暂无匹配的市场消息。'
              : 'No matching market news yet.'}
        </div>
      ) : null}

      <ul className="max-h-[720px] divide-y divide-stone-100 overflow-y-auto">
        {items.map((item) => (
          <li key={item.document_id} className="px-5 py-3.5 transition hover:bg-stone-50/70">
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-stone-400">
              <span className="font-semibold text-stone-500">{item.source}</span>
              <span aria-hidden>·</span>
              <span className="font-mono">{relativeTime(item.published_at, zh)}</span>
              {item.category ? (
                <>
                  <span aria-hidden>·</span>
                  <span>{item.category}</span>
                </>
              ) : null}
            </div>

            <a
              href={item.url || undefined}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 block text-[15px] font-semibold leading-snug text-stone-900 hover:text-sky-700"
            >
              {item.headline}
            </a>

            {item.impacts.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {item.impacts.map((impact) => (
                  <span
                    key={`${item.document_id}-${impact.asset_class}`}
                    title={impact.rationale}
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${DIRECTION_STYLE[impact.direction] ?? DIRECTION_STYLE.neutral}`}
                  >
                    <span aria-hidden>{DIRECTION_MARK[impact.direction] ?? '•'}</span>
                    {assetLabel(impact.asset_class, zh)}
                    <span className="opacity-70">{directionLabel(impact.direction, zh)}</span>
                  </span>
                ))}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
        active
          ? 'border-sky-500 bg-sky-50 text-sky-700'
          : 'border-stone-200 bg-white text-stone-500 hover:border-stone-300 hover:text-stone-700'
      }`}
    >
      {children}
    </button>
  );
}
