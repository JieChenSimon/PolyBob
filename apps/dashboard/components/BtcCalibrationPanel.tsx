'use client';

import { useQuery } from '@tanstack/react-query';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

interface GateStatus {
  strategy: string;
  instrument: string;
  promoted: boolean;
  reason: string;
  model_matches_evidence: boolean;
  n: number | null;
  t_stat: number | null;
  t_hurdle: number | null;
  significant: boolean | null;
  brier_model: number | null;
  brier_market: number | null;
}

interface Thresholds {
  min_edge: number | null;
  configured_min_edge: number | null;
  research_min_edge: number | null;
  source: string;
  consistent: boolean | null;
  error: string | null;
}

interface WorkbenchPayload {
  gate_status?: GateStatus | null;
  thresholds?: Thresholds | null;
  action?: string;
}

/** How many samples the hypothesis needs before the gate can even be attempted. */
const TARGET_N = 200;

/**
 * BTC-5m 校准台 — what this page is for while the edge is ungated.
 *
 * The verdict banner above says the framework does not apply to a five-minute
 * binary. But the panel underneath still had the shape of a trading desk —
 * 入场判断 / 最高限价 / EV / Kelly仓位 — with every field reading "不可用". The
 * *shape* of a panel is a promise, and blanking the numbers does not withdraw
 * it; a layout built around a limit price and a position size still tells you
 * the intended use is to place an order.
 *
 * The honest framing is different. ``brier_model 0.2221 < brier_market 0.2491``
 * is a real signal: the model has been beating the market's own price. What it
 * lacks is sample size — n=95 against a t-hurdle of 3.77. So the page's job is
 * to grow n, and this panel measures that job instead of a trade.
 */
