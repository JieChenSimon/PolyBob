'use client';

import { useQuery } from '@tanstack/react-query';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react';

import {
  STATUS_LABELS,
  VETO_LABELS,
  buildBreakoutWatchlist,
  buildCoreConclusion,
  buildWorkbenchLeaders,
  parseAltcoinCandidate,
  paginateCandidates,
  parseAltcoinDiscovery,
  isLiveSnapshot,
  snapshotBadge,
  formatObservedAt,
  sortCandidates,
  type AltcoinCandidate,
  type AltcoinDiscoveryWorkbench,
  type Horizon,
} from '@/domain/altcoinDiscovery/workbench';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';


const horizons: Horizon[] = ['7d', '30d', '90d'];
const riskModes = ['conservative', 'balanced', 'aggressive'] as const;

const copy = {
  zh: {
    title: '山寨币发现', subtitle: 'Binance Alpha × USDⓈ-M 永续 · 全链真实证据',
    conclusion: '核心结论', actionableLeader: '最佳可执行', potentialLeader: '最高潜力', potential: '爆拉潜力', risk: '兑现风险', coverage: '数据覆盖率',
    candidates: '候选榜', detail: '标的详情', allChains: '全部链', allStatuses: '全部状态',
    search: '搜索币种或合约', sourceHealth: '数据源状态', stale: '缓存快照', live: '当前快照', degraded: '能力降级', unavailable: '不可用',
    updated: '更新时间', price: '价格', marketCap: '市值', liquidity: '流动性', volume: '24h 成交额', chip: '筹码集中度',
    status: '状态', chain: '链', plan: '交易计划', entry: '观察入场区间', stop: '结构止损',
    target1: '目标一', target2: '目标二', rr: '风险收益比', position: '仓位上限',
    evidence: '证据明细', provider: '来源', field: '字段', value: '观测值', noData: '没有符合筛选条件的候选。',
    noSelection: '请选择一个候选标的。', refreshError: '刷新失败，继续显示最后成功快照。',
    detailError: '详情读取失败，继续显示列表快照。', listView: '候选', detailView: '详情',
    unknown: '不可用', coreUnavailable: '核心数据源不可用，未生成候选或交易建议。',
    breakout: '精选爆发候选', breakoutSubtitle: '从已筛选标的里二次排序，只展示高潜力且未被否决的研究对象。',
    breakoutEmpty: '当前没有达到精选阈值的候选。', reasons: '入选理由', blockers: '仍需确认', inspect: '查看',
    previous: '上一页', next: '下一页', page: '页',
  },
  en: {
    title: 'Altcoin Discovery', subtitle: 'Binance Alpha × USDⓈ-M perpetuals · real multi-chain evidence',
    conclusion: 'Core conclusion', actionableLeader: 'Best actionable', potentialLeader: 'Highest potential', potential: 'Pump potential', risk: 'Cash-out risk', coverage: 'Evidence coverage',
    candidates: 'Candidates', detail: 'Asset detail', allChains: 'All chains', allStatuses: 'All statuses',
    search: 'Search token or contract', sourceHealth: 'Source health', stale: 'Cached snapshot', live: 'Current snapshot', degraded: 'Degraded', unavailable: 'Unavailable',
    updated: 'Updated', price: 'Price', marketCap: 'Market cap', liquidity: 'Liquidity', volume: '24h volume', chip: 'Chip concentration',
    status: 'Status', chain: 'Chain', plan: 'Trade plan', entry: 'Watch entry zone', stop: 'Structural stop',
    target1: 'Target one', target2: 'Target two', rr: 'Reward / risk', position: 'Position cap',
    evidence: 'Evidence', provider: 'Provider', field: 'Field', value: 'Observed value', noData: 'No candidates match these filters.',
    noSelection: 'Select a candidate.', refreshError: 'Refresh failed; showing the last successful snapshot.',
    detailError: 'Detail request failed; showing list snapshot.', listView: 'List', detailView: 'Detail',
    unknown: 'Unavailable', coreUnavailable: 'Core providers are unavailable; no candidates or trade plans were generated.',
    breakout: 'Breakout Spotlight', breakoutSubtitle: 'Secondary ranking across screened assets; only high-potential non-vetoed research candidates are shown.',
    breakoutEmpty: 'No candidate currently reaches the spotlight threshold.', reasons: 'Why it is included', blockers: 'Still needs confirmation', inspect: 'Inspect',
    previous: 'Previous', next: 'Next', page: 'Page',
  },
};

