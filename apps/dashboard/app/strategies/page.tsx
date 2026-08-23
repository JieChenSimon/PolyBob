import StrategyCatalog from '@/components/StrategyCatalog';
import { WorkbenchPageHeader } from '@/components/WorkbenchChrome';

export default function StrategiesPage() {
  return (
    <>
      <WorkbenchPageHeader
        eyebrow={{ zh: '核心工作区', en: 'Core Workspace' }}
        title={{ zh: '策略中心', en: 'Strategies' }}
        description={{ zh: '查看策略版本、证据门禁、运行实例和决策来源；实验策略不会自动获得执行权限。', en: 'Review strategy versions, evidence gates, runtime instances and decision lineage; lab strategies never inherit execution permission.' }}
      />
      <main className="workbench-main"><StrategyCatalog /></main>
    </>
  );
}
