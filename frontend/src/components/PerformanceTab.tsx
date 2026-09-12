import { useState, useCallback, useEffect } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts'
import { PerformanceResponse, BenchmarkResponse } from '../types/valuation'
import TimeMachinePanel from './TimeMachinePanel'

type Period = 'week' | 'month' | 'year' | 'all'

type PerfState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; data: PerformanceResponse }
  | { status: 'error'; message: string }

type BenchState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; data: BenchmarkResponse }
  | { status: 'error'; message: string }

type SnapshotState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'done' }
  | { status: 'error'; message: string }

type LiveState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; total_live_value: number; portfolio_return_pct: number }
  | { status: 'error' }

function fmtLarge(n: number) {
  const abs = Math.abs(n)
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(2)
}

function pct(n: number) {
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

function returnColor(ret: number) {
  return ret >= 0 ? 'text-bloomberg-green' : 'text-bloomberg-red'
}

// Custom tooltip for the portfolio value chart
function PortfolioTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null
  return (
    <div className="bg-bloomberg-panel border border-bloomberg-border p-3 text-xs font-mono shadow-lg">
      <div className="text-bloomberg-text-muted mb-1">{d.date}</div>
      <div className="text-[#39ff14] font-bold">
        Valor Total: {fmtLarge(d.total_value)}€
      </div>
      <div className="text-bloomberg-electric">
        Acciones: {fmtLarge(d.invested)}€
      </div>
      <div className="text-bloomberg-text-secondary">
        Efectivo: {fmtLarge(d.cash)}€
      </div>
      {d.contribution > 0 && (
        <div className="text-bloomberg-amber mt-1">
          Aportación: +{fmtLarge(d.contribution)}€
        </div>
      )}
    </div>
  )
}

// Custom tooltip for the benchmark chart
function BenchmarkTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-bloomberg-panel border border-bloomberg-border p-3 text-xs font-mono shadow-lg">
      <div className="text-bloomberg-text-muted mb-1">{label}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} style={{ color: p.color }} className="font-bold">
          {p.name}: {p.value?.toFixed(2)}
        </div>
      ))}
    </div>
  )
}

