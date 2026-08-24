'use client';

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

export interface SimulationInstrumentPnlPoint {
  ts: number;
  label: string;
  pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  degraded: boolean;
}

function formatPnl(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '--';
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

export default function SimulationInstrumentPnlChart({
  points,
  zh,
}: {
  points: SimulationInstrumentPnlPoint[];
  zh: boolean;
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
          tickFormatter={(value) => formatPnl(Number(value))}
        />
        <Tooltip
          contentStyle={{ background: '#ffffff', border: '1px solid #e7e5e4', color: '#1c1917' }}
          labelStyle={{ color: '#78716c' }}
          formatter={(value, name) => [
            formatPnl(Number(value)),
            name === 'pnl'
              ? (zh ? '净 PnL' : 'Net PnL')
              : name === 'realized_pnl'
                ? (zh ? '已实现' : 'Realized')
                : (zh ? '未实现' : 'Unrealized'),
          ]}
        />
        <Legend />
        <Line type="monotone" dataKey="pnl" name={zh ? '净 PnL' : 'Net PnL'} stroke="#0284c7" strokeWidth={1.8} dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="realized_pnl" name={zh ? '已实现' : 'Realized'} stroke="#16a34a" strokeWidth={1.2} dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="unrealized_pnl" name={zh ? '未实现' : 'Unrealized'} stroke="#d97706" strokeWidth={1.2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
