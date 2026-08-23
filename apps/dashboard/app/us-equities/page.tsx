import { Suspense } from 'react';
import USEquityAdvisor from '@/components/USEquityAdvisor';
import AssetTerminalFrame from '@/components/AssetTerminalFrame';

export default function USEquitiesPage() {
  return (
    <>
      <main className="asset-terminal-page">
      <Suspense fallback={<div className="terminal-loading" />}>
      <AssetTerminalFrame asset="US EQUITIES" title="US Equity Market" subtitle="Quotes, chart, order-book capability and research evidence stay in one instrument context." symbol="NVDA" source="US equity providers" links={[{ href: '/us-equities?symbol=NVDA', label: 'NVDA', meta: 'Semiconductors' }, { href: '/us-equities?symbol=AAPL', label: 'AAPL', meta: 'Technology Hardware' }, { href: '/us-equities?symbol=AMD', label: 'AMD', meta: 'Semiconductors' }]}>
        <Suspense fallback={<div className="h-[620px] rounded border border-stone-200 bg-white" />}>
          <USEquityAdvisor initialMarket="US" lockMarket hideList />
        </Suspense>
      </AssetTerminalFrame>
      </Suspense>
      </main>
    </>
  );
}
