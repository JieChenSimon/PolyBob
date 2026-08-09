'use client';

import { useQuery } from '@tanstack/react-query';
import ErrorState from '@/components/ui/ErrorState';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

/**
 * Mirrors ``libs.quant.promotion_registry.PromotionRecord`` field for field.
 * It previously did not: the board sent six fields and this declared nine
 * different ones, so `total_return ?? 0` rendered a fabricated `0.00%` and
 * `win_rate` (undefined, not null) slipped past a `!== null` check and rendered
 * `NaN%` — on the landing page, for the only numbers this project is judged by.
 * `tests/contract.test.ts` now asserts the two stay in step.
 */
interface EdgeRecord {
  strategy: string;
  instrument: string;
  domain: string;
  approved: boolean;
  /** "trade" = a position may be opened; "avoid" = a filter that earns nothing. */
  role: string;
  win_rate: number | null;
  /** Percent, already scaled (-2.08 means -2.08%). Not a fraction. */
  mean_excess_pct: number | null;
  /** Cluster-robust. The board recomputes this; it is not copied from a file. */
  t_stat: number | null;
  /** The i.i.d. figure the experiments used to report. Shown struck through. */
  t_stat_iid: number | null;
  t_hurdle: number | null;
  n: number | null;
  /** Independent units. This, not `n`, is the sample size governing the error. */
  n_clusters: number | null;
  cluster_by: string;
  /** Last event the study observed. Not when the script last ran. */
  evidence_end: string | null;
  /** Computed per-request by the backend, not stored on the board. */
  evidence_age_days: number | null;
  max_evidence_age_days: number | null;
  /** True when nobody has re-measured inside the declared shelf life. */
  evidence_expired: boolean;
  implementation: string;
  evidence: string;
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
  short_perp_when_retail_crowded_long: { zh: '做空永续(散户拥挤时)', en: 'Short the perp when crowded' },
  take_side_when_model_beats_market_price: { zh: '模型优于市价时取方向', en: 'Take the side the model favours' },
};

/** A percent that is already a percent. Missing stays missing. */
function formatPct(value: number | null, digits = 2): string {
  return value === null || value === undefined || !Number.isFinite(value)
    ? '—'
    : `${value > 0 ? '+' : ''}${value.toFixed(digits)}%`;
}


/**
 * One role's worth of edges. Missing numbers render as `—`, never as a zero:
 * the point of this panel is that you can trust what it says, and a `0.00%`
 * that actually means "the backend did not send this field" is worse than a
 * blank, because it reads as a measurement.
 */
