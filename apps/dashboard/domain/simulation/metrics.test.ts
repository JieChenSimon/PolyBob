import { describe, expect, it } from 'vitest';

import {
  MIN_RELIABLE_TRADES,
  allowedRunActions,
  formatSignedRatioPercent,
  hasReliableSample,
  parseUniverseInput,
  runStatusTone,
  signedMetricTone,
  toEpochMs,
} from './metrics';

describe('simulation sample honesty', () => {
  it('flags thin or missing samples as unreliable', () => {
    expect(hasReliableSample(null)).toBe(false);
    expect(hasReliableSample(undefined)).toBe(false);
    expect(hasReliableSample(0)).toBe(false);
    expect(hasReliableSample(MIN_RELIABLE_TRADES - 1)).toBe(false);
    expect(hasReliableSample(MIN_RELIABLE_TRADES)).toBe(true);
    expect(hasReliableSample(500)).toBe(true);
  });
});

describe('simulation status semantics', () => {
  it('maps status to badge tones (running=ok, paused=warn, stopped=neutral)', () => {
    expect(runStatusTone('running')).toBe('ok');
    expect(runStatusTone('paused')).toBe('warn');
    expect(runStatusTone('stopped')).toBe('neutral');
    expect(runStatusTone(undefined)).toBe('neutral');
  });

  it('gates lifecycle actions by current status', () => {
    expect(allowedRunActions('running')).toEqual({ start: false, pause: true, stop: true });
    expect(allowedRunActions('paused')).toEqual({ start: true, pause: false, stop: true });
    expect(allowedRunActions('stopped')).toEqual({ start: true, pause: false, stop: false });
    expect(allowedRunActions(null)).toEqual({ start: false, pause: false, stop: false });
  });
});

describe('simulation metric formatting', () => {
  it('renders signed percentages from 0-1 ratios and "--" for missing values', () => {
    expect(formatSignedRatioPercent(0.1234)).toBe('+12.34%');
    expect(formatSignedRatioPercent(-0.056)).toBe('-5.60%');
    expect(formatSignedRatioPercent(0)).toBe('+0.00%');
    expect(formatSignedRatioPercent(null)).toBe('--');
    expect(formatSignedRatioPercent(undefined)).toBe('--');
    expect(formatSignedRatioPercent(Number.NaN)).toBe('--');
  });

  it('picks stat tones without faking missing data as neutral zero', () => {
    expect(signedMetricTone(0.2)).toBe('positive');
    expect(signedMetricTone(-0.1)).toBe('negative');
    expect(signedMetricTone(0)).toBe('default');
    expect(signedMetricTone(null)).toBe('muted');
  });
});

describe('universe input parsing', () => {
  it('splits on commas/whitespace, trims, and de-duplicates', () => {
    expect(parseUniverseInput('BTCUSDT, ETHUSDT,  SOLUSDT')).toEqual([
      'BTCUSDT',
      'ETHUSDT',
      'SOLUSDT',
    ]);
    expect(parseUniverseInput('BTCUSDT BTCUSDT,\nETHUSDT,')).toEqual(['BTCUSDT', 'ETHUSDT']);
    expect(parseUniverseInput('  ,, ')).toEqual([]);
  });
});

describe('equity timestamp normalization', () => {
  it('handles epoch seconds, epoch ms, and ISO strings', () => {
    expect(toEpochMs(1_700_000_000)).toBe(1_700_000_000_000);
    expect(toEpochMs(1_700_000_000_000)).toBe(1_700_000_000_000);
    expect(toEpochMs('2026-07-21T00:00:00Z')).toBe(Date.parse('2026-07-21T00:00:00Z'));
  });
});
