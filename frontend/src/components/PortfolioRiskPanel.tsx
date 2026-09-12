import { PortfolioRiskMetrics } from '../types/valuation'

interface Props {
  metrics: PortfolioRiskMetrics
}

function sharpeColor(s: number | null): string {
  if (s == null) return 'text-bloomberg-text-muted'
  if (s >= 1.5) return 'text-bloomberg-green'
  if (s >= 0.8) return 'text-bloomberg-electric'
  if (s >= 0) return 'text-bloomberg-amber'
  return 'text-bloomberg-red'
}

function sharpeLabel(s: number | null): string {
  if (s == null) return 'N/A'
  if (s >= 2.0) return 'EXCEPCIONAL'
  if (s >= 1.5) return 'EXCELENTE'
  if (s >= 1.0) return 'BUENO'
  if (s >= 0.5) return 'ACEPTABLE'
  if (s >= 0) return 'BAJO'
  return 'NEGATIVO'
}

function volColor(v: number): string {
  if (v <= 12) return 'text-bloomberg-green'
  if (v <= 20) return 'text-bloomberg-electric'
  if (v <= 30) return 'text-bloomberg-amber'
  return 'text-bloomberg-red'
}

export default function PortfolioRiskPanel({ metrics }: Props) {
  const { sharpe_ratio, annualised_return_pct, annualised_volatility_pct, portfolio_beta } = metrics

  return (
    <div className="bb-panel animate-fadeIn">
      <div className="px-4 py-2 border-b border-bloomberg-border flex items-center justify-between">
        <span className="text-bloomberg-electric text-2xs tracking-widest font-bold">
          RISK-RETURN ANALYTICS
        </span>
        <span className="text-bloomberg-text-muted text-2xs font-mono">
          252d rolling
        </span>
      </div>

      <div className="grid grid-cols-4 gap-0 divide-x divide-bloomberg-border">
        {/* Sharpe Ratio */}
        <div className="p-3 text-center">
          <div className="text-bloomberg-text-muted text-2xs tracking-wider mb-1">SHARPE</div>
          <div className={`font-mono font-bold text-lg ${sharpeColor(sharpe_ratio)}`}>
            {sharpe_ratio != null ? sharpe_ratio.toFixed(2) : '---'}
          </div>
          <div className={`text-2xs font-mono mt-0.5 ${sharpeColor(sharpe_ratio)}`}>
            {sharpeLabel(sharpe_ratio)}
          </div>
        </div>

        {/* Annualised Return */}
        <div className="p-3 text-center">
          <div className="text-bloomberg-text-muted text-2xs tracking-wider mb-1">RETORNO</div>
          <div className={`font-mono font-bold text-lg ${annualised_return_pct >= 0 ? 'text-bloomberg-green' : 'text-bloomberg-red'}`}>
            {annualised_return_pct >= 0 ? '+' : ''}{annualised_return_pct.toFixed(1)}%
          </div>
          <div className="text-2xs font-mono mt-0.5 text-bloomberg-text-muted">anualizado</div>
        </div>

        {/* Volatility */}
        <div className="p-3 text-center">
          <div className="text-bloomberg-text-muted text-2xs tracking-wider mb-1">VOLATILIDAD</div>
          <div className={`font-mono font-bold text-lg ${volColor(annualised_volatility_pct)}`}>
            {annualised_volatility_pct.toFixed(1)}%
          </div>
          <div className={`text-2xs font-mono mt-0.5 ${volColor(annualised_volatility_pct)}`}>
            {annualised_volatility_pct <= 12 ? 'BAJA' : annualised_volatility_pct <= 20 ? 'NORMAL' : annualised_volatility_pct <= 30 ? 'ALTA' : 'EXTREMA'}
          </div>
        </div>

        {/* Portfolio Beta */}
        <div className="p-3 text-center">
          <div className="text-bloomberg-text-muted text-2xs tracking-wider mb-1">BETA</div>
          <div className={`font-mono font-bold text-lg ${portfolio_beta <= 1.0 ? 'text-bloomberg-electric' : 'text-bloomberg-amber'}`}>
            {portfolio_beta.toFixed(2)}
          </div>
          <div className="text-2xs font-mono mt-0.5 text-bloomberg-text-muted">
            {portfolio_beta < 0.8 ? 'DEFENSIVO' : portfolio_beta <= 1.2 ? 'MERCADO' : 'AGRESIVO'}
          </div>
        </div>
      </div>

      {/* Sharpe visual gauge */}
      {sharpe_ratio != null && (
        <div className="px-4 py-2 border-t border-bloomberg-border">
          <div className="flex items-center gap-2">
            <span className="text-2xs text-bloomberg-text-muted font-mono w-8">-1</span>
            <div className="flex-1 h-1.5 bg-bloomberg-border rounded-full overflow-hidden relative">
              {/* Gradient bar */}
              <div className="absolute inset-0 rounded-full"
                style={{ background: 'linear-gradient(to right, #ff3333 0%, #f5a623 35%, #00aaff 55%, #00cc44 100%)' }}
              />
              {/* Marker */}
              <div
                className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full border-2 border-white bg-black shadow-lg transition-all duration-700"
                style={{ left: `${Math.min(Math.max((sharpe_ratio + 1) / 4 * 100, 0), 100)}%` }}
              />
            </div>
            <span className="text-2xs text-bloomberg-text-muted font-mono w-8 text-right">3+</span>
          </div>
        </div>
      )}
    </div>
  )
}
