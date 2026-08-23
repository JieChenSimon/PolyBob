import { Suspense } from 'react';
import USEquityAdvisor from '@/components/USEquityAdvisor';
import AssetTerminalFrame from '@/components/AssetTerminalFrame';

export default function ASharesPage() {
  return (
    <>
      <main className="asset-terminal-page">
        <Suspense fallback={<div className="terminal-loading" />}>
        <AssetTerminalFrame asset="A-SHARES" title="A-Share Market" subtitle="A-share quote freshness, chart context and research-only technical evidence." symbol="600519.SH" source="Sina A-share" links={[{ href: '/a-shares?symbol=600519.SH', label: '600519.SH', meta: '贵州茅台' }, { href: '/a-shares?symbol=000858.SZ', label: '000858.SZ', meta: '五粮液' }, { href: '/a-shares?symbol=601318.SH', label: '601318.SH', meta: '中国平安' }]}>
          <Suspense fallback={<div className="h-[620px] rounded border border-stone-200 bg-white" />}>
          <USEquityAdvisor initialMarket="CN" lockMarket hideList />
          </Suspense>
        </AssetTerminalFrame>
        </Suspense>
      </main>
    </>
  );
}
