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
            {(runtime?.data_sources ?? []).map((source) => <div key={source.id} className="flex justify-between gap-3"><span>{source.id}</span><span className="font-mono text-xs">{source.state}</span></div>)}
          </div>
        </div>
        <div className="panel p-4">
          <div className="text-xs font-bold uppercase tracking-[0.12em] text-stone-500">{zh ? '持久化与刷新' : 'Persistence & Refresh'}</div>
          <div className="mt-3 space-y-2 text-sm text-stone-700">
            <div className="flex justify-between gap-3"><span>{zh ? '数据库' : 'Database'}</span><span className="max-w-[12rem] truncate font-mono text-xs">{String(runtime?.config.database_path ?? 'unknown')}</span></div>
            <div className="flex justify-between gap-3"><span>{zh ? '盘口日志' : 'Book log'}</span><span className="font-mono text-xs">{runtime?.config.book_log_enabled ? 'bounded' : 'disabled'}</span></div>
            <div className="flex justify-between gap-3"><span>{zh ? '更新时间' : 'Updated'}</span><span className="font-mono text-xs">{runtime?.timestamp ? new Date(runtime.timestamp).toLocaleTimeString() : 'unknown'}</span></div>
          </div>
        </div>
        <div className="panel p-4">
          <div className="text-xs font-bold uppercase tracking-[0.12em] text-stone-500">{zh ? 'Portfolio' : 'Portfolio'}</div>
          <div className="mt-3 text-sm font-semibold text-stone-900">{runtime?.portfolio.state ?? 'unknown'}</div>
          <p className="mt-1 text-xs leading-5 text-stone-500">{runtime?.portfolio.truth ?? (zh ? '无法读取真实状态。' : 'Live state unavailable.')}</p>
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
              {rows.map((row) => (
                <tr key={row.capability_id} className="align-top">
                  <td className="px-5 py-4 font-semibold text-stone-900">{row.label}</td>
                  <td className="px-4 py-4 font-mono text-xs uppercase text-stone-600">{row.tier}</td>
                  <td className="px-4 py-4">
                    <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-bold uppercase ${stateTone[row.state]}`}>
                      {row.state}
                    </span>
                  </td>
                  <td className="max-w-md px-4 py-4 leading-6 text-stone-600">{row.truth}</td>
                  <td className="max-w-sm px-5 py-4 text-xs leading-5 text-stone-500">
                    {row.missing.length ? row.missing.join(' · ') : '—'}
                  </td>
                </tr>
              ))}
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
