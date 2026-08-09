'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import ErrorState from '@/components/ui/ErrorState';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';
import { instrumentHref } from '@/lib/instrument';

interface FiringInstrument {
  symbol: string;
  name?: string;
  status: string;
  direction: string | null;
  fired_on: string | null;
  evidence_zh: string;
  evidence_en: string;
}

interface Coverage {
  complete: boolean;
  days_covered: number;
  days_missing: string[];
  hint_zh: string | null;
}

interface EdgeGroup {
  strategy: string;
  domain: string;
  role: string;
  implementation: string;
  win_rate: number | null;
  mean_excess_pct: number | null;
  n: number | null;
  t_stat: number | null;
  instruments: FiringInstrument[];
  coverage: Coverage;
}

interface DemotedEdge {
  strategy: string;
  domain: string;
  n: number | null;
  n_clusters: number | null;
  cluster_by: string;
  win_rate: number | null;
  mean_excess_pct: number | null;
  t_stat: number | null;
  t_stat_iid: number | null;
  t_hurdle: number | null;
  /** Finest p-value this many independent units can express: 1/2^(G-1). */
  p_floor: number | null;
  /** False when significance is unrepresentable at this sample size. */
  resolvable: boolean | null;
  reasons_zh: string[];
  failed: string[];
}

interface FiringPayload {
  generated_at: string;
  groups: EdgeGroup[];
  demoted: DemotedEdge[];
  counts: { tradable_firing: number; avoid_firing: number };
  complete: boolean;
}

const STRATEGY_LABEL: Record<string, { zh: string; en: string }> = {
  a_share_billboard_reversal: { zh: 'A股 · 龙虎榜反转', en: 'A-share · Dragon-tiger reversal' },
  us_insider_cluster_buy: { zh: '美股 · 内部人集群买入', en: 'US · Insider cluster buy' },
  altcoin_retail_crowding: { zh: '山寨币 · 散户拥挤', en: 'Altcoin · Retail crowding' },
};

const DIRECTION_STYLE: Record<string, { zh: string; en: string; chip: string }> = {
  long: { zh: '做多', en: 'LONG', chip: 'border-emerald-300 bg-emerald-100 text-emerald-800' },
  short: { zh: '做空', en: 'SHORT', chip: 'border-sky-300 bg-sky-100 text-sky-800' },
  avoid: { zh: '回避', en: 'AVOID', chip: 'border-stone-300 bg-stone-100 text-stone-600' },
};



/**
 * 今日触发的边 — the instruments the validated edges are firing on right now.
 *
 * This is the panel the workbench was missing. Every other page asked you to
 * name an instrument and then told you whether an edge applied; but the US edge
 * fires on about five tickers a day out of thousands, so that workflow requires
 * you to already know the answer. The scoreboard says which edges exist. This
 * says where they are — which is the only form in which an event edge is
 * actionable.
 *
 * Tradable edges come first and get the visual weight. The avoidance filter is
 * present but folded down: on a busy day it lists two hundred A-shares, and a
 * list of things not to do must never bury the handful of things to do.
 */
