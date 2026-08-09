'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import ErrorState from '@/components/ui/ErrorState';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

interface JournalEntry {
  entry_id: string;
  edge_id: string;
  symbol: string;
  domain: string;
  direction: string;
  status: string;
  opened_at: string;
  planned_entry: number | null;
  planned_stop: number | null;
  planned_exit_on: string | null;
  qty: number | null;
  actual_entry: number | null;
  actual_exit: number | null;
  exit_reason: string | null;
  fees: number;
  funding: number;
  realized_pnl: number | null;
  realized_pct: number | null;
  research_pct: number | null;
  evidence: string;
  is_open: boolean;
}

interface MeasuredStats {
  closed_trades: number;
  win_rate: number;
  realized_mean_pct: number;
  research_pct: number | null;
  slippage_pct: number | null;
  total_fees: number;
  total_funding: number;
  open_positions: number;
}

interface PerformanceRow {
  edge_id: string;
  domain: string;
  research_win_rate: number | null;
  research_mean_pct: number | null;
  research_n: number | null;
  measured: MeasuredStats | null;
}

const STRATEGY_LABEL: Record<string, { zh: string; en: string }> = {
  us_insider_cluster_buy: { zh: '美股 · 内部人集群买入', en: 'US · Insider cluster buy' },
  altcoin_retail_crowding: { zh: '山寨币 · 散户拥挤', en: 'Altcoin · Retail crowding' },
};

