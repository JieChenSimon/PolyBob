export interface MarketFeatures {
  market_id: string;
  timestamp: string;
  mid_price: number;
  spread_bps: number;
  bid_price: number;
  ask_price: number;
  bid_size: number;
  ask_size: number;
  depth_imbalance: number;
  trade_intensity_1m: number;
  volume_1m: number;
  price_jump_score: number;
}

export interface DashboardMarket {
  market_id: string;
  gamma_market_id: string;
  slug: string;
  question: string;
  category: string | null;
  status: string;
  end_time: string | null;
  liquidity_score: number;
  primary_asset_id: string | null;
  features: MarketFeatures | null;
}

export interface StrategyTemplate {
  strategy_id: string;
  name: string;
  description: string;
  family: string;
  status: string;
  runtime_mode: string;
  parameters: Record<string, number | string | boolean | null>;
  risk_limits: Record<string, number | string | boolean | null>;
  product_status?: string;
  evidence_status?: string;
  fundamental_evidence?: string;
  pit_status?: string;
  trade_permission?: boolean;
  unknown_fields?: string[];
  basic_evidence?: Record<string, unknown>;
}

export interface StrategyInstance {
  instance_id: string;
  strategy_id: string;
  name: string;
  config: Record<string, number | string | boolean | null>;
  risk_limits: Record<string, number | string | boolean | null>;
  status: string;
  environment: string;
  created_at: string;
  updated_at: string;
  last_started_at: string | null;
  last_stopped_at: string | null;
  error: string | null;
}

export interface OverviewPayload {
  system: {
    api_connected: boolean;
    timestamp: string;
    mode: string;
    operating_model?: string;
  };
  markets: {
    tracked: number;
    feature_ready: number;
    widest_spread_bps: number | null;
  };
  strategy_center: {
    template_count: number;
    active_instances: number;
    families: string[];
    intent_count: number;
  };
  execution: {
    running: boolean;
    enabled?: boolean;
    mode?: string;
    portfolio_status?: 'not_configured' | 'ready' | 'stale' | 'error';
    total_value: number | null;
    pnl: number | null;
    pnl_pct: number | null;
  };
  risk: {
    portfolio_status?: 'not_configured' | 'ready' | 'stale' | 'error';
    net_exposure: number | null;
    estimated_leverage: number | null;
    alert_level: string;
    onchain_alert_count: number;
    critical_onchain_alerts: number;
    notes?: string[];
  };
}

export interface StrategyIntent {
  intent_id: string;
  strategy_id: string;
  created_at: string;
  rationale: string;
  expected_edge_bps: number;
  confidence: number;
  status: string;
  basket_id: string | null;
  error?: string | null;
  legs: Array<{
    leg_id: string;
    venue: string;
    symbol: string;
    side: string;
    quantity: number;
    limit_price: number | null;
    role: string;
  }>;
  metadata: Record<string, string>;
}

export interface OnchainSummary {
  watched_addresses: number;
  watched_tokens: number;
  alert_count: number;
  critical_alerts: number;
  recent_cex_flow_usd: number;
  pending_staging_wallets: number;
  pending_staging_value_usd: number;
  cluster_window_minutes: number;
  cex_labels: string[];
  timestamp?: string;
}

export interface OnchainWatchAddress {
  watch_id: string;
  chain: string;
  token_symbol: string;
  contract_address: string;
  address: string;
  label: string;
  entity_type: string;
  tags: string[];
  sell_threshold_usd: number;
  cex_transfer_threshold_usd: number;
  staging_transfer_threshold_usd: number;
}

export interface DistributionAlert {
  alert_id: string;
  watch_id: string;
  chain: string;
  token_symbol: string;
  contract_address: string;
  address: string;
  label: string;
  alert_type: string;
  severity: string;
  title: string;
  summary: string;
  usd_value: number;
  event_ids: string[];
  counterparty: string | null;
  created_at: string;
  metadata: Record<string, string>;
}

export interface OnchainTransferEvent {
  event_id: string;
  chain: string;
  tx_hash: string;
  block_time: string;
  token_symbol: string;
  contract_address: string;
  from_address: string;
  to_address: string;
  amount: number;
  usd_value: number;
  from_label?: string | null;
  to_label?: string | null;
  to_entity_type: string;
  action?: string | null;
  source: string;
}
