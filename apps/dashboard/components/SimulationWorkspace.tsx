'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import dynamic from 'next/dynamic';
import { useEffect, useMemo, useState } from 'react';
import { API_BASE } from '@/lib/config';
import Card from '@/components/ui/Card';
import EmptyState from '@/components/ui/EmptyState';
import ErrorState from '@/components/ui/ErrorState';
import LoadingSkeleton from '@/components/ui/LoadingSkeleton';
import SectionHeader from '@/components/ui/SectionHeader';
import StatTile from '@/components/ui/StatTile';
import StatusBadge from '@/components/ui/StatusBadge';
import { useLanguage } from '@/lib/i18n';
import { requireSuccessfulMutation } from '@/lib/mutationResponse';
import {
  formatNumber,
  formatRatioAsPercent,
  formatSigned,
  formatUsd,
  signToneClass,
} from '@/lib/format';
import {
  MIN_RELIABLE_TRADES,
  allowedRunActions,
  formatSignedRatioPercent,
  hasReliableSample,
  parseUniverseInput,
  runStatusTone,
  signedMetricTone,
  toEpochMs,
} from '@/domain/simulation/metrics';
import type { StrategyTemplate } from '@/lib/types';

const SimulationEquityChart = dynamic(() => import('./SimulationEquityChart'), {
  ssr: false,
  loading: () => <div className="h-full" />,
});

interface SimulationMetrics {
  total_return: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  max_drawdown: number | null;
  sharpe: number | null;
  trade_count: number | null;
}

interface SimulationRun {
  run_id: string;
  name: string;
  strategy_id: string;
  universe: string[];
  initial_capital: number;
  cash: number;
  status: 'running' | 'paused' | 'stopped';
  created_at: string;
  metrics: SimulationMetrics | null;
}

interface SimulationDetailMetrics extends SimulationMetrics {
  avg_win: number | null;
  avg_loss: number | null;
  per_instrument?: Array<Record<string, unknown>>;
}

interface SimulationPosition {
  instrument_id: string;
  size: number;
  avg_price: number;
}

interface SimulationTrade {
  id: string | number;
  instrument_id: string;
  side: string;
  size: number;
  price: number;
  fee: number;
  realized_pnl: number | null;
  executed_at: string;
}

interface SimulationRunDetail {
  run: SimulationRun;
  metrics: SimulationDetailMetrics | null;
  equity_curve: Array<{ ts: number | string; equity: number }>;
  positions: SimulationPosition[];
  trades: SimulationTrade[];
}

interface FeedbackResult {
  applied: boolean;
  reason?: string;
  weight_changes?: Array<{ signal: string; before: number; after: number }>;
}

interface SimulationPreset {
  id: string;
  name: { zh: string; en: string };
  description: { zh: string; en: string };
  strategy_id: string;
  config: Record<string, unknown>;
  suggested_universe: string[];
  recommended_days: number;
  focus: string;
}

interface SimulationRuntimeStatus {
  enabled: boolean;
  running: boolean;
  auto_run: boolean;
  mode: 'paper';
  trade_permission: false;
  source?: string;
  truth?: string;
}

const SIMULATION_QUERY_PREFIX = ['simulation'] as const;
const SIMULATION_REFETCH_MS = 15_000;
const SIMULATION_STALE_MS = 12_000;

async function fetchJson<T>(path: string, signal: AbortSignal | undefined): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { signal });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

