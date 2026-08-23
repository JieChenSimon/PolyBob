import RiskOpsOverview from '@/components/RiskOpsOverview';
import { WorkbenchPageHeader } from '@/components/WorkbenchChrome';

export default function RiskOpsPage() {
  return (
    <>
      <WorkbenchPageHeader
        eyebrow={{ zh: '运营工作区', en: 'Operations Workspace' }}
        title={{ zh: '风险运营', en: 'Risk Ops' }}
        description={{ zh: '集中查看组合账本、数据源、链上告警、执行残余和服务健康；未知状态不会被解释为空风险。', en: 'Monitor portfolio ledger, data sources, onchain alerts, execution residuals and service health; unknown never means no risk.' }}
      />
      <main className="workbench-main"><RiskOpsOverview /></main>
    </>
  );
}
