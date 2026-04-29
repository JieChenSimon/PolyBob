'use client';

import { useEffect, useState } from 'react';
import { API_BASE } from '@/lib/config';
import { OverviewPayload } from '@/lib/types';

export default function PersonalBrief() {
  const [overview, setOverview] = useState<OverviewPayload | null>(null);

  useEffect(() => {
    const fetchOverview = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/overview`);
        setOverview(await response.json());
      } catch (error) {
        console.error('Failed to fetch personal brief:', error);
      }
    };

    fetchOverview();
    const interval = window.setInterval(fetchOverview, 15000);
    return () => window.clearInterval(interval);
  }, []);

  const items = overview
    ? [
        {
          title: 'Market Scan',
          value: `${overview.markets.feature_ready}/${overview.markets.tracked}`,
          detail: 'feature-ready markets to review first',
        },
        {
          title: 'Strategy Desk',
          value: `${overview.strategy_center.active_instances}`,
          detail: `${overview.strategy_center.intent_count} intents in the queue`,
        },
        {
          title: 'Risk Focus',
          value: overview.risk.alert_level,
          detail: `${overview.risk.onchain_alert_count} onchain alerts, ${overview.risk.critical_onchain_alerts} critical`,
        },
      ]
    : [];

  return (
    <section className="panel p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="eyebrow">Daily Brief</div>
          <h2 className="mt-2 text-2xl font-bold tracking-[-0.05em] text-stone-900">
            Personal Market Workbench
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-stone-600">
            聚合你今天需要先看的市场、策略意图和风险信号。核心路径只服务研究、判断、paper
            执行与复盘；实验模块留在 lab，不进入默认首页判断流。
          </p>
        </div>
        <div className="rounded-full bg-stone-100 px-3 py-1 text-xs font-medium text-stone-600">
          {overview?.system.mode || 'loading'}
        </div>
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-3">
        {items.length
          ? items.map((item) => (
              <div key={item.title} className="metric-panel">
                <div className="text-xs uppercase tracking-[0.12em] text-stone-500">{item.title}</div>
                <div className="mt-2 text-2xl font-bold tracking-[-0.04em] text-stone-900">{item.value}</div>
                <div className="mt-1 text-sm text-stone-500">{item.detail}</div>
              </div>
            ))
          : Array.from({ length: 3 }).map((_, index) => (
              <div key={index} className="metric-panel animate-pulse">
                <div className="h-3 w-24 rounded bg-stone-200" />
                <div className="mt-4 h-7 w-16 rounded bg-stone-200" />
                <div className="mt-3 h-3 w-36 rounded bg-stone-200" />
              </div>
            ))}
      </div>
    </section>
  );
}
