'use client';

import { useEffect, useState } from 'react';
import { API_BASE } from '@/lib/config';
import { OverviewPayload } from '@/lib/types';

export default function OverviewSummary() {
  const [overview, setOverview] = useState<OverviewPayload | null>(null);

  useEffect(() => {
    const fetchOverview = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/overview`);
        const data = await response.json();
        setOverview(data);
      } catch (error) {
        console.error('Failed to fetch overview:', error);
      }
    };

    fetchOverview();
    const interval = window.setInterval(fetchOverview, 8000);
    return () => window.clearInterval(interval);
  }, []);

  const cards = overview
    ? [
        {
          label: 'Markets Tracked',
          value: `${overview.markets.tracked}`,
          detail: `${overview.markets.feature_ready} feature-ready`,
        },
        {
          label: 'Strategy Templates',
          value: `${overview.strategy_center.template_count}`,
          detail: overview.strategy_center.families.join(' / ') || 'No families',
        },
        {
          label: 'Execution',
          value: overview.execution.enabled === false ? 'Lab Off' : overview.execution.running ? 'Running' : 'Stopped',
          detail:
            overview.execution.enabled === false
              ? 'BTC demo disabled in core mode'
              : `PnL ${overview.execution.pnl.toFixed(2)} (${overview.execution.pnl_pct.toFixed(2)}%)`,
        },
        {
          label: 'Risk Level',
          value: overview.risk.alert_level,
          detail: `Exposure ${overview.risk.net_exposure.toFixed(4)} / Onchain ${overview.risk.onchain_alert_count}`,
        },
      ]
    : [];

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {cards.length === 0
        ? Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="metric-panel animate-pulse">
              <div className="h-3 w-24 rounded bg-stone-200" />
              <div className="mt-4 h-8 w-28 rounded bg-stone-200" />
              <div className="mt-3 h-3 w-36 rounded bg-stone-200" />
            </div>
          ))
        : cards.map((card) => (
            <div key={card.label} className="metric-panel">
              <div className="text-xs font-medium uppercase tracking-[0.14em] text-stone-500">
                {card.label}
              </div>
              <div className="mt-3 text-3xl font-bold tracking-[-0.05em] text-stone-900">
                {card.value}
              </div>
              <div className="mt-2 text-sm text-stone-500">{card.detail}</div>
            </div>
          ))}
    </div>
  );
}
