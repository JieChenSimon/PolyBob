import type { ReactNode } from 'react';

export type StatusTone = 'ok' | 'warn' | 'danger' | 'neutral' | 'accent';

const toneClasses: Record<StatusTone, string> = {
  ok: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  warn: 'bg-amber-50 text-amber-700 border-amber-200',
  danger: 'bg-rose-50 text-rose-700 border-rose-200',
  neutral: 'bg-stone-100 text-stone-600 border-stone-200',
  accent: 'bg-sky-50 text-sky-700 border-sky-200',
};

/**
 * Semantic status pill. Status honesty: stale/unknown/not-configured
 * data must be badged (warn/neutral) instead of looking like a healthy
 * zero.
 */
export default function StatusBadge({
  tone = 'neutral',
  children,
  className = '',
}: {
  tone?: StatusTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium ${toneClasses[tone]} ${className}`.trim()}
    >
      {children}
    </span>
  );
}

/** Map a portfolio/freshness status string to a badge tone. */
export function statusTone(status: string | null | undefined): StatusTone {
  switch (status) {
    case 'ready':
    case 'ok':
    case 'healthy':
    case 'running':
      return 'ok';
    case 'stale':
    case 'degraded':
    case 'warning':
      return 'warn';
    case 'error':
    case 'critical':
    case 'unavailable':
      return 'danger';
    default:
      return 'neutral';
  }
}
