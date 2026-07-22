'use client';

import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

type Market = 'US' | 'CN';

interface EquityChartPoint {
  timestamp: number;
  label: string;
  price: number;
  volume: number | null;
  session: 'premarket' | 'regular' | 'afterhours' | 'overnight' | 'all' | 'cash';
}

export interface EquityPriceChartProps {
  points: EquityChartPoint[];
  color: string;
  symbol: string;
  market: Market;
  priceLabel: string;
  volumeLabel: string;
}

// Local copies of the tiny formatters used by the tooltip, so this
// recharts-only chunk does not need to import from USEquityAdvisor.
function formatOptionalMoney(value: number | null | undefined, market: Market) {
  if (value === null || value === undefined) {
    return '--';
  }
  const prefix = market === 'CN' ? '¥' : '$';
  return `${prefix}${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatCompactVolume(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '--';
  }
  if (value >= 100_000_000) {
    return `${(value / 100_000_000).toFixed(2)}亿`;
  }
  if (value >= 10_000) {
    return `${(value / 10_000).toFixed(2)}万`;
  }
  return value.toLocaleString();
}

export default function EquityPriceChart({
  points,
  color,
  symbol,
  market,
  priceLabel,
  volumeLabel,
}: EquityPriceChartProps) {
  const gradientId = `priceFill-${symbol.replace(/[^a-zA-Z0-9]/g, '')}`;

  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={points} margin={{ top: 12, right: 8, bottom: 4, left: 0 }}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.25} />
            <stop offset="95%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#e7e5e4" vertical={false} />
        <XAxis
          dataKey="label"
          minTickGap={24}
          tick={{ fill: '#78716c', fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: '#e7e5e4' }}
        />
        <YAxis
          yAxisId="price"
          domain={['auto', 'auto']}
          orientation="right"
          tick={{ fill: '#78716c', fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={64}
        />
        <YAxis yAxisId="volume" hide domain={[0, 'dataMax']} />
        <Tooltip
          contentStyle={{ background: '#ffffff', border: '1px solid #e7e5e4', color: '#1c1917' }}
          labelStyle={{ color: '#d97706' }}
          formatter={(value, name) => {
            if (name === 'price') {
              return [formatOptionalMoney(Number(value), market), priceLabel];
            }
            return [formatCompactVolume(Number(value)), volumeLabel];
          }}
        />
        <Bar yAxisId="volume" dataKey="volume" fill="#d6d3d1" opacity={0.7} barSize={3} isAnimationActive={false} />
        <Area
          yAxisId="price"
          type="monotone"
          dataKey="price"
          stroke={color}
          strokeWidth={1.7}
          fill={`url(#${gradientId})`}
          dot={false}
          activeDot={{ r: 3, stroke: color, fill: '#ffffff' }}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
