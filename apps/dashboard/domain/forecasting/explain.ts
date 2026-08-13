export interface ForecastPointLike {
  timestamp: string;
  close_p10: number;
  close_p50: number;
  close_p90: number;
}

export interface ForecastAssessmentInput {
  expected_return: number;
  up_probability: number;
  paths: number;
  calibration_status: string;
  calendar_quality: string;
  points: ForecastPointLike[];
}

export type ForecastDirection = 'bullish' | 'bearish' | 'neutral';

export interface ForecastAssessment {
  direction: ForecastDirection;
  confidence: 'low' | 'medium';
  upPathCount: number;
  sampleAdequate: boolean;
  intervalDegenerate: boolean;
  issues: Array<'few_paths' | 'uncalibrated' | 'calendar_unverified' | 'degenerate_interval'>;
}

export function assessForecast(input: ForecastAssessmentInput): ForecastAssessment {
  const direction: ForecastDirection = input.expected_return > 0.01
    ? 'bullish'
    : input.expected_return < -0.01
      ? 'bearish'
      : 'neutral';
  const sampleAdequate = input.paths >= 100;
  const intervalDegenerate = input.points.some(
    (point) => point.close_p10 === point.close_p50 || point.close_p50 === point.close_p90,
  );
  const issues: ForecastAssessment['issues'] = [];
  if (!sampleAdequate) issues.push('few_paths');
  if (input.calibration_status !== 'calibrated') issues.push('uncalibrated');
  if (input.calendar_quality.includes('unverified')) issues.push('calendar_unverified');
  if (intervalDegenerate) issues.push('degenerate_interval');

  return {
    direction,
    confidence: issues.length === 0 ? 'medium' : 'low',
    upPathCount: Math.round(input.up_probability * input.paths),
    sampleAdequate,
    intervalDegenerate,
    issues,
  };
}

