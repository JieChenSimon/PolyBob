import { describe, expect, it } from 'vitest';

import {
  STATUS_LABELS,
  buildBreakoutWatchlist,
  buildCoreConclusion,
  buildWorkbenchLeaders,
  parseAltcoinDiscovery,
  parseAltcoinCandidate,
  paginateCandidates,
  sortCandidates,
  isLiveSnapshot,
  snapshotBadge,
  formatObservedAt,
  type AltcoinCandidate,
} from './workbench';


function candidate(overrides: Partial<AltcoinCandidate>): AltcoinCandidate {
  return {
    assetId: '56:0xabc',
    chainId: '56',
    contractAddress: '0xabc',
    symbol: 'TEST',
    futuresSymbol: 'TESTUSDT',
    mappingStatus: 'unique',
    price: 1,
    marketCap: 1_000_000,
    liquidity: 2_000_000,
    volume24h: 5_000_000,
    chipConcentrationPercent: 82,
    coverage: 0.8,
    confidence: 0.8,
    pumpPotential: {
      '7d': { value: 50, coverage: 0.8, contributions: {} },
      '30d': { value: 50, coverage: 0.8, contributions: {} },
      '90d': { value: 50, coverage: 0.8, contributions: {} },
    },
    cashoutRisk: {
      '7d': { value: 50, coverage: 0.8, contributions: {} },
      '30d': { value: 50, coverage: 0.8, contributions: {} },
      '90d': { value: 50, coverage: 0.8, contributions: {} },
    },
    status: 'watch',
    vetoes: [],
    tradePlans: {},
    evidence: [],
    ...overrides,
  };
}


