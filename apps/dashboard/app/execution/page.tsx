import ExecutionWorkspace from '@/components/ExecutionWorkspace';
import { WorkbenchPageHeader } from '@/components/WorkbenchChrome';

export default function ExecutionPage() {
  return (
    <>
      <WorkbenchPageHeader
        eyebrow={{ zh: '核心工作区', en: 'Core Workspace' }}
        title={{ zh: '执行台', en: 'Execution' }}
        description={{ zh: '审核 Paper intent、风险门禁、Basket 状态和可追溯执行记录；真实交易能力仍由能力矩阵单独控制。', en: 'Review paper intents, risk gates, basket state and traceable execution records; live trading remains separately controlled by the capability matrix.' }}
      />
      <main className="workbench-main"><ExecutionWorkspace /></main>
    </>
  );
}
