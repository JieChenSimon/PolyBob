'use client';

import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import ErrorState from '@/components/ui/ErrorState';
import LoadingSkeleton from '@/components/ui/LoadingSkeleton';
import MarketDetail from '@/components/MarketDetail';
import MarketList from '@/components/MarketList';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';
import { DashboardMarket, MarketFeatures } from '@/lib/types';
import DataTrustBar from '@/components/ui/DataTrustBar';

type RawDashboardMarket = Omit<DashboardMarket, 'features'> & { features: unknown };

function isMarketFeatures(value: unknown): value is MarketFeatures {
  if (!value || typeof value !== 'object') {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.market_id === 'string' &&
    typeof candidate.timestamp === 'string' &&
    typeof candidate.mid_price === 'number' &&
    typeof candidate.spread_bps === 'number' &&
    typeof candidate.bid_price === 'number' &&
    typeof candidate.ask_price === 'number' &&
    typeof candidate.bid_size === 'number' &&
    typeof candidate.ask_size === 'number' &&
    typeof candidate.depth_imbalance === 'number' &&
    typeof candidate.trade_intensity_1m === 'number' &&
    typeof candidate.volume_1m === 'number' &&
    typeof candidate.price_jump_score === 'number'
  );
}

function isDashboardMarket(value: unknown): value is RawDashboardMarket {
  if (!value || typeof value !== 'object') {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.market_id === 'string' &&
    typeof candidate.gamma_market_id === 'string' &&
    typeof candidate.slug === 'string' &&
    typeof candidate.question === 'string' &&
    typeof candidate.liquidity_score === 'number'
  );
}

export default function MarketsWorkspace() {
  const [selectedMarketId, setSelectedMarketId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const { language } = useLanguage();
  const zh = language === 'zh';

  const marketsQuery = useQuery<DashboardMarket[]>({
    queryKey: ['dashboard', 'markets'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/dashboard/markets`, { signal });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      return Array.isArray(payload.markets)
        ? payload.markets
            .filter(isDashboardMarket)
            .map((market: RawDashboardMarket) => ({
              ...market,
              features: isMarketFeatures(market.features) ? market.features : null,
            }))
        : [];
    },
    refetchInterval: 15_000,
    staleTime: 12_000,
  });
  const marketsData = marketsQuery.data;
  const markets = useMemo(() => marketsData ?? [], [marketsData]);

  useEffect(() => {
    setSelectedMarketId((previous) => previous || markets[0]?.market_id || null);
  }, [markets]);

  const visibleMarkets = useMemo(() => markets.filter((market) => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    if (!normalizedQuery) {
      return true;
    }

    return [market.question, market.slug, market.category || '']
      .join(' ')
      .toLowerCase()
      .includes(normalizedQuery);
  }), [markets, searchQuery]);

  const selectedMarket =
    visibleMarkets.find((market) => market.market_id === selectedMarketId) ||
    markets.find((market) => market.market_id === selectedMarketId) ||
    null;

  if (marketsQuery.isLoading && markets.length === 0) {
    return (
      <div aria-busy="true" aria-live="polite">
        <LoadingSkeleton variant="rows" count={6} />
      </div>
    );
  }

  return (
    <>
      {marketsQuery.isError ? (
        <ErrorState
          className="mb-5"
          title={zh ? '市场数据加载失败' : 'Failed to load markets'}
          message={zh ? '无法连接 PolyBob API，watchlist 暂时为空。' : 'Cannot reach the PolyBob API; the watchlist is empty for now.'}
          onRetry={() => void marketsQuery.refetch()}
          retryLabel={zh ? '重试' : 'Retry'}
        />
      ) : null}
    <div className="grid gap-6 xl:grid-cols-[380px,minmax(0,1fr)]">
      <div className="xl:col-span-2">
        <DataTrustBar
          source="Polymarket"
          observedAt={selectedMarket?.features?.timestamp}
          state={marketsQuery.isError ? 'degraded' : marketsQuery.data ? 'available' : 'unknown'}
          reason={marketsQuery.isError ? (zh ? '市场观察接口不可用' : 'Market observation API unavailable') : null}
        />
      </div>
      <div className="order-2 xl:order-1">
        <MarketList
          markets={visibleMarkets}
          selectedMarketId={selectedMarketId}
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          onSelectMarket={setSelectedMarketId}
        />
      </div>

      <div className="order-1 xl:order-2">
        <MarketDetail market={selectedMarket} />
      </div>
    </div>
    </>
  );
}
