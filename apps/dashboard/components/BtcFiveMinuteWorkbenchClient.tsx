'use client';

import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import BtcFiveMinuteMarketTerminal, { type TerminalPoint } from '@/components/BtcFiveMinuteMarketTerminal';
import BtcFiveMinuteWorkspace from '@/components/BtcFiveMinuteWorkspace';
import {
  buildUnavailableBtcFiveMinuteWorkbench,
  parseBtcFiveMinuteWorkbench,
  type BtcFiveMinuteWorkbench,
} from '@/domain/btcFiveMinute/workbench';
import { API_BASE } from '@/lib/config';

export default function BtcFiveMinuteWorkbenchClient({
  initialPayload,
  initialUpdatedAt,
}: {
  initialPayload?: unknown;
  initialUpdatedAt?: string | null;
} = {}) {
  const initialWorkbench = initialPayload === undefined ? undefined : parseBtcFiveMinuteWorkbench(initialPayload);
  const query = useQuery({
    queryKey: ['polymarket', 'btc-5m', 'workbench'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/polymarket/btc-5m/workbench`, { signal });
      return parseBtcFiveMinuteWorkbench(await response.json());
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

  return (
    <>
      <BtcFiveMinuteMarketTerminal workbench={smoothedWorkbench} history={history} />
      <BtcFiveMinuteWorkspace workbench={smoothedWorkbench} lastUpdated={lastUpdated} />
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
