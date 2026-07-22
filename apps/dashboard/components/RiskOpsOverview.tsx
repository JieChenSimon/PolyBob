'use client';

import { useQuery } from '@tanstack/react-query';
import { API_BASE } from '@/lib/config';
import ErrorState from '@/components/ui/ErrorState';
import { useLanguage } from '@/lib/i18n';
import { DistributionAlert, OnchainSummary, OnchainTransferEvent, OnchainWatchAddress } from '@/lib/types';

interface RiskSummary {
  alert_level: string;
  portfolio_status?: 'not_configured' | 'ready' | 'stale' | 'error';
  net_exposure: number | null;
  estimated_leverage: number | null;
  pnl?: number | null;
  pnl_pct?: number | null;
  open_baskets: number;
  open_intents: number;
  rejected_intents: number;
  residual_legs: number;
  onchain_alerts: number;
  critical_onchain_alerts: number;
  recent_cex_flow_usd: number;
  services: Array<{ name: string; status: string }>;
  notes: string[];
}

const RISK_OPS_REFETCH_MS = 20_000;
const RISK_OPS_STALE_MS = 16_000;

async function fetchJson<T>(path: string, signal: AbortSignal | undefined): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { signal });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

function useRiskOpsQuery<T>(key: string, fetcher: (signal: AbortSignal | undefined) => Promise<T>) {
  return useQuery<T>({
    queryKey: ['risk-ops', key],
    queryFn: ({ signal }) => fetcher(signal),
    refetchInterval: RISK_OPS_REFETCH_MS,
    staleTime: RISK_OPS_STALE_MS,
  });
}

