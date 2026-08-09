'use client';

import { useQuery } from '@tanstack/react-query';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

interface Limits {
  max_position_fraction: number;
  max_domain_fraction: number;
  max_total_risk_fraction: number;
  assumed_cross_domain_correlation: number;
}

interface AccountPayload {
  configured: boolean;
  equity: number | null;
  cash: number | null;
  open_positions: number;
  gross_notional: number;
  total_risk: number;
  correlated_risk: number;
  /** null — not 0 — when equity is unknown. 0% at risk would read as safety. */
  risk_fraction: number | null;
  positions_without_stop: number;
  limits: Limits;
  hint_zh: string | null;
}

function pct(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined || !Number.isFinite(value)
    ? '—'
    : `${(value * 100).toFixed(digits)}%`;
}

function money(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value)
    ? '—'
    : value.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

/**
 * 账户与风险预算 — the substrate the sizing half of the product was missing.
 *
 * `return = edge × size`. The edge half had a promotion gate, clustered standard
 * errors and a trial count; the size half printed `100_000 / 10` from an account
 * nobody owns. This panel shows the real one, and says plainly when there isn't
 * one — because a fabricated equity is worse than a blank, in exactly the field
 * that decides how much money moves.
 *
 * The correlated-risk figure is the one worth reading. A US equity long and an
 * altcoin short are not a hedge: in a risk-asset selloff they lose together, so
 * summing their risk as if independent is what lets two "safe" tenths become a
 * fifth of the account pointed the same way.
 */
export default function AccountPanel() {
  const { language } = useLanguage();
  const zh = language === 'zh';

  const query = useQuery<AccountPayload>({
    queryKey: ['portfolio-account'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/portfolio/account`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    refetchInterval: 120_000,
    staleTime: 60_000,
  });

  const data = query.data;
  const overBudget =
    data?.risk_fraction != null &&
    data.risk_fraction > data.limits.max_total_risk_fraction;

  return (
    <section
      aria-label={zh ? '账户与风险预算' : 'Account and risk budget'}
      className={`panel mb-6 overflow-hidden border-l-4 ${
        overBudget ? 'border-rose-500' : data?.configured ? 'border-emerald-500' : 'border-stone-300'
      }`}
    >
      <div className="border-b border-stone-200 px-5 py-4">
        <div className="eyebrow">{zh ? '仓位地基' : 'Sizing substrate'}</div>
        <h2 className="mt-0.5 text-lg font-bold tracking-[-0.02em] text-stone-900">
          {zh ? '账户与风险预算' : 'Account and risk budget'}
        </h2>
        <p className="mt-1 text-xs leading-5 text-stone-600">
          {zh
            ? '收益 = 优势 × 仓位。优势那一半有门禁、聚类标准误和试验计数;仓位这一半以前是一个写死的 100,000 除以 10。'
            : 'Return is edge times size. The edge half has a gate, clustered errors and a trial count; the size half used to be a hardcoded 100,000 divided by ten.'}
        </p>
      </div>

      {query.isPending ? (
        <p className="px-5 py-6 text-sm text-stone-400" aria-live="polite">
          {zh ? '读取中…' : 'Loading…'}
        </p>
      ) : query.isError ? (
        <p className="px-5 py-6 text-sm text-stone-500">
          {zh ? '无法读取账户状态' : 'Could not read account state'}
        </p>
      ) : !data ? null : (
        <>
          {data.hint_zh ? (
            <p className="border-b border-amber-100 bg-amber-50/70 px-5 py-3 text-xs leading-6 text-amber-900">
              {data.hint_zh}
            </p>
          ) : null}

          <div className="grid gap-px bg-stone-200 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              label={zh ? '账户权益' : 'Equity'}
              value={money(data.equity)}
              hint={data.configured ? undefined : zh ? '未配置' : 'not configured'}
              tone={data.configured ? 'plain' : 'warn'}
            />
            <Stat
              label={zh ? '持仓名义额' : 'Gross notional'}
              value={money(data.gross_notional)}
              hint={`${data.open_positions} ${zh ? '笔已成交持仓' : 'filled positions'}`}
            />
            <Stat
              label={zh ? '相关性风险' : 'Correlated risk'}
              value={money(data.correlated_risk)}
              hint={
                zh
                  ? `假设跨域相关 ${pct(data.limits.assumed_cross_domain_correlation, 0)}`
                  : `assumes ${pct(data.limits.assumed_cross_domain_correlation, 0)} cross-domain`
              }
            />
            <Stat
              label={zh ? '风险占权益' : 'Risk / equity'}
              value={pct(data.risk_fraction, 2)}
              hint={
                zh
                  ? `上限 ${pct(data.limits.max_total_risk_fraction, 0)}`
                  : `limit ${pct(data.limits.max_total_risk_fraction, 0)}`
              }
              tone={overBudget ? 'bad' : data.risk_fraction === null ? 'warn' : 'good'}
            />
          </div>

          <div className="flex flex-wrap gap-x-6 gap-y-1 px-5 py-3 text-[11px] text-stone-500">
            <span>
              {zh ? '单笔上限 ' : 'per position '}
              <span className="font-mono text-stone-700">
                {pct(data.limits.max_position_fraction, 0)}
              </span>
            </span>
            <span>
              {zh ? '单域上限 ' : 'per domain '}
              <span className="font-mono text-stone-700">
                {pct(data.limits.max_domain_fraction, 0)}
              </span>
            </span>
            {data.positions_without_stop > 0 ? (
              <span className="text-amber-700">
                {zh
                  ? `⚠ ${data.positions_without_stop} 笔没有止损价 —— 按全额名义计入风险,不是按 0`
                  : `⚠ ${data.positions_without_stop} without a stop — counted at full notional, not zero`}
              </span>
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}

function Stat({
  label,
  value,
  hint,
  tone = 'plain',
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: 'plain' | 'good' | 'warn' | 'bad';
}) {
  const toneClass =
    tone === 'good'
      ? 'text-emerald-600'
      : tone === 'warn'
        ? 'text-amber-600'
        : tone === 'bad'
          ? 'text-rose-600'
          : 'text-stone-900';
  return (
    <div className="bg-white px-5 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wide text-stone-500">{label}</div>
      <div className={`mt-1 font-mono text-xl font-bold ${toneClass}`}>{value}</div>
      {hint ? <div className="mt-0.5 text-[11px] text-stone-400">{hint}</div> : null}
    </div>
  );
}
