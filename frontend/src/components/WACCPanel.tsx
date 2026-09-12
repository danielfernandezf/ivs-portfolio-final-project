import { FundamentalData, SensitivityOverrides } from '../types/valuation'

interface Props {
  f: FundamentalData
  overrides: SensitivityOverrides
  liveWacc: number
}

function pct(n: number) { return `${(n * 100).toFixed(2)}%` }
function fmt2(n: number) { return n.toFixed(4) }

export default function WACCPanel({ f, liveWacc }: Props) {
  const isOverridden = Math.abs(liveWacc - f.wacc) > 0.0001

  return (
    <div className="bb-panel p-3">
      <div className="text-bloomberg-amber text-2xs tracking-widest mb-3">
        WACC DECOMPOSITION — CAPM
      </div>

      {/* CAPM formula display */}
      <div className="bg-black border border-bloomberg-border p-2 mb-3 text-2xs font-mono text-bloomberg-text-muted">
        <div className="text-bloomberg-electric mb-1">CAPM (Eq. 12.15)</div>
        <div>r_e = r_f + β × (r_m − r_f)</div>
        <div className="mt-1 text-bloomberg-text-secondary">
          = {pct(f.risk_free_rate)} + {fmt2(f.beta)} × {pct(f.market_risk_premium)}
        </div>
        <div className="text-bloomberg-amber">
          = {pct(f.cost_of_equity)}
        </div>
      </div>

      {/* Components */}
      <div className="space-y-2">
        {[
          { label: 'Risk-Free Rate (r_f)', value: pct(f.risk_free_rate), color: 'text-bloomberg-electric', note: '^TNX 10Y' },
          { label: 'Beta (β)', value: fmt2(f.beta), color: 'text-bloomberg-amber', note: 'vs S&P500' },
          { label: 'Equity Risk Premium', value: pct(f.market_risk_premium), color: 'text-bloomberg-text-primary', note: 'Hist. avg' },
          { label: 'Cost of Equity (r_e)', value: pct(f.cost_of_equity), color: 'text-bloomberg-amber font-bold', note: 'CAPM' },
          { label: 'Cost of Debt (after-tax)', value: pct(f.cost_of_debt_aftertax), color: 'text-bloomberg-text-primary', note: `Tax: ${(f.effective_tax_rate * 100).toFixed(0)}%` },
          { label: 'Equity Weight (E/V)', value: `${(f.equity_weight * 100).toFixed(1)}%`, color: 'text-bloomberg-text-primary', note: '' },
          { label: 'Debt Weight (D/V)', value: `${(f.debt_weight * 100).toFixed(1)}%`, color: 'text-bloomberg-text-primary', note: '' },
        ].map(row => (
          <div key={row.label} className="flex items-center justify-between gap-2">
            <div className="text-bloomberg-text-muted text-2xs flex-1">{row.label}</div>
            {row.note && <div className="text-bloomberg-text-muted text-2xs">{row.note}</div>}
            <div className={`text-xs font-mono ${row.color}`}>{row.value}</div>
          </div>
        ))}
      </div>

      {/* WACC Result */}
      <div className="mt-3 pt-2 border-t border-bloomberg-border">
        <div className="bg-black border border-bloomberg-border p-2 text-2xs font-mono text-bloomberg-text-muted mb-2">
          <div className="text-bloomberg-electric mb-1">WACC</div>
          <div>(E/V)·r_e + (D/V)·r_d·(1−T)</div>
        </div>
        <div className="flex justify-between items-center">
          <span className="bb-label">BASE WACC</span>
          <span className="text-bloomberg-amber font-bold text-sm">{pct(f.wacc)}</span>
        </div>
        {isOverridden && (
          <div className="flex justify-between items-center mt-1">
            <span className="bb-label">LIVE WACC</span>
            <span className="text-bloomberg-red font-bold text-sm">{pct(liveWacc)}</span>
          </div>
        )}
      </div>
    </div>
  )
}
