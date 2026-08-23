'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';
import DataTrustBar from '@/components/ui/DataTrustBar';

interface DueEntry { entry_id: string; symbol: string; edge_id: string; planned_exit_on: string | null; status: string; }
interface Intent { intent_id: string; strategy_id: string; status: string; error?: string | null; }
interface ExecutionPayload { intents?: Intent[]; baskets?: Array<{ basket_id: string; status: string }>; timestamp?: string; }

async function getJson<T>(path: string, signal: AbortSignal | undefined): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

export default function PendingActionsPanel() {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const dueQuery = useQuery<{ due?: DueEntry[]; as_of?: string }>({
    queryKey: ['daily-brief', 'due'],
    queryFn: ({ signal }) => getJson('/api/journal/due', signal),
    staleTime: 20_000,
    refetchInterval: 60_000,
  });
  const executionQuery = useQuery<ExecutionPayload>({
    queryKey: ['daily-brief', 'execution'],
    queryFn: ({ signal }) => getJson('/api/execution/status', signal),
    staleTime: 8_000,
    refetchInterval: 20_000,
  });
  const due = dueQuery.data?.due ?? [];
  const intents = executionQuery.data?.intents ?? [];
  const baskets = executionQuery.data?.baskets ?? [];
  const state = dueQuery.isError || executionQuery.isError ? 'degraded' : (!dueQuery.data || !executionQuery.data ? 'unknown' : 'available');
  const observedAt = executionQuery.data?.timestamp ?? dueQuery.data?.as_of ?? null;

  return (
    <section className="panel mt-5 overflow-hidden" aria-label={zh ? '待处理事项' : 'Pending actions'}>
      <div className="border-b border-stone-200 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="eyebrow">{zh ? '操作队列' : 'ACTION QUEUE'}</div>
            <h2 className="mt-1 text-lg font-bold tracking-[-0.02em] text-stone-900">{zh ? '待处理事项' : 'Pending actions'}</h2>
          </div>
          <DataTrustBar source="PolyBob API" observedAt={observedAt} state={state} reason={state === 'degraded' ? (zh ? '至少一个队列无法读取' : 'At least one queue could not be read') : null} />
        </div>
      </div>
      <div className="divide-y divide-stone-100">
        {due.map((entry) => (
          <ActionRow key={entry.entry_id} tone="warning" title={zh ? `${entry.symbol} 到期复核` : `${entry.symbol} exit review due`} detail={`${entry.edge_id} · ${entry.planned_exit_on ?? 'UNKNOWN'}`} href="/journal" action={zh ? '打开日志' : 'Open journal'} />
        ))}
        {intents.filter((intent) => !['closed', 'abandoned', 'risk_rejected', 'duplicate_blocked'].includes(intent.status)).slice(0, 5).map((intent) => (
          <ActionRow key={intent.intent_id} tone={intent.status === 'unknown' || intent.status === 'reconciling' ? 'danger' : 'neutral'} title={zh ? `意图 ${intent.status}` : `Intent ${intent.status}`} detail={`${intent.strategy_id} · ${intent.intent_id}`} href="/execution" action={zh ? '查看执行台' : 'Open execution'} />
        ))}
        {baskets.filter((basket) => ['reconciling', 'unknown', 'cancel_failed', 'partial_failure'].includes(basket.status)).slice(0, 5).map((basket) => (
          <ActionRow key={basket.basket_id} tone="danger" title={zh ? `Basket 需要对账 · ${basket.status}` : `Basket needs reconciliation · ${basket.status}`} detail={basket.basket_id} href="/execution" action={zh ? '查看状态' : 'Review status'} />
        ))}
        {state === 'available' && due.length === 0 && intents.length === 0 && baskets.length === 0 ? (
          <div className="px-5 py-5 text-sm text-stone-500">{zh ? '当前没有可读取的待处理事项。' : 'No pending actions are currently readable.'}</div>
        ) : null}
        {state !== 'available' ? <div className="px-5 py-4 text-xs text-stone-500">{zh ? '队列不完整时不推断为空；请检查风险运营。' : 'An incomplete queue is not treated as empty; check Risk Ops.'}</div> : null}
      </div>
    </section>
  );
}

function ActionRow({ tone, title, detail, href, action }: { tone: 'warning' | 'danger' | 'neutral'; title: string; detail: string; href: string; action: string }) {
  return (
    <div className="flex flex-wrap items-center gap-3 px-5 py-3">
      <span className={`action-dot action-${tone}`} aria-hidden="true" />
      <div className="min-w-0 flex-1"><div className="text-sm font-semibold text-stone-900">{title}</div><div className="mono mt-0.5 truncate text-[11px] text-stone-500">{detail}</div></div>
      <Link href={href} className="text-xs font-semibold text-sky-700 underline decoration-sky-200 underline-offset-2">{action} →</Link>
    </div>
  );
}
