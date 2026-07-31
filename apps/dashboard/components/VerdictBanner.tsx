'use client';

import { useQuery } from '@tanstack/react-query';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

interface Check {
  key: string;
  status: 'pass' | 'warn' | 'fail' | 'unknown';
  question_zh: string;
  question_en: string;
  finding_zh: string;
  finding_en: string;
}

type TrendClassification =
  | 'strong_uptrend'
  | 'uptrend'
  | 'neutral'
  | 'downtrend'
  | 'strong_downtrend';

interface TrendBlock {
  classification: TrendClassification | string;
  score?: number | null;
  /** Period -> fractional return (0.012 = +1.2%). Keys may be missing. */
  returns?: Record<string, number | null | undefined> | null;
  ma?: Record<string, number | null | undefined> | null;
  aligned?: boolean | null;
  evidence_zh?: string | null;
  evidence_en?: string | null;
  /** Optional: last price, when the backend supplies it. */
  price?: number | null;
}

type VolumeClassification =
  | 'confirming'
  | 'expanding'
  | 'drying_up'
  | 'distribution'
  | 'climax'
  | 'unavailable';

type PriceVolumeAgreement = 'confirm' | 'diverge' | 'neutral';

interface VolumeBlock {
  classification: VolumeClassification | string;
  score?: number | null;
  /** Today's volume against its 20-day average; 1.35 = 35% above normal. */
  ratio_20d?: number | null;
  /** Period -> volume ratio vs that period's average. Keys may be missing. */
  ratios?: Record<string, number | null | undefined> | null;
  price_volume_agreement?: PriceVolumeAgreement | string | null;
  latest_volume?: number | null;
  evidence_zh?: string | null;
  evidence_en?: string | null;
}

interface VerdictPayload {
  symbol: string;
  domain: string;
  verdict: 'act' | 'watch' | 'wait' | 'avoid';
  headline_zh: string;
  headline_en: string;
  checks: Check[];
  /** Added by the trend layer; absent/null when history is insufficient. */
  trend?: TrendBlock | null;
  /**
   * Added by the volume layer. Null/absent where the instrument has no daily
   * volume concept at all (Polymarket BTC-5m) — rendered as an explicit
   * "no volume data" state, never as a fake zero.
   */
  volume?: VolumeBlock | null;
  price?: number | null;
}

const VERDICT_STYLE: Record<string, string> = {
  act: 'border-emerald-300 bg-emerald-50',
  watch: 'border-amber-300 bg-amber-50',
  wait: 'border-stone-300 bg-stone-50',
  avoid: 'border-rose-300 bg-rose-50',
};

const VERDICT_TEXT: Record<string, { zh: string; en: string; tone: string }> = {
  act: { zh: '可以行动', en: 'ACT', tone: 'text-emerald-700' },
  watch: { zh: '观察', en: 'WATCH', tone: 'text-amber-700' },
  wait: { zh: '等待', en: 'WAIT', tone: 'text-stone-600' },
  avoid: { zh: '回避', en: 'AVOID', tone: 'text-rose-700' },
};

const STATUS_MARK: Record<string, { icon: string; tone: string }> = {
  pass: { icon: '✓', tone: 'text-emerald-600' },
  warn: { icon: '!', tone: 'text-amber-600' },
  fail: { icon: '✕', tone: 'text-rose-600' },
  unknown: { icon: '?', tone: 'text-stone-400' },
};

const TREND_STYLE: Record<
  string,
  { zh: string; en: string; chip: string; arrow: string }
