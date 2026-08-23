import { Suspense } from 'react';
import USEquityAdvisor from '@/components/USEquityAdvisor';
import AssetTerminalFrame from '@/components/AssetTerminalFrame';

export default function ASharesPage() {
  return (
    <>
      <main className="asset-terminal-page">
        <Suspense fallback={<div className="terminal-loading" />}>
        <AssetTerminalFrame asset="A-SHARES" title="A-Share Market" subtitle="A-share quote freshness, chart context and research-only technical evidence." symbol="600519" source="Sina A-share" links={[{ href: '/a-shares?symbol=600519', label: '600519', meta: '贵州茅台' }, { href: '/a-shares?symbol=000858', label: '000858', meta: '五粮液' }, { href: '/a-shares?symbol=601318', label: '601318', meta: '中国平安' }]}>
          <Suspense fallback={<div className="h-[620px] rounded border border-stone-200 bg-white" />}>
          <USEquityAdvisor initialMarket="CN" lockMarket hideList />
          </Suspense>
        </AssetTerminalFrame>
        </Suspense>
      </main>
    </>
  );
}
