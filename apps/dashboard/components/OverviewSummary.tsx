'use client';

import { useLanguage } from '@/lib/i18n';
import { OverviewPayload } from '@/lib/types';
import { formatNumber, formatSigned } from '@/lib/format';
import StatTile, { type StatTone } from '@/components/ui/StatTile';
import StatusBadge from '@/components/ui/StatusBadge';
import LoadingSkeleton from '@/components/ui/LoadingSkeleton';
import FreshnessBadge from '@/components/ui/FreshnessBadge';

interface OverviewSummaryProps {
  overview: OverviewPayload | null;
}

export default function OverviewSummary({ overview }: OverviewSummaryProps) {
  const { language } = useLanguage();
  const zh = language === 'zh';

  if (!overview) {
    return <LoadingSkeleton variant="tiles" count={4} />;
  }

  const portfolioConfigured = overview.risk.portfolio_status === 'ready';
  const pnl = overview.execution.pnl;
  const pnlTone: StatTone = !portfolioConfigured
    ? 'muted'
    : typeof pnl === 'number' && pnl !== 0
      ? pnl > 0 ? 'positive' : 'negative'
      : 'default';

  const cards: Array<{
    label: string;
    value: string;
    detail: string;
    tone?: StatTone;
    badge?: React.ReactNode;
  }> = [
    {
      label: zh ? '跟踪市场' : 'Markets Tracked',
      value: `${overview.markets.tracked}`,
      detail: zh ? `${overview.markets.feature_ready} 个特征可用` : `${overview.markets.feature_ready} feature-ready`,
    },
    {
      label: zh ? '策略模板' : 'Strategy Templates',
      value: `${overview.strategy_center.template_count}`,
      detail: overview.strategy_center.families.join(' / ') || (zh ? '暂无分类' : 'No families'),
    },
    {
      label: zh ? '执行' : 'Execution',
      value: !portfolioConfigured
        ? (zh ? '组合未配置' : 'No Portfolio')
        : overview.execution.enabled === false
          ? (zh ? '实验关闭' : 'Lab Off')
          : overview.execution.running
            ? (zh ? '运行中' : 'Running')
            : (zh ? '已停止' : 'Stopped'),
      detail: !portfolioConfigured
        ? (zh ? '未接入真实组合账本，盈亏未知' : 'No real portfolio ledger; PnL unknown')
        : overview.execution.enabled === false
          ? (zh ? '核心执行链路未启用' : 'Core execution path is disabled')
          : `${zh ? '盈亏' : 'PnL'} ${formatSigned(pnl, 2)} (${formatNumber(overview.execution.pnl_pct, 2)}%)`,
      tone: pnlTone,
      badge: !portfolioConfigured
        ? <StatusBadge tone="neutral">{zh ? '未配置' : 'not configured'}</StatusBadge>
        : undefined,
    },
    {
      label: zh ? '风险等级' : 'Risk Level',
      value: !portfolioConfigured ? (zh ? '未知' : 'Unknown') : overview.risk.alert_level,
      detail: `${zh ? '暴露' : 'Exposure'} ${formatNumber(overview.risk.net_exposure, 4)} / ${zh ? '链上' : 'Onchain'} ${overview.risk.onchain_alert_count}`,
      tone: !portfolioConfigured ? 'muted' : undefined,
      badge: !portfolioConfigured
        ? <StatusBadge tone="warn">{zh ? '数据不足' : 'insufficient'}</StatusBadge>
        : undefined,
    },
  ];

  return (
    <section aria-label={zh ? '系统概览' : 'System overview'}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="eyebrow">{zh ? '系统快照' : 'System Snapshot'}</div>
        <FreshnessBadge
          source="PolyBob API"
          timestamp={overview.system.timestamp}
          status={overview.system.api_connected ? undefined : 'unavailable'}
          freshMs={20_000}
          staleMs={60_000}
          language={zh ? 'zh' : 'en'}
        />
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <StatTile
            key={card.label}
            label={card.label}
            value={card.value}
            detail={card.detail}
            tone={card.tone}
            badge={card.badge}
          />
        ))}
      </div>
    </section>
  );
}
