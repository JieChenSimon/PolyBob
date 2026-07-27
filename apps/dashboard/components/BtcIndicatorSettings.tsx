'use client';

import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

export interface BtcIndicator {
  id: string;
  name: { zh: string; en: string };
  description: { zh: string; en: string };
  default: boolean;
  weight: number;
  experimental: boolean;
}

interface IndicatorCatalog {
  indicators: BtcIndicator[];
  default_enabled: string[];
}

/**
 * Modal to choose which indicators drive the BTC 5-minute up/down prediction.
 * Selection is persisted (localStorage) and returned via onSave; the workbench
 * client passes it to the API as ?indicators=.
 */
export default function BtcIndicatorSettings({
  open,
  selected,
  onClose,
  onSave,
}: {
  open: boolean;
  selected: string[] | null; // null = server defaults
  onClose: () => void;
  onSave: (ids: string[] | null) => void;
}) {
  const { language } = useLanguage();
  const zh = language === 'zh';

  const catalog = useQuery<IndicatorCatalog>({
    queryKey: ['btc-5m', 'indicators'],
    queryFn: async ({ signal }) => {
      const res = await fetch(`${API_BASE}/api/polymarket/btc-5m/indicators`, { signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return (await res.json()) as IndicatorCatalog;
    },
    enabled: open,
    staleTime: 60_000,
  });

  const indicators = catalog.data?.indicators ?? [];
  const defaults = catalog.data?.default_enabled ?? [];
  const [draft, setDraft] = useState<Set<string>>(new Set());

  // Initialise the draft from the current selection (or defaults) when opened.
  useEffect(() => {
    if (!open) return;
    const base = selected ?? defaults;
    if (base.length || indicators.length) setDraft(new Set(base));
  }, [open, selected, catalog.data]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null;

  const toggle = (id: string) => {
    setDraft((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const isDefaultSelection =
    draft.size === defaults.length && defaults.every((d) => draft.has(d));

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={zh ? '预测指标设置' : 'Prediction indicators'}
      className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 p-4"
      onClick={onClose}
    >
      <div
        className="panel max-h-[85vh] w-full max-w-lg overflow-y-auto p-0"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-stone-200 px-5 py-4">
          <div>
            <div className="eyebrow">{zh ? '5 分钟涨跌预测' : 'BTC 5m prediction'}</div>
            <h2 className="mt-0.5 text-lg font-bold tracking-[-0.02em] text-stone-900">
              {zh ? '选择参与预测的指标' : 'Choose prediction indicators'}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={zh ? '关闭' : 'Close'}
            className="rounded-md p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
          >
            ✕
          </button>
        </div>

        <p className="px-5 pt-3 text-xs leading-5 text-stone-500">
          {zh
            ? '勾选项会按权重融合成上涨概率（权重自动归一）。标"实验"的短周期多为噪声，建议先用门禁/校准检验。'
            : 'Checked indicators are weight-blended into P(up) (weights renormalised). "Experimental" ones are noisy at 5-min — validate via the gate/calibration first.'}
        </p>

        <div className="px-5 py-3">
          {catalog.isLoading ? (
            <div className="py-8 text-center text-sm text-stone-400">{zh ? '加载指标中…' : 'Loading…'}</div>
          ) : catalog.isError ? (
            <div className="py-8 text-center text-sm text-rose-600">{zh ? '加载失败' : 'Failed to load'}</div>
          ) : (
            <ul className="space-y-2">
              {indicators.map((ind) => {
                const checked = draft.has(ind.id);
                return (
                  <li key={ind.id}>
                    <label
                      className={`flex cursor-pointer gap-3 rounded-lg border p-3 transition ${
                        checked ? 'border-sky-300 bg-sky-50' : 'border-stone-200 hover:border-stone-300'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(ind.id)}
                        className="mt-0.5 h-4 w-4 accent-sky-600"
                      />
                      <span className="min-w-0">
                        <span className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-stone-900">
                            {zh ? ind.name.zh : ind.name.en}
                          </span>
                          <span className="rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-mono text-stone-500">
                            w={ind.weight}
                          </span>
                          {ind.experimental ? (
                            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                              {zh ? '实验' : 'experimental'}
                            </span>
                          ) : null}
                        </span>
                        <span className="mt-0.5 block text-xs leading-5 text-stone-500">
                          {zh ? ind.description.zh : ind.description.en}
                        </span>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-stone-200 px-5 py-3">
          <button
            type="button"
            onClick={() => setDraft(new Set(defaults))}
            className="text-xs font-medium text-stone-500 hover:text-stone-800"
          >
            {zh ? '恢复默认' : 'Reset to defaults'}
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-stone-200 px-3 py-1.5 text-sm text-stone-600 hover:bg-stone-50"
            >
              {zh ? '取消' : 'Cancel'}
            </button>
            <button
              type="button"
              onClick={() => onSave(isDefaultSelection ? null : Array.from(draft))}
              disabled={draft.size === 0}
              className="rounded-md bg-sky-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-sky-700 disabled:opacity-40"
            >
              {zh ? '应用' : 'Apply'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
