import { Suspense } from 'react';
import BestOpportunity from '@/components/BestOpportunity';
import USEquityAdvisor from '@/components/USEquityAdvisor';
import SectionIntro from '@/components/SectionIntro';
import ForecastBatchScanner from '@/components/ForecastBatchScanner';

export default function USEquitiesPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '真实行情', en: 'Real Quotes' }}
        title={{ zh: '股票观察', en: 'Equity Monitor' }}
        description={{
          zh: '先看本类别今天最好的机会,再看行情与技术观察。单个标的的投资准则判定在该标的的子页面里。',
          en: 'Start with the best opportunity in this market, then quotes and technical context. Each instrument’s verdict lives on its own page.',
        }}
      />

      <main className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:px-8">
        {/*
          A category tab answers "which of these should I look at". The verdict
          answers "what do I do about this one" and now lives at
          /us-equities/[symbol] — it used to sit here for a hardcoded default,
          which put an instrument-level judgement in a selection's slot.
        */}
        <Suspense fallback={<div className="mb-6 h-28 rounded-xl border-l-4 border-stone-200 bg-stone-50" />}>
          <BestOpportunity
            domain="us_equity"
            title={{ zh: '美股今天该看哪一只', en: 'Which US name to look at today' }}
          />
        </Suspense>
        <Suspense fallback={null}>
          <USEquityAdvisor />
        </Suspense>
        <ForecastBatchScanner domain="us_equity" symbols={['AAPL', 'MSFT', 'NVDA', 'AMZN']} />
      </main>
    </>
  );
}