function EdgeGroup({
  records,
  zh,
  title,
  note,
}: {
  records: EdgeRecord[];
  zh: boolean;
  title: string;
  note: string;
}) {
  if (records.length === 0) return null;
  return (
    <div className="border-t border-stone-100 first:border-t-0">
      <div className="bg-stone-50/70 px-5 py-2">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-stone-600">
          {title}
        </div>
        <p className="mt-0.5 text-[11px] leading-4 text-stone-500">{note}</p>
      </div>
      <ul className="divide-y divide-stone-100">
        {records.map((record) => {
          const label = STRATEGY_LABEL[record.strategy];
          const impl = record.implementation ? IMPLEMENTATION_LABEL[record.implementation] : null;
          const ret = record.mean_excess_pct;
          const known = ret !== null && ret !== undefined && Number.isFinite(ret);
          return (
            <li key={`${record.strategy}-${record.instrument}`} className="px-5 py-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-[15px] font-semibold text-stone-900">
                  {label ? (zh ? label.zh : label.en) : record.strategy}
                </span>
                <span
                  className={`font-mono text-lg font-bold ${
                    !known ? 'text-stone-400' : ret > 0 ? 'text-emerald-600' : 'text-rose-600'
                  }`}
                  title={zh ? '相对基准的平均超额收益' : 'Mean excess return vs benchmark'}
                >
                  {formatPct(ret)}
                </span>
              </div>

              <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-stone-500">
                <span>
                  {zh ? '胜率 ' : 'Win '}
                  <span className="font-mono font-semibold text-stone-700">
                    {record.win_rate === null || record.win_rate === undefined
                      ? '—'
                      : `${(record.win_rate * 100).toFixed(1)}%`}
                  </span>
                </span>
                <span>
                  {zh ? '样本 ' : 'n = '}
                  <span className="font-mono font-semibold text-stone-700">
                    {record.n?.toLocaleString() ?? '—'}
                  </span>
                </span>
                {/* Independent units, next to the raw count. 40,768 events over
                    125 weeks is a real sample; 245 events over 13 weeks is not,
                    and the two are indistinguishable if only `n` is shown. */}
                {record.n_clusters !== null && record.n_clusters !== undefined ? (
                  <span title={zh ? '互不重叠的独立时间单元数' : 'Non-overlapping independent time units'}>
                    {zh ? '独立单元 ' : 'independent '}
                    <span className="font-mono font-semibold text-stone-700">
                      {record.n_clusters}
                    </span>
                    {record.cluster_by ? (
                      <span className="text-stone-400"> ({record.cluster_by})</span>
                    ) : null}
                  </span>
                ) : null}
                {record.t_stat !== null && record.t_stat !== undefined ? (
                  <span title={zh ? '聚类标准误 t 值(计入持有期重叠)' : 'Cluster-robust t (accounts for overlapping windows)'}>
                    t ={' '}
                    <span className="font-mono font-semibold text-stone-700">
                      {record.t_stat.toFixed(2)}
                    </span>
                    {record.t_hurdle !== null && record.t_hurdle !== undefined ? (
                      <span className="text-stone-400"> / {record.t_hurdle.toFixed(2)}</span>
                    ) : null}
                  </span>
                ) : null}
                {/* The superseded statistic, struck through. An edge whose
                    i.i.d. t was 6.38 and whose clustered t is 1.74 has not
                    weakened — it was never measured correctly, and hiding the
                    old number hides how much of the "evidence" was arithmetic. */}
                {record.t_stat_iid !== null &&
                record.t_stat_iid !== undefined &&
                record.t_stat !== null &&
                Math.abs(record.t_stat_iid) > Math.abs(record.t_stat) + 0.05 ? (
                  <span
                    className="text-stone-400"
                    title={zh ? '旧的 i.i.d. 算法值,假设事件相互独立' : 'The old i.i.d. figure, which assumed independent events'}
                  >
                    <span className="line-through">t(iid) {record.t_stat_iid.toFixed(2)}</span>
                  </span>
                ) : null}
              </div>

              {impl ? (
                <span className="mt-2 inline-block rounded border border-sky-200 bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-700">
                  {zh ? impl.zh : impl.en}
                </span>
              ) : null}

              {/* Evidence age, shown before it expires rather than at the moment
                  it does. An edge is a claim about how a market behaves and
                  markets change; the board used to carry no notion of age, so a
                  finding kept its permission indefinitely. Seeing "129 / 180 天"
                  is what prompts a re-measurement in time. */}
              {record.evidence_age_days !== null &&
              record.evidence_age_days !== undefined &&
              record.max_evidence_age_days ? (
                <p
                  className={`mt-1.5 text-[11px] leading-5 ${
                    record.evidence_expired
                      ? 'font-medium text-rose-700'
                      : record.evidence_age_days > record.max_evidence_age_days * 0.75
                        ? 'text-amber-700'
                        : 'text-stone-400'
                  }`}
                >
                  {zh ? '证据截至 ' : 'evidence through '}
                  <span className="font-mono">{record.evidence_end}</span>
                  {zh ? ' · 距今 ' : ' · '}
                  <span className="font-mono">
                    {record.evidence_age_days}/{record.max_evidence_age_days}
                  </span>
                  {zh ? ' 天' : ' days old'}
                  {record.evidence_expired
                    ? zh
                      ? ' — 已过期,权限已收回,需重新测量'
                      : ' — expired; permission withdrawn, re-measure'
                    : ''}
                </p>
              ) : null}

              {record.evidence ? (
                <p className="mt-1.5 text-[11px] leading-5 text-stone-400">{record.evidence}</p>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

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

  const records = query.data?.records ?? [];
  // Approved is not tradable. An avoidance filter is a real finding that earns
  // nothing and cannot be shorted in its market; counting it here is what made
  // the desk look three edges deep when it is two.
  const tradable = records.filter((r) => r.approved && r.role === 'trade');
  const avoidFilters = records.filter((r) => r.approved && r.role === 'avoid');
  const hasAny = tradable.length + avoidFilters.length > 0;

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
          {tradable.length} {zh ? '条可开仓' : 'tradable'}
        </span>
        <span className="rounded-full border border-stone-200 bg-stone-50 px-3 py-1 text-xs font-medium text-stone-600">
          {avoidFilters.length} {zh ? '条回避过滤器' : 'avoidance filters'}
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

      {!query.isError && !hasAny ? (
        <div className="px-5 py-8 text-center text-sm text-stone-400" aria-live="polite">
          {query.isLoading
            ? (zh ? '加载中…' : 'Loading…')
            : (zh ? '暂无通过门禁的策略' : 'No promoted edges yet')}
        </div>
      ) : (
        <>
          <EdgeGroup
            records={tradable}
            zh={zh}
            title={zh ? '可开仓的边' : 'Tradable edges'}
            note={zh ? '这些边授予开仓权限' : 'These grant permission to open a position'}
          />
          <EdgeGroup
            records={avoidFilters}
            zh={zh}
            title={zh ? '回避过滤器' : 'Avoidance filters'}
            note={
              zh
                ? '真实发现,但不产生收益、也无法做空——只用于避开,不授予开仓权限'
                : 'Real findings that earn nothing and cannot be shorted — they stop you buying, they are not positions'
            }
          />
        </>
      )}

      <p className="border-t border-stone-200 px-5 py-2.5 text-[11px] leading-5 text-stone-500">
        {zh
          ? '全部基于真实数据、事前预注册假设、并通过多重检验校正后的 t 门槛。t 值用聚类标准误计算,把持有期重叠和事件扎堆算进去——所以「独立单元」而不是「样本」才是决定显著性的数字。收益为「相对基准的平均超额」,缺失的数字显示为 —,不补零。'
          : 'All measured on real data with pre-registered hypotheses and a multiple-testing-corrected t-hurdle. The t-statistic uses clustered standard errors, so overlapping holding windows and calendar bunching are accounted for — which is why "independent units", not "n", is the number that decides significance. Returns are mean excess versus benchmark; a missing number renders as — and is never filled in with a zero.'}
      </p>
    </section>
  );
}
