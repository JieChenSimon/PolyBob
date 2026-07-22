'use client';

import type { ReactNode } from 'react';

/**
 * Standard error state: amber/rose banner with the failure message and a
 * retry button wired to the query's refetch.
 */
export default function ErrorState({
  title,
  message,
  onRetry,
  retryLabel,
  className = '',
}: {
  title: ReactNode;
  message?: ReactNode;
  onRetry?: () => void;
  retryLabel?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 ${className}`.trim()}
      role="alert"
    >
      <div className="min-w-0">
        <div className="text-sm font-semibold text-rose-700">{title}</div>
        {message ? <div className="mt-0.5 text-xs text-rose-600">{message}</div> : null}
      </div>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-md border border-rose-300 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 transition hover:bg-rose-100"
        >
          {retryLabel ?? '重试'}
        </button>
      ) : null}
    </div>
  );
}
