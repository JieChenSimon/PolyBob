/**
 * Shared loading skeleton. `variant="tiles"` renders a stat-tile grid,
 * `variant="rows"` renders stacked list rows.
 */
export default function LoadingSkeleton({
  variant = 'rows',
  count = 3,
  className = '',
}: {
  variant?: 'rows' | 'tiles';
  count?: number;
  className?: string;
}) {
  if (variant === 'tiles') {
    return (
      <div className={`grid gap-4 md:grid-cols-2 xl:grid-cols-4 ${className}`.trim()} aria-busy="true">
        {Array.from({ length: count }).map((_, index) => (
          <div key={index} className="metric-panel animate-pulse">
            <div className="h-3 w-24 rounded bg-stone-200" />
            <div className="mt-4 h-7 w-28 rounded bg-stone-200" />
            <div className="mt-3 h-3 w-36 rounded bg-stone-100" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className={`space-y-3 ${className}`.trim()} aria-busy="true">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="animate-pulse rounded-lg border border-stone-200 bg-white px-4 py-3">
          <div className="h-3 w-2/3 rounded bg-stone-200" />
          <div className="mt-2 h-3 w-4/5 rounded bg-stone-100" />
        </div>
      ))}
    </div>
  );
}
