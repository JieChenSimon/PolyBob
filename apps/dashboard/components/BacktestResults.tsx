'use client';

import { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { API_BASE } from '@/lib/config';

interface BacktestResult {
  sharpe_ratio: number;
  win_rate: number;
  total_return: number;
  max_drawdown: number;
  equity_curve: Array<{ timestamp: string; value: number }>;
}

export default function BacktestResults() {
  const [results, setResults] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchResults = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/backtest/results`);
        const data = await response.json();
        setResults(data);
        setLoading(false);
      } catch (error) {
        console.error('Failed to fetch backtest results:', error);
        setLoading(false);
      }
    };

    fetchResults();
  }, []);

  if (loading) {
    return (
      <div className="panel p-6">
        <div className="animate-pulse">
          <div className="h-4 bg-stone-200 rounded w-1/3 mb-4"></div>
          <div className="h-32 bg-stone-200 rounded"></div>
        </div>
      </div>
    );
  }

  if (!results) {
    return (
      <div className="panel p-6">
        <p className="text-stone-500">No backtest results available</p>
      </div>
    );
  }

  return (
    <div className="panel p-6">
      <h3 className="text-lg font-semibold text-stone-900 mb-6">Backtest Results</h3>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="metric-panel">
          <div className="text-xs text-stone-500 uppercase tracking-wider">Sharpe Ratio</div>
          <div className="text-2xl font-bold text-stone-900 mt-1">
            {results.sharpe_ratio.toFixed(2)}
          </div>
        </div>
        <div className="metric-panel">
          <div className="text-xs text-stone-500 uppercase tracking-wider">Win Rate</div>
          <div className="text-2xl font-bold text-stone-900 mt-1">
            {(results.win_rate * 100).toFixed(1)}%
          </div>
        </div>
        <div className="metric-panel">
          <div className="text-xs text-stone-500 uppercase tracking-wider">Total Return</div>
          <div className="text-2xl font-bold text-emerald-600 mt-1">
            +{(results.total_return * 100).toFixed(1)}%
          </div>
        </div>
        <div className="metric-panel">
          <div className="text-xs text-stone-500 uppercase tracking-wider">Max Drawdown</div>
          <div className="text-2xl font-bold text-rose-600 mt-1">
            {(results.max_drawdown * 100).toFixed(1)}%
          </div>
        </div>
      </div>

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={results.equity_curve}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" />
            <XAxis
              dataKey="timestamp"
              tick={{ fontSize: 12, fill: '#78716c' }}
              tickFormatter={(value) => new Date(value).toLocaleDateString()}
            />
            <YAxis tick={{ fontSize: 12, fill: '#78716c' }} />
            <Tooltip
              contentStyle={{
                backgroundColor: '#fff',
                border: '1px solid #e7e5e4',
                borderRadius: '8px'
              }}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke="#10b981"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
