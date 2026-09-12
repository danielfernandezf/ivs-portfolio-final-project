import { useState, useCallback } from 'react'
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts'
import { MonteCarloResult } from '../types/valuation'

interface Props {
  ticker: string
  currentPrice: number
}

type LoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; data: MonteCarloResult }
  | { status: 'error'; message: string }

function fmt2(n: number) { return n.toFixed(2) }
function pctFmt(n: number) { return `${(n * 100).toFixed(1)}%` }

// Colour a percentile badge
function pctColor(price: number, current: number) {
  if (price > current * 1.2) return 'text-bloomberg-green'
  if (price > current) return 'text-bloomberg-amber'
  return 'text-bloomberg-red'
}

// Custom tooltip for the chart
function McTooltip({ active, payload, label }: {
  active?: boolean
  payload?: Array<{ name: string; value: number; color: string }>
  label?: number
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-bloomberg-panel border border-bloomberg-border p-2 text-2xs font-mono">
      <div className="text-bloomberg-amber mb-1">≈ ${label?.toFixed(2)}</div>
      {payload.map(p => (
        <div key={p.name} style={{ color: p.color }}>
          {p.name === 'density' ? 'Frecuencia' : 'Normal'}: {(p.value * 100).toFixed(3)}%
        </div>
      ))}
    </div>
  )
}

