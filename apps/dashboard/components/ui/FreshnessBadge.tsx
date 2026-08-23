import type { ReactNode } from 'react';

export type FreshnessTone = 'ok' | 'warn' | 'danger' | 'neutral';

const toneClasses: Record<FreshnessTone, string> = {
  ok: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  warn: 'border-amber-200 bg-amber-50 text-amber-700',
  danger: 'border-rose-200 bg-rose-50 text-rose-700',
  neutral: 'border-stone-200 bg-stone-100 text-stone-600',
};

const dotClasses: Record<FreshnessTone, string> = {
  ok: 'bg-emerald-500',
  warn: 'bg-amber-500',
  danger: 'bg-rose-500',
  neutral: 'bg-stone-400',
};

export interface FreshnessBadgeProps {
  /** Provider / feed name, e.g. "Binance". Rendered upper-cased. */
  source?: string | null;
  /** Age of the reading in milliseconds. Takes precedence over `timestamp`. */
  ageMs?: number | null;
  /** ISO string or epoch ms; age is derived from it when `ageMs` is absent. */
  timestamp?: string | number | null;
  /** Backend health string (ok / degraded / stale / unavailable / unknown). */
  status?: string | null;
  /** Age at or below which the feed is considered healthy (green). */
  freshMs?: number;
  /** Age above which the feed is flagged stale (amber). */
  staleMs?: number;
  /** Override the computed age text entirely. */
  label?: ReactNode;
  language?: 'zh' | 'en';
  className?: string;
}

/** Compact, locale-light age string: 230ms · 2s · 3m · 1h · 2d. */
export function formatAge(ageMs: number | null | undefined): string | null {
  if (ageMs === null || ageMs === undefined || Number.isNaN(ageMs)) {
    return null;
  }
  const ms = Math.max(0, ageMs);
  if (ms < 1000) {
    return `${Math.round(ms)}ms`;
  }
  if (ms < 60_000) {
    return `${Math.round(ms / 1000)}s`;
  }
  if (ms < 3_600_000) {
    return `${Math.round(ms / 60_000)}m`;
  }
  if (ms < 86_400_000) {
    return `${Math.round(ms / 3_600_000)}h`;
  }
  return `${Math.round(ms / 86_400_000)}d`;
}

function statusToTone(status: string | null | undefined): FreshnessTone | null {
  switch (status) {
    case 'ok':
    case 'healthy':
    case 'live':
      return 'ok';
    case 'stale':
    case 'degraded':
    case 'warning':
      return 'warn';
    case 'error':
    case 'critical':
    case 'unavailable':
      return 'danger';
    case 'unknown':
      return 'neutral';
    default:
      return null;
  }
}

function statusLabel(status: string | null | undefined, language: 'zh' | 'en'): string | null {
  const labels = language === 'zh'
    ? { realtime: '实时', delayed: '延迟', stale: '旧快照', last_close: '最后收盘', unknown: '未知' }
    : { realtime: 'realtime', delayed: 'delayed', stale: 'stale snapshot', last_close: 'last close', unknown: 'unknown' };
  return status && status in labels ? labels[status as keyof typeof labels] : null;
}

function ageToTone(ageMs: number | null, freshMs: number, staleMs: number): FreshnessTone {
  if (ageMs === null) {
    return 'neutral';
  }
  if (ageMs <= freshMs) {
    return 'ok';
  }
  if (ageMs <= staleMs) {
    return 'neutral';
  }
  return 'warn';
}

const severity: Record<FreshnessTone, number> = { ok: 0, neutral: 1, warn: 2, danger: 3 };

/**
 * Provenance + freshness pill. Surfaces where a displayed number came from
 * and how recently it updated so stale/degraded data never looks
 * authoritative. Combines an explicit backend `status` with an age-based
 * heuristic and renders the worse of the two tones.
 */
export default function FreshnessBadge({
  source,
  ageMs,
  timestamp,
  status,
  freshMs = 5_000,
  staleMs = 30_000,
  label,
  language = 'zh',
  className = '',
}: FreshnessBadgeProps) {
  let resolvedAge: number | null = ageMs ?? null;
  if (resolvedAge === null && timestamp !== null && timestamp !== undefined) {
    const then = typeof timestamp === 'number' ? timestamp : Date.parse(timestamp);
    if (!Number.isNaN(then)) {
      resolvedAge = Math.max(0, Date.now() - then);
    }
  }

  const statusTone = statusToTone(status);
  const ageTone = ageToTone(resolvedAge, freshMs, staleMs);
  const tone: FreshnessTone =
    statusTone && severity[statusTone] >= severity[ageTone] ? statusTone : ageTone;

  const explicitStatus = statusLabel(status, language);
  const ageText = label ?? explicitStatus ?? formatAge(resolvedAge);
  const sourceText = source ? source.toUpperCase() : null;

  if (!sourceText && ageText === null && !status) {
    return null;
  }

  const unavailable = tone === 'danger' && resolvedAge === null;
  const unknownText = language === 'zh' ? '无数据' : 'no data';
  const bodyText = ageText ?? (unavailable ? unknownText : explicitStatus ?? unknownText);

  const ariaAge = ageText ? (language === 'zh' ? `更新于 ${ageText}前` : `updated ${ageText} ago`) : '';
  const ariaLabel = [
    sourceText ? (language === 'zh' ? `数据源 ${sourceText}` : `source ${sourceText}`) : '',
    ariaAge,
  ]
    .filter(Boolean)
    .join(', ');

  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium ${toneClasses[tone]} ${className}`.trim()}
      title={ariaLabel || undefined}
      aria-label={ariaLabel || undefined}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotClasses[tone]}`} aria-hidden />
      {sourceText ? <span className="font-semibold">{sourceText}</span> : null}
      {sourceText && bodyText ? <span aria-hidden className="opacity-60">·</span> : null}
      {bodyText ? <span className="mono tabular-nums">{bodyText}</span> : null}
    </span>
  );
}