export default function AltcoinDiscoveryWorkspace({ initialPayload }: { initialPayload?: unknown } = {}) {
  const { language } = useLanguage();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requestedSymbol = searchParams?.get('symbol')?.toUpperCase() ?? null;
  const t = copy[language];
  const initialWorkbench = useMemo(
    () => initialPayload === undefined ? undefined : parseAltcoinDiscovery(initialPayload),
    [initialPayload],
  );
  const workbenchQuery = useQuery({
    queryKey: ['crypto', 'altcoin-discovery'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/crypto/altcoin-discovery`, { signal });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return parseAltcoinDiscovery(payload);
    },
    initialData: initialWorkbench,
    refetchInterval: 10_000,
    staleTime: 8_000,
    gcTime: 10 * 60_000,
  });
  const workbench: AltcoinDiscoveryWorkbench = workbenchQuery.data ?? parseAltcoinDiscovery(undefined);
  const [horizon, setHorizon] = useState<Horizon>('30d');
  const [riskMode, setRiskMode] = useState<(typeof riskModes)[number]>('balanced');
  const [chain, setChain] = useState('all');
  const [status, setStatus] = useState('all');
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query);
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(() => workbench.candidates[0]?.assetId ?? null);
  const [showHealth, setShowHealth] = useState(false);
  const [mobileView, setMobileView] = useState<'list' | 'detail'>('list');

  const selectAsset = useCallback((assetId: string) => {
    const candidate = workbench.candidates.find((item) => item.assetId === assetId);
    setSelectedId(assetId);
    setMobileView('detail');
    if (!candidate) return;
    const params = new URLSearchParams(searchParams?.toString() ?? '');
    params.set('symbol', candidate.futuresSymbol || `${candidate.symbol}-USDT`);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }, [pathname, router, searchParams, workbench.candidates]);

  const chains = useMemo(() => [...new Set(workbench.candidates.map((item) => item.chainId))], [workbench.candidates]);
  const filtered = useMemo(() => sortCandidates(workbench.candidates.filter((item) => {
    const needle = deferredQuery.trim().toLocaleLowerCase();
    const matchesQuery = !needle || `${item.symbol} ${item.futuresSymbol ?? ''} ${item.contractAddress}`.toLocaleLowerCase().includes(needle);
    return matchesQuery && (chain === 'all' || item.chainId === chain) && (status === 'all' || item.status === status);
  }), horizon), [workbench.candidates, deferredQuery, chain, status, horizon]);
  const candidatePage = useMemo(() => paginateCandidates(filtered, page), [filtered, page]);
  const breakoutPicks = useMemo(
    () => buildBreakoutWatchlist(workbench.candidates, horizon, language),
    [workbench.candidates, horizon, language],
  );
  const leaders = useMemo(
    () => buildWorkbenchLeaders(workbench.candidates, horizon),
    [workbench.candidates, horizon],
  );

  useEffect(() => {
    const requested = requestedSymbol?.replace(/-USDT$/, '');
    const matching = requested && workbench.candidates.find((item) =>
      item.symbol.toUpperCase() === requested || item.futuresSymbol?.toUpperCase() === requestedSymbol,
    );
    if (matching) setSelectedId(matching.assetId);
  }, [requestedSymbol, workbench.candidates]);

  useEffect(() => {
    if (!selectedId || !filtered.some((item) => item.assetId === selectedId)) {
      setSelectedId(filtered[0]?.assetId ?? null);
    }
  }, [filtered, selectedId]);

  useEffect(() => setPage(1), [deferredQuery, chain, status, horizon]);

  const detailQuery = useQuery({
    queryKey: ['crypto', 'altcoin-discovery', 'detail', selectedId],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/crypto/altcoin-discovery/${encodeURIComponent(selectedId as string)}`, { signal });
      const parsed = parseAltcoinCandidate(await response.json());
      if (!response.ok || parsed === null) {
        throw new Error(`HTTP ${response.status}`);
      }
      return parsed;
    },
    enabled: selectedId !== null,
    staleTime: 30_000,
  });

  const listSelection = workbench.candidates.find((item) => item.assetId === selectedId) ?? null;
  const detail = detailQuery.data ?? null;
  const selected = detail?.assetId === selectedId ? detail : listSelection;
  const plan = selected?.tradePlans[horizon];
  const position = plan?.positionSizes[riskMode];
  const conclusion = selected ? buildCoreConclusion(selected, horizon, language) : t.coreUnavailable;
  const badge = snapshotBadge(workbench);
  const refreshError = workbenchQuery.isError ? t.refreshError : null;
  const detailError = detailQuery.isError ? t.detailError : null;

  return (
    <section aria-label={language === 'zh' ? '山寨币发现工作台' : 'Altcoin discovery workbench'} className="crypto-workbench panel mx-auto mt-5 w-[calc(100%-24px)] max-w-shell overflow-hidden text-stone-900 md:mt-6 md:w-full">
      <header className="border-b border-stone-200 bg-stone-50 px-4 py-3 md:px-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[11px] font-semibold uppercase text-sky-600">Crypto / Altcoin Discovery</div>
            <h1 className="mt-1 text-xl font-bold md:text-2xl">{t.title}</h1>
            <p className="mt-1 text-xs text-stone-500">{t.subtitle}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <button type="button" onClick={() => setShowHealth((value) => !value)} className="terminal-button">{t.sourceHealth}</button>
            <button type="button" onClick={() => void workbenchQuery.refetch()} className="terminal-icon-button" title={language === 'zh' ? '立即刷新' : 'Refresh now'} aria-label={language === 'zh' ? '立即刷新' : 'Refresh now'}>↻</button>
            <span className={isLiveSnapshot(workbench) ? 'status-chip ok' : 'status-chip warning'}>
              {t[badge]}
            </span>
          </div>
        </div>
      </header>

      {(refreshError || detailError) && <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700">{refreshError || detailError}</div>}
      {showHealth && <SourceHealthPanel workbench={workbench} language={language} />}

      <section className="grid border-b border-stone-200 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.6fr),repeat(5,minmax(0,1fr))]">
        <Metric label={t.conclusion} value={conclusion} emphasis />
        <Metric label={t.actionableLeader} value={formatLeader(leaders.actionable, horizon)} tone="positive" />
        <Metric label={t.potentialLeader} value={formatLeader(leaders.highestPotential, horizon)} tone="positive" />
        <Metric label={`${t.potential} · ${horizon}`} value={formatScore(selected?.pumpPotential[horizon]?.value)} tone="positive" />
        <Metric label={`${t.risk} · ${horizon}`} value={formatScore(selected?.cashoutRisk[horizon]?.value)} tone="negative" />
        <Metric label={t.coverage} value={formatPercent(selected?.coverage)} />
      </section>

      <BreakoutSpotlight
        picks={breakoutPicks}
        selectedId={selectedId}
        horizon={horizon}
        language={language}
        onSelect={selectAsset}
      />

      <section className="flex flex-wrap items-center gap-2 border-b border-stone-200 bg-white px-3 py-2">
        <Segmented values={horizons} selected={horizon} onSelect={setHorizon} />
        <select value={chain} onChange={(event) => setChain(event.target.value)} className="terminal-select" aria-label={t.chain}>
          <option value="all">{t.allChains}</option>
          {chains.map((value) => <option key={value} value={value}>{chainName(value)}</option>)}
        </select>
        <select value={status} onChange={(event) => setStatus(event.target.value)} className="terminal-select" aria-label={t.status}>
          <option value="all">{t.allStatuses}</option>
          {Object.entries(STATUS_LABELS).map(([key, label]) => <option key={key} value={key}>{label[language]}</option>)}
        </select>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t.search} className="terminal-input min-w-[210px] flex-1" />
        <div className="ml-auto text-[11px] text-stone-500">{t.updated}: {formatObservedAt(workbench.observedAt)}</div>
      </section>

      <div className="flex border-b border-stone-200 md:hidden">
        <button type="button" onClick={() => setMobileView('list')} className={`mobile-view-button ${mobileView === 'list' ? 'active' : ''}`}>{t.listView}</button>
        <button type="button" onClick={() => setMobileView('detail')} className={`mobile-view-button ${mobileView === 'detail' ? 'active' : ''}`}>{t.detailView}</button>
      </div>

      <section className="grid min-h-[560px] md:grid-cols-[minmax(0,1.6fr)_minmax(360px,1fr)]">
        <div className={`${mobileView === 'detail' ? 'hidden' : 'block'} min-w-0 border-stone-200 md:block md:border-r`}>
          <div className="terminal-section-title"><span>{t.candidates}</span><span>{filtered.length} / {workbench.candidates.length}</span></div>
          <CandidateTable candidates={candidatePage.items} selectedId={selectedId} horizon={horizon} language={language} onSelect={selectAsset} />
          {filtered.length > 0 && (
            <div className="flex items-center justify-between border-t border-stone-200 bg-white px-3 py-2 text-xs">
              <button type="button" className="terminal-button" disabled={candidatePage.page === 1} onClick={() => setPage(candidatePage.page - 1)}>{t.previous}</button>
              <span className="font-mono text-stone-500">{t.page} {candidatePage.page} / {candidatePage.totalPages}</span>
              <button type="button" className="terminal-button" disabled={candidatePage.page === candidatePage.totalPages} onClick={() => setPage(candidatePage.page + 1)}>{t.next}</button>
            </div>
          )}
        </div>
        <div className={`${mobileView === 'list' ? 'hidden' : 'block'} min-w-0 md:block`}>
          <div className="terminal-section-title"><span>{t.detail}</span><span className="truncate mono">{selected?.futuresSymbol ?? '—'}</span></div>
          {selected ? (
            <div>
              <div className="sticky top-0 z-10 flex items-center justify-between border-b border-stone-200 bg-white px-4 py-3 md:static">
                <div><strong className="text-lg">{selected.symbol}</strong><span className="ml-2 text-xs text-stone-500">{chainName(selected.chainId)}</span></div>
                <span className={`candidate-status ${selected.status}`}>{STATUS_LABELS[selected.status][language]}</span>
              </div>
              <div className="grid grid-cols-2 border-b border-stone-200 xl:grid-cols-5">
                <SmallMetric label={t.price} value={formatPrice(selected.price)} />
                <SmallMetric label={t.marketCap} value={formatUsd(selected.marketCap)} />
                <SmallMetric label={t.liquidity} value={formatUsd(selected.liquidity)} />
                <SmallMetric label={t.volume} value={formatUsd(selected.volume24h)} />
                <SmallMetric label={t.chip} value={formatPercentValue(selected.chipConcentrationPercent)} />
              </div>
              <div className="border-b border-stone-200 px-4 py-4">
                <div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold">{t.plan} · {horizon}</h2><Segmented values={riskModes} selected={riskMode} onSelect={setRiskMode} /></div>
                <div className="grid grid-cols-2 gap-px bg-stone-200 sm:grid-cols-3">
                  <SmallMetric label={t.entry} value={plan?.entryLow !== null && plan?.entryLow !== undefined && plan.entryHigh !== null ? `${formatPrice(plan.entryLow)} – ${formatPrice(plan.entryHigh)}` : '—'} />
                  <SmallMetric label={t.stop} value={formatPrice(plan?.stop)} />
                  <SmallMetric label={t.target1} value={formatPrice(plan?.target1)} />
                  <SmallMetric label={t.target2} value={formatPrice(plan?.target2)} />
                  <SmallMetric label={t.rr} value={plan?.rewardRisk === null || plan?.rewardRisk === undefined ? '—' : `${plan.rewardRisk.toFixed(2)} : 1`} />
                  <SmallMetric label={t.position} value={position?.quantity === null || position?.quantity === undefined ? '—' : position.quantity.toLocaleString()} />
                </div>
                {position?.quantity === null && <p className="mt-2 text-[11px] text-stone-500">{language === 'zh' ? '组合权益未配置：保留结构价位，不伪造合约数量。' : 'Portfolio equity is not configured; structural prices remain, quantity is unavailable.'}</p>}
              </div>
              <EvidencePanel candidate={selected} horizon={horizon} language={language} />
            </div>
          ) : <div className="p-8 text-sm text-stone-500">{t.noSelection}</div>}
        </div>
      </section>
    </section>
  );
}

