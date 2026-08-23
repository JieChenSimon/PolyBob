import SimulationWorkspace from '@/components/SimulationWorkspace';
import { WorkbenchPageHeader } from '@/components/WorkbenchChrome';

export default function SimulationPage() {
  return (
    <>
      <WorkbenchPageHeader
        eyebrow={{ zh: '实验交易台', en: 'Paper Trading Lab' }}
        title={{ zh: '模拟盘', en: 'Paper Trading' }}
        description={{
          zh: '用真实行情驱动真实策略信号，在 paper 资金上记录成交、费用、资金费、持仓、净值和回撤。不会发送真实订单。',
          en: 'Run real strategy signals on real market data with paper capital; record fills, fees, funding, positions, equity and drawdown. No live orders are sent.',
        }}
        tier="lab"
      />
      <main className="workbench-main">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          <span className="font-semibold">PAPER ONLY · REAL-DATA DRIVEN</span>
          <span>行情不可用、过期或策略样本不足时，系统保持 UNKNOWN，不会虚构收益。</span>
        </div>
        <SimulationWorkspace />
      </main>
    </>
  );
}
