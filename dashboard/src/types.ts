/* ── API Response Types ─────────────────────────────────── */

export interface StreamStatus {
  stream_name: string
  strategy: string | null
  mode: string
  running: boolean
  pair: string
  equity: number | null
  balance: number | null
  peak_equity: number | null
  drawdown_pct: number | null
  circuit_breaker_active: boolean
  open_positions: number
  last_signal_check: string | null
  uptime_seconds: number
  started_at: string | null
  cycle_count: number
  last_cycle_at: string | null
  last_signal_time: string | null
  last_order_time: string | null
}

export interface StatusResponse {
  streams: Record<string, StreamStatus>
}

export interface Position {
  instrument: string
  direction: string
  units: number
  avg_price: number
  stop_loss: number | null
  take_profit: number | null
  open_time: string | null
  unrealized_pnl: number | null
}

export interface PositionsResponse {
  positions: Position[]
}

export interface PendingSignal {
  pair: string
  direction: string
  zone_price: number | null
  reason: string
  status: string
}

export interface PendingResponse {
  signal: PendingSignal | null
}

export interface ClosedTrade {
  pair: string
  direction: string
  units: number | null
  entry_price: number | null
  exit_price: number | null
  stop_loss: number | null
  take_profit: number | null
  pnl: number | null
  close_reason: string | null
  opened_at: string | null
  closed_at: string | null
}

export interface ClosedResponse {
  trades: ClosedTrade[]
  total_pnl: number
}

export interface SignalEntry {
  evaluated_at: string
  pair: string
  direction: string
  status: string
  reason: string
}

export interface SignalHistoryResponse {
  signals: SignalEntry[]
}

export interface ZoneInfo {
  price: number
  touches: number
}

export interface InsightZones {
  total: number
  support: ZoneInfo[]
  resistance: ZoneInfo[]
}

export interface NearestZone {
  price: number
  type: string
  distance_pips: number
}

export interface LatestH4 {
  open: number
  high: number
  low: number
  close: number
  buy_rejection_wick: boolean
  sell_rejection_wick: boolean
  zones_touched: number
}

export interface TrendInfo {
  direction: string
  slope: number
  ema_fast: number
  ema_slow: number
}

export interface InsightSignal {
  direction: string
  entry: number
  entry_price: number
  sl: number
  tp: number
  reason: string
}

export interface StreamInsight {
  strategy: string
  pair: string
  checks: Record<string, boolean>
  zones?: InsightZones
  nearest_zone?: NearestZone
  latest_h4?: LatestH4
  current_price?: number
  atr?: number
  trend?: TrendInfo
  signal?: InsightSignal
  result?: string
  // Scalp-specific
  multi_tf_trends?: Record<string, { direction: string }>
  latest_candle?: { open: number; high: number; low: number; close: number }
  spread_pips?: number
  max_spread_pips?: number
  ema9?: number
  price_vs_ema?: number
  sl?: number
  tp?: number
  rr_ratio?: number
  // ForgeAgent RL filter
  rl_mode?: 'disabled' | 'shadow' | 'active'
  rl_filter?: 'approved' | 'vetoed' | null
  rl_confidence?: number
  rl_assessed_at?: string
}

export interface RLDecision {
  timestamp: string
  instrument: string
  direction: string
  entry_price: number
  action: 'TAKE' | 'VETO'
  confidence: number
  mode: 'shadow' | 'active'
}

export interface InsightResponse {
  insights: Record<string, StreamInsight>
  rl_decisions?: RLDecision[]
}

export interface AccountData {
  equity: number | null
  balance: number | null
  unrealized_pnl: number | null
  open_position_count: number | null
  drawdown_pct: number | null
}

export interface AccountResponse {
  account: AccountData
}

export interface SettingsData {
  max_drawdown_pct: number
  max_concurrent_positions: number
  poll_interval_seconds: number
  leverage: number
}

export interface StreamSettingsEntry {
  name: string
  instrument: string
  strategy: string
  risk_per_trade_pct: number
  rr_ratio: number | null
  session_start_utc: number
  session_end_utc: number
}

export interface StreamSettingsResponse {
  streams: StreamSettingsEntry[]
}

export interface FailureCluster {
  pattern: string
  count: number
  losing_trades: number
  impact: number
  suggestion: string
}

export interface FailureAnalysis {
  total_trades: number
  winning_trades: number
  losing_trades: number
  exit_reasons: Record<string, number>
  worst_hours: { hour: number; losses: number; total: number; loss_rate: number }[]
  volatility_regime: Record<string, { count: number; avg_r: number }>
  trend_alignment: Record<string, { count: number; avg_r: number }>
  hold_duration: Record<string, { count: number; avg_r: number }>
  direction_analysis: Record<string, { count: number; avg_r: number }>
  high_spread_trades: { count: number; avg_r: number; threshold: number }
  failure_clusters: FailureCluster[]
}

export interface NudgeInfo {
  iteration: number
  param: string
  direction: number
  old_value: number
  new_value: number
  reason: string
  reverted: boolean
}

export interface TrainingEntry {
  timestamp: string
  label: string
  model_path: string
  instrument: string
  parameters: number
  training_timesteps: number | null
  eval_episodes: number
  iteration?: number
  nudge?: NudgeInfo | null
  metrics: {
    win_rate: number
    take_rate: number
    profit_factor: number
    max_drawdown: number
    avg_r_multiple: number
    sharpe_ratio: number
    mean_episode_reward: number
    total_trades_taken: number
    total_signals_seen: number
  }
  failures?: FailureAnalysis
}

export interface TrainingHistoryResponse {
  entries: TrainingEntry[]
}

export interface IterateStatus {
  iteration: number
  phase: string   // idle | training | evaluating | nudging | sleeping | converged
  detail: string
  best_avg_r: number
  best_iteration: number
  last_nudge: NudgeInfo | null
  updated_at: string
}

export interface IterateState {
  iteration: number
  best_avg_r: number | null
  best_iteration: number
  nudge_history: NudgeInfo[]
  env_config: Record<string, number | string>
  reward_config: Record<string, number | string>
}

export interface IterateStatusResponse {
  status: IterateStatus | Record<string, never>
  state: IterateState
}
