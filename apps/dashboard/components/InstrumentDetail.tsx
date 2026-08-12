'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import USEquityAdvisor from '@/components/USEquityAdvisor';
import VerdictBanner from '@/components/VerdictBanner';
import WisdomSignalPanel from '@/components/WisdomSignalPanel';
import ForecastLabPanel from '@/components/ForecastLabPanel';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

interface FiringInstrument {
  symbol: string;
  direction: string | null;
  fired_on: string | null;
  evidence_zh: string;
  evidence_en: string;
}

interface EdgeGroup {
  strategy: string;
  domain: string;
  role: string;
  win_rate: number | null;
  mean_excess_pct: number | null;
  n: number | null;
  instruments: FiringInstrument[];
}

const BACK_LABEL: Record<string, { href: string; zh: string; en: string }> = {
  us_equity: { href: '/us-equities', zh: '← 返回股票观察', en: '← Back to equities' },
  a_share: { href: '/markets', zh: '← 返回市场观察', en: '← Back to markets' },
  altcoin: { href: '/crypto', zh: '← 返回加密货币', en: '← Back to crypto' },
};

/**
 * One instrument's own page: the verdict lives here.
 *
 * The verdict is an instrument-level judgement — "do I understand *this* one, and
 * am I about to make a mistake on *this* one" — so it belongs on that
 * instrument's page. It used to sit at the top of a category tab with a
 * hardcoded default symbol, which meant the most consequential panel in the
 * product was answering a question about a stock you were not looking at.
 *
 * The journal shortcut is here rather than on the category page for the same
 * reason: you log a trade on an instrument, not on a market.
 */
export default function InstrumentDetail({
  symbol,
  domain,
}: {
  symbol: string;
  domain: string;
}) {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const back = BACK_LABEL[domain] ?? BACK_LABEL.us_equity;
  // Equity domains render the full detail panel below, and that panel carries the
  // verdict itself, directly above 核心结论. Keep the two in step here so the
  // banner appears exactly once.
  const hasEmbeddedVerdict = domain === 'us_equity' || domain === 'a_share';

  const firing = useQuery<{ groups: EdgeGroup[] }>({
    queryKey: ['edges-firing'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/edges/firing`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    refetchInterval: 300_000,
    staleTime: 240_000,
  });

  // Which edges are firing on *this* instrument right now, with the measured
  // numbers attached, so the page can offer to log the trade with the evidence
  // already filled in.
  const hits = (firing.data?.groups ?? []).flatMap((group) =>
    group.instruments
      .filter((item) => item.symbol.toUpperCase() === symbol.toUpperCase())
      .map((item) => ({ group, item })),
  );
  const tradable = hits.filter(({ group }) => group.role === 'trade');

  return (
    <>
      <div className="mx-auto w-full max-w-shell px-5 pt-6 md:px-8">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <Link
              href={back.href}
              className="text-xs text-stone-500 underline decoration-stone-300 hover:text-stone-800"
            >
              {zh ? back.zh : back.en}
            </Link>
            <h1 className="mt-1 font-mono text-3xl font-bold tracking-[-0.02em] text-stone-950">
              {symbol}
            </h1>
          </div>
          <Link
            href="/journal"
            className="rounded border border-stone-300 px-3 py-1.5 text-xs font-medium text-stone-700 transition hover:border-stone-500 hover:bg-stone-50"
          >
            {zh ? '交易日志' : 'Trade journal'}
          </Link>
        </div>

        {tradable.length > 0 ? (
          <div className="mb-4 rounded-lg border-2 border-emerald-300 bg-emerald-50 px-4 py-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-emerald-800">
              {zh ? '本标的当前的最佳机会' : "This instrument's best opportunity"}
            </div>
            {tradable.map(({ group, item }) => (
              <div key={group.strategy} className="mt-1.5">
                <p className="text-sm leading-6 text-emerald-950">
                  {zh ? item.evidence_zh : item.evidence_en}
                </p>
                <p className="mt-0.5 text-[11px] text-emerald-800">
                  {group.strategy}
                  {group.win_rate !== null
                    ? zh
                      ? ` · 实测胜率 ${(group.win_rate * 100).toFixed(1)}%`
                      : ` · measured win ${(group.win_rate * 100).toFixed(1)}%`
                    : ''}
                  {group.mean_excess_pct !== null
                    ? ` · ${group.mean_excess_pct > 0 ? '+' : ''}${group.mean_excess_pct.toFixed(2)}%`
                    : ''}
                  {group.n !== null ? ` · n=${group.n.toLocaleString()}` : ''}
                </p>
              </div>
            ))}
          </div>
        ) : null}

        {/* The verdict, for this instrument, on this instrument's page.
            For equity domains it is rendered *inside* the detail panel instead —
            directly above 核心结论 / 加仓观察区 / 减仓观察区, where the judgement
            belongs next to the numbers it is judging. Rendering it here as well
            put the same panel on screen twice. */}
        {hasEmbeddedVerdict ? null : <VerdictBanner symbol={symbol} domain={domain} />}
      </div>

      {/* The full instrument view — real quote, chart, moving averages, order
          book and technical read. An earlier revision of this page carried only
          the verdict, which meant clicking a name in the watchlist replaced all
          of that with a near-empty page. The panels below are the reason you
          opened the instrument at all. */}
      {hasEmbeddedVerdict ? (
        <div className="mx-auto w-full max-w-shell px-5 md:px-8">
          <USEquityAdvisor symbol={symbol} hideList />
        </div>
      ) : null}

      <div className="mx-auto w-full max-w-shell px-5 pb-10 md:px-8">
        <ForecastLabPanel symbol={symbol} domain={domain} />
        <WisdomSignalPanel symbol={symbol} domain={domain} />
      </div>
    </>
  );
}