describe('altcoin discovery contract', () => {
  it('paginates the full candidate set into bounded 30-row windows', () => {
    const candidates = Array.from({ length: 75 }, (_, index) => candidate({
      assetId: `asset-${index}`,
      symbol: `TOKEN${index}`,
    }));

    expect(paginateCandidates(candidates, 1)).toMatchObject({
      page: 1,
      pageSize: 30,
      totalPages: 3,
    });
    expect(paginateCandidates(candidates, 1).items).toHaveLength(30);
    expect(paginateCandidates(candidates, 3).items).toHaveLength(15);
    expect(paginateCandidates(candidates, 99).page).toBe(3);
    expect(paginateCandidates(candidates, 0).page).toBe(1);
  });

  it('preserves three horizons and no-plan vetoes', () => {
    const parsed = parseAltcoinDiscovery({
      status: 'degraded',
      observed_at: '2026-06-27T12:00:00Z',
      stale: false,
      candidates: [{
        asset_id: '56:0xabc',
        chain_id: '56',
        contract_address: '0xabc',
        symbol: 'VELVET',
        futures_symbol: 'VELVETUSDT',
        mapping_status: 'unique',
        price: 1.45,
        market_cap: 1450000000,
        liquidity: 6230000,
        volume_24h: 6120000,
        chip_concentration_percent: 89.5,
        coverage: 0.68,
        confidence: 0.7,
        pump_potential: {
          '7d': { value: 72, coverage: 0.7, contributions: { control: 20 } },
          '30d': { value: 75, coverage: 0.8, contributions: { accumulation: 25 } },
          '90d': { value: 65, coverage: 0.75, contributions: { floor: 20 } },
        },
        cashout_risk: {
          '7d': { value: 48, coverage: 0.7, contributions: { dev_concentration: 20 } },
          '30d': { value: 50, coverage: 0.8, contributions: { audit_risk: 10 } },
          '90d': { value: 55, coverage: 0.75, contributions: { unlock_risk: 20 } },
        },
        status: 'data_insufficient',
        vetoes: ['COVERAGE_BELOW_MINIMUM'],
        trade_plans: {},
        evidence: [],
      }],
      source_health: {
        binance_alpha: { status: 'ok', provider: 'binance_alpha' },
      },
      chain_health: {},
      universe_counts: { alpha_total: 308, unique_intersection: 128 },
    });

    expect(parsed.candidates[0]!.pumpPotential['30d']!.value).toBe(75);
    expect(parsed.candidates[0]!.cashoutRisk['90d']!.value).toBe(55);
    expect(parsed.candidates[0]!.chipConcentrationPercent).toBe(89.5);
    expect(parsed.candidates[0]!.tradePlans['30d']).toBeUndefined();
    expect(parsed.candidates[0]!.vetoes).toContain('COVERAGE_BELOW_MINIMUM');
    expect(parsed.sourceHealth.binance_alpha.status).toBe('ok');
  });

  it('never invents candidates or source health for malformed payloads', () => {
    const parsed = parseAltcoinDiscovery({ status: 'ok' });

    expect(parsed.status).toBe('unavailable');
    expect(parsed.candidates).toEqual([]);
    expect(parsed.sourceHealth).toEqual({});
  });

  it('labels only fresh successful snapshots as live', () => {
    expect(isLiveSnapshot({ status: 'ok', stale: false })).toBe(true);
    expect(isLiveSnapshot({ status: 'degraded', stale: false })).toBe(false);
    expect(isLiveSnapshot({ status: 'unavailable', stale: false })).toBe(false);
    expect(isLiveSnapshot({ status: 'ok', stale: true })).toBe(false);
    expect(snapshotBadge({ status: 'degraded', stale: false })).toBe('degraded');
    expect(snapshotBadge({ status: 'ok', stale: true })).toBe('stale');
    expect(snapshotBadge({ status: 'unavailable', stale: false })).toBe('unavailable');
  });

  it('formats observed timestamps deterministically in Shanghai time', () => {
    expect(formatObservedAt('2026-06-28T12:03:49Z')).toBe('2026-06-28 20:03:49 CST');
    expect(formatObservedAt(null)).toBe('—');
  });

  it('keeps unavailable score values as null rather than zero', () => {
    const parsed = parseAltcoinDiscovery({
      status: 'ok',
      candidates: [{
        asset_id: '56:0xabc',
        chain_id: '56',
        contract_address: '0xabc',
        symbol: 'TEST',
        mapping_status: 'unique',
        pump_potential: {
          '7d': { value: null, coverage: 0, contributions: {} },
        },
        cashout_risk: {},
        coverage: 0,
        confidence: 0,
        vetoes: [],
        trade_plans: {},
        evidence: [],
        status: 'data_insufficient',
      }],
      source_health: {},
      chain_health: {},
      universe_counts: {},
    });

    expect(parsed.candidates[0]!.pumpPotential['7d']!.value).toBeNull();
  });

  it('parses one selected candidate detail without wrapping it in a list', () => {
    const parsed = parseAltcoinCandidate({
      asset_id: '56:0xabc',
      chain_id: '56',
      contract_address: '0xabc',
      symbol: 'VELVET',
      futures_symbol: 'VELVETUSDT',
      mapping_status: 'unique',
      coverage: 0.8,
      confidence: 0.8,
      pump_potential: {},
      cashout_risk: {},
      status: 'watch',
      vetoes: [],
      trade_plans: {},
      evidence: [],
    });

    expect(parsed?.assetId).toBe('56:0xabc');
    expect(parseAltcoinCandidate({ symbol: 'missing identity' })).toBeNull();
  });

  it('provides bilingual labels for every candidate status', () => {
    expect(STATUS_LABELS.trade_eligible.zh).toBe('可执行');
    expect(STATUS_LABELS.watch.en).toBe('Watch');
    expect(STATUS_LABELS.data_insufficient.zh).toBe('数据不足');
    expect(STATUS_LABELS.vetoed.en).toBe('Vetoed');
  });

  it('orders executable candidates before watches and vetoes', () => {
    const ordered = sortCandidates([
      candidate({ symbol: 'C', status: 'vetoed' }),
      candidate({ symbol: 'A', status: 'trade_eligible' }),
      candidate({ symbol: 'B', status: 'watch' }),
    ], '30d');

    expect(ordered.map((item) => item.symbol)).toEqual(['A', 'B', 'C']);
  });

  it('uses the horizon score to order candidates within one status', () => {
    const ordered = sortCandidates([
      candidate({ symbol: 'LOW', pumpPotential: { '30d': { value: 60, coverage: 1, contributions: {} } } }),
      candidate({ symbol: 'HIGH', pumpPotential: { '30d': { value: 80, coverage: 1, contributions: {} } } }),
    ], '30d');

    expect(ordered.map((item) => item.symbol)).toEqual(['HIGH', 'LOW']);
  });

  it('separates the best executable candidate from the highest-potential candidate', () => {
    const leaders = buildWorkbenchLeaders([
      candidate({
        symbol: 'GUA',
        status: 'trade_eligible',
        pumpPotential: { '30d': { value: 74.5, coverage: 1, contributions: {} } },
        tradePlans: {
          '30d': {
            eligible: true,
            entryLow: 0.1,
            entryHigh: 0.2,
            stop: 0.08,
            target1: 0.3,
            target2: 0.4,
            rewardRisk: 2.5,
            vetoes: [],
            positionSizes: {},
          },
        },
      }),
      candidate({
        symbol: 'BULLA',
        status: 'watch',
        pumpPotential: { '30d': { value: 83.7, coverage: 1, contributions: {} } },
        tradePlans: {
          '30d': {
            eligible: false,
            entryLow: 0.01,
            entryHigh: 0.02,
            stop: 0.008,
            target1: 0.03,
            target2: 0.04,
            rewardRisk: 2.5,
            vetoes: ['LIQUIDITY_BELOW_MINIMUM'],
            positionSizes: {},
          },
        },
      }),
    ], '30d');

    expect(leaders.actionable?.symbol).toBe('GUA');
    expect(leaders.highestPotential?.symbol).toBe('BULLA');
  });

  it('recognizes actionable list summaries even when trade plans are stripped', () => {
    const actionable = candidate({
      symbol: 'SUMMARY',
      status: 'trade_eligible',
      pumpPotential: { '30d': { value: 71, coverage: 1, contributions: {} } },
      tradePlans: {},
    });
    const leaders = buildWorkbenchLeaders([actionable], '30d');
    const picks = buildBreakoutWatchlist([actionable], '30d', 'zh');

    expect(leaders.actionable?.symbol).toBe('SUMMARY');
    expect(picks[0].blockers).toEqual([]);
  });

  it('names the exact blocker when no trade plan exists', () => {
    const conclusion = buildCoreConclusion(candidate({
      status: 'data_insufficient',
      vetoes: ['COVERAGE_BELOW_MINIMUM'],
    }), '30d', 'zh');

    expect(conclusion).toContain('数据覆盖率不足');
    expect(conclusion).not.toContain('建议买入');
  });

  it('shows the actual entry range for an eligible plan', () => {
    const conclusion = buildCoreConclusion(candidate({
      status: 'trade_eligible',
      tradePlans: {
        '30d': {
          eligible: true,
          entryLow: 1.2,
          entryHigh: 1.3,
          stop: 1.1,
          target1: 1.6,
          target2: 1.9,
          rewardRisk: 2.5,
          vetoes: [],
          positionSizes: {},
        },
      },
    }), '30d', 'zh');

    expect(conclusion).toContain('1.2');
    expect(conclusion).toContain('1.3');
  });

  it('builds a focused breakout watchlist from screened non-vetoed candidates', () => {
    const picks = buildBreakoutWatchlist([
      candidate({
        symbol: 'REJECT',
        status: 'vetoed',
        pumpPotential: { '30d': { value: 95, coverage: 1, contributions: { accumulation: 70 } } },
      }),
      candidate({
        symbol: 'MID',
        status: 'watch',
        pumpPotential: { '30d': { value: 70, coverage: 0.8, contributions: { floor: 30, washout: 20 } } },
        cashoutRisk: { '30d': { value: 42, coverage: 0.8, contributions: {} } },
      }),
      candidate({
        symbol: 'TOP',
        status: 'trade_eligible',
        pumpPotential: { '30d': { value: 82, coverage: 0.9, contributions: { accumulation: 38, control: 22, floor: 18 } } },
        cashoutRisk: { '30d': { value: 31, coverage: 0.9, contributions: {} } },
        tradePlans: {
          '30d': {
            eligible: true,
            entryLow: 0.12,
            entryHigh: 0.14,
            stop: 0.1,
            target1: 0.2,
            target2: 0.28,
            rewardRisk: 3,
            vetoes: [],
            positionSizes: {},
          },
        },
      }),
    ], '30d', 'zh');

    expect(picks.map((pick) => pick.candidate.symbol)).toEqual(['TOP', 'MID']);
    expect(picks[0].reasons.join(' ')).toContain('吸筹');
    expect(picks[0].reasons.join(' ')).toContain('观察入场');
    expect(picks[0].blockers).toEqual([]);
  });

  it('keeps breakout picks honest when evidence is incomplete', () => {
    const picks = buildBreakoutWatchlist([
      candidate({
        symbol: 'THIN',
        status: 'data_insufficient',
        coverage: 0.42,
        pumpPotential: { '30d': { value: 76, coverage: 0.4, contributions: { control: 44 } } },
        cashoutRisk: { '30d': { value: 58, coverage: 0.4, contributions: {} } },
        tradePlans: {
          '30d': {
            eligible: false,
            entryLow: null,
            entryHigh: null,
            stop: null,
            target1: null,
            target2: null,
            rewardRisk: null,
            vetoes: ['COVERAGE_BELOW_MINIMUM', 'NO_STRUCTURAL_ENTRY'],
            positionSizes: {},
          },
        },
      }),
    ], '30d', 'zh');

    expect(picks).toHaveLength(1);
    expect(picks[0].blockers.join(' ')).toContain('数据覆盖率不足');
    expect(picks[0].blockers.join(' ')).toContain('没有形成结构性入场区间');
    expect(picks[0].reasons.join(' ')).not.toContain('建议买入');
  });
});
