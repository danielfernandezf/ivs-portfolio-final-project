import { useState } from 'react'
import { InvestmentVerdict, FundamentalData, TechnicalData, QualityMetrics } from '../types/valuation'
import { LiveValuation } from '../utils/frontendDCF'
import { SensitivityOverrides } from '../types/valuation'
import TradeConfirmModal from './TradeConfirmModal'

interface Props {
  verdict: InvestmentVerdict
  liveValuation: LiveValuation
  f: FundamentalData
  overrides: SensitivityOverrides
  technical: TechnicalData | null
  quality: QualityMetrics | null
}

const VERDICT_CONFIG = {
  'STRONG BUY': {
    border: 'border-bloomberg-green',
    bg: 'bg-bloomberg-green',
    text: 'text-bloomberg-green',
    bgMuted: 'bg-green-950',
    dot: '●',
    label: 'STRONG BUY',
  },
  'HOLD/MONITOR': {
    border: 'border-bloomberg-amber',
    bg: 'bg-bloomberg-amber',
    text: 'text-bloomberg-amber',
    bgMuted: 'bg-amber-950',
    dot: '●',
    label: 'HOLD / MONITOR',
  },
  'SELL/AVOID': {
    border: 'border-bloomberg-red',
    bg: 'bg-bloomberg-red',
    text: 'text-bloomberg-red',
    bgMuted: 'bg-red-950',
    dot: '●',
    label: 'SELL / AVOID',
  },
} as const

