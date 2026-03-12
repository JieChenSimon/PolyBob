'use client';

import { useEffect, useState } from 'react';
import Header from '@/components/Header';
import MarketList from '@/components/MarketList';
import MarketDetail from '@/components/MarketDetail';

export interface MarketFeatures {
  market_id: string;
  timestamp: string;
  mid_price: number;
  spread_bps: number;
  bid_price: number;
  ask_price: number;
  bid_size: number;
  ask_size: number;
  depth_imbalance: number;
  trade_intensity_1m: number;
  volume_1m: number;
  price_jump_score: number;
}

export interface DashboardMarket {
  market_id: string;
  gamma_market_id: string;
  slug: string;
  question: string;
  category: string | null;
  status: string;
  end_time: string | null;
  liquidity_score: number;
  primary_asset_id: string | null;
  features: MarketFeatures | null;
}

type RawDashboardMarket = Omit<DashboardMarket, 'features'> & { features: unknown };

const API_BASE = 'http://localhost:8000';

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

export default function Home() {
  const [markets, setMarkets] = useState<DashboardMarket[]>([]);
  const [selectedMarketId, setSelectedMarketId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  useEffect(() => {
    const fetchDashboard = async () => {
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

        setMarkets((previous) => {
          const previousSnapshot = JSON.stringify(previous);
          const nextSnapshot = JSON.stringify(nextMarkets);
          return previousSnapshot === nextSnapshot ? previous : nextMarkets;
        });
        setIsConnected(true);
        setLastUpdate(new Date());

        setSelectedMarketId((previous) => previous || nextMarkets[0]?.market_id || null);
      } catch (error) {
        console.error('Failed to fetch dashboard data:', error);
        setIsConnected(false);
      }
    };

    fetchDashboard();
    const interval = window.setInterval(fetchDashboard, 8000);
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

  const featureCount = markets.filter((market) => market.features).length;

  return (
    <div className="min-h-screen pb-10">
      <Header
        isConnected={isConnected}
        lastUpdate={lastUpdate}
        marketCount={markets.length}
        featureCount={featureCount}
      />

      <main className="mx-auto mt-6 grid w-full max-w-[1380px] gap-6 px-5 md:mt-8 md:px-8 xl:grid-cols-[380px,minmax(0,1fr)]">
        <MarketList
          markets={visibleMarkets}
          selectedMarketId={selectedMarketId}
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          onSelectMarket={setSelectedMarketId}
        />

        <MarketDetail market={selectedMarket} />
      </main>
    </div>
  );
}
