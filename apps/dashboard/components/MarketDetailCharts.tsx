'use client';

import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

type Point = {
  time: string;
  value: number;
};

export function PriceTrendChart({ data }: { data: Point[] }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <AreaChart data={data}>
        <defs>
          <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#0284c7" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#0284c7" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#e7e5e4" strokeDasharray="4 4" />
        <XAxis dataKey="time" tick={{ fill: '#78716c', fontSize: 11 }} />
        <YAxis tick={{ fill: '#78716c', fontSize: 11 }} domain={['auto', 'auto']} />
        <Tooltip
          contentStyle={{
            borderRadius: 8,
            border: '1px solid #e7e5e4',
            backgroundColor: '#ffffff',
          }}
        />
        <Area type="monotone" dataKey="value" stroke="#0284c7" strokeWidth={2} fill="url(#priceFill)" isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function SpreadHistoryChart({ data }: { data: Point[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data}>
        <CartesianGrid stroke="#e7e5e4" strokeDasharray="4 4" />
        <XAxis dataKey="time" tick={{ fill: '#78716c', fontSize: 11 }} />
        <YAxis tick={{ fill: '#78716c', fontSize: 11 }} />
        <Tooltip
          contentStyle={{
            borderRadius: 8,
            border: '1px solid #e7e5e4',
            backgroundColor: '#ffffff',
          }}
        />
        <Line type="monotone" dataKey="value" stroke="#d97706" strokeWidth={2.5} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