export default function TodaysEdges() {
  const { language } = useLanguage();
  const zh = language === 'zh';

  const query = useQuery<FiringPayload>({
    queryKey: ['edges-firing'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/edges/firing`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return (await response.json()) as FiringPayload;
    },
    refetchInterval: 300_000,
    staleTime: 240_000,
  });

  const data = query.data;
  const tradable = (data?.groups ?? []).filter((g) => g.role === 'trade');
  const avoid = (data?.groups ?? []).filter((g) => g.role === 'avoid');
  const firingCount = data?.counts.tradable_firing ?? 0;

  return (
    <section
      aria-label={zh ? '今日触发的边' : "Edges firing today"}
      className="panel mb-6 overflow-hidden"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-200 px-5 py-4">
        <div>
          <div className="eyebrow">{zh ? '今日机会' : "Today's opportunities"}</div>
          <h2 className="mt-0.5 text-lg font-bold tracking-[-0.02em] text-stone-900">
            {zh ? '已验证的边 · 今天触发在哪里' : 'Validated edges · where they are firing'}
          </h2>
        </div>
        <span
          className={`rounded-full border px-3 py-1 text-xs font-medium ${
            firingCount > 0
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-stone-200 bg-stone-50 text-stone-500'
          }`}
        >
          {firingCount} {zh ? '个可开仓机会' : 'tradable now'}
        </span>
      </div>

      {query.isError ? (
        <ErrorState
          className="m-5"
          title={zh ? '无法扫描今日机会' : 'Could not scan for opportunities'}
          message={zh ? '无法连接 PolyBob API。' : 'Cannot reach the PolyBob API.'}
          onRetry={() => void query.refetch()}
          retryLabel={zh ? '重试' : 'Retry'}
        />
      ) : null}

      {!query.isError && query.isPending ? (
        <div className="px-5 py-8 text-center text-sm text-stone-400" aria-live="polite">
          {zh ? '扫描中…' : 'Scanning…'}
        </div>
      ) : null}

      {data
        ? tradable.map((group) => (
            <EdgeFiringGroup key={group.strategy} group={group} zh={zh} />
          ))
        : null}

      {data && tradable.length === 0 && !query.isPending ? (
        <NoTradableEdges demoted={data.demoted ?? []} zh={zh} />
      ) : data && firingCount === 0 && !query.isPending ? (
        <div className="px-5 py-6 text-center text-sm text-stone-500">
          {zh
            ? '今天没有标的触发这些边。多数时候就是这样——没有机会时不制造机会。'
            : 'No instrument is firing these edges today. That is the normal state; an absence of opportunity is not a reason to invent one.'}
        </div>
      ) : null}

      {data && avoid.length > 0 ? <AvoidSummary groups={avoid} zh={zh} /> : null}
    </section>
  );
}


/**
 * The honest empty state: no tradable edge exists, and here is why.
 *
 * There is a strong temptation to render this case as a blank panel or a cheerful
 * "nothing today". Both are wrong, for the same reason: a screen that looks broken
 * or looks like a quiet day gets ignored, and someone who ignores the workbench
 * trades on a hunch instead. The panel has to make the *finding* legible — the
 * edges were measured, the numbers are real, and they are not significant once the
 * events are treated as the dependent observations they are.
 *
 * The i.i.d. figure is shown alongside the clustered one on purpose. Seeing +5.03
 * next to +2.35 on the same 667 events is what makes the correction understandable
 * rather than something that merely happened to the board.
 */
function NoTradableEdges({ demoted, zh }: { demoted: DemotedEdge[]; zh: boolean }) {
  const trades = demoted.filter((d) => d.n !== null && d.n > 0);
  return (
    <div className="border-t border-stone-100">
      <div className="bg-amber-50/60 px-5 py-4">
        <p className="text-sm font-semibold text-amber-900">
          {zh
            ? '目前没有任何可开仓的边。'
            : 'There is currently no tradable edge.'}
        </p>
        <p className="mt-1 text-xs leading-6 text-amber-800">
          {zh
            ? '这不是数据故障。此前通过门禁的两条边，t 值是按“每个事件相互独立”算的；但持有期互相重叠、事件又扎堆在同一段行情里，这个假设不成立。用聚类标准误重算同一批真实数据后，两条都掉到门槛以下。'
            : 'This is not a data outage. The two edges that previously cleared the gate had t-statistics computed as if every event were an independent draw. With overlapping holding windows and events bunched in the same market episode, that assumption fails. Recomputed with clustered standard errors on the same real data, both fall below the hurdle.'}
        </p>
      </div>

      {trades.length > 0 ? (
        <ul className="divide-y divide-stone-100">
          {trades.map((edge) => (
            <li key={edge.strategy} className="px-5 py-3">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-[13px] font-semibold text-stone-700">
                  {STRATEGY_LABEL[edge.strategy]
                    ? zh
                      ? STRATEGY_LABEL[edge.strategy].zh
                      : STRATEGY_LABEL[edge.strategy].en
                    : edge.strategy}
                </span>
                <span className="rounded border border-stone-300 bg-stone-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-stone-600">
                  {zh ? '未通过门禁' : 'not promoted'}
                </span>
              </div>

              {/* Both statistics, side by side. The gap is the point. */}
              <div className="mt-1.5 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] text-stone-600">
                {edge.n !== null ? (
                  <span>
                    {zh ? '事件数 ' : 'events '}
                    {edge.n.toLocaleString()}
                  </span>
                ) : null}
                {edge.n_clusters !== null ? (
                  <span className="text-amber-700">
                    {zh ? '独立单元 ' : 'independent units '}
                    {edge.n_clusters}
                    {edge.cluster_by ? ` (${edge.cluster_by})` : ''}
                  </span>
                ) : null}
                {edge.t_stat_iid !== null ? (
                  <span className="text-stone-400 line-through">
                    t(iid) {edge.t_stat_iid > 0 ? '+' : ''}
                    {edge.t_stat_iid.toFixed(2)}
                  </span>
                ) : null}
                {edge.t_stat !== null ? (
                  <span className="font-semibold text-stone-800">
                    t{zh ? '(聚类)' : '(clustered)'} {edge.t_stat > 0 ? '+' : ''}
                    {edge.t_stat.toFixed(2)}
                  </span>
                ) : null}
                {edge.t_hurdle !== null ? (
                  <span>
                    {zh ? '门槛 ' : 'hurdle '}
                    {edge.t_hurdle.toFixed(2)}
                  </span>
                ) : null}
                {edge.resolvable === false && edge.p_floor !== null ? (
                  <span
                    className="font-semibold text-amber-800"
                    title={
                      zh
                        ? '独立单元太少,随机化检验能表达的最小 p 值已大于门槛要求'
                        : 'Too few independent units for a randomisation test to resolve the required p-value'
                    }
                  >
                    {zh ? '最细可表达 p=' : 'finest p='}
                    {edge.p_floor.toExponential(1)}
                  </span>
                ) : null}
              </div>

              <ul className="mt-1.5 space-y-0.5">
                {edge.reasons_zh.map((reason) => (
                  <li key={reason} className="text-[11px] leading-5 text-stone-500">
                    · {reason}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      ) : null}

      <p className="border-t border-stone-100 bg-stone-50/60 px-5 py-2.5 text-[11px] leading-5 text-stone-500">
        {zh
          ? '要让这些边重新通过，唯一的办法是把样本期拉长到覆盖更多独立的行情段——在同一批周里堆更多事件不会改变任何结论。'
          : 'The only way these edges clear the gate is a longer sample spanning more independent market episodes. Adding more events inside the same weeks changes nothing.'}
      </p>
    </div>
  );
}

function EdgeFiringGroup({ group, zh }: { group: EdgeGroup; zh: boolean }) {
  const label = STRATEGY_LABEL[group.strategy];
  const dir = group.instruments[0]?.direction ?? null;
  const dirStyle = dir ? DIRECTION_STYLE[dir] : null;

  return (
    <div className="border-t border-stone-100 first:border-t-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 bg-stone-50/70 px-5 py-2">
        <span className="text-[13px] font-semibold text-stone-800">
          {label ? (zh ? label.zh : label.en) : group.strategy}
        </span>
        {dirStyle ? (
          <span
            className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${dirStyle.chip}`}
          >
            {zh ? dirStyle.zh : dirStyle.en}
          </span>
        ) : null}
        {/* The measured numbers travel with the opportunity: a row that says
            "act" must carry the evidence that earns the word. */}
        <span className="text-[11px] text-stone-500">
          {zh ? '实测 ' : 'measured '}
          {group.win_rate !== null ? `${(group.win_rate * 100).toFixed(1)}%` : '—'}
          {zh ? ' 胜率 · ' : ' win · '}
          {group.mean_excess_pct !== null
            ? `${group.mean_excess_pct > 0 ? '+' : ''}${group.mean_excess_pct.toFixed(2)}%`
            : '—'}
          {group.n !== null ? ` · n=${group.n.toLocaleString()}` : ''}
        </span>
      </div>

      {!group.coverage.complete && group.coverage.hint_zh ? (
        <p className="border-b border-amber-100 bg-amber-50/60 px-5 py-1.5 text-[11px] leading-5 text-amber-800">
          ⚠ {group.coverage.hint_zh}
        </p>
      ) : null}

      {group.instruments.length === 0 ? (
        <p className="px-5 py-3 text-xs text-stone-400">
          {zh ? '今天没有标的触发这条边' : 'No instrument is firing this edge today'}
        </p>
      ) : (
        <ul className="divide-y divide-stone-100">
          {group.instruments.map((item) => (
            <li key={`${group.strategy}-${item.symbol}-${item.fired_on ?? ""}`}>
              <Link
                href={instrumentHref(group.domain, item.symbol)}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-5 py-3 transition hover:bg-stone-50 focus:bg-stone-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-stone-400"
              >
                <span className="font-mono text-[15px] font-bold text-stone-900">
                  {item.symbol}
                </span>
                {item.name ? (
                  <span className="text-xs text-stone-500">{item.name}</span>
                ) : null}
                {item.fired_on ? (
                  <span className="font-mono text-[11px] text-stone-400">{item.fired_on}</span>
                ) : null}
                <span className="min-w-0 flex-1 text-xs leading-5 text-stone-600 md:text-right">
                  {zh ? item.evidence_zh : item.evidence_en}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Avoidance filters, collapsed. On an active day the dragon-tiger list runs to
 * two hundred names; rendering them inline would bury the handful of tradable
 * rows above under a wall of things not to do.
 */
function AvoidSummary({ groups, zh }: { groups: EdgeGroup[]; zh: boolean }) {
  const total = groups.reduce((sum, g) => sum + g.instruments.length, 0);
  return (
    <details className="border-t border-stone-200 bg-stone-50/50">
      <summary className="cursor-pointer px-5 py-3 text-xs text-stone-600 hover:bg-stone-100">
        {zh
          ? `回避清单 · ${total} 个标的今天触发了回避条件（点开查看）`
          : `Avoidance list · ${total} instruments triggered an avoidance condition today`}
      </summary>
      {groups.map((group) => (
        <div key={group.strategy} className="px-5 pb-3">
          <p className="mb-2 text-[11px] text-stone-500">
            {STRATEGY_LABEL[group.strategy]
              ? zh
                ? STRATEGY_LABEL[group.strategy].zh
                : STRATEGY_LABEL[group.strategy].en
              : group.strategy}
            {group.mean_excess_pct !== null
              ? zh
                ? ` — 实测 ${group.mean_excess_pct.toFixed(2)}%，胜率 ${
                    group.win_rate !== null ? (group.win_rate * 100).toFixed(1) : '—'
                  }%。不产生收益，只用于避开`
                : ` — measured ${group.mean_excess_pct.toFixed(2)}%; a filter, not a position`
              : ''}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {group.instruments.map((item) => (
              <span
                key={`${item.symbol}-${item.fired_on ?? ""}`}
                className="rounded border border-stone-200 bg-white px-1.5 py-0.5 font-mono text-[11px] text-stone-600"
                title={zh ? item.evidence_zh : item.evidence_en}
              >
                {item.symbol}
              </span>
            ))}
          </div>
        </div>
      ))}
    </details>
  );
}
