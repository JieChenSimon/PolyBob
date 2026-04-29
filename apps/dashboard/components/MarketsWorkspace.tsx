'use client';

import { useEffect, useState } from 'react';
import MarketDetail from '@/components/MarketDetail';
import MarketList from '@/components/MarketList';
import { API_BASE } from '@/lib/config';
import { DashboardMarket, MarketFeatures } from '@/lib/types';

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
  const [markets, setMarkets] = useState<DashboardMarket[]>([]);
  const [selectedMarketId, setSelectedMarketId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    const fetchMarkets = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/dashboard/markets`);
        const payload = await response.json();

        const nextMarkets = Array.isArray(payload.markets)
          ? payload.markets
              .filter(isDashboardMarket)
              .map((market: RawDashboardMarket) => ({
                ...market,
                features: isMarketFeatures(market.features) ? market.features : null,
              }))
          : [];

        setMarkets(nextMarkets);
        setSelectedMarketId((previous) => previous || nextMarkets[0]?.market_id || null);
      } catch (error) {
        console.error('Failed to fetch markets:', error);
      }
    };

    fetchMarkets();
    const interval = window.setInterval(fetchMarkets, 8000);
    return () => window.clearInterval(interval);
  }, []);

  const visibleMarkets = markets.filter((market) => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    if (!normalizedQuery) {
      return true;
    }

    return [market.question, market.slug, market.category || '']
      .join(' ')
      .toLowerCase()
      .includes(normalizedQuery);
  });

  const selectedMarket =
    visibleMarkets.find((market) => market.market_id === selectedMarketId) ||
    markets.find((market) => market.market_id === selectedMarketId) ||
    null;

  return (
    <div className="grid gap-6 xl:grid-cols-[380px,minmax(0,1fr)]">
      <MarketList
        markets={visibleMarkets}
        selectedMarketId={selectedMarketId}
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        onSelectMarket={setSelectedMarketId}
      />

      <MarketDetail market={selectedMarket} />
    </div>
  );
}
