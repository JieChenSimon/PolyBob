'use client';

import { useCallback, useState } from 'react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { WS_BASE } from '@/lib/config';

interface MarketData {
  price: number;
  change_24h: number;
  timestamp: string;
}

export default function BTCPrediction() {
  const [marketData, setMarketData] = useState<MarketData | null>(null);
  const [loading, setLoading] = useState(true);

  const handleMessage = useCallback((data: MarketData) => {
    setMarketData(data);
    setLoading(false);
  }, []);

  const { isConnected } = useWebSocket({
    url: `${WS_BASE}/ws/market`,
    onMessage: handleMessage,
  });

  if (loading) {
    return (
      <div className="panel p-6">
        <div className="animate-pulse">
          <div className="h-4 bg-stone-200 rounded w-1/4 mb-4"></div>
          <div className="h-8 bg-stone-200 rounded w-1/2"></div>
        </div>
      </div>
    );
  }

  if (!marketData) {
    return (
      <div className="panel p-6">
        <p className="text-stone-500">No market data available</p>
      </div>
    );
  }

  const changeColor = marketData.change_24h >= 0 ? 'text-emerald-600' : 'text-rose-600';

  return (
    <div className="panel p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-stone-900">BTC Real-Time</h3>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-500' : 'bg-stone-300'}`}></span>
          <span className="text-xs text-stone-500">
            {marketData.timestamp ? new Date(marketData.timestamp).toLocaleTimeString() : ''}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div>
          <div className="text-xs text-stone-500 uppercase tracking-wider">Price</div>
          <div className="text-3xl font-bold text-stone-900">
            ${marketData.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
        </div>
        <div>
          <div className="text-xs text-stone-500 uppercase tracking-wider">24h Change</div>
          <div className={`text-2xl font-bold ${changeColor}`}>
            {marketData.change_24h >= 0 ? '+' : ''}{marketData.change_24h.toFixed(2)}%
          </div>
        </div>
      </div>
    </div>
  );
}