function pct(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined || !Number.isFinite(value)
    ? '—'
    : `${value > 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

/**
 * 交易日志 — the only place this workbench measures *your* execution.
 *
 * Everything else reports a research win rate from a historical event study.
 * The north star is "持续提高胜率与收益率", and "持续提高" presupposes
 * measurement: without a record of what you actually entered, held and exited,
 * the 53.2% on the scoreboard can never be confirmed or refuted by your own
 * trading. The loop used to stop at the intent — no fill, no exit, no P&L.
 *
 * The comparison table is the point of the page. Research versus measured, with
 * the gap named, per edge.
 */
export default function JournalWorkspace() {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const queryClient = useQueryClient();

  const entriesQuery = useQuery<{ entries: JournalEntry[] }>({
    queryKey: ['journal-entries'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/journal/entries`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    refetchInterval: 60_000,
  });

  const perfQuery = useQuery<{ edges: PerformanceRow[] }>({
    queryKey: ['journal-performance'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/journal/performance`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    refetchInterval: 60_000,
  });

  const dueQuery = useQuery<{ due: JournalEntry[] }>({
    queryKey: ['journal-due'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/journal/due`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    refetchInterval: 60_000,
  });

  const refreshAll = () => {
    void queryClient.invalidateQueries({ queryKey: ['journal-entries'] });
    void queryClient.invalidateQueries({ queryKey: ['journal-performance'] });
    void queryClient.invalidateQueries({ queryKey: ['journal-due'] });
  };

  const entries = entriesQuery.data?.entries ?? [];
  const open = entries.filter((e) => e.is_open);
  const closed = entries.filter((e) => e.status === 'closed');
  const due = dueQuery.data?.due ?? [];

  return (
    <div className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:mt-8 md:px-8">
      {/* Research vs measured. Everything else on this page exists to fill it in. */}
      <section className="panel mb-6 overflow-hidden">
        <div className="border-b border-stone-200 px-5 py-4">
          <div className="eyebrow">{zh ? '北极星' : 'North star'}</div>
          <h2 className="mt-0.5 text-lg font-bold tracking-[-0.02em] text-stone-900">
            {zh ? '研究值 vs 你的实测值' : 'Research versus your measured results'}
          </h2>
          <p className="mt-1 text-xs leading-5 text-stone-500">
            {zh
              ? '记分牌上的胜率来自历史事件研究。这一栏是你自己交出来的。两者的差就是滑点——只有它能说明这条边在你手上是否还成立。'
              : 'The scoreboard reports a historical study. This is what you produced. The gap between them is the only evidence that an edge survives your own execution.'}
          </p>
        </div>

        {perfQuery.isError ? (
          <ErrorState
            className="m-5"
            title={zh ? '无法加载绩效' : 'Could not load performance'}
            message={zh ? '无法连接 PolyBob API。' : 'Cannot reach the PolyBob API.'}
            onRetry={() => void perfQuery.refetch()}
            retryLabel={zh ? '重试' : 'Retry'}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[46rem] text-sm">
              <thead>
                <tr className="border-b border-stone-200 text-left text-[11px] uppercase tracking-wide text-stone-500">
                  <th className="px-5 py-2 font-medium">{zh ? '边' : 'Edge'}</th>
                  <th className="px-3 py-2 text-right font-medium">{zh ? '研究胜率' : 'Research win'}</th>
                  <th className="px-3 py-2 text-right font-medium">{zh ? '研究收益' : 'Research'}</th>
                  <th className="px-3 py-2 text-right font-medium">{zh ? '实测胜率' : 'Measured win'}</th>
                  <th className="px-3 py-2 text-right font-medium">{zh ? '实测收益' : 'Measured'}</th>
                  <th className="px-3 py-2 text-right font-medium">{zh ? '滑点' : 'Slippage'}</th>
                  <th className="px-5 py-2 text-right font-medium">{zh ? '已平/持仓' : 'Closed/Open'}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {(perfQuery.data?.edges ?? []).map((row) => {
                  const m = row.measured;
                  const label = STRATEGY_LABEL[row.edge_id];
                  return (
                    <tr key={row.edge_id}>
                      <td className="px-5 py-3 font-medium text-stone-800">
                        {label ? (zh ? label.zh : label.en) : row.edge_id}
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-stone-600">
                        {row.research_win_rate !== null
                          ? `${(row.research_win_rate * 100).toFixed(1)}%`
                          : '—'}
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-stone-600">
                        {pct(row.research_mean_pct)}
                      </td>
                      <td className="px-3 py-3 text-right font-mono font-semibold text-stone-900">
                        {m ? `${(m.win_rate * 100).toFixed(1)}%` : '—'}
                      </td>
                      <td className="px-3 py-3 text-right font-mono font-semibold text-stone-900">
                        {m ? pct(m.realized_mean_pct) : '—'}
                      </td>
                      <td
                        className={`px-3 py-3 text-right font-mono font-bold ${
                          !m || m.slippage_pct === null
                            ? 'text-stone-400'
                            : m.slippage_pct >= 0
                              ? 'text-emerald-600'
                              : 'text-rose-600'
                        }`}
                      >
                        {m ? pct(m.slippage_pct) : '—'}
                      </td>
                      <td className="px-5 py-3 text-right font-mono text-xs text-stone-500">
                        {m ? `${m.closed_trades} / ${m.open_positions}` : '0 / 0'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {(perfQuery.data?.edges ?? []).every((r) => !r.measured) ? (
          <p className="border-t border-stone-200 bg-stone-50/60 px-5 py-3 text-xs leading-5 text-stone-600">
            {zh
              ? '还没有已平仓的交易，所以实测栏是「—」而不是 0%。零笔交易的胜率是「未知」，不是「零」。从「今日机会」里挑一条记进来开始。'
              : 'No closed trades yet, so the measured columns read “—” rather than 0%. A win rate over zero trades is unknown, not zero.'}
          </p>
        ) : null}
      </section>

      {due.length > 0 ? (
        <section className="panel mb-6 overflow-hidden border-amber-300">
          <div className="border-b border-amber-200 bg-amber-50 px-5 py-3">
            <h3 className="text-sm font-bold text-amber-900">
              {zh ? `${due.length} 个持仓已到验证过的持有期` : `${due.length} positions have reached their validated horizon`}
            </h3>
            <p className="mt-0.5 text-xs leading-5 text-amber-800">
              {zh
                ? '持有期是这条边的一部分。超期持有就是另一笔交易，不再有那份证据。'
                : 'The horizon is part of the edge. Holding past it is a different trade, and the evidence no longer describes it.'}
            </p>
          </div>
          <ul className="divide-y divide-stone-100">
            {due.map((entry) => (
              <EntryRow key={entry.entry_id} entry={entry} zh={zh} onDone={refreshAll} />
            ))}
          </ul>
        </section>
      ) : null}

      <section className="panel mb-6 overflow-hidden">
        <div className="flex items-center justify-between border-b border-stone-200 px-5 py-4">
          <h3 className="text-sm font-bold text-stone-900">
            {zh ? `持仓中 (${open.length})` : `Open (${open.length})`}
          </h3>
        </div>
        {entriesQuery.isError ? (
          <ErrorState
            className="m-5"
            title={zh ? '无法加载交易日志' : 'Could not load the journal'}
            message={zh ? '无法连接 PolyBob API。' : 'Cannot reach the PolyBob API.'}
            onRetry={() => void entriesQuery.refetch()}
            retryLabel={zh ? '重试' : 'Retry'}
          />
        ) : open.length === 0 ? (
          <p className="px-5 py-6 text-center text-sm text-stone-400">
            {zh ? '当前没有持仓' : 'No open positions'}
          </p>
        ) : (
          <ul className="divide-y divide-stone-100">
            {open.map((entry) => (
              <EntryRow key={entry.entry_id} entry={entry} zh={zh} onDone={refreshAll} />
            ))}
          </ul>
        )}
      </section>

      <section className="panel overflow-hidden">
        <div className="border-b border-stone-200 px-5 py-4">
          <h3 className="text-sm font-bold text-stone-900">
            {zh ? `已平仓 (${closed.length})` : `Closed (${closed.length})`}
          </h3>
        </div>
        {closed.length === 0 ? (
          <p className="px-5 py-6 text-center text-sm text-stone-400">
            {zh ? '还没有已平仓的交易' : 'No closed trades yet'}
          </p>
        ) : (
          <ul className="divide-y divide-stone-100">
            {closed.map((entry) => (
              <ClosedRow key={entry.entry_id} entry={entry} zh={zh} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function EntryRow({
  entry,
  zh,
  onDone,
}: {
  entry: JournalEntry;
  zh: boolean;
  onDone: () => void;
}) {
  const [price, setPrice] = useState('');
  const action = entry.status === 'planned' ? 'fill' : 'close';

  const mutation = useMutation({
    mutationFn: async () => {
      const response = await fetch(
        `${API_BASE}/api/journal/entries/${entry.entry_id}/${action}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ price: Number(price), reason: 'horizon' }),
        },
      );
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail ?? `HTTP ${response.status}`);
      }
      return response.json();
    },
    onSuccess: () => {
      setPrice('');
      onDone();
    },
  });

  return (
    <li className="px-5 py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-[15px] font-bold text-stone-900">{entry.symbol}</span>
        <span
          className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
            entry.direction === 'short'
              ? 'border-sky-300 bg-sky-100 text-sky-800'
              : 'border-emerald-300 bg-emerald-100 text-emerald-800'
          }`}
        >
          {entry.direction === 'short' ? (zh ? '做空' : 'SHORT') : zh ? '做多' : 'LONG'}
        </span>
        {entry.planned_exit_on ? (
          <span className="font-mono text-[11px] text-stone-500">
            {zh ? '到期 ' : 'exit '}
            {entry.planned_exit_on}
          </span>
        ) : null}
        {entry.actual_entry !== null ? (
          <span className="font-mono text-[11px] text-stone-500">
            {zh ? '成交 ' : 'filled '}
            {entry.actual_entry}
          </span>
        ) : null}
        <span className="min-w-0 flex-1 text-xs text-stone-500">{entry.evidence}</span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor={`price-${entry.entry_id}`}>
          {action === 'fill' ? (zh ? '成交价' : 'Fill price') : zh ? '平仓价' : 'Exit price'}
        </label>
        <input
          id={`price-${entry.entry_id}`}
          value={price}
          onChange={(event) => setPrice(event.target.value)}
          inputMode="decimal"
          placeholder={action === 'fill' ? (zh ? '成交价' : 'fill price') : zh ? '平仓价' : 'exit price'}
          className="w-32 rounded border border-stone-300 px-2 py-1 font-mono text-xs focus:border-stone-500 focus:outline-none"
        />
        <button
          type="button"
          disabled={!price || mutation.isPending}
          onClick={() => mutation.mutate()}
          className="rounded border border-stone-800 bg-stone-800 px-3 py-1 text-xs font-medium text-white transition hover:bg-stone-700 disabled:cursor-not-allowed disabled:border-stone-300 disabled:bg-stone-300"
        >
          {mutation.isPending
            ? zh ? '提交中…' : 'Saving…'
            : action === 'fill'
              ? zh ? '登记成交' : 'Record fill'
              : zh ? '登记平仓' : 'Close'}
        </button>
        {mutation.isError ? (
          <span className="text-xs text-rose-600">{(mutation.error as Error).message}</span>
        ) : null}
      </div>
    </li>
  );
}

function ClosedRow({ entry, zh }: { entry: JournalEntry; zh: boolean }) {
  const good = (entry.realized_pct ?? 0) > 0;
  const gap =
    entry.realized_pct !== null && entry.research_pct !== null
      ? entry.realized_pct - entry.research_pct
      : null;
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-5 py-3">
      <span className="font-mono text-[15px] font-bold text-stone-900">{entry.symbol}</span>
      <span className="text-[11px] text-stone-500">
        {entry.actual_entry} → {entry.actual_exit}
      </span>
      <span className="font-mono text-[11px] text-stone-400">{entry.exit_reason}</span>
      <span className="flex-1" />
      <span className="text-[11px] text-stone-500">
        {zh ? '研究 ' : 'research '}
        {pct(entry.research_pct)}
      </span>
      {gap !== null ? (
        <span className={`text-[11px] ${gap >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
          {zh ? '滑点 ' : 'slip '}
          {pct(gap)}
        </span>
      ) : null}
      <span
        className={`font-mono text-base font-bold ${good ? 'text-emerald-600' : 'text-rose-600'}`}
      >
        {pct(entry.realized_pct)}
      </span>
    </li>
  );
}