export default function SimulationWorkspace() {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const queryClient = useQueryClient();
  const [initialSymbol, setInitialSymbol] = useState('');

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [feedbackConfirming, setFeedbackConfirming] = useState(false);
  const [feedbackResult, setFeedbackResult] = useState<FeedbackResult | null>(null);

  const runtimeQuery = useQuery<SimulationRuntimeStatus>({
    queryKey: [...SIMULATION_QUERY_PREFIX, 'runtime'],
    queryFn: ({ signal }) => fetchJson<SimulationRuntimeStatus>('/api/simulation/status', signal),
    refetchInterval: 5_000,
    staleTime: 2_000,
  });
  const runtime = runtimeQuery.data;

  useEffect(() => {
    const symbol = new URLSearchParams(window.location.search).get('symbol');
    if (symbol) setInitialSymbol(symbol.trim().toUpperCase());
  }, []);

  const runsQuery = useQuery<SimulationRun[]>({
    queryKey: [...SIMULATION_QUERY_PREFIX, 'runs'],
    queryFn: async ({ signal }) => {
      const payload = await fetchJson<{ runs?: SimulationRun[] }>('/api/simulation/runs', signal);
      return Array.isArray(payload.runs) ? payload.runs : [];
    },
    refetchInterval: SIMULATION_REFETCH_MS,
    staleTime: SIMULATION_STALE_MS,
    enabled: runtime?.enabled === true,
  });
  const runs = runsQuery.data ?? [];
  const activeRunId = selectedRunId ?? runs[0]?.run_id ?? null;

  const detailQuery = useQuery<SimulationRunDetail>({
    queryKey: [...SIMULATION_QUERY_PREFIX, 'run-detail', activeRunId],
    queryFn: ({ signal }) => fetchJson<SimulationRunDetail>(`/api/simulation/runs/${activeRunId}`, signal),
    enabled: Boolean(activeRunId),
    refetchInterval: SIMULATION_REFETCH_MS,
    staleTime: SIMULATION_STALE_MS,
  });
  const detail = detailQuery.data ?? null;

  // Feedback confirmation/result is per run: reset when switching runs.
  useEffect(() => {
    setFeedbackConfirming(false);
    setFeedbackResult(null);
    setMutationError(null);
  }, [activeRunId]);

  const invalidateSimulation = () =>
    queryClient.invalidateQueries({ queryKey: SIMULATION_QUERY_PREFIX });

  const setRuntime = async (payload: { enabled?: boolean; auto_run?: boolean }) => {
    setBusyAction('runtime');
    setMutationError(null);
    try {
      await requireSuccessfulMutation(fetch(`${API_BASE}/api/simulation/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }));
      await queryClient.invalidateQueries({ queryKey: [...SIMULATION_QUERY_PREFIX, 'runtime'] });
      await invalidateSimulation();
    } catch (error) {
      setMutationError(error instanceof Error ? error.message : 'unknown error');
    } finally {
      setBusyAction(null);
    }
  };

  const runLifecycleAction = async (runId: string, action: 'start' | 'pause' | 'stop') => {
    setBusyAction(`${runId}:${action}`);
    setMutationError(null);
    try {
      await requireSuccessfulMutation(fetch(`${API_BASE}/api/simulation/runs/${runId}/${action}`, {
        method: 'POST',
      }));
      await invalidateSimulation();
    } catch (error) {
      setMutationError(error instanceof Error ? error.message : 'unknown error');
    } finally {
      setBusyAction(null);
    }
  };

  const applyFeedback = async (runId: string) => {
    setBusyAction(`${runId}:feedback`);
    setMutationError(null);
    setFeedbackResult(null);
    try {
      const response = await requireSuccessfulMutation(
        fetch(`${API_BASE}/api/simulation/runs/${runId}/feedback`, { method: 'POST' }),
      );
      setFeedbackResult(await response.json());
      setFeedbackConfirming(false);
      await invalidateSimulation();
    } catch (error) {
      setMutationError(error instanceof Error ? error.message : 'unknown error');
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <>
      <Card className="mb-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className={`h-2.5 w-2.5 rounded-full ${runtime?.enabled ? 'bg-emerald-500' : 'bg-stone-300'}`} />
              <strong className="text-sm text-stone-900">
                {runtime?.enabled ? (zh ? '模拟盘已启用' : 'Paper Lab enabled') : (zh ? '模拟盘未启用' : 'Paper Lab disabled')}
              </strong>
              <StatusBadge tone="neutral">PAPER ONLY</StatusBadge>
            </div>
            <p className="mt-1 text-xs text-stone-500">
              {zh
                ? '真实行情驱动、虚拟资金、真实费用与滑点；不会提交真实订单。自动反馈只在达到样本门槛后调整策略权重。'
                : 'Real-market driven with paper capital, fees and slippage; no live orders. Feedback only adjusts weights after sample guardrails pass.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void setRuntime({ enabled: !runtime?.enabled })}
              disabled={busyAction === 'runtime' || runtimeQuery.isLoading}
              className={`rounded-lg px-3 py-2 text-xs font-semibold text-white transition disabled:opacity-50 ${runtime?.enabled ? 'bg-stone-700 hover:bg-stone-900' : 'bg-emerald-600 hover:bg-emerald-700'}`}
            >
              {runtime?.enabled ? (zh ? '停用并暂停运行' : 'Disable & pause') : (zh ? '启用模拟盘' : 'Enable Paper Lab')}
            </button>
            <label className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${runtime?.enabled ? 'border-stone-200 text-stone-700' : 'border-stone-100 text-stone-400'}`}>
              <input
                type="checkbox"
                checked={runtime?.auto_run ?? false}
                disabled={!runtime?.enabled || busyAction === 'runtime'}
                onChange={(event) => void setRuntime({ auto_run: event.target.checked })}
              />
              {zh ? '自动运行标记为 Auto 的实验' : 'Auto-start runs marked Auto'}
            </label>
          </div>
        </div>
        {mutationError ? <div className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{mutationError}</div> : null}
      </Card>
      {runsQuery.isError ? (
        <ErrorState
          className="mb-5"
          title={zh ? '模拟盘数据加载失败' : 'Failed to load simulation runs'}
          message={zh ? '无法连接 PolyBob API，模拟盘列表暂时为空。' : 'Cannot reach the PolyBob API; the run list is empty for now.'}
          onRetry={() => void runsQuery.refetch()}
          retryLabel={zh ? '重试' : 'Retry'}
        />
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.85fr),minmax(0,1.15fr)]">
        <div className="space-y-6">
          <CreateRunCard zh={zh} enabled={runtime?.enabled === true} initialSymbol={initialSymbol} onCreated={(runId) => {
            if (runId) {
              setSelectedRunId(runId);
            }
            void invalidateSimulation();
          }} />

          <Card padded={false}>
            <div className="border-b border-stone-200 px-5 py-4">
              <SectionHeader
                title={zh ? '模拟盘运行' : 'Simulation Runs'}
                caption={zh
                  ? '每个运行使用真实行情逐步累积成交与净值，点击查看详情。'
                  : 'Each run accumulates trades and equity on live data. Click a run for details.'}
              />
            </div>
            <div className="space-y-3 px-4 py-4">
              {runsQuery.isLoading ? (
                <LoadingSkeleton variant="rows" count={3} />
              ) : runs.length ? (
                runs.map((run) => (
                  <RunListItem
                    key={run.run_id}
                    run={run}
                    zh={zh}
                    active={run.run_id === activeRunId}
                    onSelect={() => setSelectedRunId(run.run_id)}
                  />
                ))
              ) : (
                <EmptyState
                  title={zh ? '暂无模拟盘运行' : 'No simulation runs yet'}
                  hint={zh
                    ? '创建一个模拟盘运行开始积累真实数据：选择策略与标的，用真实行情长期检验绩效。'
                    : 'Create a simulation run to start accumulating real data: pick a strategy and universe, then let live prices test it over time.'}
                />
              )}
            </div>
          </Card>
        </div>

        <div className="space-y-6">
          {activeRunId ? (
            <RunDetailPanel
              zh={zh}
              detail={detail}
              isLoading={detailQuery.isLoading}
              isError={detailQuery.isError}
              onRetry={() => void detailQuery.refetch()}
              busyAction={busyAction}
              mutationError={mutationError}
              runId={activeRunId}
              fallbackRun={runs.find((run) => run.run_id === activeRunId) ?? null}
              onAction={runLifecycleAction}
              feedbackConfirming={feedbackConfirming}
              setFeedbackConfirming={setFeedbackConfirming}
              feedbackResult={feedbackResult}
              onApplyFeedback={applyFeedback}
            />
          ) : (
            <Card>
              <EmptyState
                title={zh ? '未选择运行' : 'No run selected'}
                hint={zh
                  ? '左侧创建或选择一个模拟盘运行后，这里会展示净值曲线、持仓和成交明细。'
                  : 'Create or select a run on the left to see its equity curve, positions, and trades here.'}
              />
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function RunListItem({
  run,
  zh,
  active,
  onSelect,
}: {
  run: SimulationRun;
  zh: boolean;
  active: boolean;
  onSelect: () => void;
}) {
  const metrics = run.metrics ?? null;
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={`w-full rounded-lg border px-4 py-3 text-left transition ${
        active
          ? 'border-sky-300 bg-sky-50/60'
          : 'border-stone-200 bg-white hover:border-stone-300 hover:bg-stone-50'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-stone-900">{run.name}</div>
          <div className="mt-0.5 truncate text-xs text-stone-500">
            {run.strategy_id} · {run.universe?.length ?? 0} {zh ? '个标的' : 'instruments'}
          </div>
        </div>
        <StatusBadge tone={runStatusTone(run.status)}>
          {statusLabel(run.status, zh)}
        </StatusBadge>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div>
          <div className="text-stone-500">{zh ? '总收益' : 'Return'}</div>
          <div className={`mt-0.5 font-semibold ${signToneClass(metrics?.total_return)}`}>
            {formatSignedRatioPercent(metrics?.total_return)}
          </div>
        </div>
        <div>
          <div className="text-stone-500">{zh ? '胜率' : 'Win Rate'}</div>
          <div className="mt-0.5 font-semibold text-stone-900">
            {formatRatioAsPercent(metrics?.win_rate, 1)}
          </div>
        </div>
        <div>
          <div className="text-stone-500">{zh ? '最大回撤' : 'Max DD'}</div>
          <div className="mt-0.5 font-semibold text-stone-900">
            {formatRatioAsPercent(metrics?.max_drawdown, 1)}
          </div>
        </div>
      </div>
    </button>
  );
}

function CreateRunCard({
  zh,
  enabled,
  initialSymbol,
  onCreated,
}: {
  zh: boolean;
  enabled: boolean;
  initialSymbol: string;
  onCreated: (runId: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [strategyId, setStrategyId] = useState('');
  const [universeRaw, setUniverseRaw] = useState(initialSymbol);
  const [capitalRaw, setCapitalRaw] = useState('10000');
  const [presetId, setPresetId] = useState('');
  const [presetConfig, setPresetConfig] = useState<Record<string, unknown> | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [autoStart, setAutoStart] = useState(false);
  const [autoFeedback, setAutoFeedback] = useState(false);

  const catalogQuery = useQuery<StrategyTemplate[]>({
    queryKey: [...SIMULATION_QUERY_PREFIX, 'strategy-catalog'],
    queryFn: async ({ signal }) => {
      const payload = await fetchJson<{ strategies?: StrategyTemplate[] }>('/api/strategies/catalog', signal);
      return Array.isArray(payload.strategies) ? payload.strategies : [];
    },
    refetchInterval: SIMULATION_REFETCH_MS,
    staleTime: SIMULATION_STALE_MS,
    enabled: open,
  });
  const strategies = catalogQuery.data ?? [];

  const presetsQuery = useQuery<SimulationPreset[]>({
    queryKey: [...SIMULATION_QUERY_PREFIX, 'presets'],
    queryFn: async ({ signal }) => {
      const payload = await fetchJson<{ presets?: SimulationPreset[] }>('/api/simulation/presets', signal);
      return Array.isArray(payload.presets) ? payload.presets : [];
    },
    staleTime: 5 * 60_000,
    enabled: open,
  });
  const presets = presetsQuery.data ?? [];
  const activePreset = presets.find((p) => p.id === presetId) ?? null;

  const applyPreset = (id: string) => {
    setPresetId(id);
    const preset = presets.find((p) => p.id === id);
    if (!preset) {
      setPresetConfig(null);
      return;
    }
    setStrategyId(preset.strategy_id);
    setUniverseRaw((preset.suggested_universe ?? []).join(', '));
    setPresetConfig(preset.config ?? {});
    setName((current) => current.trim() || (zh ? preset.name.zh : preset.name.en));
  };

  const submit = async () => {
    const universe = parseUniverseInput(universeRaw);
    const initialCapital = Number(capitalRaw);
    if (!name.trim()) {
      setFormError(zh ? '请填写运行名称。' : 'A run name is required.');
      return;
    }
    if (!strategyId) {
      setFormError(zh ? '请选择一个策略。' : 'Pick a strategy.');
      return;
    }
    if (!universe.length) {
      setFormError(zh ? '至少填写一个标的 ID。' : 'Enter at least one instrument id.');
      return;
    }
    if (!Number.isFinite(initialCapital) || initialCapital <= 0) {
      setFormError(zh ? '初始资金必须是大于 0 的数字。' : 'Initial capital must be a number greater than 0.');
      return;
    }

    setSubmitting(true);
    setFormError(null);
    try {
      const response = await requireSuccessfulMutation(fetch(`${API_BASE}/api/simulation/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          strategy_id: strategyId,
          universe,
          initial_capital: initialCapital,
          // A preset supplies tuned config (position size, slippage penalty…);
          // the visible fields above override strategy/universe/name as edited.
          config: {
            ...(presetConfig ?? {}),
            auto_run: autoStart,
            auto_feedback: autoFeedback,
          },
        }),
      }));
      const payload = await response.json().catch(() => null) as
        | { run_id?: string; run?: { run_id?: string } }
        | null;
      const createdId = payload?.run?.run_id ?? payload?.run_id ?? null;
      if (createdId && autoStart) {
        await requireSuccessfulMutation(fetch(`${API_BASE}/api/simulation/runs/${createdId}/start`, { method: 'POST' }));
      }
      setName('');
      setUniverseRaw(initialSymbol);
      setPresetId('');
      setPresetConfig(null);
      setAutoStart(false);
      setAutoFeedback(false);
      setOpen(false);
      onCreated(createdId);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'unknown error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card padded={false}>
      <div className="flex items-center justify-between gap-3 px-5 py-4">
        <SectionHeader
          title={zh ? '新建模拟盘' : 'New Simulation Run'}
          caption={zh
            ? '选择策略和标的，用 paper 资金在真实行情上运行。'
            : 'Pick a strategy and universe; runs on live prices with paper capital.'}
        />
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="shrink-0 rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700"
        >
          {open ? (zh ? '收起' : 'Close') : (zh ? '新建' : 'Create')}
        </button>
      </div>

      {open ? (
        <div className="space-y-4 border-t border-stone-200 px-5 py-4">
          <label className="block">
            <span className="text-xs font-medium uppercase tracking-[0.12em] text-stone-500">
              {zh ? '预设测试类型' : 'Preset Test Type'}
            </span>
            <select
              value={presetId}
              onChange={(event) => applyPreset(event.target.value)}
              className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 outline-none transition focus:border-sky-500"
            >
              <option value="">
                {presetsQuery.isLoading
                  ? (zh ? '加载预设中…' : 'Loading presets…')
                  : (zh ? '自定义（不使用预设）' : 'Custom (no preset)')}
              </option>
              {presets.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {zh ? preset.name.zh : preset.name.en}
                </option>
              ))}
            </select>
            {activePreset ? (
              <div className="mt-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-stone-600">
                <p>{zh ? activePreset.description.zh : activePreset.description.en}</p>
                <p className="mt-1 text-stone-500">
                  {zh ? '策略' : 'Strategy'}: <span className="font-medium text-stone-700">{activePreset.strategy_id}</span>
                  {' · '}
                  {zh ? '建议时长' : 'Suggested'}: <span className="font-medium text-stone-700">{activePreset.recommended_days} {zh ? '天' : 'days'}</span>
                </p>
                <p className="mt-1 text-amber-700">
                  {zh
                    ? '下方标的为示例占位，请替换为你自己的真实标的 ID。'
                    : 'The universe below is example placeholders — replace with your real instrument ids.'}
                </p>
              </div>
            ) : null}
          </label>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className={`flex items-start gap-2 rounded-lg border p-3 text-xs ${enabled ? 'border-stone-200 text-stone-700' : 'border-stone-100 text-stone-400'}`}>
              <input type="checkbox" checked={autoStart} disabled={!enabled} onChange={(event) => setAutoStart(event.target.checked)} />
              <span><strong className="block">{zh ? '自动启动' : 'Auto-start'}</strong>{zh ? '服务开启后自动进入 running。' : 'Start this run when the Paper Lab runner is enabled.'}</span>
            </label>
            <label className={`flex items-start gap-2 rounded-lg border p-3 text-xs ${enabled ? 'border-sky-200 text-stone-700' : 'border-stone-100 text-stone-400'}`}>
              <input type="checkbox" checked={autoFeedback} disabled={!enabled} onChange={(event) => setAutoFeedback(event.target.checked)} />
              <span><strong className="block">{zh ? '受限自适应反馈' : 'Guarded adaptive feedback'}</strong>{zh ? '达到最小平仓样本后才调整融合权重。' : 'Adjust fusion weights only after the minimum closed-trade sample.'}</span>
            </label>
          </div>

          <label className="block">
            <span className="text-xs font-medium uppercase tracking-[0.12em] text-stone-500">
              {zh ? '名称' : 'Name'}
            </span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={zh ? '例如：BTC 价差长期检验' : 'e.g. BTC spread long-run check'}
              className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 outline-none transition focus:border-sky-500"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium uppercase tracking-[0.12em] text-stone-500">
              {zh ? '策略' : 'Strategy'}
            </span>
            <select
              value={strategyId}
              onChange={(event) => setStrategyId(event.target.value)}
              className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 outline-none transition focus:border-sky-500"
            >
              <option value="">
                {catalogQuery.isLoading
                  ? (zh ? '加载策略中…' : 'Loading strategies…')
                  : (zh ? '选择策略' : 'Select a strategy')}
              </option>
              {strategyId && !strategies.some((s) => s.strategy_id === strategyId) ? (
                <option value={strategyId}>{strategyId}</option>
              ) : null}
              {strategies.map((strategy) => (
                <option key={strategy.strategy_id} value={strategy.strategy_id}>
                  {strategy.name} ({strategy.strategy_id})
                </option>
              ))}
            </select>
            {catalogQuery.isError ? (
              <span className="mt-1 block text-xs text-rose-600">
                {zh ? '策略目录加载失败，稍后重试。' : 'Failed to load the strategy catalog; try again later.'}
              </span>
            ) : null}
          </label>

          <label className="block">
            <span className="text-xs font-medium uppercase tracking-[0.12em] text-stone-500">
              {zh ? '标的列表' : 'Universe'}
            </span>
            <input
              value={universeRaw}
              onChange={(event) => setUniverseRaw(event.target.value)}
              placeholder="BTCUSDT, ETHUSDT"
              className="mono mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 outline-none transition focus:border-sky-500"
            />
            <span className="mt-1 block text-xs text-stone-500">
              {zh ? '用逗号分隔多个标的 ID。' : 'Separate multiple instrument ids with commas.'}
            </span>
          </label>

          <label className="block">
            <span className="text-xs font-medium uppercase tracking-[0.12em] text-stone-500">
              {zh ? '初始资金 (USD)' : 'Initial Capital (USD)'}
            </span>
            <input
              value={capitalRaw}
              onChange={(event) => setCapitalRaw(event.target.value)}
              inputMode="decimal"
              className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 outline-none transition focus:border-sky-500"
            />
          </label>

          {formError ? (
            <div className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{formError}</div>
          ) : null}

          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => void submit()}
              disabled={submitting || !enabled}
              className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:opacity-50"
            >
              {!enabled ? (zh ? '先启用模拟盘' : 'Enable Paper Lab first') : submitting ? (zh ? '创建中…' : 'Creating…') : (zh ? '创建运行' : 'Create Run')}
            </button>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function RunDetailPanel({
  zh,
  detail,
  isLoading,
  isError,
  onRetry,
  busyAction,
  mutationError,
  runId,
  fallbackRun,
  onAction,
  feedbackConfirming,
  setFeedbackConfirming,
  feedbackResult,
  onApplyFeedback,
}: {
  zh: boolean;
  detail: SimulationRunDetail | null;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  busyAction: string | null;
  mutationError: string | null;
  runId: string;
  fallbackRun: SimulationRun | null;
  onAction: (runId: string, action: 'start' | 'pause' | 'stop') => void;
  feedbackConfirming: boolean;
  setFeedbackConfirming: (value: boolean) => void;
  feedbackResult: FeedbackResult | null;
  onApplyFeedback: (runId: string) => void;
}) {
  const run = detail?.run ?? fallbackRun;
  const metrics = detail?.metrics ?? run?.metrics ?? null;
  const actions = allowedRunActions(run?.status);
  const thinSample = !hasReliableSample(metrics?.trade_count);
  const sampleCaption = zh ? '样本不足，指标仅供参考' : 'Thin sample; treat as indicative only';

  const chartPoints = useMemo(() => {
    const curve = detail?.equity_curve ?? [];
    return curve
      .filter((point) => Number.isFinite(point.equity))
      .map((point) => {
        const ms = toEpochMs(point.ts);
        return {
          ts: ms,
          label: new Date(ms).toLocaleString(undefined, {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
          }),
          equity: point.equity,
        };
      })
      .sort((a, b) => a.ts - b.ts);
  }, [detail?.equity_curve]);

  const trades = useMemo(() => {
    const list = detail?.trades ?? [];
    return [...list]
      .sort((a, b) => Date.parse(b.executed_at) - Date.parse(a.executed_at))
      .slice(0, 12);
  }, [detail?.trades]);

  return (
    <>
      <Card>
        <SectionHeader
          title={run ? run.name : runId}
          caption={run
            ? `${run.strategy_id} · ${zh ? '初始资金' : 'initial'} ${formatUsd(run.initial_capital)} · ${zh ? '现金' : 'cash'} ${formatUsd(run.cash, 2)}`
            : null}
          right={run ? (
            <StatusBadge tone={runStatusTone(run.status)}>{statusLabel(run.status, zh)}</StatusBadge>
          ) : null}
        />

        {isError ? (
          <ErrorState
            className="mt-4"
            title={zh ? '运行详情加载失败' : 'Failed to load run detail'}
            message={zh ? '无法获取该运行的详情数据。' : 'Cannot fetch detail data for this run.'}
            onRetry={onRetry}
            retryLabel={zh ? '重试' : 'Retry'}
          />
        ) : null}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => onAction(runId, 'start')}
            disabled={!actions.start || busyAction === `${runId}:start`}
            className="rounded-full bg-emerald-600 px-4 py-1.5 text-xs font-medium text-white transition hover:bg-emerald-700 disabled:opacity-40"
          >
            {zh ? '启动' : 'Start'}
          </button>
          <button
            type="button"
            onClick={() => onAction(runId, 'pause')}
            disabled={!actions.pause || busyAction === `${runId}:pause`}
            className="rounded-full bg-amber-600 px-4 py-1.5 text-xs font-medium text-white transition hover:bg-amber-700 disabled:opacity-40"
          >
            {zh ? '暂停' : 'Pause'}
          </button>
          <button
            type="button"
            onClick={() => onAction(runId, 'stop')}
            disabled={!actions.stop || busyAction === `${runId}:stop`}
            className="rounded-full bg-stone-600 px-4 py-1.5 text-xs font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
          >
            {zh ? '停止' : 'Stop'}
          </button>

          <div className="ml-auto">
            <button
              type="button"
              onClick={() => setFeedbackConfirming(!feedbackConfirming)}
              disabled={busyAction === `${runId}:feedback`}
              className="rounded-full border border-sky-300 bg-sky-50 px-4 py-1.5 text-xs font-medium text-sky-700 transition hover:bg-sky-100 disabled:opacity-40"
            >
              {zh ? '应用策略反馈' : 'Apply Strategy Feedback'}
            </button>
          </div>
        </div>

        {feedbackConfirming ? (
          <div className="mt-3 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3">
            <div className="text-sm text-sky-900">
              {zh
                ? '确认后将基于该运行已平仓交易的盈亏结果调整策略信号权重，此操作会影响后续决策。'
                : 'Confirming will adjust the strategy signal weights based on this run’s closed-trade outcomes. This affects future decisions.'}
            </div>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                onClick={() => onApplyFeedback(runId)}
                disabled={busyAction === `${runId}:feedback`}
                className="rounded-md bg-sky-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-sky-700 disabled:opacity-50"
              >
                {busyAction === `${runId}:feedback`
                  ? (zh ? '应用中…' : 'Applying…')
                  : (zh ? '确认应用' : 'Confirm')}
              </button>
              <button
                type="button"
                onClick={() => setFeedbackConfirming(false)}
                className="rounded-md border border-stone-300 bg-white px-3 py-1.5 text-xs font-medium text-stone-600 transition hover:border-stone-400"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
            </div>
          </div>
        ) : null}

        {feedbackResult ? (
          <div
            className={`mt-3 rounded-lg border px-4 py-3 text-sm ${
              feedbackResult.applied
                ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
                : 'border-amber-200 bg-amber-50 text-amber-900'
            }`}
          >
            {feedbackResult.applied ? (
              <>
                <div className="font-semibold">{zh ? '反馈已应用' : 'Feedback applied'}</div>
                {feedbackResult.weight_changes?.length ? (
                  <div className="mt-2 space-y-1">
                    {feedbackResult.weight_changes.map((change) => (
                      <div key={change.signal} className="mono flex items-center justify-between gap-3 text-xs">
                        <span>{change.signal}</span>
                        <span>
                          {formatNumber(change.before, 3)} → {formatNumber(change.after, 3)}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-1 text-xs">
                    {zh ? '本次没有权重变化。' : 'No weight changes this time.'}
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="font-semibold">{zh ? '反馈未应用' : 'Feedback not applied'}</div>
                <div className="mt-1 text-xs">
                  {feedbackResult.reason || (zh ? '未返回原因。' : 'No reason returned.')}
                </div>
              </>
            )}
          </div>
        ) : null}

        {mutationError ? (
          <div className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {zh ? '操作失败，请重试。' : 'Action failed. Try again.'} {mutationError}
          </div>
        ) : null}
      </Card>

      {isLoading && !detail ? (
        <LoadingSkeleton variant="tiles" count={6} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <StatTile
            label={zh ? '总收益' : 'Total Return'}
            value={formatSignedRatioPercent(metrics?.total_return)}
            tone={signedMetricTone(metrics?.total_return)}
          />
          <StatTile
            label={zh ? '胜率' : 'Win Rate'}
            value={formatRatioAsPercent(metrics?.win_rate, 1)}
            detail={thinSample ? sampleCaption : undefined}
            tone={thinSample ? 'muted' : 'default'}
          />
          <StatTile
            label={zh ? '盈亏因子' : 'Profit Factor'}
            value={formatNumber(metrics?.profit_factor, 2)}
          />
          <StatTile
            label={zh ? '最大回撤' : 'Max Drawdown'}
            value={formatRatioAsPercent(metrics?.max_drawdown, 2)}
            tone={metrics?.max_drawdown ? 'warning' : 'default'}
          />
          <StatTile
            label={zh ? '夏普比率' : 'Sharpe'}
            value={formatNumber(metrics?.sharpe, 2)}
          />
          <StatTile
            label={zh ? '成交笔数' : 'Trades'}
            value={typeof metrics?.trade_count === 'number' ? String(metrics.trade_count) : '--'}
            detail={thinSample
              ? (zh ? `少于 ${MIN_RELIABLE_TRADES} 笔平仓交易` : `Fewer than ${MIN_RELIABLE_TRADES} closed trades`)
              : undefined}
          />
        </div>
      )}

      <Card>
        <SectionHeader
          title={zh ? '净值曲线' : 'Equity Curve'}
          caption={zh ? '按时间累计的组合净值（paper 资金）。' : 'Portfolio equity over time (paper capital).'}
        />
        <div className="mt-4 h-64">
          {chartPoints.length ? (
            <SimulationEquityChart points={chartPoints} equityLabel={zh ? '净值' : 'Equity'} />
          ) : (
            <EmptyState
              className="flex h-full flex-col items-center justify-center"
              title={zh ? '暂无净值数据' : 'No equity data yet'}
              hint={zh ? '运行启动后会随行情逐步生成净值曲线。' : 'The curve fills in as the run processes live prices.'}
            />
          )}
        </div>
      </Card>

      <Card>
        <SectionHeader
          title={zh ? '持仓' : 'Positions'}
          caption={zh ? '当前未平仓头寸。' : 'Open positions right now.'}
        />
        <div className="mt-4">
          {detail?.positions?.length ? (
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-stone-200 text-xs uppercase tracking-[0.08em] text-stone-500">
                  <th className="py-2 pr-3 font-medium">{zh ? '标的' : 'Instrument'}</th>
                  <th className="py-2 pr-3 text-right font-medium">{zh ? '数量' : 'Size'}</th>
                  <th className="py-2 text-right font-medium">{zh ? '均价' : 'Avg Price'}</th>
                </tr>
              </thead>
              <tbody>
                {detail.positions.map((position) => (
                  <tr key={position.instrument_id} className="border-b border-stone-100 last:border-b-0">
                    <td className="mono py-2 pr-3 text-stone-900">{position.instrument_id}</td>
                    <td className="py-2 pr-3 text-right text-stone-700">{formatNumber(position.size, 4)}</td>
                    <td className="py-2 text-right text-stone-700">{formatNumber(position.avg_price, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState
              title={zh ? '暂无持仓' : 'No open positions'}
              hint={zh ? '策略开仓后这里会展示头寸明细。' : 'Positions appear once the strategy opens them.'}
            />
          )}
        </div>
      </Card>

      <Card>
        <SectionHeader
          title={zh ? '最近成交' : 'Recent Trades'}
          caption={zh ? '最新 12 笔成交，含手续费与已实现盈亏。' : 'Latest 12 fills with fees and realized PnL.'}
        />
        <div className="mt-4 overflow-x-auto">
          {trades.length ? (
            <table className="w-full min-w-[560px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-stone-200 text-xs uppercase tracking-[0.08em] text-stone-500">
                  <th className="py-2 pr-3 font-medium">{zh ? '标的' : 'Instrument'}</th>
                  <th className="py-2 pr-3 font-medium">{zh ? '方向' : 'Side'}</th>
                  <th className="py-2 pr-3 text-right font-medium">{zh ? '数量' : 'Size'}</th>
                  <th className="py-2 pr-3 text-right font-medium">{zh ? '价格' : 'Price'}</th>
                  <th className="py-2 pr-3 text-right font-medium">{zh ? '手续费' : 'Fee'}</th>
                  <th className="py-2 pr-3 text-right font-medium">{zh ? '已实现盈亏' : 'Realized PnL'}</th>
                  <th className="py-2 text-right font-medium">{zh ? '时间' : 'Time'}</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade) => (
                  <tr key={trade.id} className="border-b border-stone-100 last:border-b-0">
                    <td className="mono py-2 pr-3 text-stone-900">{trade.instrument_id}</td>
                    <td className={`py-2 pr-3 font-medium ${trade.side === 'buy' ? 'text-emerald-600' : 'text-rose-600'}`}>
                      {tradeSideLabel(trade.side, zh)}
                    </td>
                    <td className="py-2 pr-3 text-right text-stone-700">{formatNumber(trade.size, 4)}</td>
                    <td className="py-2 pr-3 text-right text-stone-700">{formatNumber(trade.price, 4)}</td>
                    <td className="py-2 pr-3 text-right text-stone-500">{formatNumber(trade.fee, 4)}</td>
                    <td className={`py-2 pr-3 text-right font-medium ${signToneClass(trade.realized_pnl)}`}>
                      {formatSigned(trade.realized_pnl, 2)}
                    </td>
                    <td className="py-2 text-right text-stone-500">
                      {new Date(trade.executed_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState
              title={zh ? '暂无成交' : 'No trades yet'}
              hint={zh ? '运行产生成交后会在这里列出。' : 'Fills show up here as the run trades.'}
            />
          )}
        </div>
      </Card>
    </>
  );
}

function statusLabel(status: string | null | undefined, zh: boolean) {
  switch (status) {
    case 'running':
      return zh ? '运行中' : 'running';
    case 'paused':
      return zh ? '已暂停' : 'paused';
    case 'stopped':
      return zh ? '已停止' : 'stopped';
    default:
      return zh ? '未知' : 'unknown';
  }
}

function tradeSideLabel(side: string, zh: boolean) {
  if (side === 'buy') {
    return zh ? '买入' : 'buy';
  }
  if (side === 'sell') {
    return zh ? '卖出' : 'sell';
  }
  return side;
}
