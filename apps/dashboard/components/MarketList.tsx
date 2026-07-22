'use client';

import { DashboardMarket } from '@/lib/types';
import { useLanguage } from '@/lib/i18n';
import { formatCompact, formatNumber } from '@/lib/format';
import EmptyState from '@/components/ui/EmptyState';
import StatusBadge, { type StatusTone } from '@/components/ui/StatusBadge';

interface MarketListProps {
  markets: DashboardMarket[];
  selectedMarketId: string | null;
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  onSelectMarket: (marketId: string) => void;
}

export default function MarketList({
  markets,
  selectedMarketId,
  searchQuery,
  onSearchQueryChange,
  onSelectMarket,
}: MarketListProps) {
  const { language } = useLanguage();
  const zh = language === 'zh';

  return (
    <aside
      aria-label={zh ? '市场列表' : 'Market list'}
      className="panel flex max-h-[720px] min-h-[420px] flex-col overflow-hidden xl:min-h-[720px]"
    >
      <div className="border-b border-stone-200 px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-base font-bold tracking-[-0.02em] text-stone-900">
              {zh ? '市场列表' : 'Market List'}
            </div>
            <p className="mt-1 text-sm text-stone-500">
              {zh ? '先选一个市场，再到右侧看盘口和信号解释。' : 'Select a market, then review features and signals on the right.'}
            </p>
          </div>
          <StatusBadge tone="neutral">
            {markets.length} {zh ? '个可见' : 'visible'}
          </StatusBadge>
        </div>

        <div className="mt-3">
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => onSearchQueryChange(event.target.value)}
            aria-label={zh ? '搜索市场' : 'Search markets'}
            placeholder={zh ? '搜索市场问题、slug 或分类' : 'Search question, slug, or category'}
            className="w-full rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-sm text-stone-900 outline-none transition focus:border-sky-500 focus:bg-white"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {markets.length === 0 ? (
          <EmptyState
            title={zh ? '暂无匹配市场' : 'No matching markets'}
            hint={zh
              ? '可以换个关键词，或等下一轮 watchlist 扫描完成后自动补充。'
              : 'Try another keyword or wait for the next watchlist scan.'}
          />
        ) : (
          <div className="space-y-2">
            {markets.map((market) => {
              const feature = market.features;
              const isSelected = market.market_id === selectedMarketId;
              const spread = feature?.spread_bps ?? null;
              const spreadState =
                typeof spread !== 'number'
                  ? 'waiting'
                  : spread > 500
                    ? 'wide'
                    : spread > 150
                      ? 'watch'
                      : 'healthy';
              const spreadTone: StatusTone =
                spreadState === 'healthy' ? 'ok'
                : spreadState === 'watch' ? 'warn'
                : spreadState === 'wide' ? 'danger'
                : 'neutral';

              return (
                <button
                  key={market.market_id}
                  onClick={() => onSelectMarket(market.market_id)}
                  aria-pressed={isSelected}
                  className={`w-full rounded-lg border px-4 py-3 text-left transition ${
                    isSelected
                      ? 'border-sky-500 bg-sky-50 shadow-[inset_3px_0_0_#0284c7]'
                      : 'border-stone-200 bg-white hover:border-sky-300 hover:bg-stone-50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[15px] font-semibold leading-6 text-stone-900">
                        {market.question}
                      </div>
                      <div className="mt-0.5 text-xs text-stone-500">
                        {market.category || (zh ? '未分类' : 'Uncategorized')}
                      </div>
                    </div>
                    <StatusBadge tone={spreadTone}>{formatSpreadState(spreadState, zh)}</StatusBadge>
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
                    <ListMetric label={zh ? '中间价' : 'Mid'} value={formatNumber(feature?.mid_price, 4)} />
                    <ListMetric
                      label={zh ? '价差' : 'Spread'}
                      value={typeof spread === 'number' ? `${formatNumber(spread, 1)} bps` : '--'}
                    />
                    <ListMetric label={zh ? '流动性' : 'Liquidity'} value={formatCompact(market.liquidity_score)} />
                    <ListMetric label={zh ? '量(1m)' : 'Vol (1m)'} value={formatNumber(feature?.volume_1m, 0)} />
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
}

function ListMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.1em] text-stone-400">{label}</div>
      <div className="mt-0.5 font-semibold text-stone-900">{value}</div>
    </div>
  );
}

function formatSpreadState(state: 'healthy' | 'watch' | 'wide' | 'waiting', zh: boolean) {
  const labels = {
    healthy: zh ? '健康' : 'Healthy',
    watch: zh ? '关注' : 'Watch',
    wide: zh ? '过宽' : 'Wide',
    waiting: zh ? '等待' : 'Waiting',
  };

  return labels[state];
}
