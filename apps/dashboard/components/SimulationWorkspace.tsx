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
  runStatusTone,
  signedMetricTone,
  toEpochMs,
} from '@/domain/simulation/metrics';

const SimulationEquityChart = dynamic(() => import('./SimulationEquityChart'), {
  ssr: false,
  loading: () => <div className="h-full" />,
});
const SimulationInstrumentPnlChart = dynamic(() => import('./SimulationInstrumentPnlChart'), {
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
  per_instrument?: Record<string, {
    trade_count: number;
    closed_trades: number;
    realized_pnl: number;
    win_rate: number | null;
  }>;
  execution_evidence?: {
    latest_observed_at?: string | null;
    latest_observed_instrument?: string | null;
    latest_quote_quality?: string;
    quote_observation_count?: number;
    quote_quality_counts?: Record<string, number>;
  };
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
  config?: Record<string, unknown>;
}

interface SimulationDetailMetrics extends SimulationMetrics {
  avg_win: number | null;
  avg_loss: number | null;
  per_instrument?: Record<string, {
    trade_count: number;
    closed_trades: number;
    realized_pnl: number;
    win_rate: number | null;
  }>;
}

interface FeatureAttribution {
  feature_name: string;
  average_model_weight: number | null;
  model_contribution: number | null;
  associated_realized_pnl: number | null;
  fill_count: number;
  closed_fill_count: number;
  instrument_count: number;
  methods: string[];
  quality: string[];
  attribution_status: string;
  causal_claim: boolean;
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
  instrument_pnl_curves: Record<string, Array<{
    ts: number | string;
    pnl: number;
    realized_pnl: number;
    unrealized_pnl: number;
    degraded: boolean;
  }>>;
  feature_attribution: {
    status: string;
    causal_claim: boolean;
    interpretation: string;
    row_count: number;
    features: FeatureAttribution[];
  };
  positions: SimulationPosition[];
  trades: SimulationTrade[];
}

interface FeedbackResult {
  applied: boolean;
  reason?: string;
  weight_changes?: Array<{ signal: string; before: number; after: number }>;
}

interface SimulationDomain {
  id: string;
  label: { zh: string; en: string };
  source: string;
  status: 'AVAILABLE' | 'UNKNOWN' | 'BLOCKED';
  reason: string | null;
  strategy_ids: string[];
  data_state?: {
    status: 'AVAILABLE' | 'UNKNOWN' | 'BLOCKED';
    source: string;
    observed_at: string | null;
    quote_quality: string;
    reason: string | null;
  };
  candidates: Array<{ symbol: string; status: string; reason: string | null }>;
}

interface SimulationCatalog {
  domains: SimulationDomain[];
  truth: string;
  trade_permission: false;
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
  const [initialDomain, setInitialDomain] = useState('');

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
    const params = new URLSearchParams(window.location.search);
    const symbol = params.get('instrument') || params.get('symbol');
    const domain = params.get('domain');
    if (symbol) setInitialSymbol(symbol.trim().toUpperCase());
    if (domain) setInitialDomain(domain.trim());
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
                {runtimeQuery.isError ? (zh ? '无法连接模拟盘服务' : 'Paper service unavailable') : runtimeQuery.isPending ? (zh ? '正在连接模拟盘…' : 'Connecting to paper service…') : runtime?.enabled ? (zh ? '模拟盘服务运行中' : 'Paper service running') : (zh ? '模拟盘服务已停用' : 'Paper service disabled')}
              </strong>
              <StatusBadge tone="neutral">PAPER ONLY</StatusBadge>
            </div>
            <p className="mt-1 text-xs text-stone-500">
              {zh
                ? '服务运行不等于资产域可启动；请在新建区查看每个域的真实行情、成本与研究门禁。不会提交真实订单。'
                : 'A running service does not mean an asset domain is runnable. Check each domain for real-data, cost, and research gates. No live orders are sent.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void setRuntime({ enabled: !runtime?.enabled })}
              disabled={busyAction === 'runtime' || !runtime || runtimeQuery.isError}
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
        {runtimeQuery.isError ? <ErrorState className="mt-3" title={zh ? '服务状态未知' : 'Service status unknown'} message={zh ? '无法读取服务状态，请检查后端连接后重试。已有模拟盘数据是否存在尚未核实。' : 'Check the backend connection and retry. Existing run data has not been verified.'} onRetry={() => void runtimeQuery.refetch()} retryLabel={zh ? '重新连接' : 'Reconnect'} /> : null}
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
          <CreateRunCard zh={zh} enabled={runtime?.enabled === true} initialSymbol={initialSymbol} initialDomain={initialDomain} onCreated={(runId) => {
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
  const researchFixture = isResearchFixture(run);
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
          <div className="truncate text-sm font-semibold text-stone-900">
            {researchFixture && zh ? '研究验收样例 · ' : ''}{run.name}
          </div>
          <div className="mt-0.5 truncate text-xs text-stone-500">
            {run.strategy_id} · {run.universe?.length ?? 0} {zh ? '个标的' : 'instruments'}
          </div>
        </div>
        <StatusBadge tone={runStatusTone(run.status)}>
          {statusLabel(run.status, zh)}
        </StatusBadge>
      </div>
      {researchFixture ? (
        <div className="mt-2 text-xs leading-5 text-amber-800">
          {zh ? '界面验收样例：没有可用交易证据，不代表策略表现或可启动的模拟盘。' : 'UI acceptance fixture: no usable trade evidence; it is not strategy performance or a runnable paper simulation.'}
        </div>
      ) : null}
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
  initialDomain,
  onCreated,
}: {
  zh: boolean;
  enabled: boolean;
  initialSymbol: string;
  initialDomain: string;
  onCreated: (runId: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [domainId, setDomainId] = useState(initialDomain || 'us_equity');
  const [strategyId, setStrategyId] = useState('momentum_dualma_v1');
  const [universe, setUniverse] = useState<string[]>(initialSymbol ? [initialSymbol] : []);
  const [symbolDraft, setSymbolDraft] = useState('');
  const [capitalRaw, setCapitalRaw] = useState('10000');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [autoStart, setAutoStart] = useState(false);
  const [autoFeedback, setAutoFeedback] = useState(false);

  const catalogQuery = useQuery<SimulationCatalog>({
    queryKey: [...SIMULATION_QUERY_PREFIX, 'runnable-catalog'],
    queryFn: async ({ signal }) => {
      return fetchJson<SimulationCatalog>('/api/simulation/catalog', signal);
    },
    staleTime: 60_000,
    enabled: open && enabled,
  });
  const domains = catalogQuery.data?.domains ?? [];
  const activeDomain = domains.find((domain) => domain.id === domainId) ?? null;
  const domainUsable = Boolean(
    activeDomain
      && activeDomain.status === 'AVAILABLE'
      && activeDomain.strategy_ids.length,
  );
  const domainBlocked = activeDomain?.status === 'BLOCKED' || activeDomain?.data_state?.status === 'BLOCKED';
  const domainReason = domainBlocked && zh
    ? '该资产域缺少可验证的实时执行数据或必要研究门禁，当前不能创建模拟盘。'
    : activeDomain?.data_state?.reason || activeDomain?.reason || (zh ? '启动前核验所选标的行情。' : 'Selected instruments are checked before start.');
  const strategyLabels: Record<string, { zh: string; en: string; note: string }> = {
    momentum_dualma_v1: { zh: '双均线动量', en: 'Dual-MA momentum', note: 'strictly causal rolling prices' },
    deep_drawdown_rebound_v1: { zh: '深度回撤反弹', en: 'Deep-drawdown rebound', note: 'research candidate; fundamentals remain separate' },
    signal_fusion: { zh: '信号融合', en: 'Signal fusion', note: 'prediction-market features only' },
    spread_reversion_v1: { zh: '价差回归', en: 'Spread reversion', note: 'real order-book features only' },
    spread_arbitrage_v1: { zh: '配对价差套利', en: 'Pair spread', note: 'paired snapshot feed only' },
  };

  useEffect(() => {
    if (initialDomain) setDomainId(initialDomain);
    if (initialSymbol) setUniverse([initialSymbol]);
    if (initialDomain || initialSymbol) setOpen(true);
  }, [initialDomain, initialSymbol]);

  useEffect(() => {
    if (strategyId !== 'signal_fusion') setAutoFeedback(false);
  }, [strategyId]);

  useEffect(() => {
    if (!activeDomain) return;
    if (!activeDomain.strategy_ids.includes(strategyId)) {
      setStrategyId(activeDomain.strategy_ids[0] ?? '');
    }
  }, [activeDomain, strategyId]);

  const chooseDomain = (nextDomain: SimulationDomain) => {
    setDomainId(nextDomain.id);
    setUniverse([]);
    setSymbolDraft('');
    setStrategyId(nextDomain.strategy_ids[0] ?? '');
    setFormError(null);
  };

  const toggleInstrument = (symbol: string) => {
    setUniverse((current) => current.includes(symbol)
      ? current.filter((value) => value !== symbol)
      : [...current, symbol]);
  };

  const addDraft = () => {
    const symbol = symbolDraft.trim().toUpperCase();
    if (!symbol) return;
    setUniverse((current) => current.includes(symbol) ? current : [...current, symbol]);
    setSymbolDraft('');
  };

  const submit = async () => {
    const initialCapital = Number(capitalRaw);
    if (!activeDomain) {
      setFormError(zh ? '模拟盘能力目录尚未加载。' : 'Paper Lab capability catalog has not loaded.');
      return;
    }
    if (!domainUsable) {
      setFormError(zh ? '该资产域当前不可运行，系统不会创建空模拟盘。' : 'This asset domain is not runnable now; an empty paper run will not be created.');
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
          name: name.trim() || `${zh ? activeDomain.label.zh : activeDomain.label.en} · ${strategyId}`,
          strategy_id: strategyId,
          universe,
          initial_capital: initialCapital,
          config: {
            asset_domain: activeDomain.id,
            auto_run: false,
            auto_feedback: strategyId === 'signal_fusion' && autoFeedback,
          },
        }),
      }));
      const payload = await response.json().catch(() => null) as
        | { run_id?: string; run?: { run_id?: string } }
        | null;
      const createdId = payload?.run?.run_id ?? payload?.run_id ?? null;
      if (!createdId) throw new Error(zh ? '创建响应缺少运行编号，请刷新列表核对。' : 'Creation response has no run id; refresh the run list to verify.');
      onCreated(createdId);
      if (createdId && autoStart) {
        try {
          await requireSuccessfulMutation(fetch(`${API_BASE}/api/simulation/runs/${createdId}/start`, { method: 'POST' }));
        } catch (error) {
          setFormError(`${zh ? '任务已创建，启动未通过。请在运行详情重试启动，无需重复创建。' : 'Run created; start failed. Retry start from the run details without creating another run.'} ${error instanceof Error ? error.message : ''}`);
          setOpen(false);
          return;
        }
      }
      setName('');
      setUniverse(initialSymbol ? [initialSymbol] : []);
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
            ? '真实数据、虚拟资金、可审计成交；先选资产，再选兼容策略和标的。'
            : 'Real data, paper capital, auditable fills. Choose asset, compatible strategy, then instruments.'}
        />
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="shrink-0 rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700"
        >
          {open ? (zh ? '收起' : 'Close') : (zh ? '新建' : 'Create')}
        </button>
      </div>

      {!open && formError ? <p role="alert" className="px-5 pb-4 text-sm text-amber-700">{formError}</p> : null}
      {open ? (
        <div className="space-y-4 border-t border-stone-200 px-5 py-4">
          <div>
            <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.12em] text-stone-500">
              {zh ? '1 · 资产类别' : '1 · Asset class'}
            </div>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              {domains.map((domain) => (
                <button
                  key={domain.id}
                  type="button"
                  onClick={() => chooseDomain(domain)}
                  className={`rounded-md border px-3 py-2 text-left text-xs transition ${domain.id === activeDomain?.id
                    ? 'border-sky-500 bg-sky-50 text-sky-950'
                    : 'border-stone-200 bg-white text-stone-700 hover:border-stone-400'}`}
                >
                  <span className="block font-semibold">{zh ? domain.label.zh : domain.label.en}</span>
                  <span className="mt-0.5 block truncate text-[10px] text-stone-500">{domain.data_state?.status ?? domain.status}</span>
                </button>
              ))}
            </div>
          </div>

          {activeDomain ? (
            <div className="rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-600">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge tone={(activeDomain.data_state?.status ?? activeDomain.status) === 'AVAILABLE' ? 'ok' : (activeDomain.data_state?.status ?? activeDomain.status) === 'BLOCKED' ? 'warn' : 'neutral'}>{activeDomain.data_state?.status ?? activeDomain.status}</StatusBadge>
                <span className="font-medium text-stone-800">{activeDomain.data_state?.source ?? activeDomain.source}</span>
              </div>
              <p className="mt-1">{domainReason}</p>
              {activeDomain.data_state?.observed_at ? <p className="mt-1 text-[10px] text-stone-500">{zh ? '来源时间' : 'Provider time'}: {new Date(activeDomain.data_state.observed_at).toLocaleString()} · {activeDomain.data_state.quote_quality}</p> : null}
            </div>
          ) : null}

          {!catalogQuery.isPending && !activeDomain && domains.length > 0 ? <p role="alert" className="text-sm text-amber-700">{zh ? '链接中的资产类别无法识别，请在上方选择资产类别。' : 'The linked asset class is not recognized. Choose an asset class above.'}</p> : null}
          {!domainBlocked ? <div>
            <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.12em] text-stone-500">
              {zh ? '2 · 兼容策略' : '2 · Compatible strategy'}
            </div>
            <div className="flex flex-wrap gap-2">
              {(activeDomain?.strategy_ids ?? []).map((id) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setStrategyId(id)}
                  className={`rounded-md border px-3 py-2 text-left text-xs ${strategyId === id
                    ? 'border-stone-900 bg-stone-900 text-white'
                    : 'border-stone-200 bg-white text-stone-700 hover:border-stone-400'}`}
                >
                  <span className="block font-semibold">{zh ? strategyLabels[id]?.zh ?? id : strategyLabels[id]?.en ?? id}</span>
                  <span className={`block text-[10px] ${strategyId === id ? 'text-stone-300' : 'text-stone-500'}`}>{id}</span>
                </button>
              ))}
            </div>
          </div> : <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-900">
            {zh ? '完成该域的实时数据、成本和研究门禁后，这里才会显示可运行策略与创建操作。' : 'Runnable strategies and creation controls appear after this domain has real data, cost, and research gates.'}
          </div>}

          {!domainBlocked ? <>
          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-stone-500">
                {zh ? '3 · 标的' : '3 · Instruments'}
              </span>
              <span className="text-xs text-stone-500">{universe.length} {zh ? '已选' : 'selected'}</span>
            </div>
            {universe.length > 0 ? <div className="mb-2 flex flex-wrap gap-1.5" aria-label={zh ? '已选标的' : 'Selected instruments'}>
              {universe.map((symbol) => <button key={symbol} type="button" onClick={() => toggleInstrument(symbol)} aria-label={`${zh ? '移除' : 'Remove'} ${symbol}`} className="mono rounded border border-sky-400 px-2 py-1 text-xs">{symbol} ×</button>)}
            </div> : null}
            {activeDomain?.candidates.length ? (
              <div className="flex max-h-32 flex-wrap content-start gap-1.5 overflow-y-auto rounded-md border border-stone-200 bg-white p-2">
                {activeDomain.candidates.map((candidate) => {
                  const selected = universe.includes(candidate.symbol);
                  return (
                    <button
                      key={candidate.symbol}
                      type="button"
                      onClick={() => toggleInstrument(candidate.symbol)}
                      title={candidate.reason || undefined}
                      className={`mono rounded px-2 py-1 text-xs transition ${selected
                        ? 'bg-sky-600 text-white'
                        : 'bg-stone-100 text-stone-700 hover:bg-stone-200'}`}
                    >
                      {candidate.symbol}
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-stone-300 bg-stone-50 px-3 py-2 text-xs text-stone-500">
                {zh ? '此数据源需要在下方手工输入真实标的 ID。' : 'This feed needs real instrument ids entered below.'}
              </div>
            )}
            <div className="mt-2 flex gap-2">
              <input
                value={symbolDraft}
                onChange={(event) => setSymbolDraft(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addDraft(); } }}
                placeholder={activeDomain?.id === 'a_share' ? (zh ? '例如 600519.SH' : 'e.g. 600519.SH') : (zh ? '加入范围内标的' : 'Add an in-scope symbol')}
                className="mono min-w-0 flex-1 rounded-md border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 outline-none focus:border-sky-500"
              />
              <button type="button" onClick={addDraft} className="rounded-md border border-stone-300 px-3 text-xs font-medium text-stone-700 hover:bg-stone-50">
                {zh ? '加入' : 'Add'}
              </button>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className={`flex items-start gap-2 rounded-lg border p-3 text-xs ${enabled ? 'border-stone-200 text-stone-700' : 'border-stone-100 text-stone-400'}`}>
              <input type="checkbox" checked={autoStart} disabled={!enabled} onChange={(event) => setAutoStart(event.target.checked)} />
              <span><strong className="block">{zh ? '创建后立即启动' : 'Start after creation'}</strong>{zh ? '核验所选标的行情后启动；核验失败时保留待运行任务。' : 'Start after quote checks; failed checks leave the run paused.'}</span>
            </label>
            <label className={`flex items-start gap-2 rounded-lg border p-3 text-xs ${enabled ? 'border-sky-200 text-stone-700' : 'border-stone-100 text-stone-400'}`}>
              <input type="checkbox" checked={autoFeedback} disabled={!enabled || strategyId !== 'signal_fusion'} onChange={(event) => setAutoFeedback(event.target.checked)} />
              <span><strong className="block">{zh ? '受限自适应反馈' : 'Guarded adaptive feedback'}</strong>{strategyId !== 'signal_fusion' ? (zh ? '当前策略不支持自动调权。' : 'This strategy does not support weight adaptation.') : (zh ? '达到最小平仓样本后才调整融合权重。' : 'Adjust fusion weights only after the minimum closed-trade sample.')}</span>
            </label>
          </div>

          <label className="block">
            <span className="text-xs font-medium uppercase tracking-[0.12em] text-stone-500">
              {zh ? '运行名称（可选）' : 'Run name (optional)'}
            </span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={zh ? '例如：美股动量长期验证' : 'e.g. US momentum long-run validation'}
              className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 outline-none transition focus:border-sky-500"
            />
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

          {catalogQuery.isError ? (
            <div className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">
              {zh ? '可运行策略目录加载失败；请检查 API 后重试。' : 'Runnable strategy catalog failed to load; check the API and retry.'}
            </div>
          ) : null}

          <p className="text-xs text-stone-500">
            {zh
              ? '启动时将重新验证真实来源、交易时段和数据新鲜度；不通过即 BLOCKED，不会以旧价或模拟报价成交。'
              : 'Start rechecks real source, session, and freshness. A failed check is BLOCKED; it never fills against stale or invented quotes.'}
          </p>

          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => void submit()}
              disabled={submitting || !enabled || !domainUsable}
              className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:opacity-50"
            >
              {!enabled ? (zh ? '先启用模拟盘' : 'Enable Paper Lab first') : !domainUsable ? (zh ? '当前不可运行' : 'Currently blocked') : submitting ? (zh ? '创建中…' : 'Creating…') : (zh ? '创建运行' : 'Create Run')}
            </button>
          </div>
          </> : null}
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
  const researchFixture = run ? isResearchFixture(run) : false;
  const metrics = detail?.metrics ?? run?.metrics ?? null;
  const [selectedInstrument, setSelectedInstrument] = useState<string>('ALL');
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

  const selectedCurveInstrument = selectedInstrument === 'ALL' ? null : selectedInstrument;
  const instrumentChartPoints = useMemo(() => {
    const curve = selectedCurveInstrument
      ? detail?.instrument_pnl_curves?.[selectedCurveInstrument] ?? []
      : [];
    return curve
      .filter((point) => Number.isFinite(point.pnl))
      .map((point) => {
        const ms = toEpochMs(point.ts);
        return {
          ts: ms,
          label: new Date(ms).toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
          }),
          pnl: point.pnl,
          realized_pnl: point.realized_pnl,
          unrealized_pnl: point.unrealized_pnl,
          degraded: point.degraded,
        };
      })
      .sort((a, b) => a.ts - b.ts);
  }, [detail?.instrument_pnl_curves, selectedCurveInstrument]);
  const instrumentCurveDegraded = instrumentChartPoints.some((point) => point.degraded);

  const trades = useMemo(() => {
    const list = detail?.trades ?? [];
    return [...list]
      .sort((a, b) => Date.parse(b.executed_at) - Date.parse(a.executed_at))
      .filter((trade) => selectedInstrument === 'ALL' || trade.instrument_id === selectedInstrument)
      .slice(0, 12);
  }, [detail?.trades, selectedInstrument]);

  const instruments = run?.universe ?? [];
  const latestObservedAt = metrics?.execution_evidence?.latest_observed_at ?? null;
  const latestObservedInstrument = metrics?.execution_evidence?.latest_observed_instrument ?? null;
  const selectedFreshnessMatches = selectedInstrument === 'ALL'
    || latestObservedInstrument === selectedInstrument;
  const freshnessAge = latestObservedAt ? Math.max(0, Date.now() - Date.parse(latestObservedAt)) : null;
  const freshnessLabel = freshnessAge === null || !Number.isFinite(freshnessAge)
    ? (zh ? 'UNKNOWN' : 'UNKNOWN')
    : freshnessAge <= 60_000
      ? (zh ? '实时/近 1 分钟' : 'Fresh / <1m')
      : freshnessAge <= 300_000
        ? (zh ? '延迟' : 'Delayed')
        : (zh ? '过期' : 'Stale');
  const hasExecutionEvidence = Boolean(
    chartPoints.length
    || instrumentChartPoints.length
    || detail?.trades?.length
    || detail?.positions?.length
    || Object.keys(metrics?.per_instrument ?? {}).length
    || detail?.feature_attribution?.features?.length,
  );
  const awaitingEvidence = !isLoading && !isError && !hasExecutionEvidence;

  return (
    <>
      <Card>
        <SectionHeader
          title={run ? `${researchFixture && zh ? '研究验收样例 · ' : ''}${run.name}` : runId}
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

        {researchFixture ? (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-900">
            {zh ? '这是历史界面验收样例，不是可用于检验策略收益的真实模拟盘运行。它没有交易、持仓、净值或归因证据，不能启动或应用策略反馈。' : 'This is a historical UI acceptance fixture, not a real paper run for evaluating strategy returns. It has no trade, position, equity, or attribution evidence and cannot be started or used for strategy feedback.'}
          </div>
        ) : null}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => onAction(runId, 'start')}
            disabled={researchFixture || !actions.start || busyAction === `${runId}:start`}
            className="rounded-full bg-emerald-600 px-4 py-1.5 text-xs font-medium text-white transition hover:bg-emerald-700 disabled:opacity-40"
          >
            {zh ? '启动' : 'Start'}
          </button>
          <button
            type="button"
            onClick={() => onAction(runId, 'pause')}
            disabled={researchFixture || !actions.pause || busyAction === `${runId}:pause`}
            className="rounded-full bg-amber-600 px-4 py-1.5 text-xs font-medium text-white transition hover:bg-amber-700 disabled:opacity-40"
          >
            {zh ? '暂停' : 'Pause'}
          </button>
          <button
            type="button"
            onClick={() => onAction(runId, 'stop')}
            disabled={researchFixture || !actions.stop || busyAction === `${runId}:stop`}
            className="rounded-full bg-stone-600 px-4 py-1.5 text-xs font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
          >
            {zh ? '停止' : 'Stop'}
          </button>

          <div className="ml-auto">
            <button
              type="button"
              onClick={() => setFeedbackConfirming(!feedbackConfirming)}
              disabled={researchFixture || busyAction === `${runId}:feedback` || run?.strategy_id !== 'signal_fusion' || run?.status === 'stopped'}
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

      {awaitingEvidence ? (
        <Card>
          <SectionHeader
            title={zh ? '等待可审计交易证据' : 'Awaiting auditable trading evidence'}
            caption={zh
              ? '该运行尚未产生报价观测、成交、持仓或净值点；收益、归因和策略反馈均保持 UNKNOWN。'
              : 'This run has no quote observation, fill, position, or equity point yet; return, attribution, and strategy feedback remain UNKNOWN.'}
          />
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <EvidenceTile label={zh ? '运行状态' : 'Run status'} value={statusLabel(run?.status, zh)} />
            <EvidenceTile label={zh ? '数据观测' : 'Quote observations'} value={String(metrics?.execution_evidence?.quote_observation_count ?? 0)} />
            <EvidenceTile label={zh ? '已审计成交' : 'Audited fills'} value={String(metrics?.trade_count ?? 0)} />
          </div>
          <p className="mt-4 border-t border-stone-200 pt-3 text-xs leading-5 text-stone-500">
            {zh
              ? '这不是零收益结论，也不是策略失败结论。请先让该资产域通过真实行情、成本和研究门禁并累积可复核成交；届时完整的逐标的曲线、归因、风险与交易明细会自动出现。'
              : 'This is neither a zero-return result nor a strategy-failure conclusion. Once this asset domain passes real-data, cost, and research gates and accumulates reviewable fills, the per-instrument curves, attribution, risk, and trade details appear automatically.'}
          </p>
        </Card>
      ) : (
        <>
      <Card>
        <SectionHeader
          title={zh ? '逐标的收益与解释' : 'Per-instrument performance & explanation'}
          caption={selectedInstrument === 'ALL' ? (zh ? '组合账户净值：现金与所有持仓按行情估值之和。' : 'Portfolio equity: cash plus the marked value of all positions.') : zh
            ? `当前曲线：${selectedCurveInstrument || 'UNKNOWN'}。这是标的净 PnL 贡献，不是重复分配后的账户 equity。`
            : `Curve: ${selectedCurveInstrument || 'UNKNOWN'}. This is instrument PnL contribution, not duplicated account equity.`}
        />
        <div className="mt-4 h-72">
          {selectedInstrument === 'ALL' && chartPoints.length ? (
            <SimulationEquityChart points={chartPoints} equityLabel={zh ? '账户净值' : 'Account equity'} />
          ) : instrumentChartPoints.length ? (
            <SimulationInstrumentPnlChart points={instrumentChartPoints} zh={zh} />
          ) : (
            <EmptyState
              className="flex h-full flex-col items-center justify-center"
              title={zh ? '暂无逐标的收益曲线' : 'No per-instrument PnL curve yet'}
              hint={zh
                ? '运行必须产生持久化标的 PnL 点；缺失时保持 UNKNOWN。'
                : 'The run must persist instrument PnL points; missing evidence stays UNKNOWN.'}
            />
          )}
        </div>
        {instrumentCurveDegraded ? (
          <div className="mt-3">
            <StatusBadge tone="warn">{zh ? 'DEGRADED：部分标记过期或缺失' : 'DEGRADED: stale or missing marks'}</StatusBadge>
          </div>
        ) : null}
        <div className="mt-4 overflow-x-auto">
          {Object.keys(metrics?.per_instrument ?? {}).length ? (
            <table className="w-full min-w-[620px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-stone-200 text-xs uppercase tracking-[0.08em] text-stone-500">
                  <th className="py-2 pr-3 font-medium">{zh ? '标的' : 'Instrument'}</th>
                  <th className="py-2 pr-3 text-right font-medium">{zh ? '已实现 PnL' : 'Realized PnL'}</th>
                  <th className="py-2 pr-3 text-right font-medium">{zh ? '成交' : 'Fills'}</th>
                  <th className="py-2 text-right font-medium">{zh ? '平仓胜率' : 'Closed win rate'}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(metrics?.per_instrument ?? {}).map(([instrument, item]) => (
                  <tr key={instrument} className="border-b border-stone-100 last:border-b-0">
                    <td className="mono py-2 pr-3 text-stone-900">{instrument}</td>
                    <td className={`py-2 pr-3 text-right font-medium ${signToneClass(item.realized_pnl)}`}>{formatSigned(item.realized_pnl, 2)}</td>
                    <td className="py-2 pr-3 text-right text-stone-700">{item.trade_count}</td>
                    <td className="py-2 text-right text-stone-700">{formatRatioAsPercent(item.win_rate, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-800">
              {zh ? 'UNKNOWN：当前运行没有逐标的成交结果。' : 'UNKNOWN: this run has no per-instrument outcome data.'}
            </div>
          )}
        </div>
      </Card>

      <Card>
        <SectionHeader
          title={zh ? '特征归因（描述性）' : 'Feature attribution (descriptive)'}
          caption={zh
            ? '权重/模型贡献不等于因果收益；已实现盈亏只是同一成交的结果关联。'
            : 'Weights/model contribution are not causal profit; realized PnL is only an association with the same fill.'}
        />
        {detail?.feature_attribution?.features?.length ? (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-stone-200 text-xs uppercase tracking-[0.08em] text-stone-500">
                  <th className="py-2 pr-3 font-medium">{zh ? '特征' : 'Feature'}</th>
                  <th className="py-2 pr-3 text-right font-medium">{zh ? '平均权重' : 'Avg weight'}</th>
                  <th className="py-2 pr-3 text-right font-medium">{zh ? '模型贡献' : 'Model contribution'}</th>
                  <th className="py-2 pr-3 text-right font-medium">{zh ? '结果关联 PnL' : 'Outcome PnL association'}</th>
                  <th className="py-2 pr-3 text-right font-medium">{zh ? '样本' : 'Samples'}</th>
                  <th className="py-2 font-medium">{zh ? '状态' : 'Status'}</th>
                </tr>
              </thead>
              <tbody>
                {detail.feature_attribution.features.map((feature) => (
                  <tr key={feature.feature_name} className="border-b border-stone-100 last:border-b-0">
                    <td className="mono py-2 pr-3 text-stone-900">{feature.feature_name}</td>
                    <td className="py-2 pr-3 text-right text-stone-700">{formatNumber(feature.average_model_weight, 3)}</td>
                    <td className={`py-2 pr-3 text-right ${signToneClass(feature.model_contribution)}`}>{formatSigned(feature.model_contribution, 3)}</td>
                    <td className={`py-2 pr-3 text-right ${signToneClass(feature.associated_realized_pnl)}`}>{formatSigned(feature.associated_realized_pnl, 2)}</td>
                    <td className="py-2 pr-3 text-right text-stone-700">{feature.closed_fill_count}/{feature.fill_count}</td>
                    <td className="py-2"><StatusBadge tone={feature.attribution_status === 'outcome_association_available' ? 'accent' : 'warn'}>{feature.attribution_status}</StatusBadge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-800">
            {zh ? 'UNKNOWN：没有与成交绑定的特征快照。' : 'UNKNOWN: no feature snapshots are linked to fills.'}
          </div>
        )}
        <div className="mt-3 text-[11px] text-stone-500">
          {zh
            ? `归因状态：${detail?.feature_attribution?.status ?? 'UNKNOWN'} · 因果声明：否 · 方法：模型加权分数 + 同成交结果关联`
            : `Attribution status: ${detail?.feature_attribution?.status ?? 'UNKNOWN'} · Causal claim: no · Method: weighted model score + same-fill outcome association`}
        </div>
      </Card>

      <Card>
        <SectionHeader
          title={zh ? '分析上下文' : 'Analysis Context'}
          caption={zh ? '所有缺失证据保持 UNKNOWN，不用零值补齐。' : 'Missing evidence remains UNKNOWN; no zero imputation.'}
        />
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <label className="text-xs text-stone-500">
            {zh ? '当前标的' : 'Selected instrument'}
            <select
              value={selectedInstrument}
              onChange={(event) => setSelectedInstrument(event.target.value)}
              className="mt-1 w-full rounded-md border border-stone-300 bg-white px-2 py-2 text-sm text-stone-900"
            >
              <option value="ALL">{zh ? '全部标的（组合）' : 'All instruments (portfolio)'}</option>
              {instruments.map((instrument) => <option key={instrument} value={instrument}>{instrument}</option>)}
            </select>
          </label>
          <div>
            <div className="text-xs text-stone-500">{zh ? '数据新鲜度' : 'Data freshness'}</div>
            <div className={`mt-1 text-sm font-semibold ${freshnessLabel === 'UNKNOWN' || !selectedFreshnessMatches ? 'text-amber-700' : 'text-stone-900'}`}>{!selectedFreshnessMatches ? 'UNKNOWN' : freshnessLabel}</div>
            <div className="mt-1 text-[11px] text-stone-400">{latestObservedAt ?? (zh ? '无报价观测' : 'No quote observation')} · {latestObservedInstrument ?? 'UNKNOWN'}</div>
          </div>
          <div>
            <div className="text-xs text-stone-500">{zh ? '报价质量' : 'Quote quality'}</div>
            <div className="mt-1 text-sm font-semibold text-stone-900">{metrics?.execution_evidence?.latest_quote_quality ?? 'UNKNOWN'}</div>
            <div className="mt-1 text-[11px] text-stone-400">{zh ? '观测数' : 'Observations'}: {metrics?.execution_evidence?.quote_observation_count ?? 'UNKNOWN'}</div>
          </div>
        </div>
      </Card>

      <Card>
        <SectionHeader
          title={zh ? '配置权重（非成交快照）' : 'Configured weights (not fill snapshots)'}
          caption={zh ? '这里只显示运行配置；实际成交使用的特征快照和模型贡献见下方归因表。' : 'Run configuration only; actual fill snapshots and model contributions are shown in the attribution table below.'}
        />
        {run?.config && typeof (run.config as Record<string, unknown>).feature_weights === 'object' ? (
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            {Object.entries((run.config as Record<string, Record<string, number>>).feature_weights).map(([name, weight]) => (
              <div key={name} className="flex items-center justify-between rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-xs">
                <span className="mono text-stone-600">{name}</span><span className="mono font-semibold text-stone-900">{formatNumber(weight, 3)}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-800">
            {zh ? 'UNKNOWN：该运行没有持久化特征权重。反馈按钮不会凭空生成权重。' : 'UNKNOWN: this run has no persisted feature weights. Feedback cannot invent weights.'}
          </div>
        )}
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
                {detail.positions.filter((position) => selectedInstrument === 'ALL' || position.instrument_id === selectedInstrument).map((position) => (
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
      )}
    </>
  );
}

function EvidenceTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-stone-200 bg-stone-50 px-3 py-2">
      <div className="text-[11px] uppercase tracking-[0.08em] text-stone-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-stone-900">{value}</div>
    </div>
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

function isResearchFixture(run: SimulationRun) {
  const config = run.config as Record<string, unknown> | undefined;
  return config?.purpose === 'ui_acceptance_fixture'
    || config?.research_fixture === true
    || /^attribution smoke$/i.test(run.name.trim());
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
