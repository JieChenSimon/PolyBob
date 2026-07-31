'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import ErrorState from '@/components/ui/ErrorState';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

interface WisdomSignal {
  kind: string;
  direction: 'buy' | 'exit';
  price: number;
  stop_price: number | null;
  stop_pct: number | null;
  confidence: number;
  volume_confirmed: boolean;
  rationale_zh: string;
  rationale_en: string;
}

interface WisdomPayload {
  symbol: string;
  domain: string;
  source: string;
  as_of: string | null;
  last_close: number;
  bars: number;
  signals: WisdomSignal[];
  position_sizing: {
    allowed: boolean;
    allocation?: number;
    risk_pct?: number;
    reason?: string;
  } | null;
  rules: { stop_loss_max_pct: number; capital_parts: number; min_risk_reward: number };
}

const KIND_LABEL: Record<string, { zh: string; en: string }> = {
  uptrend_breakout: { zh: '升势突破前高', en: 'Uptrend breakout' },
  resistance_breakout: { zh: '突破阻力线', en: 'Resistance breakout' },
  false_breakdown: { zh: '假跌破反弹', en: 'False breakdown reversal' },
  parabolic_exhaustion: { zh: '暴涨后首阴', en: 'Parabolic exhaustion' },
  distribution: { zh: '量增价滞（出货）', en: 'Distribution' },
};

/**
 * Critical-point signals from 《炒股的智慧》, usable on any instrument.
 *
 * Shows the book's stop-loss and sizing rules alongside each signal, because in
 * the book they are inseparable from the entry — and carries its own caveat that
 * these are observations for review, not gate-approved edges.
 */
