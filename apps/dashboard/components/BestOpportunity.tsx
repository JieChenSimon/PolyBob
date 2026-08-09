'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';
import { instrumentHref } from '@/lib/instrument';

interface FiringInstrument {
  symbol: string;
  name?: string;
  direction: string | null;
  fired_on: string | null;
  evidence_zh: string;
  evidence_en: string;
  detail?: Record<string, unknown>;
}

interface EdgeGroup {
  strategy: string;
  domain: string;
  role: string;
  win_rate: number | null;
  mean_excess_pct: number | null;
  n: number | null;
  instruments: FiringInstrument[];
  coverage: { complete: boolean; hint_zh: string | null };
}

interface FiringPayload {
  groups: EdgeGroup[];
}

const STRATEGY_LABEL: Record<string, { zh: string; en: string }> = {
  us_insider_cluster_buy: { zh: '内部人集群买入', en: 'Insider cluster buy' },
  altcoin_retail_crowding: { zh: '散户拥挤', en: 'Retail crowding' },
  a_share_billboard_reversal: { zh: '龙虎榜反转', en: 'Dragon-tiger reversal' },
};

const DIRECTION = {
  long: { zh: '做多', en: 'LONG', chip: 'border-emerald-300 bg-emerald-100 text-emerald-800' },
  short: { zh: '做空', en: 'SHORT', chip: 'border-sky-300 bg-sky-100 text-sky-800' },
  avoid: { zh: '回避', en: 'AVOID', chip: 'border-stone-300 bg-stone-100 text-stone-600' },
} as const;

/**
 * 本类别最佳机会 — the top of every instrument tab.
 *
 * A category tab answers a different question from an instrument page. This one
 * is "which of these should I be looking at", and until now it had no answer:
 * the tab opened with a verdict banner for one hardcoded symbol, which is an
 * instrument-level judgement standing in the place where a *selection* belongs.
 *
 * Ranking is by evidence, not by convenience: tradable edges before avoidance
 * filters, then by the size of the triggering event (dollar value of the insider
 * cluster, how far past its percentile the crowding is). The measured win rate
 * and mean excess travel with it, because a row that says "look here" has to
 * carry the reason.
 */
