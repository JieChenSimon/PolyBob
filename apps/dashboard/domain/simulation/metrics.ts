/**
 * Pure helpers for the simulation (模拟盘) workspace.
 *
 * Metric honesty rules live here so they can be unit tested:
 * missing values render "--" (never a fake zero), and thin samples
 * are flagged instead of presented as reliable statistics.
 */

import type { StatTone } from '@/components/ui/StatTile';
import type { StatusTone } from '@/components/ui/StatusBadge';

const EMPTY = '--';

export type SimulationRunStatus = 'running' | 'paused' | 'stopped';

/** Below this closed-trade count, ratio metrics are labelled unreliable. */
export const MIN_RELIABLE_TRADES = 20;

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** True when the closed-trade sample is large enough to trust ratios. */
export function hasReliableSample(tradeCount: number | null | undefined): boolean {
  return isNumber(tradeCount) && tradeCount >= MIN_RELIABLE_TRADES;
}

/** Badge tone for a run status: running=emerald, paused=amber, stopped=stone. */
export function runStatusTone(status: string | null | undefined): StatusTone {
  switch (status) {
    case 'running':
      return 'ok';
    case 'paused':
      return 'warn';
    case 'stopped':
      return 'neutral';
    default:
      return 'neutral';
  }
}

/**
 * Which lifecycle actions make sense for the current status.
 * start: anything not already running; pause: only running;
 * stop: anything not already stopped.
 */
export function allowedRunActions(status: string | null | undefined): {
  start: boolean;
  pause: boolean;
  stop: boolean;
} {
  return {
    start: status === 'paused' || status === 'stopped',
    pause: status === 'running',
    stop: status === 'running' || status === 'paused',
  };
}

/**
 * "+12.34%" / "-3.21%" from a 0-1 ratio (API returns fractional
 * returns/drawdowns), or "--" when missing.
 */
export function formatSignedRatioPercent(value: number | null | undefined, digits = 2): string {
  if (!isNumber(value)) {
    return EMPTY;
  }
  const pct = value * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(digits)}%`;
}

/** StatTile tone for a signed metric: positive/negative/muted(missing). */
export function signedMetricTone(value: number | null | undefined): StatTone {
  if (!isNumber(value)) {
    return 'muted';
  }
  if (value === 0) {
    return 'default';
  }
  return value > 0 ? 'positive' : 'negative';
}

/**
 * Parse a comma/whitespace separated universe input into a clean,
 * de-duplicated id list.
 */
export function parseUniverseInput(raw: string): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const part of raw.split(/[,\s]+/)) {
    const id = part.trim();
    if (id && !seen.has(id)) {
      seen.add(id);
      result.push(id);
    }
  }
  return result;
}

/** Normalize an equity-curve timestamp (epoch seconds, ms, or ISO) to ms. */
export function toEpochMs(ts: number | string): number {
  if (typeof ts === 'number') {
    return ts < 1e12 ? ts * 1000 : ts;
  }
  return new Date(ts).getTime();
}
