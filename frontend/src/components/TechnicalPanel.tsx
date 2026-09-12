import { TechnicalData } from '../types/valuation'

interface Props {
  tech: TechnicalData
  currentPrice: number
}

function pct(n: number) { return `${(n * 100).toFixed(1)}%` }
function fmt(n: number) { return n.toFixed(2) }

export default function TechnicalPanel({ tech, currentPrice }: Props) {
  const trendColor =
    tech.trend_direction === 'BULLISH'
      ? 'text-bloomberg-green'
      : tech.trend_direction === 'BEARISH'
      ? 'text-bloomberg-red'
      : 'text-bloomberg-amber'

  const macdColor =
    tech.macd_signal === 'BUY'
      ? 'text-bloomberg-green'
      : tech.macd_signal === 'SELL'
      ? 'text-bloomberg-red'
      : 'text-bloomberg-amber'

  const riskColor =
    tech.risk_label === 'LOW'
      ? 'text-bloomberg-green'
      : tech.risk_label === 'MODERATE'
      ? 'text-bloomberg-amber'
      : tech.risk_label === 'HIGH'
      ? 'text-bloomberg-red'
      : 'text-bloomberg-red'

  return (
    <div className="bb-panel p-3">
      <div className="text-bloomberg-amber text-2xs tracking-widest mb-1">
        TECHNICAL RISK — PROBABILISTIC
      </div>
      <div className="text-bloomberg-text-muted text-2xs mb-3">
        El Arte de Especular methodology (Cava 2006). Isolated from fundamental DCF.
      </div>

      {/* Trend */}
      <div className="mb-3">
        <div className="flex justify-between items-center mb-1">
          <span className="bb-label">TREND</span>
          <span className={`font-mono text-xs font-bold ${trendColor}`}>
            {tech.trend_direction} / {tech.trend_strength}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-1 text-2xs">
          <div className="flex justify-between">
            <span className="text-bloomberg-text-muted">vs MA50</span>
            <span className={tech.price_vs_ma50 >= 0 ? 'text-bloomberg-green' : 'text-bloomberg-red'}>
              {pct(tech.price_vs_ma50)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-bloomberg-text-muted">vs MA200</span>
            <span className={tech.price_vs_ma200 >= 0 ? 'text-bloomberg-green' : 'text-bloomberg-red'}>
              {pct(tech.price_vs_ma200)}
            </span>
          </div>
        </div>
      </div>

      {/* Momentum */}
      <div className="mb-3 pt-2 border-t border-bloomberg-border">
        <div className="flex justify-between items-center mb-1">
          <span className="bb-label">MACD SIGNAL</span>
          <span className={`font-mono text-xs font-bold ${macdColor}`}>
            {tech.macd_signal}
          </span>
        </div>
        <div className="flex justify-between text-2xs">
          <span className="text-bloomberg-text-muted">RSI(14)</span>
          <span className={
            tech.rsi_signal === 'OVERBOUGHT' ? 'text-bloomberg-red' :
            tech.rsi_signal === 'OVERSOLD' ? 'text-bloomberg-green' :
            'text-bloomberg-text-secondary'
          }>
            {fmt(tech.rsi_14)} — {tech.rsi_signal}
          </span>
        </div>
      </div>

      {/* Volatility */}
      <div className="mb-3 pt-2 border-t border-bloomberg-border">
        <div className="flex justify-between items-center mb-1">
          <span className="bb-label">VOLATILITY</span>
          <span className="font-mono text-xs text-bloomberg-amber">
            {pct(tech.annualised_volatility)} / {tech.volatility_regime}
          </span>
        </div>
      </div>

      {/* Fibonacci */}
      <div className="mb-3 pt-2 border-t border-bloomberg-border">
        <div className="bb-label mb-1">FIBONACCI (52W)</div>
        <div className="space-y-0.5 text-2xs">
          {[
            { label: '23.6%', val: tech.fib_236 },
            { label: '38.2%', val: tech.fib_382 },
            { label: '50.0%', val: tech.fib_500 },
            { label: '61.8%', val: tech.fib_618 },
            { label: '78.6%', val: tech.fib_786 },
          ].map(fib => {
            const isNear = Math.abs(currentPrice - fib.val) / currentPrice < 0.02
            return (
              <div key={fib.label} className={`flex justify-between ${isNear ? 'text-bloomberg-amber' : ''}`}>
                <span className="text-bloomberg-text-muted">{fib.label}</span>
                <span className="font-mono">${fmt(fib.val)}{isNear ? ' ◄' : ''}</span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Probability scenarios */}
      <div className="mb-3 pt-2 border-t border-bloomberg-border">
        <div className="bb-label mb-2">3-SCENARIO PROBABILITY (12M)</div>
        <div className="space-y-1 text-2xs">
          <div className="flex justify-between">
            <span className="text-bloomberg-green">BULL ({(tech.bull_probability * 100).toFixed(0)}%)</span>
            <span className="font-mono">${fmt(tech.bull_price_target)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-bloomberg-amber">BASE ({(tech.base_probability * 100).toFixed(0)}%)</span>
            <span className="font-mono">${fmt(tech.base_price_target)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-bloomberg-red">BEAR ({(tech.bear_probability * 100).toFixed(0)}%)</span>
            <span className="font-mono">${fmt(tech.bear_price_target)}</span>
          </div>
        </div>
        <div className="flex justify-between text-xs mt-2 pt-1 border-t border-bloomberg-border border-opacity-50">
          <span className="text-bloomberg-text-muted">P-WEIGHTED</span>
          <span className="text-bloomberg-amber font-bold">${fmt(tech.probability_weighted_price)}</span>
        </div>
      </div>

      {/* Risk Score */}
      <div className="pt-2 border-t border-bloomberg-border">
        <div className="flex justify-between items-center mb-1">
          <span className="bb-label">COMPOSITE RISK SCORE</span>
          <span className={`font-mono text-xs font-bold ${riskColor}`}>
            {tech.risk_label}
          </span>
        </div>
        <div className="w-full bg-bloomberg-border rounded h-1.5 mt-1">
          <div
            className="h-1.5 rounded transition-all duration-500"
            style={{
              width: `${tech.risk_score}%`,
              backgroundColor: tech.risk_score > 75 ? '#ff3333' : tech.risk_score > 50 ? '#f5a623' : '#00cc44',
            }}
          />
        </div>
        <div className="flex justify-between text-2xs mt-0.5">
          <span className="text-bloomberg-green">LOW</span>
          <span className="text-bloomberg-text-muted">{tech.risk_score.toFixed(0)}/100</span>
          <span className="text-bloomberg-red">VERY HIGH</span>
        </div>
      </div>
    </div>
  )
}
