'use client';

import { useQuery } from '@tanstack/react-query';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';
import ErrorState from '@/components/ui/ErrorState';

type Tier = 'core' | 'lab' | 'archive';
type State = 'available' | 'disabled' | 'degraded' | 'unknown' | 'blocked';

interface Capability {
  capability_id: string;
  label: string;
  tier: Tier;
  state: State;
  routes: string[];
  api_prefixes: string[];
  trade_permission: boolean;
  truth: string;
  missing: string[];
}

interface CapabilityPayload {
  product_mode: string;
  trade_execution_ready: boolean;
  rows: Capability[];
}

interface RuntimePayload {
  timestamp: string;
  product_mode: string;
  config: Record<string, string | number | boolean>;
  data_sources: Array<{ id: string; state: State; refresh_seconds: number | string }>;
  services: Array<{ name: string; status: string; tier?: string }>;
  portfolio: { state: string; truth: string };
}

async function loadCapabilities(signal?: AbortSignal): Promise<CapabilityPayload> {
  const response = await fetch(`${API_BASE}/api/capabilities`, { signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function loadRuntime(signal?: AbortSignal): Promise<RuntimePayload> {
  const response = await fetch(`${API_BASE}/api/runtime/status`, { signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

const stateTone: Record<State, string> = {
  available: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  disabled: 'border-stone-200 bg-stone-100 text-stone-600',
  degraded: 'border-amber-200 bg-amber-50 text-amber-800',
  unknown: 'border-amber-200 bg-amber-50 text-amber-800',
  blocked: 'border-rose-200 bg-rose-50 text-rose-800',
};

const capabilityChinese: Record<string, { label: string; truth: string; missing: Record<string, string> }> = {
  market_observation: {
    label: '市场与标的观察',
    truth: '用于行情观察与研究；页面会显示数据源时效与覆盖范围。',
    missing: {},
  },
  research_promotion: {
    label: '研究证据与晋级门禁',
    truth: '研究门禁用于区分已验证结论与尚未放行的候选。',
    missing: { 'promotion gate is disabled': '研究门禁已关闭' },
  },
  manual_journal: {
    label: '手工交易日志',
    truth: '仅用于研究记录，不是券商或复式记账账本。',
    missing: { "execution fills are not yet the journal's sole source": '成交回报尚非日志唯一来源' },
  },
  portfolio_risk: {
    label: '组合与风险状态',
    truth: '在成交账本接入组合视图前，风险结果不具备执行权威性。',
    missing: {
      'account equity is not configured': '账户权益未配置',
      'canonical fill ledger is not connected to portfolio views': '权威成交账本尚未接入组合视图',
    },
  },
  kronos_forecast: {
    label: 'Kronos 预测实验',
    truth: '需主动开启的概率预测实验，预测本身不授予交易权限。',
    missing: { 'rolling out-of-sample calibration is not yet available': '滚动样本外校准尚不可用' },
  },
  development_control: {
    label: '开发控制与运行边界',
    truth: 'Git 关联的任务状态与本机工作台的只读能力真相。',
    missing: {},
  },
  paper_execution: {
    label: '模拟意图与篮子执行',
    truth: '原型路径存在，但未接入权威订单、成交与对账链路。',
    missing: {
      'execution ledger integration': '执行账本集成',
      reconciliation: '对账',
      'enforced kill switch': '强制熔断开关',
    },
  },
  strategy_runtime: {
    label: '策略模板与运行实例',
    truth: '模板与已停止实例仅供研究；不代表已有获准交易系统。',
    missing: {
      'approved trade edge': '获准交易优势',
      'versioned decision lineage': '版本化决策链路',
      'canonical portfolio integration': '权威组合接入',
    },
  },
  simulation: {
    label: '研究模拟盘',
    truth: '使用配置的行情事件总线进行 paper 研究比较，绝不发送真实订单。',
    missing: { 'runtime service is not started': '运行时服务未启动' },
  },
  auto_trader: {
    label: '自动交易器',
    truth: '历史实验原型，已从核心产品路径排除并默认关闭。',
    missing: {
      'approved trade edge': '获准交易优势',
      'certified venue adapter': '认证交易场所适配器',
      'execution risk controls': '执行风险控制',
    },
  },
};

function displayState(state: string | undefined, zh: boolean) {
  const normalized = (state || 'unknown').toLowerCase();
  if (!zh) return normalized;
  return ({
    available: '可用',
    disabled: '已关闭',
    degraded: '降级',
    unknown: '未知',
    blocked: '已阻断',
    not_configured: '未配置',
    running: '运行中',
    not_started: '未启动',
  } as Record<string, string>)[normalized] || normalized;
}

function capabilityDisplay(row: Capability, zh: boolean) {
  if (!zh) return { label: row.label, truth: row.truth, missing: row.missing };
  const translation = capabilityChinese[row.capability_id];
  return {
    label: translation?.label || row.label,
    truth: translation?.truth || row.truth,
    missing: row.missing.map((item) => translation?.missing[item] || item),
  };
}

function displaySource(sourceId: string, zh: boolean) {
  if (!zh) return sourceId;
  return ({
    polymarket_discovery: 'Polymarket 市场目录',
    polymarket_realtime: 'Polymarket 实时行情',
    feature_snapshots: '特征快照',
    altcoin_discovery: '加密资产发现',
  } as Record<string, string>)[sourceId] || sourceId;
}

function displayPortfolioTruth(truth: string | undefined, zh: boolean) {
  if (!zh || !truth) return truth;
  if (truth.toLowerCase().includes('account equity is not configured')) {
    return '尚未配置账户权益，因此仓位规模与组合盈亏保持未知。';
  }
  return truth;
}

export default function SettingsOverview() {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const query = useQuery({
    queryKey: ['capability-boundaries'],
    queryFn: ({ signal }) => loadCapabilities(signal),
    staleTime: 15_000,
  });
  const runtimeQuery = useQuery({
    queryKey: ['runtime-status'],
    queryFn: ({ signal }) => loadRuntime(signal),
    staleTime: 5_000,
    refetchInterval: 15_000,
  });

  if (query.isError) {
    return (
      <ErrorState
        title={zh ? '无法读取运行边界' : 'Could not load runtime boundaries'}
        message={zh ? 'API 状态未知；不会把能力显示为可用。' : 'API state is unknown; no capability is assumed available.'}
        onRetry={() => void query.refetch()}
        retryLabel={zh ? '重试' : 'Retry'}
      />
    );
  }

  const rows = query.data?.rows ?? [];
  const runtime = runtimeQuery.data;
  return (
    <div className="space-y-5">
      <section className="grid gap-4 md:grid-cols-3" aria-label={zh ? '真实运行配置' : 'Live runtime configuration'}>
        <div className="panel p-4">
          <div className="text-xs font-bold uppercase tracking-[0.12em] text-stone-500">{zh ? '数据源' : 'Data Sources'}</div>
          <div className="mt-3 space-y-2 text-sm text-stone-700">
            {(runtime?.data_sources ?? []).map((source) => <div key={source.id} className="flex justify-between gap-3"><span>{displaySource(source.id, zh)}</span><span className="font-mono text-xs">{displayState(source.state, zh)}</span></div>)}
          </div>
        </div>
        <div className="panel p-4">
          <div className="text-xs font-bold uppercase tracking-[0.12em] text-stone-500">{zh ? '持久化与刷新' : 'Persistence & Refresh'}</div>
          <div className="mt-3 space-y-2 text-sm text-stone-700">
            <div className="flex justify-between gap-3"><span>{zh ? '数据库' : 'Database'}</span><span className="text-xs">{zh ? '本机持久化存储' : String(runtime?.config.database_path ?? 'unknown')}</span></div>
            <div className="flex justify-between gap-3"><span>{zh ? '盘口日志' : 'Book log'}</span><span className="font-mono text-xs">{runtime?.config.book_log_enabled ? (zh ? '受控写入' : 'bounded') : (zh ? '已关闭' : 'disabled')}</span></div>
            <div className="flex justify-between gap-3"><span>{zh ? '更新时间' : 'Updated'}</span><span className="font-mono text-xs">{runtime?.timestamp ? new Date(runtime.timestamp).toLocaleTimeString() : (zh ? '未知' : 'unknown')}</span></div>
          </div>
        </div>
        <div className="panel p-4">
          <div className="text-xs font-bold uppercase tracking-[0.12em] text-stone-500">{zh ? '组合账本' : 'Portfolio'}</div>
          <div className="mt-3 text-sm font-semibold text-stone-900">{displayState(runtime?.portfolio.state, zh)}</div>
          <p className="mt-1 text-xs leading-5 text-stone-500">{displayPortfolioTruth(runtime?.portfolio.truth, zh) ?? (zh ? '无法读取真实状态。' : 'Live state unavailable.')}</p>
        </div>
      </section>
      <section className="panel overflow-hidden" aria-label={zh ? '系统运行边界' : 'System runtime boundary'}>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-200 px-5 py-4">
          <div>
            <div className="text-sm font-bold text-stone-900">{zh ? '能力真相矩阵' : 'Capability Truth Matrix'}</div>
            <div className="mt-1 text-xs text-stone-500">
              {query.data?.product_mode ?? (zh ? '读取中' : 'loading')}
            </div>
          </div>
          <span className="rounded-md border border-rose-200 bg-rose-50 px-2.5 py-1 text-xs font-bold text-rose-800">
            {zh ? '真实交易未就绪' : 'LIVE TRADING NOT READY'}
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-left text-sm">
            <thead className="bg-stone-50 text-xs uppercase tracking-[0.08em] text-stone-500">
              <tr>
                <th className="px-5 py-3">{zh ? '能力' : 'Capability'}</th>
                <th className="px-4 py-3">{zh ? '边界' : 'Tier'}</th>
                <th className="px-4 py-3">{zh ? '状态' : 'State'}</th>
                <th className="px-4 py-3">{zh ? '真实含义' : 'Truth'}</th>
                <th className="px-5 py-3">{zh ? '缺口' : 'Missing'}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {rows.map((row) => {
                const display = capabilityDisplay(row, zh);
                return <tr key={row.capability_id} className="align-top">
                  <td className="px-5 py-4 font-semibold text-stone-900">{display.label}</td>
                  <td className="px-4 py-4 font-mono text-xs uppercase text-stone-600">{row.tier}</td>
                  <td className="px-4 py-4">
                    <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-bold uppercase ${stateTone[row.state]}`}>
                      {displayState(row.state, zh)}
                    </span>
                  </td>
                  <td className="max-w-md px-4 py-4 leading-6 text-stone-600">{display.truth}</td>
                  <td className="max-w-sm px-5 py-4 text-xs leading-5 text-stone-500">
                    {display.missing.length ? display.missing.join(' · ') : '—'}
                  </td>
                </tr>;
              })}
              {!rows.length ? (
                <tr><td className="px-5 py-8 text-stone-500" colSpan={5}>{zh ? '正在读取真实运行状态…' : 'Loading runtime truth…'}</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <p className="text-xs leading-5 text-stone-500">
        {zh
          ? '规则：未知不等于零；API 存在不等于生产就绪；Lab 结果永远不自动获得交易权限。'
          : 'Rules: unknown is not zero; an API is not proof of production readiness; Lab output never grants trade permission.'}
      </p>
    </div>
  );
}
