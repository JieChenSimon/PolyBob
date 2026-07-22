import { describe, expect, it } from 'vitest';
import { buildUnavailableBtcFiveMinuteWorkbench, parseBtcFiveMinuteWorkbench } from './workbench';

describe('BTC five-minute workbench domain', () => {
  it('accepts real CLOB payloads with both outcomes', () => {
    const parsed = parseBtcFiveMinuteWorkbench({
      source: 'polymarket_clob',
      action: 'watch_up',
      recommended_outcome: 'UP',
      reason_codes: [],
      slug: 'btc-updown-5m-1782384600',
      seconds_to_expiry: 120,
      target_price: { source: 'polymarket_event_metadata', price: 61189.13539580122 },
      btc_reference: {
        source: 'okx_swap',
        price: 107500,
        timestamp: '2026-06-25T10:51:41Z',
        provider_timestamp: '2026-06-25T10:51:40.900Z',
        received_at: '2026-06-25T10:51:41Z',
        round_trip_ms: 83,
        staleness_ms: 100,
        latency_quality: 'provider_timestamp',
        sources: [
          {
            source: 'okx_swap',
            symbol: 'BTC-USDT-SWAP',
            status: 'ok',
            selected: true,
            price: 107500,
            provider_timestamp: '2026-06-25T10:51:40.900Z',
            received_at: '2026-06-25T10:51:41Z',
            round_trip_ms: 83,
            staleness_ms: 100,
            latency_quality: 'provider_timestamp',
          },
          {
            source: 'coinbase_spot',
            symbol: 'BTC-USD',
            status: 'error',
            selected: false,
            price: null,
            received_at: '2026-06-25T10:51:41Z',
            round_trip_ms: 300,
            staleness_ms: null,
            latency_quality: 'unavailable',
            error: 'timeout',
          },
        ],
      },
      data_health: {
        polymarket_market: { status: 'ok', provider: 'Polymarket Gamma', message: 'market resolved' },
        polymarket_orderbook: { status: 'ok', provider: 'Polymarket CLOB', message: 'both books loaded' },
        btc_reference: { status: 'ok', provider: 'okx_swap', message: 'reference available' },
        target_price: { status: 'ok', provider: 'Polymarket', message: 'target available' },
      },
      entry_optimizer: {
        decision: 'enter',
        recommended_outcome: 'UP',
        core_conclusion: '当前入场候选：UP，限价不高于 0.500，建议仓位 3.00%。',
        max_acceptable_price: 0.5,
        kelly_fraction: 0.03,
        expected_value: 0.08,
        win_probability: 0.62,
      },
      outcomes: {
        UP: {
          token_id: 'up-token',
          is_real_orderbook: true,
          best_bid: 0.48,
          best_ask: 0.5,
          spread: 0.02,
          bid_depth_top3: 900,
          ask_depth_top3: 900,
          candidate_entry_price: 0.5,
          estimated_edge: 0.06,
          model_probability: 0.56,
          entry_analysis: {
            entry_decision: 'enter',
            entry_price: 0.5,
            max_acceptable_price: 0.5,
            win_probability: 0.62,
            expected_value: 0.08,
            cost_penalty: 0.01,
            kelly_fraction: 0.03,
            entry_band: { enter_below: 0.5, watch_below: 0.52, avoid_above: 0.55 },
            risk_notes: [],
          },
          levels: { bids: [{ price: 0.48, size: 900 }], asks: [{ price: 0.5, size: 900 }] },
        },
        DOWN: {
          token_id: 'down-token',
          is_real_orderbook: true,
          best_bid: 0.47,
          best_ask: 0.49,
          spread: 0.02,
          bid_depth_top3: 900,
          ask_depth_top3: 900,
          candidate_entry_price: null,
          estimated_edge: -0.05,
          model_probability: 0.44,
          entry_analysis: {
            entry_decision: 'avoid',
            entry_price: 0.49,
            max_acceptable_price: 0.3,
            win_probability: 0.38,
            expected_value: -0.08,
            cost_penalty: 0.01,
            kelly_fraction: 0,
            entry_band: { enter_below: 0.3, watch_below: 0.31, avoid_above: 0.34 },
            risk_notes: ['NEGATIVE_OR_SMALL_EV'],
          },
          levels: { bids: [{ price: 0.47, size: 900 }], asks: [{ price: 0.49, size: 900 }] },
        },
      },
    });

    expect(parsed.isTradable).toBe(true);
    expect(parsed.coreConclusion).toContain('UP');
    expect(parsed.outcomes.UP.candidate_entry_price).toBe(0.5);
    expect(parsed.target_price?.price).toBe(61189.13539580122);
    expect(parsed.btc_reference?.source).toBe('okx_swap');
    expect(parsed.btc_reference?.staleness_ms).toBe(100);
    expect(parsed.btc_reference?.sources[0].selected).toBe(true);
    expect(parsed.data_health.btc_reference.status).toBe('ok');
    expect(parsed.data_health.polymarket_orderbook.status).toBe('ok');
    expect(parsed.entry_optimizer?.decision).toBe('enter');
    expect(parsed.entry_optimizer?.recommended_outcome).toBe('UP');
    expect(parsed.outcomes.UP.entry_analysis?.entry_decision).toBe('enter');
    expect(parsed.outcomes.UP.entry_analysis?.entry_band.enter_below).toBe(0.5);
  });

  it('keeps unavailable payloads as no-trade without fake outcomes', () => {
    const parsed = parseBtcFiveMinuteWorkbench({
      source: 'unavailable',
      action: 'no_trade',
      recommended_outcome: null,
      reason_codes: ['WORKBENCH_UNAVAILABLE'],
      error: '503 Service Unavailable',
      error_diagnosis: {
        category: 'provider_status',
        responsibility: 'external_provider',
        provider: 'Polymarket Gamma',
        endpoint: 'https://gamma-api.polymarket.com/markets',
        retryable: true,
        likely_cause: 'Polymarket Gamma 返回 503。',
        user_action: '等待外部服务恢复。',
        technical_detail: '503 Service Unavailable',
      },
      btc_reference: {
        source: 'coinbase_spot',
        symbol: 'BTC-USD',
        price: 58571.39,
        sources: [{ source: 'coinbase_spot', symbol: 'BTC-USD', status: 'ok', selected: true, price: 58571.39 }],
      },
      data_health: {
        polymarket_market: { status: 'unavailable', provider: 'Polymarket Gamma', message: '503 Service Unavailable' },
        polymarket_orderbook: { status: 'unavailable', provider: 'Polymarket CLOB', message: 'order book not loaded because market discovery failed' },
        btc_reference: { status: 'ok', provider: 'coinbase_spot', message: 'BTC reference available' },
        target_price: { status: 'unavailable', provider: 'Polymarket page', message: 'target unavailable' },
      },
    });

    expect(parsed.isTradable).toBe(false);
    expect(parsed.coreConclusion).toBe('真实盘口不可用，跳过交易。');
    expect(parsed.outcomes.UP.is_real_orderbook).toBe(false);
    expect(parsed.outcomes.UP.candidate_entry_price).toBeNull();
    expect(parsed.error_diagnosis?.category).toBe('provider_status');
    expect(parsed.error_diagnosis?.provider).toBe('Polymarket Gamma');
    expect(parsed.btc_reference?.price).toBe(58571.39);
    expect(parsed.data_health.btc_reference.status).toBe('ok');
    expect(parsed.data_health.polymarket_market.message).toContain('503');
  });

  it('builds a no-trade snapshot when the frontend request fails', () => {
    const parsed = buildUnavailableBtcFiveMinuteWorkbench(new Error('network failed'));

    expect(parsed.source).toBe('unavailable');
    expect(parsed.action).toBe('no_trade');
    expect(parsed.isTradable).toBe(false);
    expect(parsed.error).toBe('network failed');
    expect(parsed.error_diagnosis?.category).toBe('local_api');
    expect(parsed.error_diagnosis?.responsibility).toBe('browser_to_polybob_api');
    expect(parsed.data_health.btc_reference.status).toBe('unavailable');
    expect(parsed.data_health.polymarket_market.status).toBe('unavailable');
  });
});
