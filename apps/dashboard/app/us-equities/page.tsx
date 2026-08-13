import { Suspense } from 'react';
import USEquityAdvisor from '@/components/USEquityAdvisor';

export default function USEquitiesPage() {
  return (
    <main className="mx-auto w-full max-w-shell px-5 pb-10 pt-4 md:px-8">
      <header className="mb-3 flex flex-wrap items-end justify-between gap-2 border-b border-stone-200 pb-3">
        <div>
          <div className="mono text-[10px] font-semibold uppercase tracking-wide text-sky-700">US / CN EQUITY WORKBENCH</div>
          <h1 className="mt-1 text-xl font-semibold text-stone-950">股票研究工作台</h1>
        </div>
        <p className="max-w-2xl text-xs leading-5 text-stone-500">
          股票池负责选择，右侧只分析当前标的；行情来源、时效、技术观察与 Kronos Lab 状态保持在同一工作面。
        </p>
      </header>
      <Suspense fallback={<div className="h-[620px] rounded border border-stone-200 bg-white" />}>
        <USEquityAdvisor />
      </Suspense>
    </main>
  );
}
