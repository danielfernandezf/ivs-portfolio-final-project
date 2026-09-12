export interface InvestmentVerdict {
  verdict: 'STRONG BUY' | 'HOLD/MONITOR' | 'SELL/AVOID'
  margin_of_safety: number    // percentage, e.g. 25.3
  expected_return: number     // decimal, e.g. 0.31
  hurdle_rate: number         // CAPM cost of equity — decimal
  clears_hurdle: boolean
  key_risk: string
  rationale: string
}

export interface DCFAssumptions {
  revenue_growth_rate: number
  fcf_margin: number
  terminal_growth_rate: number
  wacc_override: number | null
  projection_years: number
}

export interface FundamentalData {
  ticker: string
  company_name: string
  sector: string
  currency: string
  current_price: number

  // WACC decomposition
  wacc: number
  cost_of_equity: number
  cost_of_debt_aftertax: number
  equity_weight: number
  debt_weight: number

  // Inputs
  beta: number
  risk_free_rate: number
  market_risk_premium: number
  effective_tax_rate: number

  // Balance sheet
  market_cap: number
  total_debt: number
  cash: number
  net_debt: number
  shares_outstanding: number

  // FCF
  fcf_history: number[]
  base_fcf: number
  projected_fcfs: number[]
  pv_fcfs: number[]
  terminal_value: number
  pv_terminal_value: number

  // Valuation
  enterprise_value: number
  equity_value: number
  intrinsic_price_per_share: number
  upside_downside_pct: number

  assumptions: DCFAssumptions
  verdict: InvestmentVerdict
}

export interface TechnicalData {
  ticker: string
  trend_direction: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
  trend_strength: 'STRONG' | 'MODERATE' | 'WEAK'
  price_vs_ma50: number
  price_vs_ma200: number
  macd_signal: 'BUY' | 'SELL' | 'NEUTRAL'
  macd_value: number
  macd_signal_line: number
  annualised_volatility: number
  volatility_regime: 'LOW' | 'NORMAL' | 'HIGH' | 'EXTREME'
  fib_236: number
  fib_382: number
  fib_500: number
  fib_618: number
  fib_786: number
  bull_price_target: number
  base_price_target: number
  bear_price_target: number
  bull_probability: number
  base_probability: number
  bear_probability: number
  probability_weighted_price: number
  rsi_14: number
  rsi_signal: 'OVERBOUGHT' | 'OVERSOLD' | 'NEUTRAL'
  risk_score: number
  risk_label: 'LOW' | 'MODERATE' | 'HIGH' | 'VERY HIGH'
}

export interface ValuationResponse {
  fundamental: FundamentalData
  technical: TechnicalData | null
  quality: QualityMetrics | null   // Phase 5
}

// ── Phase 5 — Quality & Survival types ───────────────────────────────────────

export interface AltmanZScore {
  z_score: number
  zone: 'SAFE' | 'GREY' | 'DISTRESS' | 'N/A'
  x1_wc_to_assets: number
  x2_re_to_assets: number
  x3_ebit_to_assets: number
  x4_mktcap_to_liab: number
  x5_rev_to_assets: number
  triggers_override: boolean
  note: string
}

export interface PiotroskiScore {
  score: number             // 0–9
  f1_roa_positive: boolean
  f2_ocf_positive: boolean
  f3_roa_improving: boolean
  f4_accruals_quality: boolean
  f5_leverage_improving: boolean
  f6_liquidity_improving: boolean
  f7_no_dilution: boolean
  f8_gross_margin_improving: boolean
  f9_asset_turnover_improving: boolean
  triggers_override: boolean
  signals_computed: number
}

export interface SectorBenchmark {
  pe_ratio: number | null
  ev_ebitda: number | null
  sector_pe: number
  sector_ev_ebitda: number
  pe_vs_sector_pct: number | null
  ev_ebitda_vs_sector_pct: number | null
}

export interface LiquidityMetrics {
  avg_volume_10d: number
  max_shares_in_position: number
  volume_impact_pct: number
  alert: string | null
}

export interface QualityMetrics {
  ticker: string
  altman: AltmanZScore
  piotroski: PiotroskiScore
  benchmark: SectorBenchmark
  liquidity: LiquidityMetrics
  verdict_override: boolean
  override_reason: string | null
}

export interface SensitivityOverrides {
  wacc: number
  growthRate: number
  terminalGrowth: number
  fcfMargin: number
}

export interface ExportThesisPayload {
  ticker: string
  snapshot: {
    fundamental: FundamentalData & { verdict: InvestmentVerdict }
    technical: TechnicalData | null
  }
  allocated_weight_pct?: number
}

// ── Portfolio types ──────────────────────────────────────────────────────────

export interface PortfolioPosition {
  id: number
  ticker: string
  company_name: string
  shares: number
  purchase_price: number
  purchase_date: string
  sector: string
  currency: string
  intrinsic_price_at_purchase: number
  mos_at_purchase: number
  allocated_weight_pct: number
  cost_basis_total: number
  is_manual_override: boolean
}

export interface LivePortfolioPosition extends PortfolioPosition {
  live_price: number
  price_is_live?: boolean
  current_market_value: number
  return_pct: number
  live_mos: number
}

export interface PortfolioSummary {
  positions: PortfolioPosition[]
  cash_balance: number
  initial_capital: number
  invested_capital: number
  total_portfolio_value: number
  n_positions: number
}

