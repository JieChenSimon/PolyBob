import { Suspense } from 'react';
import BestOpportunity from '@/components/BestOpportunity';
import GlobalSentimentPanel from '@/components/GlobalSentimentPanel';
import MarketNewsTerminal from '@/components/MarketNewsTerminal';
import MarketsWorkspace from '@/components/MarketsWorkspace';
import SectionIntro from '@/components/SectionIntro';

export default function MarketsPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '核心路径', en: 'Core Path' }}
        title={{ zh: '市场观察', en: 'Markets' }}
        description={{
          zh: '实时市场消息与跨资产影响分析;watchlist、盘口特征、信号和异常。单个标的的投资准则判定在该标的的子页面里。',
          en: 'Real-time market wire with cross-asset impact analysis. Each instrument’s verdict lives on its own page.',
        }}
      />

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
      </main>
    </>
  );
}
