import { describe, expect, it } from 'vitest';
import { assessForecast } from './explain';

describe('assessForecast', () => {
  it('does not present three paths as a reliable probability', () => {
    const assessment = assessForecast({
      expected_return: -0.0988,
      up_probability: 0,
      paths: 3,
      calibration_status: 'uncalibrated',
      calendar_quality: 'weekday_only_unverified_holidays',
      points: [{ timestamp: '2026-08-13', close_p10: 218, close_p50: 222, close_p90: 222 }],
    });

    expect(assessment.direction).toBe('bearish');
    expect(assessment.confidence).toBe('low');
    expect(assessment.upPathCount).toBe(0);
    expect(assessment.sampleAdequate).toBe(false);
    expect(assessment.issues).toEqual([
      'few_paths',
      'uncalibrated',
      'calendar_unverified',
      'degenerate_interval',
    ]);
  });

  it('only treats a sufficiently sampled calibrated run as medium confidence', () => {
    const assessment = assessForecast({
      expected_return: 0.02,
      up_probability: 0.6,
      paths: 100,
      calibration_status: 'calibrated',
      calendar_quality: 'exact_24x7',
      points: [{ timestamp: '2026-08-13', close_p10: 98, close_p50: 101, close_p90: 104 }],
    });

    expect(assessment.direction).toBe('bullish');
    expect(assessment.confidence).toBe('medium');
    expect(assessment.sampleAdequate).toBe(true);
    expect(assessment.issues).toEqual([]);
  });
});
