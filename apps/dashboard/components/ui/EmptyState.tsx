import type { ReactNode } from 'react';

/**
 * Standard empty state: dashed border, "暂无数据"-style title plus a hint
 * explaining what would populate the section.
 */
export default function EmptyState({
  title,
  hint,
  className = '',
}: {
  title: ReactNode;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-lg border border-dashed border-stone-300 bg-stone-50 px-5 py-8 text-center ${className}`.trim()}
    >
      <div className="text-sm font-medium text-stone-600">{title}</div>
      {hint ? <div className="mx-auto mt-1 max-w-md text-xs leading-5 text-stone-500">{hint}</div> : null}
    </div>
  );
}