export default function MonteCarloChart({ ticker, currentPrice }: Props) {
  const [state, setState] = useState<LoadState>({ status: 'idle' })

  const runSimulation = useCallback(async () => {
    setState({ status: 'loading' })
    try {
      const res = await fetch(`/api/montecarlo/${ticker}`)
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const data: MonteCarloResult = await res.json()
      setState({ status: 'loaded', data })
    } catch (e) {
      setState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }, [ticker])

  return (
    <div className="bb-panel">
      {/* Header */}
      <div className="px-4 py-2 border-b border-bloomberg-border flex items-center justify-between">
        <div>
          <span className="text-bloomberg-amber font-mono font-bold text-xs tracking-widest">
            MONTE CARLO DCF
          </span>
          <span className="text-bloomberg-text-muted text-2xs ml-3">
            10 000 ITERACIONES · DISTRIBUCIÓN DE VALOR INTRÍNSECO
          </span>
        </div>
        <button
          onClick={runSimulation}
          disabled={state.status === 'loading'}
          className="px-3 py-1 border border-bloomberg-amber text-bloomberg-amber font-mono text-2xs hover:bg-bloomberg-amber hover:text-black transition-colors disabled:opacity-50"
        >
          {state.status === 'loading' ? '⟳ SIMULANDO...' : state.status === 'loaded' ? '↺ RE-RUN' : '▶ EJECUTAR SIMULACIÓN'}
        </button>
      </div>

      {/* Idle state */}
      {state.status === 'idle' && (
        <div className="px-4 py-8 text-center">
          <div className="text-bloomberg-text-muted text-2xs leading-relaxed max-w-md mx-auto">
            Ejecuta 10 000 escenarios DCF con ruido gaussiano en la tasa de crecimiento (σ histórico de FCF)
            y el WACC (σ derivado de la incertidumbre del beta). Genera la distribución de probabilidad
            del Valor Intrínseco y calcula P(intrínseco &gt; precio de mercado).
          </div>
        </div>
      )}

      {/* Loading state */}
      {state.status === 'loading' && (
        <div className="flex items-center justify-center py-12 gap-3">
          <div className="text-bloomberg-amber font-mono text-xs animate-pulse">
            EJECUTANDO 10 000 ITERACIONES DCF...
          </div>
          <div className="flex gap-1">
            {[0, 1, 2, 3, 4].map(i => (
              <div key={i} className="w-1 h-5 bg-bloomberg-amber animate-bounce"
                style={{ animationDelay: `${i * 0.1}s` }} />
            ))}
          </div>
        </div>
      )}

      {/* Error state */}
      {state.status === 'error' && (
        <div className="px-4 py-4 text-bloomberg-red text-xs font-mono">
          ⚠ {state.message}
          <button onClick={runSimulation} className="ml-3 text-bloomberg-amber hover:underline">↺ reintentar</button>
        </div>
      )}

      {/* Loaded state */}
      {state.status === 'loaded' && (() => {
        const d = state.data

        return (
          <div>
            {/* Percentile stats row */}
            <div className="grid grid-cols-5 gap-0 border-b border-bloomberg-border">
              {[
                { label: 'P10', val: d.p10 },
                { label: 'P25', val: d.p25 },
                { label: 'P50 — MEDIANA', val: d.p50 },
                { label: 'P75', val: d.p75 },
                { label: 'P90', val: d.p90 },
              ].map(({ label, val }) => (
                <div key={label} className="px-3 py-2 text-center border-r border-bloomberg-border last:border-r-0">
                  <div className="bb-label text-2xs">{label}</div>
                  <div className={`font-mono font-bold text-sm ${pctColor(val, currentPrice)}`}>
                    ${fmt2(val)}
                  </div>
                </div>
              ))}
            </div>

            {/* Chart */}
            <div className="px-2 pt-3 pb-2" style={{ height: 280 }}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart
                  data={d.histogram}
                  margin={{ top: 4, right: 16, left: 0, bottom: 4 }}
                >
                  <CartesianGrid strokeDasharray="2 4" stroke="#1e2530" vertical={false} />
                  <XAxis
                    dataKey="price_mid"
                    type="number"
                    domain={['dataMin', 'dataMax']}
                    tickFormatter={v => `$${(v as number).toFixed(0)}`}
                    tick={{ fill: '#6b7685', fontSize: 9, fontFamily: 'monospace' }}
                    axisLine={{ stroke: '#2a3441' }}
                    tickLine={false}
                  />
                  <YAxis hide />
                  <Tooltip content={<McTooltip />} />

                  {/* Histogram bars */}
                  <Bar
                    dataKey="density"
                    fill="#1e3a5f"
                    stroke="#2a5080"
                    strokeWidth={0.5}
                    opacity={0.85}
                    isAnimationActive={false}
                  />

                  {/* Normal distribution overlay */}
                  <Line
                    type="monotone"
                    dataKey="normal_density"
                    stroke="#00FF88"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                    filter="url(#glow)"
                  />

                  {/* Current market price — electric blue vertical line */}
                  <ReferenceLine
                    x={currentPrice}
                    stroke="#00BFFF"
                    strokeWidth={2}
                    strokeDasharray="4 3"
                    label={{
                      value: `PRECIO  $${fmt2(currentPrice)}`,
                      position: 'insideTopRight',
                      fill: '#00BFFF',
                      fontSize: 9,
                      fontFamily: 'monospace',
                    }}
                  />

                  {/* Median (P50) — amber vertical line */}
                  <ReferenceLine
                    x={d.p50}
                    stroke="#FFB300"
                    strokeWidth={1.5}
                    strokeDasharray="3 3"
                    label={{
                      value: `P50  $${fmt2(d.p50)}`,
                      position: 'insideTopLeft',
                      fill: '#FFB300',
                      fontSize: 9,
                      fontFamily: 'monospace',
                    }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            {/* Footer stats */}
            <div className="border-t border-bloomberg-border px-4 py-2 grid grid-cols-2 gap-4 text-2xs font-mono">
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-bloomberg-text-muted">P(intrínseco &gt; precio mercado)</span>
                  <span className={`font-bold ${d.probability_above_market >= 0.5 ? 'text-bloomberg-green' : 'text-bloomberg-red'}`}>
                    {pctFmt(d.probability_above_market)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-bloomberg-text-muted">Media de la distribución</span>
                  <span className="text-bloomberg-electric">${fmt2(d.mean)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-bloomberg-text-muted">Desv. estándar</span>
                  <span className="text-bloomberg-text-secondary">±${fmt2(d.std)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-bloomberg-text-muted">Iteraciones válidas</span>
                  <span className="text-bloomberg-text-secondary">{d.iterations.toLocaleString()}</span>
                </div>
              </div>
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-bloomberg-text-muted">μ crecimiento FCF</span>
                  <span className="text-bloomberg-text-secondary">{d.growth_mean_pct.toFixed(1)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-bloomberg-text-muted">σ crecimiento FCF</span>
                  <span className="text-bloomberg-amber">±{d.growth_std_pct.toFixed(1)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-bloomberg-text-muted">μ WACC</span>
                  <span className="text-bloomberg-text-secondary">{d.wacc_mean_pct.toFixed(2)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-bloomberg-text-muted">σ WACC</span>
                  <span className="text-bloomberg-amber">±{d.wacc_std_pct.toFixed(2)}%</span>
                </div>
              </div>
            </div>

            {/* KS test row */}
            <div className="border-t border-bloomberg-border px-4 py-1.5 flex items-center gap-6 text-2xs font-mono text-bloomberg-text-muted">
              <span>KS-TEST (bondad de ajuste a normal):</span>
              <span>
                stat = <span className="text-bloomberg-text-secondary">{d.ks_statistic.toFixed(4)}</span>
              </span>
              <span>
                p-value = <span className={d.ks_pvalue > 0.05 ? 'text-bloomberg-green' : 'text-bloomberg-amber'}>
                  {d.ks_pvalue.toFixed(4)}
                </span>
              </span>
              <span className="ml-auto">
                <span className="text-bloomberg-electric">■</span> Precio mercado &nbsp;
                <span className="text-bloomberg-amber">■</span> Mediana (P50) &nbsp;
                <span className="text-bloomberg-green">■</span> Curva normal
              </span>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
