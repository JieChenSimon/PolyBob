'use client';

import { DashboardMarket } from '@/lib/types';

interface MarketListProps {
  markets: DashboardMarket[];
  selectedMarketId: string | null;
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  onSelectMarket: (marketId: string) => void;
}

function formatCompact(value: number) {
  return new Intl.NumberFormat('en', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);
}

function formatMetric(value: number | null | undefined, digits: number) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '--';
  }

  return value.toFixed(digits);
}

export default function MarketList({
  markets,
  selectedMarketId,
  searchQuery,
  onSearchQueryChange,
  onSelectMarket,
}: MarketListProps) {
  return (
    <aside className="panel flex min-h-[720px] flex-col overflow-hidden">
      <div className="border-b border-stone-200/80 px-5 py-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
              Market List
            </div>
            <p className="mt-1 text-sm text-stone-500">
              先选一个市场，再到右侧看盘口和信号解释。
            </p>
          </div>
          <div className="rounded-full bg-stone-100 px-3 py-1 text-xs font-medium text-stone-600">
            {markets.length} visible
          </div>
        </div>

        <div className="mt-4">
          <input
            value={searchQuery}
            onChange={(event) => onSearchQueryChange(event.target.value)}
            placeholder="搜索市场问题、slug 或 category"
            className="w-full rounded-2xl border border-stone-200 bg-stone-50 px-4 py-3 text-sm text-stone-900 outline-none transition focus:border-amber-400 focus:bg-white"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {markets.length === 0 ? (
          <div className="rounded-3xl border border-dashed border-stone-200 bg-stone-50 px-5 py-12 text-center text-sm text-stone-500">
            没有匹配的市场。可以换个关键词，或者等下一轮扫描完成。
          </div>
        ) : (
          <div className="space-y-3">
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

              return (
                <button
                  key={market.market_id}
                  onClick={() => onSelectMarket(market.market_id)}
                  className={`w-full rounded-[24px] border px-4 py-4 text-left transition ${
                    isSelected
                      ? 'border-stone-900 bg-stone-900 text-white shadow-[0_18px_40px_rgba(28,23,20,0.18)]'
                      : 'border-stone-200 bg-white/85 hover:border-amber-300 hover:bg-white'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className={`text-[15px] font-semibold leading-6 ${isSelected ? 'text-white' : 'text-stone-900'}`}>
                        {market.question}
                      </div>
                      <div className={`mt-1 text-xs ${isSelected ? 'text-stone-300' : 'text-stone-500'}`}>
                        {market.category || 'Uncategorized'}
                      </div>
                    </div>
                    <span
                      className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
                        spreadState === 'healthy'
                          ? isSelected
                            ? 'bg-emerald-500/20 text-emerald-200'
                            : 'bg-emerald-100 text-emerald-700'
                          : spreadState === 'watch'
                            ? isSelected
                              ? 'bg-amber-500/20 text-amber-100'
                              : 'bg-amber-100 text-amber-700'
                            : spreadState === 'wide'
                              ? isSelected
                                ? 'bg-rose-500/20 text-rose-100'
                                : 'bg-rose-100 text-rose-700'
                              : isSelected
                                ? 'bg-stone-700 text-stone-200'
                                : 'bg-stone-100 text-stone-600'
                      }`}
                    >
                      {spreadState === 'healthy'
                        ? 'Healthy'
                        : spreadState === 'watch'
                          ? 'Watch'
                          : spreadState === 'wide'
                            ? 'Wide'
                            : 'Waiting'}
                    </span>
                  </div>

                  <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <div className={`text-[11px] uppercase tracking-[0.12em] ${isSelected ? 'text-stone-400' : 'text-stone-400'}`}>
                        Mid Price
                      </div>
                      <div className={`mt-1 font-semibold ${isSelected ? 'text-white' : 'text-stone-900'}`}>
                        {formatMetric(feature?.mid_price, 4)}
                      </div>
                    </div>
                    <div>
                      <div className={`text-[11px] uppercase tracking-[0.12em] ${isSelected ? 'text-stone-400' : 'text-stone-400'}`}>
                        Spread
                      </div>
                      <div className={`mt-1 font-semibold ${isSelected ? 'text-white' : 'text-stone-900'}`}>
                        {typeof spread === 'number' ? `${formatMetric(spread, 1)} bps` : '--'}
                      </div>
                    </div>
                    <div>
                      <div className={`text-[11px] uppercase tracking-[0.12em] ${isSelected ? 'text-stone-400' : 'text-stone-400'}`}>
                        Liquidity
                      </div>
                      <div className={`mt-1 font-semibold ${isSelected ? 'text-white' : 'text-stone-900'}`}>
                        {formatCompact(market.liquidity_score)}
                      </div>
                    </div>
                    <div>
                      <div className={`text-[11px] uppercase tracking-[0.12em] ${isSelected ? 'text-stone-400' : 'text-stone-400'}`}>
                        Volume (1m)
                      </div>
                      <div className={`mt-1 font-semibold ${isSelected ? 'text-white' : 'text-stone-900'}`}>
                        {formatMetric(feature?.volume_1m, 0)}
                      </div>
                    </div>
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