export default function WisdomSignalPanel({
  symbol,
  domain = 'auto',
}: {
  symbol: string;
  domain?: string;
}) {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const [input, setInput] = useState(symbol);
  const [active, setActive] = useState(symbol);

  const query = useQuery<WisdomPayload>({
    queryKey: ['wisdom', active, domain],
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({ symbol: active, domain });
      const response = await fetch(`${API_BASE}/api/wisdom/signals?${params}`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return (await response.json()) as WisdomPayload;
    },
    enabled: Boolean(active),
    refetchInterval: 300_000,
    staleTime: 240_000,
  });

  const data = query.data;
  const signals = data?.signals ?? [];

  return (
    <section
      aria-label={zh ? '炒股的智慧信号' : 'Trading wisdom signals'}
      className="panel mb-6 overflow-hidden"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-200 px-5 py-4">
        <div>
          <div className="eyebrow">{zh ? '临界点策略' : 'Critical Points'}</div>
          <h2 className="mt-0.5 text-lg font-bold tracking-[-0.02em] text-stone-900">
            {zh ? '炒股的智慧 · 信号' : 'Trading Wisdom · Signals'}
          </h2>
        </div>
        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            setActive(input.trim());
          }}
        >
          <label className="sr-only" htmlFor={`wisdom-symbol-${symbol}`}>
            {zh ? '标的代码' : 'Symbol'}
          </label>
          <input
            id={`wisdom-symbol-${symbol}`}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            className="w-32 rounded-md border border-stone-200 bg-stone-50 px-2.5 py-1.5 font-mono text-sm text-stone-900 outline-none transition focus:border-sky-500 focus:bg-white"
          />
          <button
            type="submit"
            className="rounded-md border border-stone-200 bg-white px-3 py-1.5 text-xs font-medium text-stone-600 transition hover:border-sky-300 hover:text-sky-700"
          >
            {zh ? '分析' : 'Analyse'}
          </button>
        </form>
      </div>

      {query.isError ? (
        <ErrorState
          className="m-5"
          title={zh ? '信号加载失败' : 'Failed to load signals'}
          message={zh ? '真实行情不可用或标的代码有误。' : 'Real quotes unavailable or bad symbol.'}
          onRetry={() => void query.refetch()}
          retryLabel={zh ? '重试' : 'Retry'}
        />
      ) : null}

      {data ? (
        <div className="flex flex-wrap gap-x-5 gap-y-1 border-b border-stone-200 px-5 py-2.5 text-[11px] text-stone-500">
          <span className="font-mono font-semibold text-stone-700">{data.symbol}</span>
          <span>{data.domain}</span>
          <span>
            {zh ? '收盘 ' : 'Close '}
            <span className="font-mono text-stone-700">{data.last_close.toFixed(2)}</span>
          </span>
          <span>
            {data.bars} {zh ? '根K线' : 'bars'}
          </span>
          <span>
            {data.source} · {data.as_of}
          </span>
        </div>
      ) : null}

      {!query.isError && signals.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-stone-400" aria-live="polite">
          {query.isLoading
            ? (zh ? '分析中…' : 'Analysing…')
            : (zh ? '当前无临界点信号——书中：没有信号就等待' : 'No critical point right now — wait')}
        </div>
      ) : (
        <ul className="divide-y divide-stone-100">
          {signals.map((sig, index) => {
            const label = KIND_LABEL[sig.kind];
            const isBuy = sig.direction === 'buy';
            return (
              <li key={`${sig.kind}-${index}`} className="px-5 py-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded border px-2 py-0.5 text-[11px] font-semibold ${
                      isBuy
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                        : 'border-rose-200 bg-rose-50 text-rose-700'
                    }`}
                  >
                    {isBuy ? (zh ? '买入' : 'BUY') : (zh ? '卖出' : 'EXIT')}
                  </span>
                  <span className="text-sm font-semibold text-stone-900">
                    {label ? (zh ? label.zh : label.en) : sig.kind}
                  </span>
                  {sig.volume_confirmed ? (
                    <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-700">
                      {zh ? '放量确认' : 'volume ✓'}
                    </span>
                  ) : null}
                  <span className="ml-auto font-mono text-xs text-stone-500">
                    {zh ? '置信 ' : 'conf '}
                    {(sig.confidence * 100).toFixed(0)}%
                  </span>
                </div>

                <p className="mt-1.5 text-xs leading-5 text-stone-600">
                  {zh ? sig.rationale_zh : sig.rationale_en}
                </p>

                {sig.stop_price ? (
                  <div className="mt-2 flex flex-wrap gap-x-4 text-[11px] text-stone-500">
                    <span>
                      {zh ? '止损 ' : 'Stop '}
                      <span className="font-mono font-semibold text-rose-600">
                        {sig.stop_price.toFixed(2)}
                      </span>
                    </span>
                    {sig.stop_pct !== null ? (
                      <span>
                        {zh ? '风险 ' : 'Risk '}
                        <span className="font-mono font-semibold text-stone-700">
                          {(sig.stop_pct * 100).toFixed(1)}%
                        </span>
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      {data?.position_sizing ? (
        <div className="border-t border-stone-200 bg-stone-50/60 px-5 py-3 text-[11px] text-stone-600">
          {data.position_sizing.allowed ? (
            <>
              {zh ? '仓位建议(资金十分之一):' : 'Size (one of ten parts): '}
              <span className="font-mono font-semibold text-stone-800">
                {data.position_sizing.allocation?.toLocaleString()}
              </span>
              {zh ? ' · 单笔风险 ' : ' · risk '}
              <span className="font-mono font-semibold text-stone-800">
                {((data.position_sizing.risk_pct ?? 0) * 100).toFixed(1)}%
              </span>
            </>
          ) : (
            <>
              {zh ? '不建议入场:' : 'Entry rejected: '}
              <span className="text-rose-600">{data.position_sizing.reason}</span>
            </>
          )}
        </div>
      ) : null}

      <p className="border-t border-stone-200 px-5 py-2.5 text-[11px] leading-5 text-stone-500">
        {zh
          ? '说明:源自《炒股的智慧》(陈江挺)。作者原话「股票买卖的思维方式不是机械式的」——这些是供复核的观察,尚未通过本项目的真实数据门禁,不作为已验证优势。止损上限 20%,资金分十份,风险报酬比至少 1:3。'
          : 'From 《炒股的智慧》 (Chen Jiangting). The author insists the method "is not mechanical" — these are observations for review, and have NOT cleared this project\'s real-data promotion gate. Stop ≤20%, capital in ten parts, minimum 1:3 risk/reward.'}
      </p>
    </section>
  );
}
