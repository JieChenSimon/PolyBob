'use client';

import { useEffect, useState } from 'react';
import { API_BASE } from '@/lib/config';
import { DistributionAlert, OnchainSummary, OnchainTransferEvent, OnchainWatchAddress } from '@/lib/types';

interface RiskSummary {
  alert_level: string;
  net_exposure: number;
  estimated_leverage: number;
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

export default function RiskOpsOverview() {
  const [summary, setSummary] = useState<RiskSummary | null>(null);
  const [onchainSummary, setOnchainSummary] = useState<OnchainSummary | null>(null);
  const [watchlists, setWatchlists] = useState<OnchainWatchAddress[]>([]);
  const [alerts, setAlerts] = useState<DistributionAlert[]>([]);
  const [events, setEvents] = useState<OnchainTransferEvent[]>([]);

  useEffect(() => {
    const fetchSummary = async () => {
      try {
        const [summaryResponse, onchainResponse, watchlistResponse, alertResponse, eventResponse] = await Promise.all([
          fetch(`${API_BASE}/api/risk/summary`),
          fetch(`${API_BASE}/api/onchain/summary`),
          fetch(`${API_BASE}/api/onchain/watchlists`),
          fetch(`${API_BASE}/api/onchain/alerts?limit=8`),
          fetch(`${API_BASE}/api/onchain/events?limit=8`),
        ]);
        const summaryPayload = await summaryResponse.json();
        const onchainPayload = await onchainResponse.json();
        const watchlistPayload = await watchlistResponse.json();
        const alertPayload = await alertResponse.json();
        const eventPayload = await eventResponse.json();

        setSummary(summaryPayload);
        setOnchainSummary(onchainPayload);
        setWatchlists(Array.isArray(watchlistPayload.watchlists) ? watchlistPayload.watchlists : []);
        setAlerts(Array.isArray(alertPayload.alerts) ? alertPayload.alerts : []);
        setEvents(Array.isArray(eventPayload.events) ? eventPayload.events : []);
      } catch (error) {
        console.error('Failed to fetch risk summary:', error);
      }
    };

    fetchSummary();
    const interval = window.setInterval(fetchSummary, 10000);
    return () => window.clearInterval(interval);
  }, []);

  return (
    <div className="grid gap-6 xl:grid-cols-[0.9fr,1.1fr]">
      <div className="grid gap-6">
        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            Risk Snapshot
          </div>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <Metric label="Alert Level" value={summary?.alert_level || 'unknown'} />
            <Metric label="Net Exposure" value={summary ? summary.net_exposure.toFixed(4) : '--'} />
            <Metric label="Estimated Leverage" value={summary ? summary.estimated_leverage.toFixed(2) : '--'} />
            <Metric label="Open Intents" value={summary ? String(summary.open_intents) : '--'} />
            <Metric label="Rejected Intents" value={summary ? String(summary.rejected_intents) : '--'} />
            <Metric label="Open Baskets" value={summary ? String(summary.open_baskets) : '--'} />
            <Metric label="Residual Legs" value={summary ? String(summary.residual_legs) : '--'} />
            <Metric label="Onchain Alerts" value={summary ? String(summary.onchain_alerts) : '--'} />
            <Metric label="Critical Onchain" value={summary ? String(summary.critical_onchain_alerts) : '--'} />
            <Metric label="Recent CEX Flow" value={summary ? formatUsd(summary.recent_cex_flow_usd) : '--'} />
            <Metric label="Service Count" value={summary ? String(summary.services.length) : '--'} />
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            Onchain Distribution Monitor
          </div>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <Metric label="Watched Tokens" value={onchainSummary ? String(onchainSummary.watched_tokens) : '--'} />
            <Metric label="Watched Addresses" value={onchainSummary ? String(onchainSummary.watched_addresses) : '--'} />
            <Metric label="Alert Count" value={onchainSummary ? String(onchainSummary.alert_count) : '--'} />
            <Metric label="Window" value={onchainSummary ? `${onchainSummary.cluster_window_minutes}m` : '--'} />
            <Metric label="Staging Wallets" value={onchainSummary ? String(onchainSummary.pending_staging_wallets) : '--'} />
            <Metric label="Pending Staging" value={onchainSummary ? formatUsd(onchainSummary.pending_staging_value_usd) : '--'} />
          </div>
          <div className="mt-5 rounded-2xl bg-stone-50 px-4 py-4 text-sm leading-6 text-stone-600">
            这块现在是平台级链上观察面。后续只要把标准化转账事件持续送进 `/api/onchain/events`，
            就能监控部署地址直接卖出、转向 CEX，以及“先转 staging wallet 再进 CEX”的两跳出货。
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            Watch Addresses
          </div>
          <div className="mt-5 space-y-3">
            {watchlists.length ? (
              watchlists.slice(0, 6).map((watch) => (
                <div key={watch.watch_id} className="rounded-2xl border border-stone-200 bg-stone-50 px-4 py-4">
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
                    <span className="rounded-full bg-white px-3 py-1">Sell {formatUsd(watch.sell_threshold_usd)}</span>
                    <span className="rounded-full bg-white px-3 py-1">CEX {formatUsd(watch.cex_transfer_threshold_usd)}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                No onchain watchlist loaded.
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-6">
        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            Recent Alerts
          </div>
          <div className="mt-5 space-y-3">
            {alerts.length ? (
              alerts.map((alert) => (
                <div key={alert.alert_id} className="rounded-2xl border border-stone-200 bg-stone-50 px-4 py-4">
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
                    <div>{formatUsd(alert.usd_value)} to {alert.counterparty || '--'}</div>
                    <div>{new Date(alert.created_at).toLocaleString()}</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                No distribution alerts yet.
              </div>
            )}
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            Recent Onchain Events
          </div>
          <div className="mt-5 space-y-3">
            {events.length ? (
              events.map((event) => (
                <div key={event.event_id} className="rounded-2xl border border-stone-200 bg-stone-50 px-4 py-4">
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
              <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 px-4 py-8 text-sm text-stone-500">
                No onchain events yet.
              </div>
            )}
          </div>
        </div>

        <div className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">
            Service Health
          </div>
          <div className="mt-5 space-y-3">
            {summary?.services.map((service) => (
              <div key={service.name} className="flex items-center justify-between rounded-2xl border border-stone-200 bg-stone-50 px-4 py-3">
                <span className="font-medium text-stone-900">{service.name}</span>
                <span className="rounded-full bg-stone-900 px-3 py-1 text-xs font-medium text-white">
                  {service.status}
                </span>
              </div>
            ))}
          </div>

          <div className="mt-6 rounded-2xl bg-amber-50 px-4 py-4 text-sm text-amber-900">
            {(summary?.notes || []).join(' ')}
          </div>
        </div>
      </div>
    </div>
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

function severityClass(severity: string) {
  if (severity === 'critical') {
    return 'bg-rose-600 text-white';
  }
  if (severity === 'high') {
    return 'bg-amber-500 text-white';
  }
  return 'bg-stone-200 text-stone-800';
}

function shortAddress(value: string) {
  if (value.length <= 12) {
    return value;
  }
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}
