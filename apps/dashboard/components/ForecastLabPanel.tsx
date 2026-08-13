'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import ForecastFanChart from '@/components/ForecastFanChart';
import { assessForecast } from '@/domain/forecasting/explain';
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

interface InstrumentSettingPayload {
  domain: string;
  symbol: string;
  enabled: boolean;
  horizon: number;
  updated_at: string | null;
  engine_enabled?: boolean;
  engine_ready?: boolean;
  engine_reason?: string | null;
  promotion_status: 'lab_only';
  trade_permission: false;
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
  instrument_id: string;
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
  explanation: {
    method: string;
    causal_attribution_available: false;
    input_state: {
      interpretation: 'descriptive_not_causal';
      return_5d: number | null;
      return_20d: number | null;
      realized_volatility_20d: number | null;
      drawdown_from_60d_high: number | null;
      volume_ratio_5d_vs_20d: number | null;
      history: Array<{ timestamp: string; close: number }>;
    };
    baseline: {
      name: 'unchanged_last_close';
      terminal_price: number;
      expected_return: 0;
    };
    historical_validation: {
      status: 'unknown';
      reason: string;
    };
    invalidation_rule: string;
  };
}

async function responseJson<T>(response: Response): Promise<T> {
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
  return payload as T;
}

export default function ForecastLabPanel({ symbol, domain }: { symbol: string; domain: string }) {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const queryClient = useQueryClient();
  const [horizon, setHorizon] = useState(5);

  const status = useQuery<ForecastStatusPayload>({
    queryKey: ['forecast-lab-status'],
    queryFn: async ({ signal }) => responseJson(await fetch(`${API_BASE}/api/forecasting/status`, { signal })),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
  const setting = useQuery<InstrumentSettingPayload>({
    queryKey: ['forecast-instrument', domain, symbol],
    queryFn: async ({ signal }) => responseJson(await fetch(
      `${API_BASE}/api/forecasting/instruments/${encodeURIComponent(domain)}/${encodeURIComponent(symbol)}`,
      { signal },
    )),
    staleTime: 30_000,
  });

  useEffect(() => {
    setHorizon(setting.data?.horizon ?? 5);
  }, [domain, setting.data?.horizon, symbol]);

  const configure = useMutation<InstrumentSettingPayload, Error, { enabled: boolean; horizon: number }>({
    mutationFn: async (request) => responseJson(await fetch(
      `${API_BASE}/api/forecasting/instruments/${encodeURIComponent(domain)}/${encodeURIComponent(symbol)}`,
      {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(request),
      },
    )),
    onSuccess: (payload) => {
      queryClient.setQueryData(['forecast-instrument', domain, symbol], payload);
      void queryClient.invalidateQueries({ queryKey: ['forecast-enabled-instruments'] });
    },
  });
  const run = useMutation<ForecastPayload, Error>({
    mutationFn: async () => {
      if (setting.data?.horizon !== horizon) {
        await configure.mutateAsync({ enabled: true, horizon });
      }
      return responseJson(await fetch(`${API_BASE}/api/forecasting/runs`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ symbol, domain, horizon }),
      }));
    },
  });

  const engineReady = status.data?.enabled === true && status.data?.ready === true;
  const instrumentEnabled = setting.data?.enabled === true;
  const busy = configure.isPending || run.isPending;
  const stateLabel = status.isLoading || setting.isLoading
    ? (zh ? '检查中' : 'CHECKING')
    : status.isError || setting.isError
      ? 'UNKNOWN'
      : !engineReady
        ? (zh ? '引擎关闭' : 'ENGINE OFF')
        : instrumentEnabled
          ? `${symbol} READY`
          : `${symbol} OFF`;
  const error = configure.error || run.error || setting.error || status.error;

  return (
    <section className="border-b border-violet-200 bg-white" aria-label="Kronos Forecast Lab">
      <div className="grid gap-3 bg-violet-50/70 px-4 py-3 lg:grid-cols-[minmax(0,1fr),auto] lg:items-center">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="mono text-[10px] font-bold uppercase tracking-wide text-violet-700">Kronos Lab</span>
            <span className="mono rounded border border-violet-300 bg-white px-2 py-0.5 text-[10px] font-semibold text-violet-700">{stateLabel}</span>
            <span className="mono rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
              {zh ? '交易权限拒绝' : 'TRADE DENIED'}
            </span>
          </div>
          <p className="mt-1 truncate text-xs text-stone-600">
            {zh
              ? `${symbol} 独立授权 · ${status.data?.model_id || 'Kronos-base'} · 实验结果不进入交易。`
              : `${symbol} instrument opt-in · ${status.data?.model_id || 'Kronos-base'} · research only.`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label={zh ? '预测周期' : 'Forecast horizon'}
            value={horizon}
            disabled={!instrumentEnabled || busy}
            onChange={(event) => setHorizon(Number(event.target.value))}
            className="mono rounded border border-stone-300 bg-white px-2 py-1.5 text-xs text-stone-700 disabled:bg-stone-100"
          >
            {[1, 5, 10, 20].map((value) => <option key={value} value={value}>{value}D</option>)}
          </select>
          <button
            type="button"
            disabled={busy || (!instrumentEnabled && !engineReady)}
            onClick={() => configure.mutate({ enabled: !instrumentEnabled, horizon })}
            className="rounded border border-violet-400 bg-white px-3 py-1.5 text-xs font-semibold text-violet-700 disabled:cursor-not-allowed disabled:border-stone-300 disabled:text-stone-400"
          >
            {configure.isPending
              ? (zh ? '保存中…' : 'SAVING…')
              : instrumentEnabled
                ? (zh ? '关闭此标的' : 'DISABLE')
                : (zh ? '启用此标的' : 'ENABLE')}
          </button>
          <button
            type="button"
            disabled={!instrumentEnabled || !engineReady || busy}
            onClick={() => run.mutate()}
            className="rounded border border-violet-500 bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:border-stone-300 disabled:bg-stone-300"
          >
            {run.isPending ? (zh ? '推理中…' : 'RUNNING…') : (zh ? '运行预测' : 'RUN')}
          </button>
        </div>
      </div>

      {!engineReady ? (
        <div className="grid gap-1 border-t border-violet-100 px-4 py-2 text-[11px] text-stone-600 md:grid-cols-[1fr,auto]">
          <span>{status.data?.reason || (zh ? '预测引擎状态未知。' : 'Forecast engine state is unknown.')}</span>
          <code className="mono text-violet-700">POLYBOB_UV_EXTRA=forecasting · ENABLE_LAB_KRONOS_FORECASTING=true</code>
        </div>
      ) : null}
      {error ? <div className="border-t border-rose-100 bg-rose-50 px-4 py-2 text-xs text-rose-700">UNKNOWN · {error.message}</div> : null}
      {run.data ? <ForecastResult payload={run.data} zh={zh} /> : null}
    </section>
  );
}

