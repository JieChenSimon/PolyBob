import OverviewWorkspace from '@/components/OverviewWorkspace';
import AccountPanel from '@/components/AccountPanel';
import EdgeScoreboard from '@/components/EdgeScoreboard';
import TodaysEdges from '@/components/TodaysEdges';
import { WorkbenchPageHeader } from '@/components/WorkbenchChrome';
import PendingActionsPanel from '@/components/PendingActionsPanel';

export default function OverviewPage() {
  return (
    <>
      <WorkbenchPageHeader
        eyebrow={{ zh: '核心工作区', en: 'Core Workspace' }}
        title={{ zh: '每日简报', en: 'Daily Brief' }}
        description={{
          zh: '先看今天哪些标的触发了已验证的边，再看记分牌、市场与风险；实验模块不占用首页判断流。',
          en: 'Start with where today’s validated edges are firing, then the scoreboard, markets and risk.',
        }}
      />

      <main className="mx-auto mt-4 w-full max-w-shell px-5 pb-10 md:mt-5 md:px-8">
        {/* Opportunities before inventory. The scoreboard says which edges
            exist; this says where they are firing today, and for an event edge
            that is the only actionable form — the US edge fires on ~5 tickers a
            day out of thousands, so a "type a symbol and I will tell you no"
            workflow requires you to already know the answer. */}
        <TodaysEdges />
        <PendingActionsPanel />
        <EdgeScoreboard />
        <AccountPanel />
        <OverviewWorkspace />
      </main>
    </>
  );
}