> = {
  strong_uptrend: {
    zh: '强势上升',
    en: 'STRONG UPTREND',
    chip: 'border-emerald-300 bg-emerald-100 text-emerald-800',
    arrow: '▲▲',
  },
  uptrend: {
    zh: '上升',
    en: 'UPTREND',
    chip: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    arrow: '▲',
  },
  neutral: {
    zh: '横盘',
    en: 'NEUTRAL',
    chip: 'border-stone-300 bg-stone-100 text-stone-600',
    arrow: '→',
  },
  downtrend: {
    zh: '下降',
    en: 'DOWNTREND',
    chip: 'border-rose-200 bg-rose-50 text-rose-700',
    arrow: '▼',
  },
  strong_downtrend: {
    zh: '强势下降',
    en: 'STRONG DOWNTREND',
    chip: 'border-rose-300 bg-rose-100 text-rose-800',
    arrow: '▼▼',
  },
};

const UNKNOWN_TREND = {
  zh: '未知',
  en: 'UNKNOWN',
  chip: 'border-stone-300 bg-stone-100 text-stone-500',
  arrow: '?',
};

/** The return ladder, shortest horizon first. */
const RETURN_PERIODS: { key: string; zh: string; en: string }[] = [
  { key: '1w', zh: '1周', en: '1W' },
  { key: '1m', zh: '1月', en: '1M' },
  { key: '2m', zh: '2月', en: '2M' },
  { key: '3m', zh: '3月', en: '3M' },
  { key: '6m', zh: '6月', en: '6M' },
  { key: '1y', zh: '1年', en: '1Y' },
];

const MA_KEYS = ['ma20', 'ma50', 'ma200'] as const;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** Price-scale aware formatting: big numbers need fewer decimals than cheap alts. */
function formatLevel(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude >= 1000) return value.toFixed(0);
  if (magnitude >= 10) return value.toFixed(2);
  if (magnitude >= 1) return value.toFixed(3);
  return value.toFixed(5);
}

/**
 * One cell of the multi-timeframe return ladder.
 *
 * Colour never carries the meaning alone — every cell also shows an explicit
 * ▲/▼/· sign glyph and a signed percentage, so the ladder is readable in
 * greyscale and by colour-blind readers.
 */
function ReturnCell({
  label,
  value,
  ariaLabel,
}: {
  label: string;
  value: number | null | undefined;
  ariaLabel: string;
}) {
  const known = isFiniteNumber(value);
  const positive = known && value > 0;
  const negative = known && value < 0;
  const tone = positive
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : negative
      ? 'border-rose-200 bg-rose-50 text-rose-700'
      : 'border-stone-200 bg-stone-50 text-stone-500';
  const glyph = positive ? '▲' : negative ? '▼' : '·';

  return (
    <div
      className={`rounded-md border px-1.5 py-1 text-center ${tone}`}
      aria-label={ariaLabel}
      role="listitem"
    >
      <div className="text-[10px] font-semibold uppercase tracking-wide opacity-70">
        {label}
      </div>
      <div className="mono mt-0.5 whitespace-nowrap text-[11px] font-bold leading-4 sm:text-xs">
        <span aria-hidden="true">{glyph}</span>{' '}
        {known ? `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%` : '--'}
      </div>
    </div>
  );
}

/**
 * The trend block: classification badge, multi-timeframe return ladder and the
 * moving-average reading. This is part of the core conclusion, so it sits
 * directly under the verdict headline rather than at the bottom of the checks.
 */
