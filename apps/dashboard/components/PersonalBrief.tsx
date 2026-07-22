'use client';

import { useLanguage } from '@/lib/i18n';
import { OverviewPayload } from '@/lib/types';
import StatusBadge, { statusTone } from '@/components/ui/StatusBadge';
import LoadingSkeleton from '@/components/ui/LoadingSkeleton';

interface PersonalBriefProps {
  overview: OverviewPayload | null;
}

/**
 * "What should I look at today" — the answer sits at the top of the
 * Daily Brief with the largest visual weight (priority list), while the
 * supporting risk/market numbers stay on the right.
 */
export default function PersonalBrief({ overview }: PersonalBriefProps) {
  const { language } = useLanguage();
  const zh = language === 'zh';

  const priorities = overview ? buildPriorities(overview, zh) : [];
  const portfolioStatus = overview?.risk.portfolio_status;
  const riskItems = overview
    ? [
        {
          label: zh ? '风险级别' : 'Risk Level',
          value: portfolioStatus === 'ready'
            ? overview.risk.alert_level
            : (zh ? '未知' : 'unknown'),
        },
        {
          label: zh ? '组合账本' : 'Portfolio Ledger',
          value: (
            <StatusBadge tone={statusTone(portfolioStatus)}>
              {formatPortfolioStatus(portfolioStatus, zh)}
            </StatusBadge>
          ),
        },
        {
          label: zh ? '严重链上告警' : 'Critical Onchain',
          value: String(overview.risk.critical_onchain_alerts),
        },
      ]
    : [];
  const marketItems = overview
    ? [
        {
          label: zh ? '可复核市场' : 'Reviewable Markets',
          value: `${overview.markets.feature_ready}/${overview.markets.tracked}`,
        },
        {
          label: zh ? '最宽价差' : 'Widest Spread',
          value: typeof overview.markets.widest_spread_bps === 'number'
            ? `${overview.markets.widest_spread_bps.toFixed(1)} bps`
            : '--',
        },
        {
          label: zh ? '策略意图' : 'Strategy Intents',
          value: String(overview.strategy_center.intent_count),
        },
      ]
    : [];

  return (
    <section className="panel p-5 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-bold tracking-[-0.02em] text-stone-900">
            {zh ? '今日优先事项' : 'Top Priorities Today'}
          </h2>
          <p className="mt-1 max-w-3xl text-sm leading-5 text-stone-500">
            {zh
              ? '先看这里：需要处理的市场、策略意图和风险信号。实验模块不进入默认判断流。'
              : 'Start here: the markets, strategy intents, and risk signals that need attention. Lab modules stay outside the default flow.'}
          </p>
        </div>
        <StatusBadge tone={overview ? 'accent' : 'neutral'}>
          {overview?.system.mode || (zh ? '加载中' : 'loading')}
        </StatusBadge>
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.15fr),minmax(0,0.85fr)]">
        <div className="space-y-3">
          {overview ? priorities.map((item) => (
            <div key={item.title} className="flex gap-3 rounded-lg border border-stone-200 bg-white px-4 py-3">
              <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${item.tone}`} />
              <div className="min-w-0">
                <div className="text-[15px] font-semibold text-stone-900">{item.title}</div>
                <div className="mt-0.5 text-sm leading-5 text-stone-500">{item.detail}</div>
              </div>
            </div>
          )) : <LoadingSkeleton count={4} />}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <BriefGroup title={zh ? '风险' : 'Risk'} items={riskItems} loading={!overview} />
          <BriefGroup title={zh ? '市场与策略' : 'Markets & Strategy'} items={marketItems} loading={!overview} />
        </div>
      </div>
    </section>
  );
}

function buildPriorities(overview: OverviewPayload, zh: boolean) {
  const priorities: Array<{ title: string; detail: string; tone: string }> = [];

  if (overview.risk.portfolio_status !== 'ready') {
    priorities.push({
      title: zh ? '先接入组合账本' : 'Connect the portfolio ledger first',
      detail: zh
        ? '没有持仓和现金基线时，加仓、减仓和风险判断只能作为观察，不能作为执行依据。'
        : 'Without positions and cash as a baseline, sizing and risk calls remain observational.',
      tone: 'bg-rose-500',
    });
  }

  if (overview.risk.critical_onchain_alerts > 0) {
    priorities.push({
      title: zh ? '复核严重链上告警' : 'Review critical onchain alerts',
      detail: zh
        ? `${overview.risk.critical_onchain_alerts} 个严重告警需要在风险运营页确认来源和对手方。`
        : `${overview.risk.critical_onchain_alerts} critical alerts need source and counterparty review in Risk Ops.`,
      tone: 'bg-amber-500',
    });
  }

  if (overview.strategy_center.intent_count > 0) {
    priorities.push({
      title: zh ? '处理策略意图队列' : 'Process strategy intents',
      detail: zh
        ? `${overview.strategy_center.intent_count} 个 intent 等待提交、拒绝或复盘。`
        : `${overview.strategy_center.intent_count} intents are waiting for submit, reject, or review.`,
      tone: 'bg-sky-500',
    });
  }

  if (overview.markets.feature_ready > 0) {
    priorities.push({
      title: zh ? '查看可用特征市场' : 'Review feature-ready markets',
      detail: zh
        ? `${overview.markets.feature_ready} 个市场已有盘口特征，优先看价差、深度和异常变化。`
        : `${overview.markets.feature_ready} markets have order-book features ready for spread, depth, and anomaly review.`,
      tone: 'bg-emerald-500',
    });
  }

  return priorities.length ? priorities.slice(0, 4) : [{
    title: zh ? '等待下一轮市场扫描' : 'Waiting for the next market scan',
    detail: zh ? '当前没有需要立即处理的市场、策略或风险事项。' : 'There are no urgent market, strategy, or risk items right now.',
    tone: 'bg-stone-400',
  }];
}

function BriefGroup({
  title,
  items,
  loading,
}: {
  title: string;
  items: Array<{ label: string; value: React.ReactNode }>;
  loading: boolean;
}) {
  return (
    <div className="rounded-lg border border-stone-200 bg-stone-50/60 p-4">
      <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-stone-500">{title}</div>
      <div className="mt-3 space-y-3">
        {loading ? <LoadingSkeleton count={3} /> : items.map((item) => (
          <div key={item.label} className="flex items-center justify-between gap-4 text-sm">
            <span className="text-stone-500">{item.label}</span>
            <span className="font-semibold text-stone-900">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatPortfolioStatus(status: OverviewPayload['risk']['portfolio_status'] | undefined, zh: boolean) {
  if (status === 'ready') {
    return zh ? '已就绪' : 'ready';
  }
  if (status === 'stale') {
    return zh ? '已过期' : 'stale';
  }
  if (status === 'error') {
    return zh ? '错误' : 'error';
  }
  return zh ? '未配置' : 'not configured';
}