export default function PerformanceTab() {
  const [period, setPeriod] = useState<Period>('all')
  const [perfState, setPerfState] = useState<PerfState>({ status: 'idle' })
  const [benchState, setBenchState] = useState<BenchState>({ status: 'idle' })
  const [snapState, setSnapState] = useState<SnapshotState>({ status: 'idle' })
  const [liveState, setLiveState] = useState<LiveState>({ status: 'idle' })

  const loadPerformance = useCallback(async (p: Period) => {
    setPerfState({ status: 'loading' })
    try {
      const res = await fetch(`/api/portfolio/performance?period=${p}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: PerformanceResponse = await res.json()
      setPerfState({ status: 'loaded', data })
    } catch (e) {
      setPerfState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }, [])

  const loadLive = useCallback(async () => {
    setLiveState({ status: 'loading' })
    try {
      const res = await fetch('/api/portfolio/live')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setLiveState({
        status: 'loaded',
        total_live_value: data.total_live_value,
        portfolio_return_pct: data.portfolio_return_pct,
      })
    } catch {
      setLiveState({ status: 'error' })
    }
  }, [])

  const loadBenchmark = useCallback(async () => {
    setBenchState({ status: 'loading' })
    try {
      const res = await fetch('/api/portfolio/benchmark')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: BenchmarkResponse = await res.json()
      setBenchState({ status: 'loaded', data })
    } catch (e) {
      setBenchState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }, [])

  const takeSnapshot = useCallback(async () => {
    setSnapState({ status: 'loading' })
    try {
      const res = await fetch('/api/portfolio/snapshot', { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setSnapState({ status: 'done' })
      // Refresh performance data
      loadPerformance(period)
      loadBenchmark()
    } catch (e) {
      setSnapState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }, [period, loadPerformance, loadBenchmark])

  // Auto-load on mount and when period changes
  useEffect(() => {
    loadPerformance(period)
  }, [period, loadPerformance])

  useEffect(() => {
    loadBenchmark()
    loadLive()
  }, [loadBenchmark, loadLive])

  const handlePeriodChange = (p: Period) => {
    setPeriod(p)
  }

  return (
    <div className="p-3 space-y-3">
      {/* Header */}
      <div className="bb-panel p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <span className="text-bloomberg-amber font-mono font-bold text-sm tracking-widest">
              PERFORMANCE ANALYTICS
            </span>
            <span className="text-bloomberg-text-muted text-2xs ml-3">
              Rendimiento de la cartera vs mercado
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={takeSnapshot}
              disabled={snapState.status === 'loading'}
              className="px-3 py-1.5 border border-bloomberg-electric text-bloomberg-electric font-mono text-2xs hover:bg-bloomberg-electric hover:text-black transition-colors disabled:opacity-50"
            >
              {snapState.status === 'loading' ? 'REGISTRANDO...' : '📸 SNAPSHOT LIVE'}
            </button>
          </div>
        </div>

        {/* Period selector */}
        <div className="flex gap-1">
          {(['week', 'month', 'year', 'all'] as Period[]).map(p => (
            <button
              key={p}
              onClick={() => handlePeriodChange(p)}
              className={`
                px-3 py-1 font-mono text-2xs tracking-widest border transition-all duration-200
                ${period === p
                  ? 'border-bloomberg-amber text-bloomberg-amber bg-bloomberg-amber bg-opacity-10'
                  : 'border-transparent text-bloomberg-text-muted hover:text-bloomberg-amber hover:border-bloomberg-border'}
              `}
            >
              {p === 'week' ? 'SEMANAL' : p === 'month' ? 'MENSUAL' : p === 'year' ? 'ANUAL' : 'TODO'}
            </button>
          ))}
        </div>

        {/* Summary cards */}
        {perfState.status === 'loaded' && (
          <div className="grid grid-cols-4 gap-3 mt-3">
            {/* Rentabilidad: usa portfolio/live para valor real intradía */}
            <div className="bg-black border border-bloomberg-border p-3">
              <div className="bb-label mb-1">RENTABILIDAD TOTAL</div>
              <div className={`font-mono font-bold text-base ${
                liveState.status === 'loaded'
                  ? returnColor(liveState.portfolio_return_pct)
                  : returnColor(perfState.data.twr_pct)
              }`}>
                {liveState.status === 'loaded'
                  ? pct(liveState.portfolio_return_pct)
                  : pct(perfState.data.twr_pct)}
              </div>
            </div>

            {/* Valor actual live */}
            <div className="bg-black border border-bloomberg-border p-3">
              <div className="bb-label mb-1">VALOR LIVE</div>
              <div className="font-mono font-bold text-base text-[#39ff14]">
                {liveState.status === 'loaded'
                  ? `${fmtLarge(liveState.total_live_value)}€`
                  : liveState.status === 'loading' ? '...' : '—'}
              </div>
            </div>

            {/* Capital invertido */}
            <div className="bg-black border border-bloomberg-border p-3">
              <div className="bb-label mb-1">CAPITAL INVERTIDO</div>
              <div className="font-mono font-bold text-base text-bloomberg-text-primary">
                {fmtLarge(perfState.data.initial_capital)}€
              </div>
            </div>

            {/* Aportaciones */}
            <div className="bg-black border border-bloomberg-border p-3">
              <div className="bb-label mb-1">APORTACIONES</div>
              <div className="font-mono font-bold text-base text-bloomberg-amber">
                {fmtLarge(perfState.data.total_contributions)}€
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Loading states */}
      {perfState.status === 'loading' && (
        <div className="flex items-center justify-center h-32 gap-3">
          <div className="text-bloomberg-amber font-mono text-sm animate-pulse">
            CARGANDO HISTORIAL...
          </div>
          <div className="flex gap-1">
            {[0, 1, 2].map(i => (
              <div key={i} className="w-1 h-4 bg-bloomberg-amber animate-bounce"
                style={{ animationDelay: `${i * 0.15}s` }} />
            ))}
          </div>
        </div>
      )}

      {perfState.status === 'error' && (
        <div className="bb-panel p-4 text-bloomberg-red text-xs font-mono">
          Error: {perfState.message}
          <button onClick={() => loadPerformance(period)} className="ml-4 text-bloomberg-amber hover:underline">
            reintentar
          </button>
        </div>
      )}

      {/* Empty state */}
      {perfState.status === 'loaded' && perfState.data.history.length === 0 && (
        <div className="bb-panel p-8 text-center space-y-4">
          <div className="text-bloomberg-text-muted text-sm font-mono">
            SIN DATOS DE RENDIMIENTO
          </div>
          <div className="text-bloomberg-text-muted text-2xs max-w-md mx-auto">
            Haz clic en "SNAPSHOT LIVE" para registrar el valor actual de tu cartera,
            o realiza una operación de compra/venta. El historial se construirá con cada acción.
          </div>
          <button
            onClick={takeSnapshot}
            disabled={snapState.status === 'loading'}
            className="px-4 py-2 border border-bloomberg-amber text-bloomberg-amber font-mono text-xs hover:bg-bloomberg-amber hover:text-black transition-colors"
          >
            {snapState.status === 'loading' ? 'REGISTRANDO...' : 'REGISTRAR PRIMER SNAPSHOT'}
          </button>
          {snapState.status === 'done' && (
            <div className="text-bloomberg-green text-2xs font-mono animate-pulse">
              Snapshot registrado correctamente
            </div>
          )}
        </div>
      )}

      {/* ── Portfolio Value Chart ─────────────────────────────────────── */}
      {perfState.status === 'loaded' && perfState.data.history.length > 0 && (
        <div className="bb-panel p-4">
          <div className="px-1 pb-3 border-b border-bloomberg-border mb-4">
            <span className="text-bloomberg-electric text-2xs tracking-widest">
              VALOR TOTAL DE LA CARTERA
            </span>
            <span className="text-bloomberg-text-muted text-2xs ml-2">
              (Efectivo + Acciones)
            </span>
          </div>

          <ResponsiveContainer width="100%" height={320}>
            <AreaChart data={perfState.data.history} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
              <defs>
                <linearGradient id="neonGreenGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#39ff14" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#39ff14" stopOpacity={0.02} />
                </linearGradient>
                <linearGradient id="electricBlueGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00aaff" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#00aaff" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
              <XAxis
                dataKey="date"
                tick={{ fill: '#666', fontSize: 10, fontFamily: 'monospace' }}
                tickFormatter={(d: string) => d.slice(5, 10)}
                stroke="#1e1e1e"
              />
              <YAxis
                tick={{ fill: '#666', fontSize: 10, fontFamily: 'monospace' }}
                tickFormatter={(v: number) => fmtLarge(v)}
                stroke="#1e1e1e"
                domain={['auto', 'auto']}
              />
              <Tooltip content={<PortfolioTooltip />} />
              <Legend
                wrapperStyle={{ fontSize: 10, fontFamily: 'monospace' }}
              />
              <ReferenceLine
                y={perfState.data.initial_capital}
                stroke="#f5a623"
                strokeDasharray="6 4"
                strokeOpacity={0.5}
                label={{
                  value: 'Capital Inicial',
                  fill: '#f5a623',
                  fontSize: 9,
                  fontFamily: 'monospace',
                  position: 'insideTopRight',
                }}
              />
              <Area
                type="monotone"
                dataKey="total_value"
                name="Valor Total"
                stroke="#39ff14"
                strokeWidth={2.5}
                fill="url(#neonGreenGrad)"
                dot={false}
                activeDot={{ r: 4, stroke: '#39ff14', strokeWidth: 2, fill: '#0a0a0a' }}
              />
              <Area
                type="monotone"
                dataKey="invested"
                name="Acciones"
                stroke="#00aaff"
                strokeWidth={1.5}
                fill="url(#electricBlueGrad)"
                dot={false}
                activeDot={{ r: 3, stroke: '#00aaff', strokeWidth: 1, fill: '#0a0a0a' }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Benchmark: Portfolio vs S&P 500 ─────────────────────────── */}
      {benchState.status === 'loading' && (
        <div className="bb-panel px-4 py-6 flex items-center gap-3 text-2xs font-mono text-bloomberg-text-muted">
          <div className="animate-pulse">DESCARGANDO DATOS DEL S&P 500 (SPY)...</div>
          <div className="flex gap-1">
            {[0, 1, 2].map(i => (
              <div key={i} className="w-1 h-3 bg-bloomberg-electric animate-bounce"
                style={{ animationDelay: `${i * 0.15}s` }} />
            ))}
          </div>
        </div>
      )}

      {benchState.status === 'error' && (
        <div className="bb-panel p-3 text-bloomberg-red text-2xs font-mono">
          Benchmark error: {benchState.message}
          <button onClick={loadBenchmark} className="ml-3 text-bloomberg-amber hover:underline">
            reintentar
          </button>
        </div>
      )}

      {benchState.status === 'loaded' && benchState.data.dates.length > 0 && (
        <div className="bb-panel p-4">
          <div className="px-1 pb-3 border-b border-bloomberg-border mb-4 flex items-center justify-between">
            <div>
              <span className="text-bloomberg-electric text-2xs tracking-widest">
                CARTERA vs S&P 500 (SPY)
              </span>
              <span className="text-bloomberg-text-muted text-2xs ml-2">
                Base = 100,000
              </span>
            </div>
            <div className="flex items-center gap-4 text-2xs font-mono">
              <span className={returnColor(benchState.data.portfolio_return_pct)}>
                Cartera: {pct(benchState.data.portfolio_return_pct)}
              </span>
              <span className="text-bloomberg-text-secondary">
                SPY: {pct(benchState.data.spy_return_pct)}
              </span>
              <span className={`font-bold ${returnColor(benchState.data.alpha_pct)}`}>
                Alpha: {pct(benchState.data.alpha_pct)}
              </span>
            </div>
          </div>

          <ResponsiveContainer width="100%" height={320}>
            <AreaChart
              data={benchState.data.dates.map((d, i) => ({
                date: d,
                portfolio: benchState.data.portfolio_indexed[i],
                spy: benchState.data.spy_indexed[i],
              }))}
              margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
            >
              <defs>
                <linearGradient id="benchPortGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#39ff14" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#39ff14" stopOpacity={0.02} />
                </linearGradient>
                <linearGradient id="benchSpyGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ffffff" stopOpacity={0.08} />
                  <stop offset="95%" stopColor="#ffffff" stopOpacity={0.01} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
              <XAxis
                dataKey="date"
                tick={{ fill: '#666', fontSize: 10, fontFamily: 'monospace' }}
                tickFormatter={(d: string) => d.slice(5, 10)}
                stroke="#1e1e1e"
              />
              <YAxis
                tick={{ fill: '#666', fontSize: 10, fontFamily: 'monospace' }}
                stroke="#1e1e1e"
                domain={['auto', 'auto']}
              />
              <Tooltip content={<BenchmarkTooltip />} />
              <Legend
                wrapperStyle={{ fontSize: 10, fontFamily: 'monospace' }}
              />
              <ReferenceLine
                y={100000}
                stroke="#f5a623"
                strokeDasharray="6 4"
                strokeOpacity={0.4}
                label={{
                  value: 'Base 100,000',
                  fill: '#f5a623',
                  fontSize: 9,
                  fontFamily: 'monospace',
                  position: 'insideTopRight',
                }}
              />
              <Area
                type="monotone"
                dataKey="portfolio"
                name="Mi Cartera"
                stroke="#39ff14"
                strokeWidth={2.5}
                fill="url(#benchPortGrad)"
                dot={false}
                activeDot={{ r: 4, stroke: '#39ff14', strokeWidth: 2, fill: '#0a0a0a' }}
              />
              <Area
                type="monotone"
                dataKey="spy"
                name="S&P 500 (SPY)"
                stroke="rgba(255,255,255,0.5)"
                strokeWidth={1.5}
                fill="url(#benchSpyGrad)"
                dot={false}
                activeDot={{ r: 3, stroke: '#fff', strokeWidth: 1, fill: '#0a0a0a' }}
              />
            </AreaChart>
          </ResponsiveContainer>

          {/* Alpha verdict */}
          <div className="mt-3 flex justify-center">
            <div className={`
              px-4 py-2 border font-mono text-xs tracking-widest
              ${benchState.data.alpha_pct >= 0
                ? 'border-bloomberg-green text-bloomberg-green bg-bloomberg-green bg-opacity-5'
                : 'border-bloomberg-red text-bloomberg-red bg-bloomberg-red bg-opacity-5'}
            `}>
              {benchState.data.alpha_pct >= 0
                ? `BATIENDO AL MERCADO POR ${pct(benchState.data.alpha_pct)}`
                : `POR DEBAJO DEL MERCADO EN ${pct(Math.abs(benchState.data.alpha_pct))}`
              }
            </div>
          </div>
        </div>
      )}

      {benchState.status === 'loaded' && benchState.data.dates.length === 0 && perfState.status === 'loaded' && perfState.data.history.length > 0 && (
        <div className="bb-panel p-4 text-center text-bloomberg-text-muted text-2xs font-mono">
          Benchmark no disponible. Se necesitan al menos 2 snapshots para comparar con el S&P 500.
        </div>
      )}

      {/* ── Máquina del tiempo: la cartera en una fecha pasada ──────────────── */}
      <TimeMachinePanel />
    </div>
  )
}
