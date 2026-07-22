import { describe, expect, it } from 'vitest';

import { appendNavigationMetric } from './navigationMetrics';

describe('navigation metrics', () => {
  it('keeps only the most recent bounded samples', () => {
    const metrics = Array.from({ length: 20 }, (_, index) => ({
      from: `/from-${index}`,
      to: `/to-${index}`,
      durationMs: index,
      recordedAt: index,
    }));

    const next = appendNavigationMetric(metrics, {
      from: '/from-new',
      to: '/to-new',
      durationMs: 42,
      recordedAt: 42,
    });

    expect(next).toHaveLength(20);
    expect(next[0].from).toBe('/from-1');
    expect(next.at(-1)?.durationMs).toBe(42);
  });
});
