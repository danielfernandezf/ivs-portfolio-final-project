import { FundamentalData, SensitivityOverrides } from '../types/valuation'

interface Props {
  overrides: SensitivityOverrides
  onOverride: (key: keyof SensitivityOverrides, val: number) => void
  f: FundamentalData
}

interface SliderConfig {
  key: keyof SensitivityOverrides
  label: string
  min: number
  max: number
  step: number
  format: (v: number) => string
  color: string
  description: string
}

const SLIDERS: SliderConfig[] = [
  {
    key: 'wacc',
    label: 'WACC',
    min: 3,
    max: 20,
    step: 0.1,
    format: v => `${v.toFixed(1)}%`,
    color: '#f5a623',
    description: 'Discount rate applied to all future FCFs',
  },
  {
    key: 'growthRate',
    label: 'FCF GROWTH (Y1-5)',
    min: -20,
    max: 50,
    step: 0.5,
    format: v => `${v.toFixed(1)}%`,
    color: '#00aaff',
    description: 'Annual FCF growth rate for 5-year projection',
  },
  {
    key: 'terminalGrowth',
    label: 'TERMINAL GROWTH',
    min: 0,
    max: 5,
    step: 0.1,
    format: v => `${v.toFixed(1)}%`,
    color: '#00cc44',
    description: 'Perpetuity growth (Gordon Growth Model). Must be < WACC.',
  },
  {
    key: 'fcfMargin',
    label: 'FCF MARGIN',
    min: 1,
    max: 40,
    step: 0.5,
    format: v => `${v.toFixed(1)}%`,
    color: '#888888',
    description: 'Informational: target FCF margin % of revenue',
  },
]

export default function SensitivityPanel({ overrides, onOverride, f }: Props) {
  return (
    <div className="bb-panel p-3">
      <div className="text-bloomberg-amber text-2xs tracking-widest mb-1">
        SENSITIVITY — SCENARIO ANALYSIS
      </div>
      <div className="text-bloomberg-text-muted text-2xs mb-3">
        Drag sliders to stress-test the model. Price updates in real-time.
      </div>

      <div className="space-y-4">
        {SLIDERS.map(s => {
          const val = overrides[s.key]
          const baseVal = s.key === 'wacc'
            ? f.wacc * 100
            : s.key === 'growthRate'
            ? f.assumptions.revenue_growth_rate * 100
            : s.key === 'terminalGrowth'
            ? f.assumptions.terminal_growth_rate * 100
            : f.assumptions.fcf_margin * 100

          const delta = val - baseVal
          const deltaStr = delta >= 0 ? `+${delta.toFixed(1)}%` : `${delta.toFixed(1)}%`
          const isChanged = Math.abs(delta) > 0.05

          return (
            <div key={s.key}>
              <div className="flex justify-between items-center mb-1">
                <span className="text-2xs text-bloomberg-text-muted">{s.label}</span>
                <div className="flex items-center gap-2">
                  {isChanged && (
                    <span className={`text-2xs font-mono ${delta > 0 ? 'text-bloomberg-red' : 'text-bloomberg-green'}`}>
                      {deltaStr}
                    </span>
                  )}
                  <span className="text-xs font-mono font-bold" style={{ color: s.color }}>
                    {s.format(val)}
                  </span>
                </div>
              </div>
              <input
                type="range"
                min={s.min}
                max={s.max}
                step={s.step}
                value={val}
                onChange={e => onOverride(s.key, parseFloat(e.target.value))}
                className="bb-slider"
                style={{ accentColor: s.color }}
              />
              <div className="flex justify-between text-2xs text-bloomberg-text-muted mt-0.5">
                <span>{s.format(s.min)}</span>
                <span className="text-bloomberg-text-muted text-2xs truncate mx-2 text-center" style={{ maxWidth: '120px' }}>
                  {s.description}
                </span>
                <span>{s.format(s.max)}</span>
              </div>
              {isChanged && (
                <div className="flex justify-between text-2xs mt-0.5">
                  <span className="text-bloomberg-text-muted">Base: {s.format(baseVal)}</span>
                  <button
                    onClick={() => onOverride(s.key, baseVal)}
                    className="text-bloomberg-text-muted hover:text-bloomberg-amber transition-colors"
                  >
                    ↺ reset
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Scenario presets */}
      <div className="mt-4 pt-3 border-t border-bloomberg-border">
        <div className="bb-label mb-2">QUICK SCENARIOS</div>
        <div className="grid grid-cols-3 gap-1">
          {[
            {
              name: 'BULL',
              color: 'text-bloomberg-green',
              vals: { wacc: f.wacc * 100 - 1, growthRate: f.assumptions.revenue_growth_rate * 100 + 10, terminalGrowth: 3.0, fcfMargin: f.assumptions.fcf_margin * 100 + 5 },
            },
            {
              name: 'BASE',
              color: 'text-bloomberg-amber',
              vals: { wacc: f.wacc * 100, growthRate: f.assumptions.revenue_growth_rate * 100, terminalGrowth: f.assumptions.terminal_growth_rate * 100, fcfMargin: f.assumptions.fcf_margin * 100 },
            },
            {
              name: 'BEAR',
              color: 'text-bloomberg-red',
              vals: { wacc: f.wacc * 100 + 2, growthRate: Math.max(f.assumptions.revenue_growth_rate * 100 - 8, -10), terminalGrowth: 1.5, fcfMargin: Math.max(f.assumptions.fcf_margin * 100 - 5, 1) },
            },
          ].map(scenario => (
            <button
              key={scenario.name}
              onClick={() => {
                Object.entries(scenario.vals).forEach(([k, v]) =>
                  onOverride(k as keyof SensitivityOverrides, v)
                )
              }}
              className={`text-2xs font-mono py-1.5 border border-bloomberg-border hover:bg-bloomberg-border transition-colors ${scenario.color}`}
            >
              {scenario.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
