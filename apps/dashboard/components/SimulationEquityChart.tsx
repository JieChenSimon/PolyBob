'use client';

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

export interface SimulationEquityPoint {
  ts: number;
  label: string;
  equity: number;
}

// Local formatter so this recharts-only chunk stays self-contained
// (same pattern as EquityPriceChart).
function formatEquity(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '--';
  }
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

export default function SimulationEquityChart({
  points,
  equityLabel,
}: {
  points: SimulationEquityPoint[];
  equityLabel: string;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={points} margin={{ top: 12, right: 8, bottom: 4, left: 0 }}>
        <CartesianGrid stroke="#e7e5e4" vertical={false} />
        <XAxis
          dataKey="label"
          minTickGap={32}
          tick={{ fill: '#78716c', fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: '#e7e5e4' }}
        />
        <YAxis
          domain={['auto', 'auto']}
          orientation="right"
          tick={{ fill: '#78716c', fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={72}
          tickFormatter={(value) => formatEquity(Number(value))}
        />
        <Tooltip
          contentStyle={{ background: '#ffffff', border: '1px solid #e7e5e4', color: '#1c1917' }}
          labelStyle={{ color: '#78716c' }}
          formatter={(value) => [formatEquity(Number(value)), equityLabel]}
        />
        <Line
          type="monotone"
          dataKey="equity"
          stroke="#0284c7"
          strokeWidth={1.7}
          dot={false}
          activeDot={{ r: 3, stroke: '#0284c7', fill: '#ffffff' }}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
