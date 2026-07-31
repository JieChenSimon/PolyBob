'use client';

import { useQuery } from '@tanstack/react-query';
import ErrorState from '@/components/ui/ErrorState';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

interface EdgeRecord {
  strategy: string;
  instrument: string;
  approved: boolean;
  win_rate: number | null;
  total_return: number | null;
  t_stat?: number | null;
  n?: number | null;
  implementation?: string;
  evidence?: string;
  failed: string[];
}

interface BoardPayload {
  records: EdgeRecord[];
  promoted: string[];
  total: number;
  require_strategy_promotion: boolean;
}

const STRATEGY_LABEL: Record<string, { zh: string; en: string }> = {
  a_share_billboard_reversal: { zh: 'A股 · 龙虎榜反转', en: 'A-share · Dragon-tiger reversal' },
  us_insider_cluster_buy: { zh: '美股 · 内部人集群买入', en: 'US · Insider cluster buy' },
  altcoin_retail_crowding: { zh: '山寨币 · 散户拥挤', en: 'Altcoin · Retail crowding' },
};

const IMPLEMENTATION_LABEL: Record<string, { zh: string; en: string }> = {
  avoidance_filter_only_no_shorting: { zh: '回避过滤器(A股难做空)', en: 'Avoidance filter (no shorting)' },
  long_after_cluster_filing: { zh: '做多(申报公开后)', en: 'Long after filing' },
  avoid_or_short_when_retail_crowded_long: { zh: '回避/做空(散户拥挤时)', en: 'Avoid/short when crowded' },
};

/**
 * The project's scoreboard: which edges cleared the promotion gate on real data,
 * with the win rate and mean excess return that are the north-star metrics.
 * Deliberately shows the direction of each edge — two of the three are avoidance
 * signals, not long trades, and presenting them as returns alone would mislead.
 */
export default function EdgeScoreboard() {
  const { language } = useLanguage();
  const zh = language === 'zh';

  const query = useQuery<BoardPayload>({
    queryKey: ['promotion-board'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/strategies/promotion-board`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return (await response.json()) as BoardPayload;
    },
    refetchInterval: 300_000,
    staleTime: 240_000,
  });

  const approved = (query.data?.records ?? []).filter((r) => r.approved);

  return (
    <section
      aria-label={zh ? '策略记分牌' : 'Edge scoreboard'}
      className="panel mb-6 overflow-hidden"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-200 px-5 py-4">
        <div>
          <div className="eyebrow">{zh ? '核心记分牌' : 'Scoreboard'}</div>
          <h2 className="mt-0.5 text-lg font-bold tracking-[-0.02em] text-stone-900">
            {zh ? '已验证的策略优势' : 'Validated Edges'}
          </h2>
        </div>
        <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
          {approved.length} {zh ? '个已通过门禁' : 'passed the gate'}
        </span>
      </div>

      {query.isError ? (
        <ErrorState
          className="m-5"
          title={zh ? '记分牌加载失败' : 'Failed to load scoreboard'}
          message={zh ? '无法连接 PolyBob API。' : 'Cannot reach the PolyBob API.'}
          onRetry={() => void query.refetch()}
          retryLabel={zh ? '重试' : 'Retry'}
        />
      ) : null}

      {!query.isError && approved.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-stone-400" aria-live="polite">
          {query.isLoading
            ? (zh ? '加载中…' : 'Loading…')
            : (zh ? '暂无通过门禁的策略' : 'No promoted edges yet')}
        </div>
      ) : (
        <ul className="divide-y divide-stone-100">
          {approved.map((record) => {
            const label = STRATEGY_LABEL[record.strategy];
            const impl = record.implementation ? IMPLEMENTATION_LABEL[record.implementation] : null;
            const ret = record.total_return ?? 0;
            const positive = ret > 0;
            return (
              <li key={`${record.strategy}-${record.instrument}`} className="px-5 py-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-[15px] font-semibold text-stone-900">
                    {label ? (zh ? label.zh : label.en) : record.strategy}
                  </span>
                  <span
                    className={`font-mono text-lg font-bold ${
                      positive ? 'text-emerald-600' : 'text-rose-600'
                    }`}
                  >
                    {positive ? '+' : ''}
                    {(ret * 100).toFixed(2)}%
                  </span>
                </div>

                <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-stone-500">
                  <span>
                    {zh ? '胜率 ' : 'Win '}
                    <span className="font-mono font-semibold text-stone-700">
                      {record.win_rate !== null ? `${(record.win_rate * 100).toFixed(1)}%` : '—'}
                    </span>
                  </span>
                  <span>
                    {zh ? '样本 ' : 'n = '}
                    <span className="font-mono font-semibold text-stone-700">
                      {record.n?.toLocaleString() ?? '—'}
                    </span>
                  </span>
                  {record.t_stat != null ? (
                    <span>
                      t ={' '}
                      <span className="font-mono font-semibold text-stone-700">
                        {record.t_stat.toFixed(2)}
                      </span>
                    </span>
                  ) : null}
                </div>

                {impl ? (
                  <span className="mt-2 inline-block rounded border border-sky-200 bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-700">
                    {zh ? impl.zh : impl.en}
                  </span>
                ) : null}

                {record.evidence ? (
                  <p className="mt-1.5 text-[11px] leading-5 text-stone-400">{record.evidence}</p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      <p className="border-t border-stone-200 px-5 py-2.5 text-[11px] leading-5 text-stone-500">
        {zh
          ? '说明:负收益的两项是「回避信号」——它们的价值在于避开陷阱,而非做空。全部基于真实数据、事前预注册假设、并通过多重检验校正后的 t 门槛。'
          : 'Note: the two negative rows are avoidance signals — their value is sidestepping a trap, not shorting. All measured on real data with pre-registered hypotheses and a multiple-testing-corrected t-hurdle.'}
      </p>
    </section>
  );
}