export default function VerdictPanel({ verdict, liveValuation, f, overrides, technical, quality }: Props) {
  const [modalOpen, setModalOpen] = useState(false)

  // Re-derive live margin of safety from the frontend DCF (slider-responsive)
  const liveMoS = liveValuation.intrinsicPrice > 0
    ? ((liveValuation.intrinsicPrice - f.current_price) / liveValuation.intrinsicPrice) * 100
    : -100

  const liveExpectedReturn = f.current_price > 0
    ? (liveValuation.intrinsicPrice - f.current_price) / f.current_price
    : 0

  const liveClears = liveExpectedReturn > f.cost_of_equity

  // Live verdict (recalculated in browser — mirrors Python logic exactly)
  let liveVerdict: 'STRONG BUY' | 'HOLD/MONITOR' | 'SELL/AVOID'
  if (liveMoS > 20 && liveClears) {
    liveVerdict = 'STRONG BUY'
  } else if (liveMoS >= 0) {
    liveVerdict = 'HOLD/MONITOR'
  } else {
    liveVerdict = 'SELL/AVOID'
  }

  // Phase 5 quality override: force SELL/AVOID if Z-Score in distress or F-Score < 5
  const qualityOverrideActive = quality?.verdict_override === true
  if (qualityOverrideActive) {
    liveVerdict = 'SELL/AVOID'
  }

  const cfg = VERDICT_CONFIG[liveVerdict]
  const isOverridden = liveVerdict !== verdict.verdict

  // Cannot confirm if quality override is active, regardless of DCF verdict
  const canConfirm = !qualityOverrideActive && (liveVerdict === 'STRONG BUY' || liveVerdict === 'HOLD/MONITOR')

  return (
    <div className={`bb-panel border-l-2 ${cfg.border}`}>
      {/* Verdict Banner */}
      <div className={`px-4 py-3 ${cfg.bgMuted} border-b border-bloomberg-border`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className={`text-lg ${cfg.text} animate-pulse`}>{cfg.dot}</span>
            <div>
              <div className={`font-mono font-bold text-base tracking-widest ${cfg.text}`}>
                {cfg.label}
              </div>
              <div className="text-bloomberg-text-muted text-2xs">
                INVESTMENT COMMITTEE VERDICT
                {qualityOverrideActive && (
                  <span className="ml-2 text-bloomberg-red font-bold">[QUALITY OVERRIDE]</span>
                )}
                {!qualityOverrideActive && isOverridden && (
                  <span className="ml-2 text-bloomberg-amber">[LIVE — SLIDER ADJUSTED]</span>
                )}
              </div>
            </div>
          </div>

          {/* Margin of Safety badge */}
          <div className={`text-center border ${cfg.border} px-3 py-1`}>
            <div className="bb-label">MARGIN OF SAFETY</div>
            <div className={`font-mono font-bold text-lg ${cfg.text}`}>
              {liveMoS > 0 ? '+' : ''}{liveMoS.toFixed(1)}%
            </div>
          </div>
        </div>
      </div>

      {/* Metrics row */}
      <div className="px-4 py-3 grid grid-cols-3 gap-3 border-b border-bloomberg-border">
        <div>
          <div className="bb-label">EXPECTED RETURN</div>
          <div className={`font-mono font-bold text-sm ${liveExpectedReturn > 0 ? 'text-bloomberg-green' : 'text-bloomberg-red'}`}>
            {liveExpectedReturn > 0 ? '+' : ''}{(liveExpectedReturn * 100).toFixed(1)}%
          </div>
        </div>
        <div>
          <div className="bb-label">CAPM HURDLE</div>
          <div className="font-mono font-bold text-sm text-bloomberg-text-secondary">
            {(f.cost_of_equity * 100).toFixed(2)}%
          </div>
        </div>
        <div>
          <div className="bb-label">CLEARS HURDLE</div>
          <div className={`font-mono font-bold text-sm ${liveClears ? 'text-bloomberg-green' : 'text-bloomberg-red'}`}>
            {liveClears ? '✓ YES' : '✗ NO'}
          </div>
        </div>
      </div>

      {/* Decision criteria */}
      <div className="px-4 py-2 border-b border-bloomberg-border">
        <div className="bb-label mb-2">DECISION CRITERIA</div>
        <div className="space-y-1 text-2xs font-mono">
          <div className="flex items-center gap-2">
            <span className={liveMoS > 20 ? 'text-bloomberg-green' : 'text-bloomberg-red'}>
              {liveMoS > 20 ? '✓' : '✗'}
            </span>
            <span className="text-bloomberg-text-muted">Margin of Safety &gt; 20%</span>
            <span className={`ml-auto ${liveMoS > 20 ? 'text-bloomberg-green' : 'text-bloomberg-red'}`}>
              {liveMoS.toFixed(1)}%
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className={liveClears ? 'text-bloomberg-green' : 'text-bloomberg-red'}>
              {liveClears ? '✓' : '✗'}
            </span>
            <span className="text-bloomberg-text-muted">Expected return &gt; CAPM hurdle</span>
            <span className={`ml-auto ${liveClears ? 'text-bloomberg-green' : 'text-bloomberg-red'}`}>
              {(liveExpectedReturn * 100).toFixed(1)}% vs {(f.cost_of_equity * 100).toFixed(2)}%
            </span>
          </div>
        </div>
      </div>

      {/* Primary risk */}
      <div className="px-4 py-2 border-b border-bloomberg-border">
        <div className="bb-label mb-1">PRIMARY RISK</div>
        <p className="text-bloomberg-text-secondary text-2xs leading-relaxed">
          {verdict.key_risk}
        </p>
      </div>

      {/* Rationale */}
      <div className="px-4 py-2 border-b border-bloomberg-border">
        <div className="bb-label mb-1">IC RATIONALE</div>
        <p className="text-bloomberg-text-muted text-2xs leading-relaxed">
          {verdict.rationale}
        </p>
      </div>

      {/* Confirm section */}
      <div className="px-4 py-3">
        <button
          onClick={() => canConfirm && setModalOpen(true)}
          disabled={!canConfirm}
          className={`
            w-full py-3 font-mono font-bold text-sm tracking-widest
            border-2 transition-all duration-300
            ${canConfirm
              ? `${cfg.border} ${cfg.text} hover:bg-bloomberg-border cursor-pointer hover:shadow-[0_0_20px_rgba(0,204,68,0.2)]`
              : 'border-bloomberg-text-muted text-bloomberg-text-muted cursor-not-allowed opacity-40'}
          `}
        >
          {canConfirm
            ? '⬆ CONFIRMAR OPERACIÓN E INICIAR SEGUIMIENTO'
            : '✗ OPERACIÓN NO CONFIRMABLE — REVISAR PARÁMETROS'}
        </button>
        {!canConfirm && qualityOverrideActive && (
          <p className="text-bloomberg-red text-2xs mt-2 text-center">
            {quality?.override_reason}
          </p>
        )}
        {!canConfirm && !qualityOverrideActive && (
          <p className="text-bloomberg-text-muted text-2xs mt-2 text-center">
            La confirmación requiere Margen de Seguridad ≥ 0% y/o ajustar los parámetros de valoración.
          </p>
        )}
      </div>

      {/* Trade Confirmation Modal */}
      <TradeConfirmModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        f={f}
        liveValuation={liveValuation}
        overrides={overrides}
        technical={technical}
        quality={quality}
        liveVerdict={liveVerdict}
        liveMoS={liveMoS}
        liveExpectedReturn={liveExpectedReturn}
        liveClears={liveClears}
      />
    </div>
  )
}
