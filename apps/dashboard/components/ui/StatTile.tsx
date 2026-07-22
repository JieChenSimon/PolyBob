import type { ReactNode } from 'react';

export type StatTone = 'default' | 'positive' | 'negative' | 'warning' | 'accent' | 'muted';

const valueTone: Record<StatTone, string> = {
  default: 'text-stone-900',
  positive: 'text-emerald-600',
  negative: 'text-rose-600',
  warning: 'text-amber-600',
  accent: 'text-sky-700',
  muted: 'text-stone-400',
};

/**
 * Uniform stat tile: caption label, large tabular value, optional detail
 * line and badge. Every metric grid across the app should use it.
 */
export default function StatTile({
  label,
  value,
  detail,
  tone = 'default',
  badge,
  size = 'md',
}: {
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
  tone?: StatTone;
  badge?: ReactNode;
  size?: 'md' | 'lg';
}) {
  return (
    <div className="metric-panel">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-stone-500">
          {label}
        </div>
        {badge}
      </div>
      <div
        className={`mt-2 truncate font-bold tracking-[-0.02em] ${valueTone[tone]} ${
          size === 'lg' ? 'text-3xl' : 'text-2xl'
        }`}
      >
        {value}
      </div>
      {detail ? <div className="mt-1 truncate text-sm text-stone-500">{detail}</div> : null}
    </div>
  );
}
