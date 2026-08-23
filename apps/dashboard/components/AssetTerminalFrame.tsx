'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import DataTrustBar, { type DataTrustState } from '@/components/ui/DataTrustBar';
import { useLanguage } from '@/lib/i18n';
import { useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { API_BASE } from '@/lib/config';

export interface TerminalLink {
  href: string;
  label: string;
  meta?: string;
}

export default function AssetTerminalFrame({
  asset,
  title,
  subtitle,
  symbol,
  links,
  source,
  state = 'unknown',
  children,
}: {
  asset: string;
  title: string;
  subtitle: string;
  symbol?: string;
  links: TerminalLink[];
  source: string;
  state?: DataTrustState;
  children: ReactNode;
}) {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const searchParams = useSearchParams();
  const querySymbol = searchParams?.get('symbol');
  const activeSymbol = (querySymbol || symbol || title).toUpperCase();
  const capabilitiesQuery = useQuery<{ rows?: Array<{ capability_id: string; state: DataTrustState; truth?: string }> }>({
    queryKey: ['asset-terminal-capabilities'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/capabilities`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    staleTime: 20_000,
    refetchInterval: 30_000,
  });
  const capabilities = capabilitiesQuery.data?.rows ?? [];
  const paperExecution = capabilities.find((item) => item.capability_id === 'paper_execution');
  const researchRuntime = capabilities.find((item) => item.capability_id === 'strategy_runtime');
  return (
    <section className="terminal-frame">
      <div className="terminal-frame-topbar">
        <div className="terminal-breadcrumb">
          <span className="terminal-kicker">{asset}</span>
          <span className="terminal-divider">/</span>
          <strong>{activeSymbol}</strong>
        </div>
        <div className="terminal-top-actions">
          <span className="terminal-mode">{zh ? '研究工作台' : 'RESEARCH WORKSPACE'}</span>
          <Link href={`/simulation?symbol=${encodeURIComponent(activeSymbol)}`} className="terminal-action">
            {zh ? '开启模拟' : 'Paper test'}
          </Link>
          <Link href="/settings" className="terminal-action">{zh ? '边界' : 'Boundaries'}</Link>
        </div>
      </div>

      <div className="terminal-instrument-bar">
        <div>
          <div className="terminal-title-row">
            <h2>{title}</h2>
            {activeSymbol ? <span className="terminal-symbol">{activeSymbol}</span> : null}
          </div>
          <p>{subtitle}</p>
        </div>
        <DataTrustBar source={source} state={state} />
      </div>

      <div className="terminal-layout">
        <aside className="terminal-watchlist" aria-label={zh ? '标的队列' : 'Instrument queue'}>
          <div className="terminal-section-label">{zh ? '标的队列' : 'MARKET QUEUE'}</div>
          <div className="terminal-queue-tabs">
            <span className="active">{zh ? '关注' : 'Watch'}</span>
            <span>{zh ? '最近' : 'Recent'}</span>
          </div>
          <div className="terminal-link-list">
            {links.map((item, index) => {
              const itemSymbol = new URL(item.href, 'http://polybob.local').searchParams.get('symbol')?.toUpperCase();
              const selected = itemSymbol ? itemSymbol === activeSymbol : index === 0;
              return (
              <Link key={item.href} href={item.href} className={`terminal-link-row ${selected ? 'selected' : ''}`}>
                <span>
                  <strong>{item.label}</strong>
                  {item.meta ? <small>{item.meta}</small> : null}
                </span>
                <span className="terminal-chevron">›</span>
              </Link>
              );
            })}
          </div>
          <div className="terminal-queue-note">
            {zh ? '选择标的后，中心区域保持图表、盘口和研究证据同步。' : 'Select an instrument to keep chart, book and research evidence in one context.'}
          </div>
        </aside>

        <main className="terminal-main">{children}</main>

        <aside className="terminal-dock">
          <div className="terminal-section-label">{zh ? '研究与风险' : 'RESEARCH & RISK'}</div>
          <div className="terminal-dock-card">
            <div className="terminal-card-label">{activeSymbol} · {zh ? '研究门禁' : 'RESEARCH GATE'}</div>
            <strong className="terminal-unknown">{researchRuntime?.state?.toUpperCase() || 'UNKNOWN'}</strong>
            <p>{researchRuntime?.truth || (zh ? '尚无标的级样本外校准结论。' : 'No instrument-level out-of-sample calibration is available.')}</p>
          </div>
          <div className="terminal-dock-card">
            <div className="terminal-card-label">{activeSymbol} · {zh ? '执行权限' : 'EXECUTION PERMISSION'}</div>
            <strong className={paperExecution?.state === 'available' ? 'terminal-available' : 'terminal-blocked'}>{paperExecution?.state?.toUpperCase() || (zh ? '已阻断' : 'BLOCKED')}</strong>
            <p>{paperExecution?.truth || (zh ? '研究页面不会自动获得交易权限。' : 'Research pages never inherit execution permission.')}</p>
          </div>
          <div className="terminal-dock-card terminal-dock-muted">
            <div className="terminal-card-label">{zh ? '页面结构' : 'WORKSPACE MODEL'}</div>
            <p>{zh ? '图表 · 盘口 · 证据 · 风险 · 账本' : 'Chart · book · evidence · risk · ledger'}</p>
          </div>
        </aside>
      </div>
    </section>
  );
}