export default function RiskOpsOverview() {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const summaryQuery = useRiskOpsQuery('summary', (signal) => fetchJson<RiskSummary>('/api/risk/summary', signal));
  const onchainQuery = useRiskOpsQuery('onchain-summary', (signal) => fetchJson<OnchainSummary>('/api/onchain/summary', signal));
  const watchlistQuery = useRiskOpsQuery('watchlists', async (signal) => {
    const payload = await fetchJson<{ watchlists?: OnchainWatchAddress[] }>('/api/onchain/watchlists', signal);
    return Array.isArray(payload.watchlists) ? payload.watchlists : [];
  });
  const alertQuery = useRiskOpsQuery('alerts', async (signal) => {
    const payload = await fetchJson<{ alerts?: DistributionAlert[] }>('/api/onchain/alerts?limit=8', signal);
    return Array.isArray(payload.alerts) ? payload.alerts : [];
  });
  const eventQuery = useRiskOpsQuery('events', async (signal) => {
    const payload = await fetchJson<{ events?: OnchainTransferEvent[] }>('/api/onchain/events?limit=8', signal);
    return Array.isArray(payload.events) ? payload.events : [];
  });
  const summary = summaryQuery.data ?? null;
  const onchainSummary = onchainQuery.data ?? null;
  const watchlists = watchlistQuery.data ?? [];
  const alerts = alertQuery.data ?? [];
  const events = eventQuery.data ?? [];

  return (
    <>
    {summaryQuery.isError ? (
      <ErrorState
        className="mb-5"
        title={zh ? '风险数据加载失败' : 'Failed to load risk data'}
        message={zh ? '无法连接 PolyBob API，以下指标显示为未知。' : 'Cannot reach the PolyBob API; metrics below show as unknown.'}
        onRetry={() => void summaryQuery.refetch()}
        retryLabel={zh ? '重试' : 'Retry'}
      />
    ) : null}
    <div className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr),minmax(0,1.1fr)]">
      <div className="grid gap-6">
        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            {zh ? '风险快照' : 'Risk Snapshot'}
          </div>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <Metric label={zh ? '告警级别' : 'Alert Level'} value={summary?.alert_level || (zh ? '未知' : 'unknown')} />
            <Metric label={zh ? '组合账本' : 'Portfolio'} value={formatPortfolioStatus(summary?.portfolio_status, zh)} />
            <Metric label={zh ? '净敞口' : 'Net Exposure'} value={formatOptionalNumber(summary?.net_exposure, 4)} />
            <Metric label={zh ? '估算杠杆' : 'Estimated Leverage'} value={formatOptionalNumber(summary?.estimated_leverage, 2)} />
            <Metric label={zh ? '盈亏' : 'PnL'} value={formatOptionalNumber(summary?.pnl, 2)} />
            <Metric label={zh ? '未处理意图' : 'Open Intents'} value={summary ? String(summary.open_intents) : '--'} />
            <Metric label={zh ? '已拒绝意图' : 'Rejected Intents'} value={summary ? String(summary.rejected_intents) : '--'} />
            <Metric label={zh ? '未完成 Basket' : 'Open Baskets'} value={summary ? String(summary.open_baskets) : '--'} />
            <Metric label={zh ? '残余腿' : 'Residual Legs'} value={summary ? String(summary.residual_legs) : '--'} />
            <Metric label={zh ? '链上告警' : 'Onchain Alerts'} value={summary ? String(summary.onchain_alerts) : '--'} />
            <Metric label={zh ? '严重链上' : 'Critical Onchain'} value={summary ? String(summary.critical_onchain_alerts) : '--'} />
            <Metric label={zh ? '近期 CEX 流量' : 'Recent CEX Flow'} value={summary ? formatUsd(summary.recent_cex_flow_usd) : '--'} />
            <Metric label={zh ? '服务数量' : 'Service Count'} value={summary ? String(summary.services.length) : '--'} />
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            {zh ? '链上分发监控' : 'Onchain Distribution Monitor'}
          </div>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <Metric label={zh ? '监控代币' : 'Watched Tokens'} value={onchainSummary ? String(onchainSummary.watched_tokens) : '--'} />
            <Metric label={zh ? '监控地址' : 'Watched Addresses'} value={onchainSummary ? String(onchainSummary.watched_addresses) : '--'} />
            <Metric label={zh ? '告警数量' : 'Alert Count'} value={onchainSummary ? String(onchainSummary.alert_count) : '--'} />
            <Metric label={zh ? '聚合窗口' : 'Window'} value={onchainSummary ? `${onchainSummary.cluster_window_minutes}m` : '--'} />
            <Metric label={zh ? '中转钱包' : 'Staging Wallets'} value={onchainSummary ? String(onchainSummary.pending_staging_wallets) : '--'} />
            <Metric label={zh ? '待确认中转金额' : 'Pending Staging'} value={onchainSummary ? formatUsd(onchainSummary.pending_staging_value_usd) : '--'} />
          </div>
          <div className="mt-5 rounded-lg bg-stone-50 px-4 py-4 text-sm leading-6 text-stone-600">
            {zh
              ? '这里展示平台级链上观察面：部署地址直接卖出、转向 CEX，以及“先转 staging wallet 再进 CEX”的两跳出货都会归入同一条风险线索。'
              : 'This is the platform onchain watch surface: direct deployer sells, CEX transfers, and two-hop staging-wallet distribution are grouped into the same risk trail.'}
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            {zh ? '监控地址' : 'Watch Addresses'}
          </div>
          <div className="mt-5 space-y-3">
            {watchlists.length ? (
              watchlists.slice(0, 6).map((watch) => (
                <div key={watch.watch_id} className="rounded-lg border border-stone-200 bg-stone-50 px-4 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold text-stone-900">{watch.label}</div>
                      <div className="mt-1 text-xs uppercase tracking-[0.12em] text-stone-500">
                        {watch.token_symbol} / {watch.chain} / {watch.entity_type}
                      </div>
                    </div>
                    <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-stone-700">
                      {watch.watch_id}
                    </span>
                  </div>
                  <div className="mono mt-3 text-xs text-stone-500">{watch.address}</div>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-stone-600">
                    <span className="rounded-full bg-white px-3 py-1">{zh ? '卖出阈值' : 'Sell'} {formatUsd(watch.sell_threshold_usd)}</span>
                    <span className="rounded-full bg-white px-3 py-1">CEX {formatUsd(watch.cex_transfer_threshold_usd)}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                {zh ? '暂无链上监控地址。' : 'No onchain watchlist loaded.'}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-6">
        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            {zh ? '最近告警' : 'Recent Alerts'}
          </div>
          <div className="mt-5 space-y-3">
            {alerts.length ? (
              alerts.map((alert) => (
                <div key={alert.alert_id} className="rounded-lg border border-stone-200 bg-stone-50 px-4 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold text-stone-900">{alert.title}</div>
                      <div className="mt-1 text-sm text-stone-600">{alert.summary}</div>
                    </div>
                    <span className={`rounded-full px-3 py-1 text-xs font-medium ${severityClass(alert.severity)}`}>
                      {alert.severity}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-2 text-sm text-stone-600">
                    <div>{alert.token_symbol} / {alert.chain} / {alert.alert_type}</div>
                    <div>{formatUsd(alert.usd_value)} {zh ? '至' : 'to'} {alert.counterparty || '--'}</div>
                    <div>{new Date(alert.created_at).toLocaleString()}</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                {zh ? '暂无分发告警。' : 'No distribution alerts yet.'}
              </div>
            )}
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            {zh ? '最近链上事件' : 'Recent Onchain Events'}
          </div>
          <div className="mt-5 space-y-3">
            {events.length ? (
              events.map((event) => (
                <div key={event.event_id} className="rounded-lg border border-stone-200 bg-stone-50 px-4 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold text-stone-900">
                        {event.token_symbol} / {event.chain}
                      </div>
                      <div className="mt-1 text-sm text-stone-600">
                        {shortAddress(event.from_address)} → {shortAddress(event.to_address)}
                      </div>
                    </div>
                    <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-stone-700">
                      {event.to_entity_type}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-2 text-sm text-stone-600">
                    <div>{formatUsd(event.usd_value)} / {event.source}</div>
                    <div>{new Date(event.block_time).toLocaleString()}</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                {zh ? '暂无链上事件。' : 'No onchain events yet.'}
              </div>
            )}
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            {zh ? '服务健康' : 'Service Health'}
          </div>
          <div className="mt-5 space-y-3">
            {summary?.services.map((service) => (
              <div key={service.name} className="flex items-center justify-between rounded-lg border border-stone-200 bg-stone-50 px-4 py-3">
                <span className="font-medium text-stone-900">{service.name}</span>
                <span className={`rounded-full px-3 py-1 text-xs font-medium ${serviceStatusClass(service.status)}`}>
                  {service.status}
                </span>
              </div>
            ))}
          </div>

          <div className="mt-6 rounded-lg bg-amber-50 px-4 py-4 text-sm text-amber-900">
            {(summary?.notes || []).join(' ') || (zh ? '暂无风险备注。' : 'No risk notes.')}
          </div>
        </div>
      </div>
    </div>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-panel">
      <div className="text-xs uppercase tracking-[0.12em] text-stone-500">{label}</div>
      <div className="mt-2 text-2xl font-bold tracking-[-0.04em] text-stone-900">{value}</div>
    </div>
  );
}

function formatUsd(value: number) {
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatOptionalNumber(value: number | null | undefined, digits: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '--';
}

function formatPortfolioStatus(value: RiskSummary['portfolio_status'] | undefined, zh: boolean) {
  if (value === 'ready') {
    return zh ? '已就绪' : 'ready';
  }
  if (value === 'stale') {
    return zh ? '已过期' : 'stale';
  }
  if (value === 'error') {
    return zh ? '错误' : 'error';
  }
  return zh ? '未配置' : 'not configured';
}

function serviceStatusClass(status: string) {
  if (status === 'ok' || status === 'healthy' || status === 'running') {
    return 'border border-emerald-200 bg-emerald-50 text-emerald-700';
  }
  if (status === 'degraded' || status === 'stale' || status === 'warning') {
    return 'border border-amber-200 bg-amber-50 text-amber-700';
  }
  if (status === 'error' || status === 'down' || status === 'unavailable') {
    return 'border border-rose-200 bg-rose-50 text-rose-700';
  }
  return 'border border-stone-200 bg-stone-100 text-stone-600';
}

function severityClass(severity: string) {
  if (severity === 'critical') {
    return 'border border-rose-200 bg-rose-50 text-rose-700';
  }
  if (severity === 'high') {
    return 'border border-amber-200 bg-amber-50 text-amber-700';
  }
  return 'border border-stone-200 bg-stone-100 text-stone-600';
}

function shortAddress(value: string) {
  if (value.length <= 12) {
    return value;
  }
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}