export default function BestOpportunity({
  domain,
  title,
}: {
  domain: string;
  title?: { zh: string; en: string };
}) {
  const { language } = useLanguage();
  const zh = language === 'zh';

  const query = useQuery<FiringPayload>({
    queryKey: ['edges-firing'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/edges/firing`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    refetchInterval: 300_000,
    staleTime: 240_000,
  });

  const groups = (query.data?.groups ?? []).filter((g) => g.domain === domain);
  const tradable = groups.filter((g) => g.role === 'trade' && g.instruments.length > 0);
  const avoid = groups.filter((g) => g.role === 'avoid' && g.instruments.length > 0);

  // Tradable first; an avoidance filter is only the headline when there is
  // nothing to actually do.
  const chosen = tradable[0] ?? avoid[0] ?? null;
  const top = chosen?.instruments[0] ?? null;
  const others = (chosen?.instruments ?? []).slice(1, 5);
  const incomplete = groups.some((g) => !g.coverage.complete);

  return (
    <section
      aria-label={zh ? '本类别最佳机会' : 'Best opportunity in this market'}
      className={`panel mb-6 overflow-hidden border-l-4 ${
        top && chosen?.role === 'trade' ? 'border-emerald-500' : 'border-stone-300'
      }`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-stone-200 px-5 py-3">
        <div>
          <div className="eyebrow">{zh ? '本类别最佳机会' : 'Best opportunity here'}</div>
          <h2 className="mt-0.5 text-base font-bold tracking-[-0.02em] text-stone-900">
            {title ? (zh ? title.zh : title.en) : zh ? '今天该看哪一个' : 'Which one to look at today'}
          </h2>
        </div>
        <Link
          href="/overview"
          className="text-xs text-stone-500 underline decoration-stone-300 hover:text-stone-800"
        >
          {zh ? '看全部机会' : 'All opportunities'}
        </Link>
      </div>

      {query.isPending ? (
        <p className="px-5 py-5 text-sm text-stone-400" aria-live="polite">
          {zh ? '扫描中…' : 'Scanning…'}
        </p>
      ) : query.isError ? (
        <p className="px-5 py-5 text-sm text-stone-500">
          {zh ? '无法扫描机会——接口不可用' : 'Could not scan — the API is unavailable'}
        </p>
      ) : !top || !chosen ? (
        <p className="px-5 py-5 text-sm text-stone-500">
          {zh
            ? '本类别今天没有已验证的边在触发。没有机会时不制造机会。'
            : 'No validated edge is firing in this market today. An absence of opportunity is not a reason to invent one.'}
        </p>
      ) : (
        <>
          <Link
            href={instrumentHref(chosen.domain, top.symbol)}
            className="block px-5 py-4 transition hover:bg-stone-50 focus:bg-stone-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-stone-400"
          >
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="font-mono text-2xl font-bold text-stone-950">{top.symbol}</span>
              {top.name ? <span className="text-sm text-stone-600">{top.name}</span> : null}
              {top.direction && top.direction in DIRECTION ? (
                <span
                  className={`rounded border px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${
                    DIRECTION[top.direction as keyof typeof DIRECTION].chip
                  }`}
                >
                  {zh
                    ? DIRECTION[top.direction as keyof typeof DIRECTION].zh
                    : DIRECTION[top.direction as keyof typeof DIRECTION].en}
                </span>
              ) : null}
              <span className="text-xs text-stone-500">
                {STRATEGY_LABEL[chosen.strategy]
                  ? zh
                    ? STRATEGY_LABEL[chosen.strategy].zh
                    : STRATEGY_LABEL[chosen.strategy].en
                  : chosen.strategy}
              </span>
              {chosen.win_rate !== null ? (
                <span className="text-xs text-stone-500">
                  {zh ? '实测胜率 ' : 'measured win '}
                  <span className="font-mono font-semibold text-stone-700">
                    {(chosen.win_rate * 100).toFixed(1)}%
                  </span>
                  {chosen.mean_excess_pct !== null
                    ? ` · ${chosen.mean_excess_pct > 0 ? '+' : ''}${chosen.mean_excess_pct.toFixed(2)}%`
                    : ''}
                  {chosen.n !== null ? ` · n=${chosen.n.toLocaleString()}` : ''}
                </span>
              ) : null}
            </div>
            <p className="mt-1.5 text-sm leading-6 text-stone-700">
              {zh ? top.evidence_zh : top.evidence_en}
            </p>
            <p className="mt-1 text-xs text-stone-400">
              {zh ? '点击查看该标的的投资准则判定 →' : "Open this instrument's verdict →"}
            </p>
          </Link>

          {others.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2 border-t border-stone-100 bg-stone-50/60 px-5 py-2.5">
              <span className="text-[11px] text-stone-500">
                {zh ? '同样在触发：' : 'Also firing:'}
              </span>
              {others.map((item) => (
                <Link
                  key={`${item.symbol}-${item.fired_on ?? ''}`}
                  href={instrumentHref(chosen.domain, item.symbol)}
                  className="rounded border border-stone-200 bg-white px-2 py-0.5 font-mono text-[11px] text-stone-700 hover:border-stone-400"
                >
                  {item.symbol}
                </Link>
              ))}
            </div>
          ) : null}
        </>
      )}

      {incomplete ? (
        <p className="border-t border-amber-100 bg-amber-50/60 px-5 py-1.5 text-[11px] leading-5 text-amber-800">
          {zh
            ? '⚠ 数据覆盖不完整，这个排名可能有遗漏。'
            : '⚠ Coverage is incomplete, so this ranking may be missing rows.'}
        </p>
      ) : null}
    </section>
  );
}
