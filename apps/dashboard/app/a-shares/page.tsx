import { Suspense } from 'react';
import USEquityAdvisor from '@/components/USEquityAdvisor';
import { WorkbenchPageHeader } from '@/components/WorkbenchChrome';

export default function ASharesPage() {
  return (
    <>
      <WorkbenchPageHeader
        eyebrow={{ zh: '核心工作区', en: 'Core Workspace' }}
        title={{ zh: 'A股', en: 'A-Shares' }}
        description={{ zh: '独立查看 A 股行情、技术观察、数据来源和研究型预测状态。', en: 'Review A-share quotes, technical context, data provenance and research forecast state in one dedicated workspace.' }}
      />
      <main className="workbench-main">
        <Suspense fallback={<div className="h-[620px] rounded border border-stone-200 bg-white" />}>
          <USEquityAdvisor initialMarket="CN" lockMarket />
        </Suspense>
      </main>
    </>
  );
}