function TrendSection({ trend, price, zh }: { trend: TrendBlock; price: number | null; zh: boolean }) {
  const style = TREND_STYLE[trend.classification] ?? UNKNOWN_TREND;
  const returns = trend.returns ?? {};
  const ma = trend.ma ?? {};
  const evidence = zh ? trend.evidence_zh : trend.evidence_en;
  const hasReturns = RETURN_PERIODS.some((period) => isFiniteNumber(returns[period.key]));
  const hasMa = MA_KEYS.some((key) => isFiniteNumber(ma[key]));

  return (
    <div className="border-t border-stone-200/70 bg-white/60 px-5 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="eyebrow">{zh ? '趋势' : 'Trend'}</span>
        <span
          className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-bold ${style.chip}`}
          aria-label={`${zh ? '趋势分类' : 'Trend classification'}: ${zh ? style.zh : style.en}`}
        >
          <span aria-hidden="true">{style.arrow}</span>
          {zh ? style.zh : style.en}
        </span>
        {isFiniteNumber(trend.score) ? (
          <span className="mono text-[11px] text-stone-500">
            {zh ? '强度' : 'Score'} {trend.score.toFixed(2)}
          </span>
        ) : null}
        {trend.aligned === true ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
            <span aria-hidden="true">✓</span>
            {zh ? '均线多头排列' : 'MAs aligned'}
          </span>
        ) : trend.aligned === false ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-[11px] font-semibold text-stone-500">
            <span aria-hidden="true">✕</span>
            {zh ? '均线未排列' : 'MAs not aligned'}
          </span>
        ) : null}
      </div>

      {hasReturns ? (
        <div
          className="mt-2.5 grid grid-cols-3 gap-1.5 sm:grid-cols-6"
          role="list"
          aria-label={zh ? '多周期涨跌幅' : 'Multi-timeframe returns'}
        >
          {RETURN_PERIODS.map((period) => {
            const value = returns[period.key];
            const readable = isFiniteNumber(value)
              ? `${(value * 100).toFixed(1)}%`
              : zh
                ? '数据不足'
                : 'no data';
            return (
              <ReturnCell
                key={period.key}
                label={zh ? period.zh : period.en}
                value={value}
                ariaLabel={`${zh ? period.zh : period.en} ${zh ? '涨跌幅' : 'return'} ${readable}`}
              />
            );
          })}
        </div>
      ) : (
        <p className="mt-2 text-xs text-stone-500">
          {zh ? '多周期涨跌幅：历史不足' : 'Multi-timeframe returns: insufficient history'}
        </p>
      )}

      {hasMa ? (
        <div
          className="mt-2 flex flex-wrap items-center gap-1.5"
          role="list"
          aria-label={zh ? '均线读数' : 'Moving-average reading'}
        >
          {isFiniteNumber(price) ? (
            <span className="mono rounded-md border border-sky-200 bg-sky-50 px-2 py-1 text-[11px] font-semibold text-sky-700" role="listitem">
              {zh ? '现价' : 'Price'} {formatLevel(price)}
            </span>
          ) : null}
          {MA_KEYS.map((key) => {
            const level = ma[key];
            const known = isFiniteNumber(level);
            const above = known && isFiniteNumber(price) ? price > level : null;
            const tone =
              above === true
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : above === false
                  ? 'border-rose-200 bg-rose-50 text-rose-700'
                  : 'border-stone-200 bg-stone-50 text-stone-600';
            const relation =
              above === true
                ? { glyph: '▲', zh: '价在其上', en: 'price above' }
                : above === false
                  ? { glyph: '▼', zh: '价在其下', en: 'price below' }
                  : null;
            return (
              <span
                key={key}
                role="listitem"
                className={`mono rounded-md border px-2 py-1 text-[11px] font-semibold ${tone}`}
                aria-label={`${key.toUpperCase()} ${known ? formatLevel(level) : zh ? '历史不足' : 'insufficient history'}${
                  relation ? `, ${zh ? relation.zh : relation.en}` : ''
                }`}
              >
                {relation ? <span aria-hidden="true">{relation.glyph} </span> : null}
                {key.toUpperCase()} {known ? formatLevel(level) : '--'}
              </span>
            );
          })}
        </div>
      ) : (
        <p className="mt-2 text-xs text-stone-500">
          {zh ? '均线：历史不足' : 'Moving averages: insufficient history'}
        </p>
      )}

      {evidence ? (
        <p className="mt-2 text-xs leading-5 text-stone-600">{evidence}</p>
      ) : null}
    </div>
  );
}

/**
 * The verdict banner that opens every instrument page.
 *
 * Its purpose is the book's warning — "犯错并不可怕，可怕的是不知自己犯了错" — so it
 * always shows the reasoning, never a bare recommendation, and states plainly
 * when a check is unknown rather than quietly passing it.
 */
export default function VerdictBanner({
  symbol,
  domain = 'auto',
}: {
  symbol: string;
  domain?: string;
}) {
  const { language } = useLanguage();
  const zh = language === 'zh';

  const query = useQuery<VerdictPayload>({
    queryKey: ['verdict', symbol, domain],
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({ symbol, domain });
      const response = await fetch(`${API_BASE}/api/verdict?${params}`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return (await response.json()) as VerdictPayload;
    },
    refetchInterval: 300_000,
    staleTime: 240_000,
  });

  const data = query.data;
  const style = data ? VERDICT_STYLE[data.verdict] : VERDICT_STYLE.wait;
  const label = data ? VERDICT_TEXT[data.verdict] : null;

  return (
    <section
      aria-label={zh ? '投资准则判定' : 'Investment principle verdict'}
      className={`mb-6 rounded-xl border-2 ${style} overflow-hidden`}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-4">
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-wide text-stone-500">
            {zh ? '投资准则判定' : 'Verdict'} · {data?.symbol ?? symbol}
          </div>
          <div className={`mt-0.5 text-2xl font-bold tracking-tight ${label?.tone ?? 'text-stone-600'}`}>
            {query.isLoading
              ? (zh ? '判定中…' : 'Judging…')
              : query.isError
                ? (zh ? '无法判定' : 'Cannot judge')
                : label
                  ? (zh ? label.zh : label.en)
                  : '—'}
          </div>
        </div>
        <p className="flex-1 text-sm leading-6 text-stone-700 md:text-right">
          {query.isError
            ? (zh ? '真实数据不可用——没有数据就没有判断' : 'Real data unavailable — no data, no judgement')
            : data
              ? (zh ? data.headline_zh : data.headline_en)
              : ''}
        </p>
      </div>

      {data ? (
        data.trend ? (
          <TrendSection
            trend={data.trend}
            price={isFiniteNumber(data.price) ? data.price : (data.trend.price ?? null)}
            zh={zh}
          />
        ) : (
          <div className="border-t border-stone-200/70 bg-white/60 px-5 py-3">
            <span className="eyebrow">{zh ? '趋势' : 'Trend'}</span>
            <p className="mt-1 text-xs leading-5 text-stone-500">
              {zh
                ? '历史不足，无法给出多周期趋势与均线读数——不猜，就是不知道。'
                : 'Insufficient history for multi-timeframe trend and moving averages — unknown, not guessed.'}
            </p>
          </div>
        )
      ) : null}

      {data ? (
        <ul className="divide-y divide-stone-200/70 border-t border-stone-200/70 bg-white/60">
          {data.checks.map((check) => {
            const mark = STATUS_MARK[check.status] ?? STATUS_MARK.unknown;
            return (
              <li key={check.key} className="flex gap-3 px-5 py-2.5">
                <span
                  className={`mt-0.5 font-mono text-sm font-bold ${mark.tone}`}
                  aria-label={check.status}
                >
                  {mark.icon}
                </span>
                <span className="min-w-0">
                  <span className="block text-xs font-semibold text-stone-700">
                    {zh ? check.question_zh : check.question_en}
                  </span>
                  <span className="mt-0.5 block text-xs leading-5 text-stone-600">
                    {zh ? check.finding_zh : check.finding_en}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}

      <p className="border-t border-stone-200/70 px-5 py-2 text-[11px] leading-5 text-stone-500">
        {zh
          ? '「犯错并不可怕，可怕的是不知自己犯了错，知错却不肯认错就更加不可救药。」——判定默认是「等待」，多数时候什么都不做才是对的。'
          : '"Being wrong is not the danger — not knowing you are wrong is." The default verdict is WAIT; most of the time, doing nothing is correct.'}
      </p>
    </section>
  );
}
