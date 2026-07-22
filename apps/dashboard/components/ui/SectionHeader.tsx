import type { ReactNode } from 'react';

/**
 * Section title inside a card: consistent size, optional caption and a
 * right-aligned slot for badges or actions.
 */
export default function SectionHeader({
  title,
  caption,
  right,
  className = '',
}: {
  title: ReactNode;
  caption?: ReactNode;
  right?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex flex-wrap items-start justify-between gap-3 ${className}`.trim()}>
      <div className="min-w-0">
        <h3 className="text-base font-bold tracking-[-0.02em] text-stone-900">{title}</h3>
        {caption ? <p className="mt-1 text-sm leading-5 text-stone-500">{caption}</p> : null}
      </div>
      {right ? <div className="flex shrink-0 items-center gap-2">{right}</div> : null}
    </div>
  );
}
