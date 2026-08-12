'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

interface ForecastStatusPayload {
  enabled: boolean;
  ready: boolean;
  loaded: boolean;
  reason: string | null;
  model_id: string;
  model_revision: string;
  device: string;
  promotion_status: 'lab_only';
}

interface ForecastPoint {
  timestamp: string;
  open_p50: number;
  high_p50: number;
  low_p50: number;
  close_p10: number;
  close_p50: number;
  close_p90: number;
}

interface ForecastPayload {
  run_id: string;
  status: 'ready';
  as_of: string;
  source: string;
  model_id: string;
  model_revision: string;
  context_rows: number;
  horizon: number;
  paths: number;
  last_close: number;
  expected_return: number;
  up_probability: number;
  calendar_quality: string;
  calibration_status: string;
  promotion_status: string;
  trade_permission: boolean;
  gate_reason: string;
  points: ForecastPoint[];
}

async function responseJson<T>(response: Response): Promise<T> {
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `HTTP ${response.status}`);
  }
  return payload as T;
}

export default function ForecastLabPanel({ symbol, domain }: { symbol: string; domain: string }) {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const [requested, setRequested] = useState(false);
  const [horizon, setHorizon] = useState(5);

  const status = useQuery<ForecastStatusPayload>({
    queryKey: ['forecast-lab-status'],
    queryFn: async ({ signal }) => responseJson(await fetch(`${API_BASE}/api/forecasting/status`, { signal })),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
  const forecast = useQuery<ForecastPayload>({
    queryKey: ['forecast-lab', domain, symbol, horizon],
    enabled: requested && status.data?.enabled === true && status.data?.ready === true,
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({ symbol, domain, horizon: String(horizon) });
      return responseJson(await fetch(`${API_BASE}/api/forecasting/forecast?${params}`, { signal }));
    },
    staleTime: 10 * 60_000,
    retry: false,
  });

  const labReady = status.data?.enabled && status.data?.ready;
  const stateLabel = status.isLoading
    ? (zh ? '检查中' : 'CHECKING')
    : status.isError
      ? 'UNKNOWN'
      : !status.data?.ready
        ? 'MISSING'
        : status.data.enabled
          ? 'LAB READY'
          : 'LAB OFF';

  return (
    <section className="mt-4 overflow-hidden rounded border border-violet-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-violet-100 bg-violet-50 px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-stone-900">Kronos Forecast Lab</h2>
            <span className="mono rounded border border-violet-300 bg-white px-2 py-0.5 text-[10px] font-semibold text-violet-700">
              {stateLabel}
            </span>
            <span className="mono rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
              {zh ? '未晋级' : 'UNPROMOTED'}
            </span>
          </div>
          <p className="mt-1 text-xs text-stone-600">
            {zh ? '实验预测只提供研究证据，不授予开仓权限。' : 'Experimental forecasts are evidence only and never grant trade permission.'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            aria-label={zh ? '预测周期' : 'Forecast horizon'}
            value={horizon}
            onChange={(event) => { setHorizon(Number(event.target.value)); setRequested(false); }}
            className="mono rounded border border-stone-300 bg-white px-2 py-1.5 text-xs text-stone-700"
          >
            {[1, 5, 10, 20].map((value) => <option key={value} value={value}>{value}D</option>)}
          </select>
          <button
            type="button"
            disabled={!labReady || forecast.isFetching}
            onClick={() => { setRequested(true); void forecast.refetch(); }}
            className="rounded border border-violet-400 bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:border-stone-300 disabled:bg-stone-300"
          >
            {forecast.isFetching ? (zh ? '推理中…' : 'RUNNING…') : (zh ? '运行实验预测' : 'RUN FORECAST')}
          </button>
        </div>
      </div>

      {!labReady ? (
        <div className="grid gap-2 px-4 py-3 text-xs text-stone-600 md:grid-cols-[1fr,auto]">
          <span>{status.data?.reason || (zh ? '预测服务状态未知。' : 'Forecast service state is unknown.')}</span>
          <code className="mono text-[11px] text-violet-700">ENABLE_LAB_KRONOS_FORECASTING=true</code>
        </div>
      ) : null}

      {forecast.error ? (
        <div className="border-t border-rose-100 bg-rose-50 px-4 py-3 text-xs text-rose-700">
          UNKNOWN · {forecast.error.message}
        </div>
      ) : null}

      {forecast.data ? <ForecastResult payload={forecast.data} zh={zh} /> : null}
    </section>
  );
}

function ForecastResult({ payload, zh }: { payload: ForecastPayload; zh: boolean }) {
  const direction = payload.expected_return > 0 ? 'text-emerald-600' : payload.expected_return < 0 ? 'text-rose-600' : 'text-stone-700';
  return (
    <div className="border-t border-violet-100">
      <div className="grid grid-cols-2 gap-px bg-stone-200 md:grid-cols-5">
        <Metric label={zh ? '终点中位收益' : 'Median return'} value={`${payload.expected_return >= 0 ? '+' : ''}${(payload.expected_return * 100).toFixed(2)}%`} tone={direction} />
        <Metric label={zh ? '上涨路径占比' : 'Up paths'} value={`${(payload.up_probability * 100).toFixed(0)}%`} />
        <Metric label={zh ? '预测路径' : 'Paths'} value={String(payload.paths)} />
        <Metric label={zh ? '上下文' : 'Context'} value={`${payload.context_rows} bars`} />
        <Metric className="col-span-2 md:col-span-1" label={zh ? '交易权限' : 'Trade permission'} value={payload.trade_permission ? 'GRANTED' : 'DENIED'} tone={payload.trade_permission ? 'text-emerald-600' : 'text-amber-600'} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] border-collapse text-left text-xs">
          <thead className="bg-stone-50 text-[10px] uppercase text-stone-500">
            <tr>
              <th className="px-4 py-2">{zh ? '预测日' : 'Date'}</th>
              <th className="px-3 py-2">P10</th>
              <th className="px-3 py-2">P50</th>
              <th className="px-3 py-2">P90</th>
              <th className="px-3 py-2">{zh ? '区间宽度' : 'Band width'}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {payload.points.map((point) => {
              const width = Math.max(0, ((point.close_p90 - point.close_p10) / payload.last_close) * 100);
              return (
                <tr key={point.timestamp}>
                  <td className="mono px-4 py-2 text-stone-600">{point.timestamp.slice(0, 10)}</td>
                  <td className="mono px-3 py-2 text-rose-600">{point.close_p10.toFixed(3)}</td>
                  <td className="mono px-3 py-2 font-semibold text-stone-900">{point.close_p50.toFixed(3)}</td>
                  <td className="mono px-3 py-2 text-emerald-600">{point.close_p90.toFixed(3)}</td>
                  <td className="px-3 py-2">
                    <div className="h-1.5 w-28 overflow-hidden rounded bg-stone-100">
                      <div className="h-full bg-violet-400" style={{ width: `${Math.min(100, width * 10)}%` }} />
                    </div>
                    <span className="mono mt-1 block text-[10px] text-stone-500">{width.toFixed(2)}%</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="grid gap-1 border-t border-stone-100 px-4 py-3 text-[10px] text-stone-500 md:grid-cols-2">
        <span className="mono">{payload.model_id}@{payload.model_revision.slice(0, 8)} · {payload.source} · as-of {payload.as_of.slice(0, 10)}</span>
        <span className="md:text-right">{payload.calendar_quality} · {payload.calibration_status} · {payload.gate_reason}</span>
      </div>
    </div>
  );
}

function Metric({ label, value, tone = 'text-stone-900', className = '' }: { label: string; value: string; tone?: string; className?: string }) {
  return (
    <div className={`bg-white px-4 py-3 ${className}`}>
      <div className="mono text-[9px] uppercase text-stone-500">{label}</div>
      <div className={`mono mt-1 text-base font-semibold ${tone}`}>{value}</div>
    </div>
  );
}
