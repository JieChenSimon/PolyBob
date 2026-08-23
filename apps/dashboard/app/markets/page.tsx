import { Suspense } from 'react';
import BestOpportunity from '@/components/BestOpportunity';
import GlobalSentimentPanel from '@/components/GlobalSentimentPanel';
import MarketNewsTerminal from '@/components/MarketNewsTerminal';
import MarketsWorkspace from '@/components/MarketsWorkspace';
import ForecastBatchScanner from '@/components/ForecastBatchScanner';
import { WorkbenchPageHeader } from '@/components/WorkbenchChrome';

export default function MarketsPage() {
  return (
    <>
      <WorkbenchPageHeader eyebrow={{ zh: '核心工作区', en: 'Core Workspace' }} title={{ zh: '市场观察', en: 'Markets' }} description={{ zh: '快速筛选值得复核的市场，再联动查看行情、盘口、证据和数据可信度。', en: 'Triage markets worth reviewing, then inspect quotes, order book, evidence and data trust in one workspace.' }} />

      <main className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:mt-8 md:px-8">
        <Suspense fallback={<div className="mb-6 h-28 rounded-xl border-l-4 border-stone-200 bg-stone-50" />}>
          <BestOpportunity
            domain="a_share"
            title={{ zh: 'A股今天要回避哪些', en: 'Which A-shares to avoid today' }}
          />
        </Suspense>
        <GlobalSentimentPanel />
        <MarketNewsTerminal />
        <MarketsWorkspace />
        <ForecastBatchScanner domain="a_share" symbols={['600519', '000858', '601318', '300750']} />
      </main>
    </>
  );
}
