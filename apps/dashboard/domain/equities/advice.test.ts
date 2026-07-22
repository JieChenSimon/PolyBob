import { describe, expect, it } from 'vitest';
import { buildTechnicalAdvice } from './advice';

const text = {
  unavailableHeadline: 'Insufficient data',
  unavailableRationale: 'No quote.',
  holdHeadline: 'Hold / Watch',
  holdRationale: 'Hold.',
  riskTrimHeadline: 'Risk trim',
  riskTrimRationale: 'Risk.',
  trimHeadline: 'Trim into strength',
  trimRationale: 'Trim.',
  addHeadline: 'Add on pullback',
  addRationale: 'Add.',
  waitHeadline: 'Wait for trigger',
  waitRationale: 'Wait.',
};

describe('buildTechnicalAdvice', () => {
  it('uses localized text supplied by the caller', () => {
    const advice = buildTechnicalAdvice({
      quote: { price: null },
      technicals: { latestClose: null, movingAverages: null },
      chart: null,
      selectedSymbol: 'NVDA',
      market: 'US',
      text,
    });

    expect(advice.headline).toBe('Insufficient data');
    expect(advice.rationale).toBe('No quote.');
  });

  it('uses the nearest resistance above current price instead of the highest candidate', () => {
    const advice = buildTechnicalAdvice({
      quote: { price: 100 },
      technicals: {
        latestClose: 100,
        movingAverages: {
          ma20: 104,
          ma50: 130,
          ma200: 95,
        },
      },
      chart: {
        symbol: 'NVDA',
        points: [{ price: 98 }, { price: 104 }, { price: 140 }],
      },
      selectedSymbol: 'NVDA',
      market: 'US',
      text,
    });

    expect(advice.resistance).toBe(104);
    expect(advice.trimLow).toBeLessThan(130);
  });

  it('ignores stale chart points from another symbol', () => {
    const advice = buildTechnicalAdvice({
      quote: { price: 100 },
      technicals: {
        latestClose: 100,
        movingAverages: {
          ma20: 99,
          ma50: 97,
          ma200: 94,
        },
      },
      chart: {
        symbol: 'AAPL',
        points: [{ price: 70 }, { price: 150 }],
      },
      selectedSymbol: 'NVDA',
      market: 'US',
      text,
    });

    expect(advice.support).toBe(99);
    expect(advice.resistance).toBe(104);
  });
});
