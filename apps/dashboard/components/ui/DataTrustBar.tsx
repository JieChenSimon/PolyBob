'use client';

import FreshnessBadge from '@/components/ui/FreshnessBadge';
import { useLanguage } from '@/lib/i18n';

export type DataTrustState = 'available' | 'degraded' | 'unknown' | 'blocked' | 'disabled';

export default function DataTrustBar({
  source,
  observedAt,
  state,
  reason,
  staleMs = 60_000,
}: {
  source?: string | null;
  observedAt?: string | null;
  state: DataTrustState;
  reason?: string | null;
  staleMs?: number;
}) {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const statusLabel = {
    available: zh ? '可用' : 'available',
    degraded: zh ? '降级' : 'degraded',
    unknown: 'UNKNOWN',
    blocked: zh ? '已阻断' : 'blocked',
    disabled: zh ? '已关闭' : 'disabled',
  }[state];
  return (
    <div className={`data-trust-bar data-trust-${state}`} role="status">
      <span className="data-trust-label">{zh ? '数据可信度' : 'DATA TRUST'}</span>
      <span className="data-trust-state">{statusLabel}</span>
      <FreshnessBadge
        source={source}
        timestamp={observedAt}
        status={state === 'available' ? undefined : state === 'blocked' ? 'critical' : state === 'disabled' ? 'unknown' : state}
        staleMs={staleMs}
      />
      {reason ? <span className="data-trust-reason" title={reason}>{reason}</span> : null}
    </div>
  );
}
