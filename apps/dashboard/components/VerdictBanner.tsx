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

interface VerdictPayload {
  symbol: string;
  domain: string;
  verdict: 'act' | 'watch' | 'wait' | 'avoid';
  headline_zh: string;
  headline_en: string;
  checks: Check[];
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