function BreakoutSpotlight({ picks, selectedId, horizon, language, onSelect }: { picks: ReturnType<typeof buildBreakoutWatchlist>; selectedId: string | null; horizon: Horizon; language: 'zh' | 'en'; onSelect: (id: string) => void }) {
  const t = copy[language];
  return (
    <section className="border-b border-stone-200 bg-white">
      <div className="terminal-section-title">
        <span>{t.breakout}</span>
        <span>{horizon} · {picks.length}</span>
      </div>
      <div className="px-3 py-3">
        <p className="mb-3 text-[11px] text-stone-500">{t.breakoutSubtitle}</p>
        {picks.length === 0 ? (
          <div className="border border-stone-200 bg-white px-3 py-3 text-xs text-stone-500">{t.breakoutEmpty}</div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-3">
            {picks.map((pick, index) => {
              const selected = pick.candidate.assetId === selectedId;
              return (
                <article key={pick.candidate.assetId} className={`min-w-0 border bg-white p-3 ${selected ? 'border-sky-500 shadow-[inset_3px_0_0_#0284c7]' : 'border-stone-200'}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[10px] font-semibold uppercase text-sky-600">#{index + 1}</div>
                      <div className="mt-1 flex min-w-0 items-center gap-2">
                        <strong className="truncate text-base">{pick.candidate.symbol}</strong>
                        <span className={`candidate-status ${pick.candidate.status}`}>{STATUS_LABELS[pick.candidate.status][language]}</span>
                      </div>
                      <div className="mt-1 truncate font-mono text-[10px] text-stone-400">{pick.candidate.futuresSymbol ?? pick.candidate.contractAddress}</div>
                    </div>
                    <button type="button" className="terminal-button shrink-0" onClick={() => onSelect(pick.candidate.assetId)}>{t.inspect}</button>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-px bg-stone-100">
                    <SmallMetric label={t.potential} value={formatScore(pick.candidate.pumpPotential[horizon]?.value)} />
                    <SmallMetric label={t.risk} value={formatScore(pick.candidate.cashoutRisk[horizon]?.value)} />
                    <SmallMetric label={t.chip} value={formatPercentValue(pick.candidate.chipConcentrationPercent)} />
                  </div>
                  <div className="mt-3">
                    <div className="text-[10px] font-semibold uppercase text-stone-400">{t.reasons}</div>
                    <ul className="mt-1 space-y-1 text-xs text-stone-700">
                      {pick.reasons.slice(0, 5).map((reason) => <li key={reason} className="leading-5">• {reason}</li>)}
                    </ul>
                  </div>
                  {pick.blockers.length > 0 && (
                    <div className="mt-3 border-l-2 border-amber-400 bg-amber-50 px-2 py-2">
                      <div className="text-[10px] font-semibold uppercase text-amber-600">{t.blockers}</div>
                      <ul className="mt-1 space-y-1 text-xs text-amber-100">
                        {pick.blockers.map((blocker) => <li key={blocker} className="leading-5">• {blocker}</li>)}
                      </ul>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

function CandidateTable({ candidates, selectedId, horizon, language, onSelect }: { candidates: AltcoinCandidate[]; selectedId: string | null; horizon: Horizon; language: 'zh' | 'en'; onSelect: (id: string) => void }) {
  const t = copy[language];
  if (candidates.length === 0) return <div className="p-8 text-sm text-stone-500">{t.noData}</div>;
  return <div className="max-h-[620px] overflow-auto"><table className="terminal-table"><thead><tr><th>{language === 'zh' ? '标的' : 'Asset'}</th><th>{t.chain}</th><th>{t.price}</th><th>{t.marketCap}</th><th>{t.chip}</th><th>7D</th><th>30D</th><th>90D</th><th>{t.risk}</th><th>{t.coverage}</th></tr></thead><tbody>{candidates.map((item) => <tr key={item.assetId} className={item.assetId === selectedId ? 'selected' : ''} onClick={() => onSelect(item.assetId)}><td><strong>{item.symbol}</strong><small>{item.futuresSymbol ?? 'NO PERP'}</small></td><td>{chainName(item.chainId)}</td><td className="mono">{formatPrice(item.price)}</td><td>{formatUsd(item.marketCap)}</td><td>{formatPercentValue(item.chipConcentrationPercent)}</td>{horizons.map((value) => <td key={value}>{formatScore(item.pumpPotential[value]?.value)}</td>)}<td className="risk-value">{formatScore(item.cashoutRisk[horizon]?.value)}</td><td>{formatPercent(item.coverage)}</td></tr>)}</tbody></table></div>;
}

function EvidencePanel({ candidate, horizon, language }: { candidate: AltcoinCandidate; horizon: Horizon; language: 'zh' | 'en' }) {
  const t = copy[language];
  const plan = candidate.tradePlans[horizon];
  const vetoes = [...new Set([...candidate.vetoes, ...(plan?.vetoes ?? [])])];
  return <div className="px-4 py-4"><h2 className="text-sm font-semibold">{t.evidence}</h2>{vetoes.length > 0 && <div className="mt-3 border-l-2 border-amber-400 bg-amber-50 px-3 py-2 text-xs text-amber-100">{vetoes.map((code) => <div key={code}>{VETO_LABELS[code]?.[language] ?? code}</div>)}</div>}<div className="mt-3 overflow-x-auto"><table className="terminal-table compact"><thead><tr><th>{language === 'zh' ? '指标' : 'Metric'}</th><th>{t.value}</th><th>{t.provider}</th><th>{t.field}</th></tr></thead><tbody>{candidate.evidence.map((item, index) => <tr key={`${item.name}-${index}`}><td>{item.name}</td><td className="mono">{formatEvidence(item.value)}</td><td>{item.provider}</td><td>{item.field ?? '—'}</td></tr>)}</tbody></table></div></div>;
}

function SourceHealthPanel({ workbench, language }: { workbench: AltcoinDiscoveryWorkbench; language: 'zh' | 'en' }) {
  const sources = [...Object.entries(workbench.sourceHealth), ...Object.entries(workbench.chainHealth)];
  return <div className="grid border-b border-stone-200 bg-white sm:grid-cols-2 lg:grid-cols-4">{sources.map(([key, health]) => <div key={key} className="border-b border-r border-stone-200 px-3 py-2 text-xs"><div className="flex justify-between gap-2"><strong>{health.provider}</strong><span className={`health-dot ${health.status}`}>{health.status}</span></div><p className="mt-1 text-stone-500">{health.message ?? health.failureCategory ?? (language === 'zh' ? '无补充信息' : 'No additional detail')}</p></div>)}</div>;
}

function Metric({ label, value, emphasis = false, tone }: { label: string; value: string; emphasis?: boolean; tone?: 'positive' | 'negative' }) { return <div className="min-w-0 border-b border-r border-stone-200 px-4 py-3"><div className="text-[10px] uppercase text-stone-400">{label}</div><div className={`mt-1 ${emphasis ? 'text-sm font-semibold leading-5 text-amber-600' : 'text-xl font-bold'} ${tone === 'positive' ? 'text-emerald-400' : tone === 'negative' ? 'text-rose-400' : ''}`}>{value}</div></div>; }
function SmallMetric({ label, value }: { label: string; value: string }) { return <div className="min-w-0 bg-white px-3 py-3"><div className="text-[10px] text-stone-400">{label}</div><div className="mt-1 break-words font-mono text-sm font-semibold">{value}</div></div>; }
function Segmented<T extends string>({ values, selected, onSelect }: { values: readonly T[]; selected: T; onSelect: (value: T) => void }) { return <div className="flex border border-stone-200">{values.map((value) => <button type="button" key={value} onClick={() => onSelect(value)} className={`terminal-segment ${selected === value ? 'active' : ''}`}>{value}</button>)}</div>; }
function chainName(value: string) { return ({ '1': 'ETH', '56': 'BSC', '8453': 'BASE', CT_501: 'SOL' } as Record<string, string>)[value] ?? value; }
function formatPrice(value: number | null | undefined) { if (value === null || value === undefined) return '—'; return value >= 1 ? value.toLocaleString('en-US', { maximumFractionDigits: 4 }) : value.toLocaleString('en-US', { maximumSignificantDigits: 6 }); }
function formatUsd(value: number | null | undefined) { if (value === null || value === undefined) return '—'; return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 2 }).format(value); }
function formatScore(value: number | null | undefined) { return value === null || value === undefined ? '—' : value.toFixed(1); }
function formatPercent(value: number | null | undefined) { return value === null || value === undefined ? '—' : `${(value * 100).toFixed(0)}%`; }
function formatPercentValue(value: number | null | undefined) { return value === null || value === undefined ? '—' : `${value.toFixed(1)}%`; }
function formatLeader(candidate: AltcoinCandidate | null, horizon: Horizon) { return candidate ? `${candidate.symbol} ${formatScore(candidate.pumpPotential[horizon]?.value)}` : '—'; }
function formatEvidence(value: unknown) { if (typeof value === 'number') return Number.isFinite(value) ? value.toFixed(4) : '—'; if (typeof value === 'string') return value; if (value === null || value === undefined) return '—'; return JSON.stringify(value); }
