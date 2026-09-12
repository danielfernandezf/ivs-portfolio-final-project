import { useState, useEffect, useCallback } from 'react'
import { FundamentalData, TechnicalData, PositionSizingResult, CorrelationMatrix, QualityMetrics } from '../types/valuation'
import { LiveValuation } from '../utils/frontendDCF'
import { SensitivityOverrides } from '../types/valuation'

const MAX_WEIGHT_PCT = 10.0

interface Props {
  isOpen: boolean
  onClose: () => void
  f: FundamentalData
  liveValuation: LiveValuation
  overrides: SensitivityOverrides
  technical: TechnicalData | null
  quality: QualityMetrics | null
  liveVerdict: 'STRONG BUY' | 'HOLD/MONITOR' | 'SELL/AVOID'
  liveMoS: number
  liveExpectedReturn: number
  liveClears: boolean
}

interface CorrWarning {
  existingTicker: string
  correlation: number
}

type ModalState =
  | { step: 'loading' }
  | { step: 'sizing'; sizing: PositionSizingResult; corrWarnings: CorrWarning[] }
  | { step: 'executing' }
  | { step: 'done'; message: string; files?: { factsheet: string; thesis: string } }
  | { step: 'error'; message: string }

function fmt2(n: number) { return n.toFixed(2) }
function fmtLarge(n: number) {
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(2)
}

