'use client';

import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
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
    refetchInterval: 3_000,
    staleTime: 2_000,
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

  return (
    <>
      <BtcFiveMinuteMarketTerminal workbench={workbench} history={history} />
      <BtcFiveMinuteWorkspace workbench={workbench} lastUpdated={lastUpdated} />
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