export interface LivePortfolioResponse {
  live_positions: LivePortfolioPosition[]
  cash_balance: number
  total_live_value: number
  portfolio_return_pct: number
  stale_prices?: number
}

// ── Phase 4 — Quant Engine types ─────────────────────────────────────────────

export interface MonteCarloHistBin {
  price_mid: number
  count: number
  density: number
  normal_density: number
}

export interface MonteCarloResult {
  ticker: string
  current_price: number
  iterations: number
  p10: number
  p25: number
  p50: number
  p75: number
  p90: number
  mean: number
  std: number
  probability_above_market: number   // 0–1 fraction
  histogram: MonteCarloHistBin[]
  growth_mean_pct: number
  growth_std_pct: number
  wacc_mean_pct: number
  wacc_std_pct: number
  ks_statistic: number
  ks_pvalue: number
}

export interface CorrelationWarning {
  ticker1: string
  ticker2: string
  correlation: number
}

export interface CorrelationMatrix {
  tickers: string[]
  matrix: Record<string, Record<string, number>>
  warnings: CorrelationWarning[]
  /** Posiciones excluidas por falta de histórico — la matriz no las cubre. */
  missing_tickers?: string[]
  data_period: string
  n_observations: number
  message?: string
}

// ── Phase 7 — Portfolio Risk Analytics ──────────────────────────────────────

export interface PortfolioAlert {
  ticker: string
  type: 'Z_SCORE_DISTRESS' | 'Z_SCORE_GREY' | 'F_SCORE_WEAK'
  severity: 'critical' | 'warning'
  title: string
  detail: string
  z_score?: number
  f_score?: number
}

export interface PortfolioRiskMetrics {
  sharpe_ratio: number | null
  annualised_return_pct: number
  annualised_volatility_pct: number
  portfolio_beta: number
  alerts: PortfolioAlert[]
  n_positions: number
}

// ── Phase 8 — Performance & Benchmarking ─────────────────────────────────────

export interface HistoryPoint {
  date: string
  total_value: number
  cash: number
  invested: number
  contribution: number
  event: string
}

export interface PerformanceResponse {
  history: HistoryPoint[]
  twr_pct: number
  total_contributions: number
  initial_capital: number
}

export interface BenchmarkResponse {
  dates: string[]
  portfolio_indexed: number[]
  spy_indexed: number[]
  portfolio_return_pct: number
  spy_return_pct: number
  alpha_pct: number
}

// ── Rendimientos diarios por posición (heatmap junto a la correlación) ───────

export interface DailyReturnStats {
  mean: number
  best: number
  worst: number
  win_rate: number
  cumulative: number
}

export interface DailyReturnsResponse {
  tickers: string[]
  dates: string[]
  /** returns[ticker][fecha] = variación % de esa sesión */
  returns: Record<string, Record<string, number>>
  stats: Record<string, DailyReturnStats>
  n_days: number
  period_days?: number
}

// ── Time machine — la cartera en una fecha pasada ────────────────────────────

export interface AsOfPosition {
  ticker: string
  company_name: string
  sector: string
  shares: number
  purchase_price: number
  purchase_date: string
  price_at_date: number
  market_value: number
  cost_basis: number
  return_pct: number
  /** Variación en la ventana de comparación; null si no hay histórico bastante */
  period_pct: number | null
  weight_pct: number
  stale_price: boolean
}

export interface AsOfResponse {
  /** Sesión efectivamente usada (puede diferir de la pedida: findes/festivos) */
  date: string
  requested_date: string
  is_trading_day?: boolean
  positions: AsOfPosition[]
  cash: number
  invested: number
  total_value: number
  capital_at_date: number
  return_pct: number
  period_change_pct: number | null
  comparison_date: string | null
  compare_sessions?: number
  n_positions?: number
  available_from: string | null
  available_to: string | null
  trading_days?: string[]
  message?: string
}

// ── Movers — top performers del universo rastreado ──────────────────────────

export interface MoverRow {
  ticker: string
  company_name: string
  sector: string
  /** Margin of safety de la última valoración del screener; null si no valorada */
  mos_pct: number | null
  verdict: string | null
  last_close: number
  last_date: string
  day_pct: number | null
  week_pct: number
  month_pct: number | null
}

export interface MoversStatus {
  running: boolean
  done: number
  total: number
  started_at: string | null
  error: string | null
  progress_pct: number
}

export interface MoversResponse {
  gainers: MoverRow[]
  losers: MoverRow[]
  n_tickers: number
  n_universe: number
  as_of: string | null
  last_run: string | null
  status: MoversStatus
}

export interface PositionSizingResult {
  ticker: string
  margin_of_safety: number
  beta: number
  raw_weight_pct: number
  recommended_weight_pct: number
  capped_at_limit: boolean
  capital_to_deploy: number
  shares_to_buy: number
  estimated_cost: number
  cash_available: number
  cash_sufficient: boolean
  shortfall: number
  // Phase 6 — portfolio capacity
  portfolio_used_pct: number
  capacity_remaining_pct: number
  max_affordable_shares: number
  initial_capital: number
  sell_candidate_ticker: string | null
  sell_candidate_mos: number | null
  sell_candidate_proceeds: number | null
  liquidity_alert: string | null
  portfolio_total: number
}