export default function BtcCalibrationPanel() {
  const { language } = useLanguage();
  const zh = language === 'zh';

  const query = useQuery<WorkbenchPayload>({
    queryKey: ['btc5m-calibration'],
    queryFn: async ({ signal }) => {
      // Its own endpoint, not the workbench's: these figures come from the
      // research file rather than the live book, and they must still render
      // when the CLOB is down — which is when this page most needs something
      // honest to say.
      const response = await fetch(`${API_BASE}/api/polymarket/btc-5m/calibration`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const gate = query.data?.gate_status ?? null;
  const thresholds = query.data?.thresholds ?? null;
  if (query.isPending) {
    return <section className="panel mb-5 border-l-4 border-slate-500 px-5 py-4 text-sm text-slate-400">{zh ? '正在读取校准证据…' : 'Loading calibration evidence…'}</section>;
  }
  if (query.isError) {
    return <section className="panel mb-5 border-l-4 border-amber-500 px-5 py-4" role="status">
      <div className="eyebrow">{zh ? '校准台' : 'Calibration'}</div>
      <h2 className="mt-1 text-base font-semibold text-stone-900">{zh ? '校准证据暂不可用' : 'Calibration evidence unavailable'}</h2>
      <p className="mt-1 text-xs leading-5 text-stone-600">{zh ? '未读取到本轮研究快照；不显示旧统计，也不生成交易动作。' : 'The current research snapshot could not be read; stale statistics and trade actions are withheld.'}</p>
    </section>;
  }
  if (!gate) return null;

  const n = gate.n;
  const progress = typeof n === 'number' ? Math.min(100, Math.round((n / TARGET_N) * 100)) : null;
  const modelBeatsMarket =
    gate.brier_model !== null && gate.brier_market !== null && gate.brier_model < gate.brier_market;

  return (
    <section className="panel mb-5 overflow-hidden border-l-4 border-sky-500">
      <div className="border-b border-stone-200 px-5 py-4">
        <div className="eyebrow">{zh ? '校准台' : 'Calibration'}</div>
        <h2 className="mt-0.5 text-lg font-bold tracking-[-0.02em] text-stone-900">
          {zh ? '这个模块现在的用途：把样本量做上去' : 'What this module is for: growing the sample'}
        </h2>
        <p className="mt-1 text-xs leading-5 text-stone-600">
          {zh
            ? '这条假设还没过门禁，所以这里不出限价、不出仓位。但模型的 Brier 分数确实优于市场价——缺的只是样本。每多观察一个窗口的结算，n 就长一格。'
            : 'The hypothesis has not cleared the gate, so no limit price and no position size are produced here. The model’s Brier score does beat the market’s, though — what is missing is sample. Every settled window adds to n.'}
        </p>
      </div>

      <div className="grid gap-px bg-stone-200 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label={zh ? '模型 Brier' : 'Model Brier'}
          value={gate.brier_model !== null ? gate.brier_model.toFixed(4) : '—'}
          tone={modelBeatsMarket ? 'good' : 'plain'}
          hint={zh ? '越低越准' : 'lower is better'}
        />
        <Stat
          label={zh ? '市场 Brier' : 'Market Brier'}
          value={gate.brier_market !== null ? gate.brier_market.toFixed(4) : '—'}
          hint={zh ? '盘口隐含概率的准度' : "the book's own accuracy"}
        />
        <Stat
          label={zh ? 't 值 / 门槛' : 't-stat / hurdle'}
          value={
            gate.t_stat !== null && gate.t_hurdle !== null
              ? `${gate.t_stat.toFixed(2)} / ${gate.t_hurdle.toFixed(2)}`
              : '—'
          }
          tone={gate.significant ? 'good' : 'warn'}
          hint={zh ? '多重检验校正后' : 'after multiple-testing correction'}
        />
        <Stat
          label={zh ? '入场阈值(来自研究)' : 'Entry threshold (from research)'}
          value={thresholds?.min_edge !== null && thresholds?.min_edge !== undefined
            ? thresholds.min_edge.toFixed(2)
            : '—'}
          tone={thresholds?.consistent === false ? 'warn' : 'plain'}
          hint={thresholds?.source ?? ''}
        />
      </div>

      <div className="px-5 py-4">
        <div className="flex items-baseline justify-between text-xs">
          <span className="font-medium text-stone-700">
            {zh ? '样本进度' : 'Sample progress'}
          </span>
          <span className="font-mono text-stone-600">
            n = {typeof n === 'number' ? n : 'UNKNOWN'} / {TARGET_N}
          </span>
        </div>
        <div
          className="mt-1.5 h-2 overflow-hidden rounded-full bg-stone-200"
          role="progressbar"
          aria-valuenow={typeof n === 'number' ? n : undefined}
          aria-valuemin={0}
          aria-valuemax={TARGET_N}
          aria-label={zh ? '样本进度' : 'Sample progress'}
        >
          <div className="h-full rounded-full bg-sky-500" style={{ width: `${progress ?? 0}%` }} />
        </div>
        <p className="mt-2 text-[11px] leading-5 text-stone-500">
          {zh
            ? `门禁状态：${gate.promoted ? '已通过' : '未通过'}——${gate.reason}`
            : `Gate: ${gate.promoted ? 'passed' : 'not passed'} — ${gate.reason}`}
        </p>
        {thresholds?.error ? (
          <p className="mt-1 text-[11px] leading-5 text-amber-700">⚠ {thresholds.error}</p>
        ) : null}
        {!gate.model_matches_evidence ? (
          <p className="mt-1 text-[11px] leading-5 text-amber-700">
            {zh
              ? '⚠ 当前启用的指标与研究时的模型不同，这些证据不适用于它。'
              : '⚠ The enabled indicators differ from the studied model, so this evidence does not describe it.'}
          </p>
        ) : null}
      </div>
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
  tone?: 'plain' | 'good' | 'warn';
}) {
  const toneClass =
    tone === 'good' ? 'text-emerald-600' : tone === 'warn' ? 'text-amber-600' : 'text-stone-900';
  return (
    <div className="bg-white px-5 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wide text-stone-500">{label}</div>
      <div className={`mt-1 font-mono text-xl font-bold ${toneClass}`}>{value}</div>
      {hint ? <div className="mt-0.5 text-[11px] text-stone-400">{hint}</div> : null}
    </div>
  );
}