function ForecastResult({ payload, zh }: { payload: ForecastPayload; zh: boolean }) {
  const assessment = assessForecast(payload);
  const direction = payload.expected_return > 0 ? 'text-emerald-600' : payload.expected_return < 0 ? 'text-rose-600' : 'text-stone-700';
  const directionLabel = assessment.direction === 'bullish'
    ? (zh ? '偏多' : 'BULLISH')
    : assessment.direction === 'bearish'
      ? (zh ? '偏空' : 'BEARISH')
      : (zh ? '中性' : 'NEUTRAL');
  const issueText = {
    few_paths: zh ? `仅 ${payload.paths} 条采样路径，不能视为真实概率` : `Only ${payload.paths} sampled paths; not a real probability`,
    uncalibrated: zh ? '尚未进行标的级概率校准' : 'No instrument-level calibration',
    calendar_unverified: zh ? '交易日历尚未核对节假日' : 'Exchange holidays are not verified',
    degenerate_interval: zh ? '部分分位数重合，区间已经退化' : 'Some quantiles overlap; interval is degenerate',
  } as const;
  const endpoint = payload.points[payload.points.length - 1];
  const input = payload.explanation.input_state;
  const percent = (value: number | null) => value === null ? 'UNKNOWN' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;
  const pathMetric = assessment.sampleAdequate
    ? `${(payload.up_probability * 100).toFixed(0)}%`
    : `${assessment.upPathCount}/${payload.paths}`;

  return (
    <div className="border-t border-violet-100">
      <div className="grid gap-2 border-b border-stone-200 bg-stone-950 px-4 py-3 text-white md:grid-cols-[minmax(0,1fr),auto] md:items-center">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`mono text-sm font-bold ${assessment.direction === 'bearish' ? 'text-rose-400' : assessment.direction === 'bullish' ? 'text-emerald-400' : 'text-stone-200'}`}>{directionLabel}</span>
            <span className={`rounded border px-2 py-0.5 text-[10px] font-semibold ${assessment.confidence === 'low' ? 'border-amber-500/60 text-amber-300' : 'border-sky-500/60 text-sky-300'}`}>
              {assessment.confidence === 'low' ? (zh ? '低可信度' : 'LOW CONFIDENCE') : (zh ? '中等可信度' : 'MEDIUM CONFIDENCE')}
            </span>
            <span className="rounded border border-stone-600 px-2 py-0.5 text-[10px] text-stone-300">{zh ? '研究用途' : 'RESEARCH ONLY'}</span>
          </div>
          <p className="mt-1 text-xs text-stone-300">
            {zh
              ? `Kronos 的 ${payload.horizon} 日终点中位预测为 ${endpoint?.close_p50.toFixed(2) ?? 'UNKNOWN'}，相对当前收盘价 ${payload.last_close.toFixed(2)} 为 ${percent(payload.expected_return)}。`
              : `Kronos median terminal forecast is ${endpoint?.close_p50.toFixed(2) ?? 'UNKNOWN'} over ${payload.horizon} days, ${percent(payload.expected_return)} from ${payload.last_close.toFixed(2)}.`}
          </p>
        </div>
        <div className="mono text-[10px] text-stone-400 md:text-right">
          {zh ? '预测分布 ≠ 因果解释 ≠ 交易建议' : 'Forecast distribution ≠ causality ≠ advice'}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-px bg-stone-200 md:grid-cols-5">
        <Metric label={zh ? '终点中位收益' : 'Median return'} value={`${payload.expected_return >= 0 ? '+' : ''}${(payload.expected_return * 100).toFixed(2)}%`} tone={direction} />
        <Metric label={zh ? '上涨采样路径' : 'Up sampled paths'} value={pathMetric} tone={assessment.sampleAdequate ? 'text-stone-900' : 'text-amber-600'} />
        <Metric label={zh ? '不变价基准' : 'Unchanged baseline'} value={payload.explanation.baseline.terminal_price.toFixed(2)} />
        <Metric label={zh ? '历史验证' : 'Walk-forward'} value="UNKNOWN" tone="text-amber-600" />
        <Metric className="col-span-2 md:col-span-1" label={zh ? '交易权限' : 'Trade permission'} value={payload.trade_permission ? 'GRANTED' : 'DENIED'} tone={payload.trade_permission ? 'text-emerald-600' : 'text-amber-600'} />
      </div>

      <div className="grid border-b border-stone-200 xl:grid-cols-[minmax(0,1.55fr),minmax(280px,0.75fr)]">
        <div className="min-w-0 border-b border-stone-200 px-3 py-3 xl:border-b-0 xl:border-r">
          <div className="mb-1 flex items-center justify-between gap-3 px-1">
            <h3 className="text-xs font-semibold text-stone-800">{zh ? '价格路径与预测区间' : 'Price path and forecast band'}</h3>
            <span className="mono text-[10px] text-stone-500">{payload.paths} {zh ? '条路径' : 'paths'}</span>
          </div>
          <ForecastFanChart
            history={input.history}
            forecast={payload.points}
            lastClose={payload.last_close}
            symbol={payload.instrument_id}
            zh={zh}
          />
        </div>
        <div className="divide-y divide-stone-100">
          <ExplanationSection title={zh ? '可信度检查' : 'Confidence checks'}>
            <ul className="space-y-1.5">
              {assessment.issues.map((issue) => (
                <li key={issue} className="flex gap-2 text-xs text-stone-700">
                  <span className="mono text-amber-600">!</span><span>{issueText[issue]}</span>
                </li>
              ))}
            </ul>
          </ExplanationSection>
          <ExplanationSection title={zh ? '输入状态（非因果归因）' : 'Input state (not causal attribution)'}>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <SmallMetric label={zh ? '近 5 日收益' : '5D return'} value={percent(input.return_5d)} />
              <SmallMetric label={zh ? '近 20 日收益' : '20D return'} value={percent(input.return_20d)} />
              <SmallMetric label={zh ? '20 日年化波动' : '20D ann. vol'} value={percent(input.realized_volatility_20d)} />
              <SmallMetric label={zh ? '距 60 日高点' : 'From 60D high'} value={percent(input.drawdown_from_60d_high)} />
              <SmallMetric
                label={zh ? '5/20 日量比' : '5D/20D volume'}
                value={input.volume_ratio_5d_vs_20d === null ? 'UNKNOWN' : `${input.volume_ratio_5d_vs_20d.toFixed(2)}×`}
              />
              <SmallMetric label={zh ? '模型上下文' : 'Model context'} value={`${payload.context_rows} bars`} />
            </div>
          </ExplanationSection>
          <ExplanationSection title={zh ? '解释边界' : 'Explanation boundary'}>
            <p className="text-xs leading-5 text-stone-600">
              {zh
                ? '这些指标描述模型看到的价格与成交量环境，不证明它们导致了本次预测；Kronos 当前不提供可验证的特征归因。'
                : 'These metrics describe the observed price/volume regime. They do not prove causality; Kronos has no validated feature attribution here.'}
            </p>
          </ExplanationSection>
        </div>
      </div>

      <div className="grid gap-px bg-stone-200 md:grid-cols-3">
        <RuleCell
          title={zh ? '基准对照' : 'Baseline comparison'}
          body={zh ? `价格不变基准为 ${payload.last_close.toFixed(2)}；模型终点中位数偏离 ${percent(payload.expected_return)}。` : `Unchanged baseline is ${payload.last_close.toFixed(2)}; model median differs by ${percent(payload.expected_return)}.`}
        />
        <RuleCell
          title={zh ? '区间失效条件' : 'Interval invalidation'}
          body={zh ? '对应日期实际收盘价落在 P10–P90 之外，即记为区间突破；这不是因果证伪。' : 'A realized close outside that date’s P10–P90 band is an interval breach, not causal falsification.'}
        />
        <RuleCell
          title={zh ? '历史可靠性' : 'Historical reliability'}
          body={zh ? 'UNKNOWN：尚未建立该标的、该模型版本的滚动样本外验证。' : 'UNKNOWN: no walk-forward validation exists for this instrument and model revision.'}
        />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] border-collapse text-left text-xs">
          <thead className="bg-stone-50 text-[10px] uppercase text-stone-500">
            <tr><th className="px-4 py-2">{zh ? '预测日' : 'Date'}</th><th className="px-3 py-2">P10</th><th className="px-3 py-2">P50</th><th className="px-3 py-2">P90</th><th className="px-3 py-2">{zh ? '区间宽度' : 'Band width'}</th></tr>
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
                  <td className="mono px-3 py-2 text-stone-600">{width.toFixed(2)}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="grid gap-1 border-t border-stone-100 px-4 py-2 text-[10px] text-stone-500 md:grid-cols-2">
        <span className="mono">{payload.model_id}@{payload.model_revision.slice(0, 8)} · {payload.source} · as-of {payload.as_of.slice(0, 10)}</span>
        <span className="md:text-right">{payload.calendar_quality} · {payload.calibration_status} · {payload.gate_reason}</span>
      </div>
    </div>
  );
}

function ExplanationSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="px-4 py-3">
      <h3 className="mono mb-2 text-[10px] font-semibold uppercase tracking-wide text-stone-500">{title}</h3>
      {children}
    </section>
  );
}

function SmallMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] text-stone-500">{label}</div>
      <div className="mono mt-0.5 font-semibold text-stone-800">{value}</div>
    </div>
  );
}

function RuleCell({ title, body }: { title: string; body: string }) {
  return (
    <div className="bg-stone-50 px-4 py-3">
      <div className="mono text-[10px] font-semibold uppercase text-stone-500">{title}</div>
      <p className="mt-1 text-xs leading-5 text-stone-700">{body}</p>
    </div>
  );
}

function Metric({ label, value, tone = 'text-stone-900', className = '' }: { label: string; value: string; tone?: string; className?: string }) {
  return (
    <div className={`bg-white px-4 py-2.5 ${className}`}>
      <div className="mono text-[9px] uppercase text-stone-500">{label}</div>
      <div className={`mono mt-1 text-base font-semibold ${tone}`}>{value}</div>
    </div>
  );
}
