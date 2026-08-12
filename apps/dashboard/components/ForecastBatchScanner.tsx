'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

interface ScanRow {
  symbol: string;
  status: string;
  expected_return?: number;
  up_probability?: number;
  as_of?: string;
  source?: string;
  paths?: number;
  reason?: string;
  trade_permission: false;
}

export default function ForecastBatchScanner({
  domain,
  symbols,
}: {
  domain: 'crypto_spot' | 'us_equity' | 'a_share';
  symbols: string[];
}) {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const [rows, setRows] = useState<ScanRow[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const status = useQuery<{ enabled: boolean; ready: boolean; reason: string | null }>({
    queryKey: ['forecast-lab-status'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/forecasting/status`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    staleTime: 60_000,
  });
  const enabled = status.data?.enabled && status.data?.ready;

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/forecasting/scan`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ domain, symbols: symbols.slice(0, 8), horizon: 5 }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      setRows(payload.rows || []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setRunning(false);
    }
  };

  return (
    <section className="mt-6 overflow-hidden rounded border border-violet-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-violet-100 bg-violet-50 px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-stone-900">{zh ? 'Kronos 批量预测扫描' : 'Kronos Batch Forecast Scan'}</h2>
            <span className="mono rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">LAB ONLY</span>
          </div>
          <p className="mt-1 text-xs text-stone-600">
            {zh ? `同一窗口扫描 ${symbols.slice(0, 8).join(' · ')}；结果不授予交易权限。` : `Same-window scan: ${symbols.slice(0, 8).join(' · ')}. No trade permission.`}
          </p>
        </div>
        <button
          type="button"
          disabled={!enabled || running}
          onClick={() => void run()}
          className="rounded border border-violet-400 bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:border-stone-300 disabled:bg-stone-300"
        >
          {running ? (zh ? '扫描中…' : 'SCANNING…') : (zh ? '运行 5 日扫描' : 'RUN 5D SCAN')}
        </button>
      </div>
      {!enabled ? <div className="px-4 py-3 text-xs text-stone-600">{status.data?.reason || 'UNKNOWN'}</div> : null}
      {error ? <div className="border-t border-rose-100 bg-rose-50 px-4 py-3 text-xs text-rose-700">UNKNOWN · {error}</div> : null}
      {rows.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[700px] text-left text-xs">
            <thead className="bg-stone-50 text-[10px] uppercase text-stone-500">
              <tr><th className="px-4 py-2">Symbol</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">5D P50</th><th className="px-3 py-2">Up paths</th><th className="px-3 py-2">As-of / Source</th><th className="px-3 py-2">Permission</th></tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {rows.map((row) => (
                <tr key={row.symbol}>
                  <td className="mono px-4 py-2 font-semibold text-stone-900">{row.symbol}</td>
                  <td className="mono px-3 py-2 text-violet-700">{row.status}</td>
                  <td className={`mono px-3 py-2 ${(row.expected_return || 0) >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>{row.expected_return === undefined ? '--' : `${row.expected_return >= 0 ? '+' : ''}${(row.expected_return * 100).toFixed(2)}%`}</td>
                  <td className="mono px-3 py-2 text-stone-700">{row.up_probability === undefined ? '--' : `${(row.up_probability * 100).toFixed(0)}% / n=${row.paths}`}</td>
                  <td className="mono px-3 py-2 text-[10px] text-stone-500">{row.reason || `${row.as_of?.slice(0, 10)} · ${row.source}`}</td>
                  <td className="mono px-3 py-2 font-semibold text-amber-600">DENIED</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
