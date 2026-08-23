import { Suspense } from 'react';
import USEquityAdvisor from '@/components/USEquityAdvisor';
import { WorkbenchPageHeader } from '@/components/WorkbenchChrome';

export default function USEquitiesPage() {
  return (
    <>
      <WorkbenchPageHeader eyebrow={{ zh: '核心工作区', en: 'Core Workspace' }} title={{ zh: '股票观察', en: 'Equities' }} description={{ zh: '股票池负责选择，当前标的联动行情、技术观察、数据来源和实验边界。', en: 'Select an instrument and keep quotes, technical context, data provenance and lab boundaries linked.' }} />
      <main className="workbench-main">
      <Suspense fallback={<div className="h-[620px] rounded border border-stone-200 bg-white" />}>
        <USEquityAdvisor />
      </Suspense>
      </main>
    </>
  );
}
