import { useState, useCallback, useEffect, useRef } from 'react'
import { MoversResponse, MoverRow } from '../types/valuation'

interface Props {
  /** Salta al Analyzer con el ticker seleccionado */
  onAnalyze?: (ticker: string) => void
}

type State =
  | { status: 'loading' }
  | { status: 'loaded'; data: MoversResponse }
  | { status: 'error'; message: string }

function pct(n: number | null, d = 1) {
  if (n === null || n === undefined) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(d)}%`
}

function retColor(n: number | null) {
  if (n === null || n === undefined) return 'text-bloomberg-text-muted'
  return n >= 0 ? 'text-bloomberg-green' : 'text-bloomberg-red'
}

/** Barra proporcional al movimiento, normalizada al mayor de la lista. */
function MoveBar({ value, max, positive }: { value: number; max: number; positive: boolean }) {
  const width = max > 0 ? Math.min(Math.abs(value) / max * 100, 100) : 0
  return (
    <div className="h-1 w-full bg-black bg-opacity-40 mt-0.5">
      <div
        className="h-full transition-all duration-300"
        style={{
          width: `${width}%`,
          backgroundColor: positive ? '#2E9E4F' : '#C62828',
        }}
      />
    </div>
  )
}

function fmtWhen(iso: string | null): string {
  if (!iso) return 'nunca'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('es-ES', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function MoversTable({
  rows, title, accent, onAnalyze,
}: {
  rows: MoverRow[]
  title: string
  accent: 'green' | 'red'
  onAnalyze?: (ticker: string) => void
}) {
  const max = rows.length ? Math.max(...rows.map(r => Math.abs(r.week_pct))) : 0
  const headColor = accent === 'green' ? 'text-bloomberg-green' : 'text-bloomberg-red'

  return (
    <div className="min-w-0">
      <div className={`px-3 py-1.5 border-b border-bloomberg-border ${headColor} font-mono text-2xs tracking-widest font-bold`}>
        {title}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-2xs font-mono">
          <thead>
            <tr className="text-bloomberg-text-muted border-b border-bloomberg-border border-opacity-40">
              <th className="text-left px-3 py-1.5">TICKER</th>
              <th className="text-right px-2 py-1.5">SEMANA</th>
              <th className="text-right px-2 py-1.5">DÍA</th>
              <th className="text-right px-2 py-1.5">MES</th>
              <th className="text-right px-2 py-1.5">CIERRE</th>
              <th className="text-right px-3 py-1.5">MoS</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr
                key={r.ticker}
                onClick={() => onAnalyze?.(r.ticker)}
                className={`border-b border-bloomberg-border border-opacity-20 transition-colors ${
                  onAnalyze ? 'cursor-pointer hover:bg-bloomberg-panel' : ''
                }`}
                title={onAnalyze ? `Analizar ${r.ticker}` : undefined}
              >
                <td className="px-3 py-1.5">
                  <div className="text-bloomberg-amber font-bold">{r.ticker}</div>
                  <div className="text-bloomberg-text-muted truncate max-w-[150px]" style={{ fontSize: '8px' }}>
                    {r.company_name !== r.ticker ? r.company_name : r.sector}
                  </div>
                </td>
                <td className={`text-right px-2 py-1.5 font-bold ${retColor(r.week_pct)}`}>
                  {pct(r.week_pct)}
                  <MoveBar value={r.week_pct} max={max} positive={r.week_pct >= 0} />
                </td>
                <td className={`text-right px-2 py-1.5 ${retColor(r.day_pct)}`}>{pct(r.day_pct)}</td>
                <td className={`text-right px-2 py-1.5 ${retColor(r.month_pct)}`}>{pct(r.month_pct)}</td>
                <td className="text-right px-2 py-1.5 text-bloomberg-text-secondary">
                  {r.last_close.toFixed(2)}
                </td>
                <td className="text-right px-3 py-1.5">
                  {/* Sin MoS = fuera del último escaneo del screener, no "MoS = 0" */}
                  {r.mos_pct === null || r.mos_pct === undefined ? (
                    <span className="text-bloomberg-text-muted" title="No valorada en el último escaneo">—</span>
                  ) : (
                    <span className={r.mos_pct > 20 ? 'text-bloomberg-green' : r.mos_pct > 0 ? 'text-bloomberg-amber' : 'text-bloomberg-red'}>
                      {r.mos_pct.toFixed(0)}%
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-center text-bloomberg-text-muted">
                  Sin datos — lanza un recálculo.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function WeeklyMovers({ onAnalyze }: Props) {
  const [state, setState] = useState<State>({ status: 'loading' })
  const [limit, setLimit] = useState(15)
  const [refreshing, setRefreshing] = useState(false)
  const pollRef = useRef<number | null>(null)

  const load = useCallback(async (n: number) => {
    try {
      const res = await fetch(`/api/screener/movers?limit=${n}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: MoversResponse = await res.json()
      setState({ status: 'loaded', data })
      return data
    } catch (e) {
      setState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
      return null
    }
  }, [])

  useEffect(() => { load(limit) }, [limit, load])

  // Mientras el job corre, se sondea cada 3s para ver avanzar la barra.
  // La dependencia es el booleano, no el objeto `state`: si dependiera del estado
  // completo, cada respuesta del sondeo lo cambiaría y el intervalo se destruiría
  // y recrearía en cada tick.
  const isRunning = state.status === 'loaded' && state.data.status.running

  useEffect(() => {
    if (!isRunning) {
      setRefreshing(false)
      return
    }
    const id = window.setInterval(() => { load(limit) }, 3000)
    pollRef.current = id
    return () => {
      window.clearInterval(id)
      pollRef.current = null
    }
  }, [isRunning, limit, load])

  const triggerRefresh = useCallback(async () => {
    setRefreshing(true)
    try {
      await fetch('/api/screener/movers/refresh', { method: 'POST' })
      await load(limit)
    } catch {
      setRefreshing(false)
    }
  }, [limit, load])

  if (state.status === 'loading') {
    return (
      <div className="bb-panel px-4 py-6 flex items-center gap-3 text-2xs font-mono text-bloomberg-text-muted">
        <div className="animate-pulse">CARGANDO TOP PERFORMERS...</div>
      </div>
    )
  }

  if (state.status === 'error') {
    return (
      <div className="bb-panel p-3 text-bloomberg-red text-2xs font-mono">
        ⚠ Movers: {state.message}
        <button onClick={() => load(limit)} className="ml-3 text-bloomberg-amber hover:underline">↺ reintentar</button>
      </div>
    )
  }

  const { data } = state
  const running = data.status.running
  const noData = !data.gainers.length && !data.losers.length && !running

  return (
    <div className="bb-panel">
      {/* Header */}
      <div className="px-4 py-2 border-b border-bloomberg-border flex items-center justify-between gap-3 flex-wrap">
        <div>
          <span className="text-bloomberg-amber font-mono font-bold text-xs tracking-widest">
            TOP PERFORMERS SEMANALES
          </span>
          <span className="text-bloomberg-text-muted text-2xs ml-3">
            {data.n_tickers > 0
              ? `${data.n_tickers} DE ${data.n_universe} EMPRESAS · CIERRE ${data.as_of ?? '—'}`
              : 'UNIVERSO SIN CALCULAR'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {[10, 15, 25].map(n => (
            <button
              key={n}
              onClick={() => setLimit(n)}
              className={`
                px-2 py-0.5 font-mono text-2xs border transition-all duration-200
                ${limit === n
                  ? 'border-bloomberg-amber text-bloomberg-amber bg-bloomberg-amber bg-opacity-10'
                  : 'border-transparent text-bloomberg-text-muted hover:text-bloomberg-amber hover:border-bloomberg-border'}
              `}
            >
              TOP {n}
            </button>
          ))}
          <button
            onClick={triggerRefresh}
            disabled={running || refreshing}
            className="px-3 py-1 border border-bloomberg-electric text-bloomberg-electric font-mono text-2xs hover:bg-bloomberg-electric hover:text-black transition-colors disabled:opacity-40"
          >
            {running ? 'CALCULANDO...' : '↻ RECALCULAR'}
          </button>
        </div>
      </div>

      {/* Progreso del job */}
      {running && (
        <div className="px-4 py-2 border-b border-bloomberg-border">
          <div className="flex items-center justify-between text-2xs font-mono text-bloomberg-text-muted mb-1">
            <span className="animate-pulse">
              DESCARGANDO PRECIOS — {data.status.done} / {data.status.total} TICKERS
            </span>
            <span className="text-bloomberg-amber">{data.status.progress_pct.toFixed(0)}%</span>
          </div>
          <div className="h-1 w-full bg-black">
            <div
              className="h-full bg-bloomberg-amber transition-all duration-500"
              style={{ width: `${data.status.progress_pct}%` }}
            />
          </div>
        </div>
      )}

      {data.status.error && (
        <div className="px-4 py-2 border-b border-bloomberg-border text-bloomberg-red text-2xs font-mono">
          ⚠ Último cálculo con error: {data.status.error}
        </div>
      )}

      {noData ? (
        <div className="p-6 text-center space-y-3">
          <div className="text-bloomberg-text-muted text-2xs font-mono">
            Todavía no se ha calculado el rendimiento del universo.
          </div>
          <button
            onClick={triggerRefresh}
            className="px-4 py-2 border border-bloomberg-amber text-bloomberg-amber font-mono text-2xs hover:bg-bloomberg-amber hover:text-black transition-colors"
          >
            CALCULAR AHORA
          </button>
          <div className="text-bloomberg-text-muted" style={{ fontSize: '8px' }}>
            Tarda unos minutos: descarga precios de ~2300 empresas en tandas.
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-px bg-bloomberg-border">
          <div className="bg-bloomberg-bg">
            <MoversTable rows={data.gainers} title="▲ MEJORES DE LA SEMANA" accent="green" onAnalyze={onAnalyze} />
          </div>
          <div className="bg-bloomberg-bg">
            <MoversTable rows={data.losers} title="▼ PEORES DE LA SEMANA" accent="red" onAnalyze={onAnalyze} />
          </div>
        </div>
      )}

      {/* Pie */}
      <div className="px-4 py-2 border-t border-bloomberg-border text-2xs font-mono text-bloomberg-text-muted">
        Semana = 5 sesiones de bolsa (no 7 días naturales, para que un festivo no falsee la ventana).
        MoS es el margen de seguridad del último escaneo del screener: un valor que sube fuerte y
        sigue con MoS alto es la combinación interesante. Último cálculo: {fmtWhen(data.last_run)}.
        {onAnalyze && ' Haz clic en una fila para analizarla.'}
      </div>
    </div>
  )
}
