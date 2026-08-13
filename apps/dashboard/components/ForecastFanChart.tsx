'use client';

interface HistoryPoint {
  timestamp: string;
  close: number;
}

interface ForecastPoint {
  timestamp: string;
  close_p10: number;
  close_p50: number;
  close_p90: number;
}

export default function ForecastFanChart({
  history,
  forecast,
  lastClose,
  symbol,
  zh,
}: {
  history: HistoryPoint[];
  forecast: ForecastPoint[];
  lastClose: number;
  symbol: string;
  zh: boolean;
}) {
  const width = 900;
  const height = 260;
  const pad = { left: 48, right: 18, top: 18, bottom: 30 };
  const historyValues = history.map((point) => point.close);
  const values = [
    ...historyValues,
    ...forecast.flatMap((point) => [point.close_p10, point.close_p50, point.close_p90]),
    lastClose,
  ];
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const margin = Math.max((rawMax - rawMin) * 0.08, lastClose * 0.005);
  const min = rawMin - margin;
  const max = rawMax + margin;
  const allCount = Math.max(2, history.length + forecast.length);
  const x = (index: number) => pad.left + (index / (allCount - 1)) * (width - pad.left - pad.right);
  const y = (value: number) => pad.top + ((max - value) / (max - min)) * (height - pad.top - pad.bottom);
  const historyPath = history.map((point, index) => `${index === 0 ? 'M' : 'L'}${x(index)},${y(point.close)}`).join(' ');
  const originIndex = Math.max(0, history.length - 1);
  const forecastSeries = [{ close_p50: lastClose, close_p10: lastClose, close_p90: lastClose }, ...forecast];
  const medianPath = forecastSeries.map((point, index) => `${index === 0 ? 'M' : 'L'}${x(originIndex + index)},${y(point.close_p50)}`).join(' ');
  const upper = forecastSeries.map((point, index) => `${x(originIndex + index)},${y(point.close_p90)}`);
  const lower = [...forecastSeries].reverse().map((point, reverseIndex) => {
    const index = forecastSeries.length - 1 - reverseIndex;
    return `${x(originIndex + index)},${y(point.close_p10)}`;
  });
  const band = [...upper, ...lower].join(' ');
  const splitX = x(originIndex);

  return (
    <div>
      <div className="h-[250px] w-full">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-full w-full"
          role="img"
          aria-label={zh ? `${symbol} 历史收盘价与 Kronos 预测区间` : `${symbol} history and Kronos forecast interval`}
        >
          {[0, 0.5, 1].map((ratio) => {
            const value = max - (max - min) * ratio;
            const gridY = y(value);
            return (
              <g key={ratio}>
                <line x1={pad.left} y1={gridY} x2={width - pad.right} y2={gridY} stroke="#e7e5e4" strokeWidth="1" />
                <text x={pad.left - 7} y={gridY + 4} textAnchor="end" fill="#78716c" fontSize="11">{value.toFixed(1)}</text>
              </g>
            );
          })}
          <line x1={pad.left} y1={y(lastClose)} x2={width - pad.right} y2={y(lastClose)} stroke="#a8a29e" strokeDasharray="5 4" />
          <polygon points={band} fill="#8b5cf6" fillOpacity="0.16" />
          <path d={historyPath} fill="none" stroke="#57534e" strokeWidth="2" vectorEffect="non-scaling-stroke" />
          <path d={medianPath} fill="none" stroke="#7c3aed" strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
          <line x1={splitX} y1={pad.top} x2={splitX} y2={height - pad.bottom} stroke="#7c3aed" strokeDasharray="3 3" />
          <circle cx={splitX} cy={y(lastClose)} r="4" fill="#fff" stroke="#7c3aed" strokeWidth="2" />
          <text x={splitX - 7} y={height - 10} textAnchor="end" fill="#57534e" fontSize="11">{zh ? '历史' : 'History'}</text>
          <text x={splitX + 7} y={height - 10} fill="#7c3aed" fontSize="11">{zh ? '预测' : 'Forecast'}</text>
        </svg>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 px-2 text-[10px] text-stone-500">
        <span><i className="mr-1 inline-block h-0.5 w-4 bg-stone-600 align-middle" />{zh ? '历史收盘' : 'History'}</span>
        <span><i className="mr-1 inline-block h-0.5 w-4 bg-violet-600 align-middle" />P50</span>
        <span><i className="mr-1 inline-block h-2 w-4 bg-violet-200 align-middle" />P10–P90</span>
        <span><i className="mr-1 inline-block w-4 border-t border-dashed border-stone-400 align-middle" />{zh ? '价格不变基准' : 'Unchanged baseline'}</span>
      </div>
    </div>
  );
}
