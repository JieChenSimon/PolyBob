export interface NavigationMetric {
  from: string;
  to: string;
  durationMs: number;
  recordedAt: number;
}

export function appendNavigationMetric(
  metrics: NavigationMetric[],
  metric: NavigationMetric,
  limit = 20,
) {
  return [...metrics, metric].slice(-Math.max(1, limit));
}
