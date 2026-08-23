'use client';

import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import BtcFiveMinuteMarketTerminal, { type TerminalPoint } from '@/components/BtcFiveMinuteMarketTerminal';
import BtcFiveMinuteWorkspace from '@/components/BtcFiveMinuteWorkspace';
import BtcIndicatorSettings from '@/components/BtcIndicatorSettings';
import {
  buildUnavailableBtcFiveMinuteWorkbench,
  parseBtcFiveMinuteWorkbench,
  type BtcFiveMinuteWorkbench,
} from '@/domain/btcFiveMinute/workbench';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

const INDICATORS_STORAGE_KEY = 'btc5m.indicators';

function loadStoredIndicators(): string[] | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(INDICATORS_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) && parsed.length ? parsed.map(String) : null;
  } catch {
    return null;
  }
}

export default function BtcFiveMinuteWorkbenchClient({
  initialPayload,
  initialUpdatedAt,
}: {
  initialPayload?: unknown;
  initialUpdatedAt?: string | null;
} = {}) {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const [indicators, setIndicators] = useState<string[] | null>(() => loadStoredIndicators());
  const [settingsOpen, setSettingsOpen] = useState(false);

  const initialWorkbench = initialPayload === undefined ? undefined : parseBtcFiveMinuteWorkbench(initialPayload);
  const query = useQuery({
    queryKey: ['polymarket', 'btc-5m', 'workbench', indicators?.join(',') ?? 'default'],
    queryFn: async ({ signal }) => {
      const qs = indicators && indicators.length ? `?indicators=${encodeURIComponent(indicators.join(','))}` : '';
      const response = await fetch(`${API_BASE}/api/polymarket/btc-5m/workbench${qs}`, { signal });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = payload && typeof payload === 'object' && 'detail' in payload
          ? String(payload.detail)
          : `HTTP ${response.status}`;
        throw new Error(detail);
      }
      return parseBtcFiveMinuteWorkbench(payload);
    },
    initialData: initialWorkbench,
    initialDataUpdatedAt: initialUpdatedAt ? Date.parse(initialUpdatedAt) : undefined,
    // Near-real-time: poll faster and refetch on focus so the 5-minute window
    // (where the last seconds matter) stays live.
    refetchInterval: 1_500,
    staleTime: 1_000,
    refetchOnWindowFocus: true,
  });
  const [history, setHistory] = useState<TerminalPoint[]>(() => {
    if (initialWorkbench === undefined) {
      return [];
    }
    return [{
      timestamp: 0,
      price: typeof initialWorkbench.btc_reference?.price === 'number' ? initialWorkbench.btc_reference.price : null,
      upProbability: midpoint(initialWorkbench.outcomes.UP.best_bid, initialWorkbench.outcomes.UP.best_ask),
    }];
  });
  const lastHistoryUpdate = useRef(query.dataUpdatedAt);

  useEffect(() => {
    if (!query.data || query.dataUpdatedAt === 0 || query.dataUpdatedAt === lastHistoryUpdate.current) {
      return;
    }
    lastHistoryUpdate.current = query.dataUpdatedAt;
    setHistory((previous) => [
      ...previous,
      {
        timestamp: query.dataUpdatedAt,
        price: typeof query.data.btc_reference?.price === 'number' ? query.data.btc_reference.price : null,
        upProbability: midpoint(query.data.outcomes.UP.best_bid, query.data.outcomes.UP.best_ask),
      },
    ].slice(-80));
  }, [query.data, query.dataUpdatedAt]);

  const workbench: BtcFiveMinuteWorkbench | null = query.data
    ?? (query.error ? buildUnavailableBtcFiveMinuteWorkbench(query.error) : null);
  const lastUpdated = query.dataUpdatedAt > 0
    ? new Date(query.dataUpdatedAt).toLocaleTimeString()
    : formatInitialUpdatedAt(initialUpdatedAt);

  // 1s wall-clock tick used only to smooth the expiry countdown between polls.
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 1_000);
    return () => clearInterval(id);
  }, []);

  // Tick the expiry countdown down locally each second from the last server
  // snapshot, so it reads as live instead of stepping by the poll interval.
  const smoothedWorkbench = useMemo(() => {
    if (!workbench || typeof workbench.seconds_to_expiry !== 'number' || query.dataUpdatedAt <= 0) {
      return workbench;
    }
    const elapsed = Math.max(0, (nowMs - query.dataUpdatedAt) / 1000);
    const remaining = Math.max(0, Math.round(workbench.seconds_to_expiry - elapsed));
    if (remaining === workbench.seconds_to_expiry) {
      return workbench;
    }
    return { ...workbench, seconds_to_expiry: remaining };
  }, [workbench, query.dataUpdatedAt, nowMs]);

  const activeCount = indicators?.length ?? null;

  return (
    <>
      <div className="mx-auto mb-3 flex w-full max-w-shell justify-end px-5 md:px-8">
        <button
          type="button"
          onClick={() => setSettingsOpen(true)}
          className="rounded-md border border-stone-200 bg-white px-3 py-1.5 text-xs font-medium text-stone-600 transition hover:border-sky-300 hover:text-sky-700"
        >
          {zh ? '⚙︎ 预测指标' : '⚙︎ Indicators'}
          <span className="ml-1.5 text-stone-400">
            {activeCount === null ? (zh ? '默认' : 'default') : `${activeCount}`}
          </span>
        </button>
      </div>
      <BtcFiveMinuteMarketTerminal workbench={smoothedWorkbench} history={history} />
      <BtcFiveMinuteWorkspace workbench={smoothedWorkbench} lastUpdated={lastUpdated} />
      <BtcIndicatorSettings
        open={settingsOpen}
        selected={indicators}
        onClose={() => setSettingsOpen(false)}
        onSave={(ids) => {
          setIndicators(ids);
          try {
            if (ids) window.localStorage.setItem(INDICATORS_STORAGE_KEY, JSON.stringify(ids));
            else window.localStorage.removeItem(INDICATORS_STORAGE_KEY);
          } catch {
            /* ignore storage errors */
          }
          setSettingsOpen(false);
        }}
      />
    </>
  );
}

function midpoint(bid: number | null, ask: number | null) {
  if (bid === null || ask === null) {
    return null;
  }
  return (bid + ask) / 2;
}

function formatInitialUpdatedAt(value: string | null | undefined) {
  if (!value) {
    return null;
  }
  return value.replace('T', ' ').replace(/\.\d+Z$/, 'Z');
}
