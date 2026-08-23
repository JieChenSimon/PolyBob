'use client';

import { useQuery } from '@tanstack/react-query';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';
import { OverviewPayload } from '@/lib/types';
import OverviewSummary from '@/components/OverviewSummary';
import PersonalBrief from '@/components/PersonalBrief';
import ErrorState from '@/components/ui/ErrorState';
import LoadingSkeleton from '@/components/ui/LoadingSkeleton';

export default function OverviewWorkspace() {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const overviewQuery = useQuery<OverviewPayload>({
    queryKey: ['overview'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/overview`, { signal });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.json();
    },
    refetchInterval: 15_000,
    staleTime: 12_000,
  });
  const overview = overviewQuery.data ?? null;

  if (overviewQuery.isLoading && !overview) {
    return (
      <div aria-busy="true" aria-live="polite" className="space-y-5">
        <LoadingSkeleton variant="rows" count={2} />
        <LoadingSkeleton variant="tiles" count={4} />
      </div>
    );
  }

  return (
    <>
      {overviewQuery.isError ? (
        <ErrorState
          className="mb-5"
          title={zh ? '简报数据加载失败' : 'Failed to load the daily brief'}
          message={zh ? '无法连接 PolyBob API，相关状态为未知；请先恢复连接。' : 'Cannot reach the PolyBob API; affected states are UNKNOWN until the connection is restored.'}
          onRetry={() => void overviewQuery.refetch()}
          retryLabel={zh ? '重试' : 'Retry'}
        />
      ) : null}

      <PersonalBrief overview={overview} />

      <div className="mt-5">
        <OverviewSummary overview={overview} />
      </div>
    </>
  );
}