export default function TradeConfirmModal({
  isOpen, onClose, f, liveValuation, overrides, technical, quality,
  liveVerdict, liveMoS, liveExpectedReturn, liveClears,
}: Props) {
  const [state, setState] = useState<ModalState>({ step: 'loading' })
  const [manualShares, setManualShares] = useState<number>(0)
  const [isManualOverride, setIsManualOverride] = useState(false)

  // ALL hooks MUST be above the early return ──────────────────────────────────

  useEffect(() => {
    if (!isOpen) return
    setState({ step: 'loading' })

    const sizingParams = new URLSearchParams({
      mos_pct: String(liveMoS),
      beta: String(f.beta),
      current_price: String(f.current_price),
    })

    const sizingFetch = fetch(`/api/portfolio/sizing/${f.ticker}?${sizingParams}`).then(r => r.json())
    const corrFetch = fetch(`/api/portfolio/correlation?include=${f.ticker}`)
      .then(r => r.ok ? r.json() : { tickers: [], matrix: {}, warnings: [] })
      .catch(() => ({ tickers: [], matrix: {}, warnings: [] }))

    Promise.all([sizingFetch, corrFetch])
      .then(([sizing, corrData]: [PositionSizingResult, CorrelationMatrix]) => {
        const warnings: CorrWarning[] = []
        const existingTickers = (corrData.tickers ?? []).filter(t => t !== f.ticker)
        for (const existing of existingTickers) {
          const corr = corrData.matrix?.[f.ticker]?.[existing] ?? 0
          if (corr > 0.75) {
            warnings.push({ existingTicker: existing, correlation: corr })
          }
        }
        setManualShares(sizing.shares_to_buy ?? 0)
        setIsManualOverride(false)
        setState({ step: 'sizing', sizing, corrWarnings: warnings })
      })
      .catch(e => setState({ step: 'error', message: String(e) }))
  }, [isOpen, f.ticker, liveMoS, f.beta, f.current_price])

  const handleSharesChange = useCallback((raw: string) => {
    const parsed = parseInt(raw, 10)
    const val = isNaN(parsed) || parsed < 0 ? 0 : parsed
    setManualShares(val)
  }, [])

  // ── Early return AFTER all hooks ───────────────────────────────────────────
  if (!isOpen) return null

  // ── Derived values (safe — only used in render below) ──────────────────────
  const sizingData = state.step === 'sizing' ? state.sizing : null
  const portfolioTotal = sizingData?.portfolio_total ?? 1
  const manualCost = manualShares * f.current_price
  const manualWeightPct = sizingData ? (manualCost / portfolioTotal) * 100 : 0
  const exceedsWeightCap = manualWeightPct > MAX_WEIGHT_PCT
  const exceedsCash = sizingData ? manualCost > (sizingData.cash_available ?? 0) + 0.01 : false
  const isOverride = sizingData ? manualShares !== sizingData.shares_to_buy : false

  const buildSnapshot = (weightPct: number) => ({
    fundamental: {
      ...f,
      intrinsic_price_per_share: liveValuation.intrinsicPrice,
      enterprise_value: liveValuation.enterpriseValue,
      equity_value: liveValuation.equityValue,
      projected_fcfs: liveValuation.projectedFcfs,
      pv_fcfs: liveValuation.pvFcfs,
      terminal_value: liveValuation.terminalValue,
      pv_terminal_value: liveValuation.pvTerminalValue,
      upside_downside_pct: liveExpectedReturn,
      assumptions: {
        ...f.assumptions,
        wacc_override: overrides.wacc / 100,
        revenue_growth_rate: overrides.growthRate / 100,
        terminal_growth_rate: overrides.terminalGrowth / 100,
        fcf_margin: overrides.fcfMargin / 100,
      },
      verdict: {
        verdict: liveVerdict,
        margin_of_safety: liveMoS,
        expected_return: liveExpectedReturn,
        hurdle_rate: f.cost_of_equity,
        clears_hurdle: liveClears,
        key_risk: f.verdict.key_risk,
        rationale: f.verdict.rationale,
      },
    },
    technical,
    quality,
  })

  const executeBuy = async (sizing: PositionSizingResult) => {
    const sharesToUse = manualShares > 0 ? manualShares : sizing.shares_to_buy
    const actualWeightPct = (sharesToUse * f.current_price / sizing.portfolio_total) * 100
    const manual = sharesToUse !== sizing.shares_to_buy
    setState({ step: 'executing' })
    try {
      const buyRes = await fetch('/api/portfolio/buy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker: f.ticker,
          company_name: f.company_name,
          shares: sharesToUse,
          price_per_share: f.current_price,
          sector: f.sector,
          currency: f.currency,
          intrinsic_price: liveValuation.intrinsicPrice,
          mos_pct: liveMoS,
          allocated_weight_pct: actualWeightPct,
          is_manual_override: manual,
        }),
      })
      if (!buyRes.ok) {
        const err = await buyRes.json()
        throw new Error(err.detail || `Buy failed: HTTP ${buyRes.status}`)
      }

      const expRes = await fetch('/api/export-thesis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker: f.ticker,
          snapshot: buildSnapshot(actualWeightPct),
          allocated_weight_pct: actualWeightPct,
          is_manual_override: manual,
        }),
      })
      const expData = expRes.ok ? await expRes.json() : null

      setState({
        step: 'done',
        message: `${sharesToUse} acciones de ${f.ticker} añadidas. Peso: ${actualWeightPct.toFixed(2)}%${manual ? ' (ajuste manual)' : ''}`,
        files: expData?.files,
      })
    } catch (e) {
      setState({ step: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }

  const executeSellAndBuy = async (sizing: PositionSizingResult) => {
    if (!sizing.sell_candidate_ticker) return
    setState({ step: 'executing' })
    try {
      const sellRes = await fetch(
        `/api/portfolio/sell/${sizing.sell_candidate_ticker}?at_live_price=true`,
        { method: 'POST' }
      )
      if (!sellRes.ok) {
        const err = await sellRes.json()
        throw new Error(err.detail || `Sell failed: HTTP ${sellRes.status}`)
      }
      const sizingParams = new URLSearchParams({
        mos_pct: String(liveMoS),
        beta: String(f.beta),
        current_price: String(f.current_price),
      })
      const newSizingRes = await fetch(`/api/portfolio/sizing/${f.ticker}?${sizingParams}`)
      const newSizing: PositionSizingResult = await newSizingRes.json()
      await executeBuy(newSizing)
    } catch (e) {
      setState({ step: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center animate-fadeIn">
      <div className="absolute inset-0 bg-black bg-opacity-80 backdrop-blur-sm" onClick={onClose} />

      <div className="relative z-10 w-full max-w-lg mx-4 bb-panel border border-bloomberg-amber shadow-2xl shadow-bloomberg-amber/10 max-h-[90vh] overflow-y-auto animate-scaleIn">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-bloomberg-border bg-bloomberg-panel sticky top-0 z-10">
          <div>
            <span className="text-bloomberg-amber font-mono font-bold tracking-widest">
              TRADE CONFIRMATION
            </span>
            <span className="text-bloomberg-text-muted text-2xs ml-3">
              {f.ticker} — {f.company_name}
            </span>
          </div>
          <button onClick={onClose} className="text-bloomberg-text-muted hover:text-bloomberg-red text-lg font-mono">
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">

          {state.step === 'loading' && (
            <div className="flex items-center justify-center py-8 gap-3">
              <div className="text-bloomberg-amber font-mono text-xs animate-pulse">
                ANALIZANDO CARTERA Y CORRELACIONES...
              </div>
              <div className="flex gap-1">
                {[0, 1, 2].map(i => (
                  <div key={i} className="w-1 h-3 bg-bloomberg-amber animate-bounce"
                    style={{ animationDelay: `${i * 0.15}s` }} />
                ))}
              </div>
            </div>
          )}

          {state.step === 'executing' && (
            <div className="flex items-center justify-center py-8 gap-3">
              <div className="text-bloomberg-electric font-mono text-xs animate-pulse">
                EJECUTANDO OPERACIÓN...
              </div>
            </div>
          )}

          {state.step === 'sizing' && (() => {
            const { sizing, corrWarnings } = state
            return (
              <>
                {/* Correlation warnings */}
                {corrWarnings.length > 0 && (
                  <div className="bg-orange-950 border border-orange-500 border-opacity-60 p-3 space-y-2">
                    <div className="text-orange-400 text-2xs tracking-widest font-bold flex items-center gap-2">
                      <span>⚠</span>
                      <span>ADVERTENCIA — CORRELACIÓN ALTA</span>
                    </div>
                    {corrWarnings.map(w => (
                      <div key={w.existingTicker} className="text-orange-300 text-2xs font-mono leading-relaxed">
                        <span className="font-bold text-orange-400">{f.ticker}</span>
                        {' '}correlación alta con{' '}
                        <span className="font-bold text-orange-400">{w.existingTicker}</span>
                        {' '}({(w.correlation * 100).toFixed(1)}%). No añade diversificación real.
                      </div>
                    ))}
                  </div>
                )}

                {/* Capital usage bar */}
                <div className="bg-black border border-bloomberg-border p-3">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-bloomberg-text-muted text-2xs font-mono">USO DE CAPITAL</span>
                    <span className={`font-mono font-bold text-xs ${(sizing.portfolio_used_pct ?? 0) >= 90 ? 'text-bloomberg-red' : (sizing.portfolio_used_pct ?? 0) >= 70 ? 'text-bloomberg-amber' : 'text-bloomberg-green'}`}>
                      {(sizing.portfolio_used_pct ?? 0).toFixed(1)}% invertido
                    </span>
                  </div>
                  <div className="w-full h-2 bg-bloomberg-border overflow-hidden">
                    <div
                      className={`h-full transition-all ${(sizing.portfolio_used_pct ?? 0) >= 90 ? 'bg-bloomberg-red' : (sizing.portfolio_used_pct ?? 0) >= 70 ? 'bg-bloomberg-amber' : 'bg-bloomberg-green'}`}
                      style={{ width: `${Math.min(sizing.portfolio_used_pct ?? 0, 100)}%` }}
                    />
                  </div>
                  <div className="flex justify-between mt-1 text-2xs font-mono text-bloomberg-text-muted">
                    <span>Efectivo: {fmtLarge(sizing.cash_available)}€</span>
                    <span>Disponible: {(sizing.capacity_remaining_pct ?? 100).toFixed(1)}%</span>
                  </div>
                </div>

                {/* Summary cards */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-black border border-bloomberg-border p-3">
                    <div className="bb-label mb-1">EFECTIVO DISPONIBLE</div>
                    <div className="text-bloomberg-electric font-mono font-bold text-base">
                      {fmtLarge(sizing.cash_available)}€
                    </div>
                  </div>
                  <div className="bg-black border border-bloomberg-border p-3">
                    <div className="bb-label mb-1">CARTERA TOTAL</div>
                    <div className="font-mono font-bold text-base text-bloomberg-text-primary">
                      {fmtLarge(sizing.portfolio_total)}€
                    </div>
                  </div>
                </div>

                {/* Editable sizing */}
                <div className="bg-black border border-bloomberg-amber border-opacity-40 p-3">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-bloomberg-amber text-2xs tracking-widest">POSITION SIZING</span>
                    {isOverride ? (
                      <span className="text-bloomberg-amber text-2xs font-mono border border-bloomberg-amber border-opacity-50 px-2 py-0.5">
                        AJUSTE MANUAL
                      </span>
                    ) : (
                      <span className="text-bloomberg-text-muted text-2xs font-mono">RECOMENDACIÓN SISTEMA</span>
                    )}
                  </div>

                  <div className="space-y-2 text-2xs font-mono">
                    <div className="flex justify-between items-center">
                      <span className="text-bloomberg-text-muted">Acciones</span>
                      <div className="flex items-center gap-2">
                        <input
                          type="number"
                          min={0}
                          value={manualShares}
                          onChange={e => handleSharesChange(e.target.value)}
                          className="w-20 bg-bloomberg-border text-bloomberg-green font-mono font-bold text-right px-2 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-bloomberg-amber border border-transparent"
                        />
                        <span className="text-bloomberg-text-muted">acc.</span>
                      </div>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-bloomberg-text-muted">Peso resultante</span>
                      <span className={`font-bold ${exceedsWeightCap ? 'text-bloomberg-red' : 'text-bloomberg-amber'}`}>
                        {manualWeightPct.toFixed(2)}%{exceedsWeightCap && ' ✗ MAX 10%'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-bloomberg-text-muted">Coste estimado</span>
                      <span className={`font-bold ${exceedsCash ? 'text-bloomberg-red' : 'text-bloomberg-text-primary'}`}>
                        {fmtLarge(manualCost)}€
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-bloomberg-text-muted">Precio</span>
                      <span className="text-bloomberg-text-secondary">${fmt2(f.current_price)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-bloomberg-text-muted">MoS</span>
                      <span className={liveMoS > 20 ? 'text-bloomberg-green' : 'text-bloomberg-amber'}>
                        {liveMoS.toFixed(1)}%
                      </span>
                    </div>
                  </div>

                  {sizing.capped_at_limit && !isOverride && (
                    <div className="mt-3 pt-2 border-t border-bloomberg-border text-bloomberg-amber text-2xs flex items-center gap-2">
                      <span>⚠</span>
                      <span>Reducido de {sizing.raw_weight_pct.toFixed(2)}% a 10.00% (límite institucional).</span>
                    </div>
                  )}

                  {isOverride && (
                    <button
                      onClick={() => { setManualShares(sizing.shares_to_buy); setIsManualOverride(false) }}
                      className="mt-2 text-bloomberg-text-muted text-2xs hover:text-bloomberg-amber font-mono"
                    >
                      ↺ Restaurar recomendación ({sizing.shares_to_buy} acc.)
                    </button>
                  )}
                </div>

                {/* Capacity / cash errors */}
                {exceedsCash && (
                  <div className="bg-red-950 border border-bloomberg-red border-opacity-60 p-3 space-y-2">
                    <div className="text-bloomberg-red text-2xs tracking-widest font-bold">
                      ✗ CAPITAL INSUFICIENTE
                    </div>
                    <p className="text-bloomberg-text-secondary text-2xs">
                      Se requieren {fmtLarge(manualCost)}€ pero solo hay {fmtLarge(sizing.cash_available)}€.
                    </p>
                    <button
                      onClick={() => { setManualShares(sizing.max_affordable_shares ?? Math.floor(sizing.cash_available / f.current_price)); setIsManualOverride(true) }}
                      className="w-full py-1.5 border border-bloomberg-amber text-bloomberg-amber font-mono text-2xs tracking-widest hover:bg-bloomberg-amber hover:text-black transition-colors"
                    >
                      A — AJUSTAR AL MÁXIMO ({sizing.max_affordable_shares ?? Math.floor(sizing.cash_available / f.current_price)} acc.)
                    </button>
                    {sizing.sell_candidate_ticker && (
                      <button
                        onClick={() => executeSellAndBuy(sizing)}
                        className="w-full py-1.5 border border-bloomberg-red text-bloomberg-red font-mono text-2xs tracking-widest hover:bg-bloomberg-red hover:text-black transition-colors"
                      >
                        B — VENDER {sizing.sell_candidate_ticker} + COMPRAR {f.ticker}
                      </button>
                    )}
                  </div>
                )}

                {exceedsWeightCap && (
                  <div className="bg-red-950 border border-bloomberg-red border-opacity-40 px-3 py-2 text-bloomberg-red text-2xs font-mono animate-fadeIn">
                    ✗ Peso {manualWeightPct.toFixed(2)}% supera el limite institucional del 10%. Reduce acciones.
                  </div>
                )}

                {/* Confirm */}
                {!exceedsCash && !exceedsWeightCap && (
                  <button
                    onClick={() => executeBuy(sizing)}
                    disabled={manualShares === 0}
                    className="w-full py-3 border-2 border-bloomberg-green text-bloomberg-green font-mono font-bold text-sm tracking-widest hover:bg-bloomberg-green hover:text-black transition-colors disabled:opacity-40"
                  >
                    CONFIRMAR COMPRA — {manualShares} × {f.ticker} @ ${fmt2(f.current_price)}
                  </button>
                )}
              </>
            )
          })()}

          {state.step === 'done' && (
            <div className="space-y-3">
              <div className="text-bloomberg-green font-mono font-bold text-sm flex items-center gap-2">
                <span>✓</span><span>OPERACIÓN COMPLETADA</span>
              </div>
              <p className="text-bloomberg-text-secondary text-xs">{state.message}</p>
              {state.files && (
                <div className="bg-black border border-bloomberg-green border-opacity-30 p-3 space-y-1 text-2xs font-mono">
                  <div className="text-bloomberg-text-muted">Tesis guardada:</div>
                  <div className="text-bloomberg-electric">├── {state.files.factsheet.split(/[\\/]/).slice(-1)[0]}</div>
                  <div className="text-bloomberg-electric">└── {state.files.thesis.split(/[\\/]/).slice(-1)[0]}</div>
                </div>
              )}
              <button
                onClick={onClose}
                className="w-full py-2 border border-bloomberg-border text-bloomberg-text-muted font-mono text-xs hover:border-bloomberg-amber hover:text-bloomberg-amber transition-colors"
              >
                CERRAR
              </button>
            </div>
          )}

          {state.step === 'error' && (
            <div className="space-y-3">
              <div className="text-bloomberg-red font-mono text-sm">⚠ ERROR</div>
              <p className="text-bloomberg-text-secondary text-xs break-all">{state.message}</p>
              <button
                onClick={() => setState({ step: 'loading' })}
                className="text-bloomberg-text-muted text-2xs hover:text-bloomberg-amber font-mono"
              >
                ↺ reintentar
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
