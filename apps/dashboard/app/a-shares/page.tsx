import { Suspense } from 'react';
import USEquityAdvisor from '@/components/USEquityAdvisor';
import { WorkbenchPageHeader } from '@/components/WorkbenchChrome';
import AssetTerminalFrame from '@/components/AssetTerminalFrame';

export default function ASharesPage() {
  return (
    <>
      <WorkbenchPageHeader
        eyebrow={{ zh: '核心工作区', en: 'Core Workspace' }}
        title={{ zh: 'A股', en: 'A-Shares' }}
        description={{ zh: '独立查看 A 股行情、技术观察、数据来源和研究型预测状态。', en: 'Review A-share quotes, technical context, data provenance and research forecast state in one dedicated workspace.' }}
      />
      <main className="workbench-main">
        <AssetTerminalFrame asset="A-SHARES" title="A-Share Market" subtitle="A-share quote freshness, chart context and research-only technical evidence." symbol="600519" source="Sina A-share" links={[{ href: '/a-shares?symbol=600519', label: '600519', meta: '贵州茅台' }, { href: '/a-shares?symbol=000858', label: '000858', meta: '五粮液' }, { href: '/a-shares?symbol=601318', label: '601318', meta: '中国平安' }]}>
          <Suspense fallback={<div className="h-[620px] rounded border border-stone-200 bg-white" />}>
          <USEquityAdvisor initialMarket="CN" lockMarket />
          </Suspense>
        </AssetTerminalFrame>
      </main>
    </>
  );
}
