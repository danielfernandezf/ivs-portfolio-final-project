import { useState, useCallback, useEffect, useRef } from 'react'
import WeeklyMovers from './WeeklyMovers'

// ── Types ─────────────────────────────────────────────────────────────────────
interface ScreenerRow {
  ticker: string
  company_name: string
  sector: string
  currency: string
  current_price: number
  intrinsic_price: number
  mos_pct: number
  upside_pct: number
  expected_return_pct: number
  hurdle_rate_pct: number
  clears_hurdle: boolean
  beta: number
  wacc_pct: number | null
  market_cap: number
  verdict: string
  key_risk: string
  // Enrutado por tipo de empresa + control de calidad de datos
  model?: string
  confidence?: number
  confidence_label?: string
  flags?: string[]
  financial_currency?: string
  fx_rate?: number
}

interface ScanStatus {
  running: boolean
  total: number
  done: number
  current: string | null
  started_at: string | null
  progress_pct: number
  rate_limited?: boolean
}

interface UniverseRefresh {
  running: boolean
  found: number
  error: string | null
  finished_at: string | null
}

interface ScreenerResponse {
  status: ScanStatus
  results: ScreenerRow[]
  errors: { ticker: string; error: string }[]
  last_scan: string | null
  universe_size: number
  universe_refresh?: UniverseRefresh
}

// Cap how many chips / table rows we render so a ~2300-name universe doesn't
// freeze the DOM.
const MAX_CHIPS = 400
const MAX_ROWS = 300

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtLarge(n: number) {
  const abs = Math.abs(n)
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(n / 1e6).toFixed(0)}M`
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(0)
}
function pct(n: number, d = 1) { return `${n >= 0 ? '+' : ''}${n.toFixed(d)}%` }
function mosColor(mos: number) {
  if (mos > 20) return 'text-bloomberg-green'
  if (mos > 0) return 'text-bloomberg-amber'
  return 'text-bloomberg-red'
}
function verdictBadge(v: string) {
  if (v === 'STRONG BUY') return 'text-bloomberg-green border-bloomberg-green'
  if (v.startsWith('HOLD')) return 'text-bloomberg-amber border-bloomberg-amber'
  return 'text-bloomberg-red border-bloomberg-red'
}
// Etiqueta corta y legible del modelo de valoración aplicado a cada empresa.
function modelLabel(m?: string): { text: string; title: string } {
  switch (m) {
    case 'EXCESS_RETURN':
      return { text: 'BANCO', title: 'Modelo de Exceso de Retorno sobre fondos propios (banca / seguros)' }
    case 'REIT_AFFO':
      return { text: 'REIT', title: 'Modelo AFFO (fondos de operaciones ajustados) para inmobiliario cotizado' }
    case 'DCF':
    default:
      return { text: 'DCF', title: 'Descuento de flujos de caja libres a WACC' }
  }
}
function confColor(label?: string) {
  if (label === 'ALTA') return 'text-bloomberg-green'
  if (label === 'MEDIA') return 'text-bloomberg-amber'
  return 'text-bloomberg-red'
}
function timeAgo(iso: string | null): string {
  if (!iso) return 'nunca'
  const then = new Date(iso).getTime()
  const mins = Math.floor((Date.now() - then) / 60000)
  if (mins < 1) return 'hace segundos'
  if (mins < 60) return `hace ${mins} min`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `hace ${hrs} h`
  return `hace ${Math.floor(hrs / 24)} d`
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function ScreenerTab({ onAnalyze }: { onAnalyze: (ticker: string) => void }) {
  const [data, setData] = useState<ScreenerResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [minMos, setMinMos] = useState<number>(-999)
  const [strongOnly, setStrongOnly] = useState(false)
  const [showUniverse, setShowUniverse] = useState(false)
  const [universe, setUniverse] = useState<string[]>([])
  const [newTicker, setNewTicker] = useState('')
  const pollRef = useRef<number | null>(null)

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/screener/status')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json: ScreenerResponse = await res.json()
      setData(json)
      setError(null)
      return json
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return null
    }
  }, [])

  const fetchUniverse = useCallback(async () => {
    try {
      const res = await fetch('/api/screener/universe')
      const json = await res.json()
      setUniverse(json.tickers ?? [])
    } catch { /* noop */ }
  }, [])

  // Initial load + universe
  useEffect(() => {
    fetchStatus()
    fetchUniverse()
  }, [fetchStatus, fetchUniverse])

  // Poll while a scan OR a universe refresh is running
  const busy = (data?.status.running ?? false) || (data?.universe_refresh?.running ?? false)
  useEffect(() => {
    if (busy && pollRef.current === null) {
      pollRef.current = window.setInterval(() => {
        fetchStatus().then(j => { if (j && !j.universe_refresh?.running) fetchUniverse() })
      }, 1500)
    }
    if (!busy && pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [busy, fetchStatus, fetchUniverse])

  const startScan = useCallback(async (fresh = false) => {
    try {
      await fetch(`/api/screener/scan${fresh ? '?fresh=true' : ''}`, { method: 'POST' })
      await fetchStatus()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [fetchStatus])

  const refreshUniverse = useCallback(async () => {
    if (!window.confirm(
      'Reconstruir el universo descargando TODOS los small/mid caps USA ($300M–$10B) ' +
      'de Yahoo Finance (~2300 acciones). Tarda ~1 min. ¿Continuar?'
    )) return
    try {
      await fetch('/api/screener/universe/refresh', { method: 'POST' })
      await fetchStatus()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [fetchStatus])

  const addTicker = useCallback(async () => {
    const t = newTicker.toUpperCase().trim()
    if (!t) return
    const res = await fetch('/api/screener/universe/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker: t }),
    })
    const json = await res.json()
    setUniverse(json.tickers ?? [])
    setNewTicker('')
  }, [newTicker])

  const removeTicker = useCallback(async (t: string) => {
    const res = await fetch('/api/screener/universe/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker: t }),
    })
    const json = await res.json()
    setUniverse(json.tickers ?? [])
  }, [])

  const status = data?.status
  const running = status?.running ?? false
  const refreshing = data?.universe_refresh?.running ?? false

  let rows = data?.results ?? []
  rows = rows.filter(r => r.mos_pct >= minMos)
  if (strongOnly) rows = rows.filter(r => r.verdict === 'STRONG BUY')
  const visibleRows = rows.slice(0, MAX_ROWS)

  const strongCount = (data?.results ?? []).filter(r => r.verdict === 'STRONG BUY').length

  return (
    <div className="p-3 space-y-3">
      {/* Mejores y peores de la semana en todo el universo rastreado */}
      <WeeklyMovers onAnalyze={onAnalyze} />

      {/* Header / controls */}
      <div className="bb-panel p-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <span className="text-bloomberg-amber font-mono font-bold text-sm tracking-widest">
              SCREENER · MARGEN DE SEGURIDAD
            </span>
            <div className="text-bloomberg-text-muted text-2xs mt-1">
              Small/Mid Caps USA · modelo según tipo de empresa (DCF · Banca · REIT) · rankeadas por convicción · último escaneo: {timeAgo(data?.last_scan ?? null)}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowUniverse(v => !v)}
              className="px-3 py-1.5 border border-bloomberg-border text-bloomberg-text-secondary font-mono text-xs hover:border-bloomberg-amber hover:text-bloomberg-amber transition-colors"
            >
              ⚙ UNIVERSO ({data?.universe_size ?? universe.length})
            </button>
            <button
              onClick={refreshUniverse}
              disabled={busy}
              title="Descargar todos los small/mid caps USA de Yahoo ($300M–$10B)"
              className="px-3 py-1.5 border border-bloomberg-border text-bloomberg-text-secondary font-mono text-xs hover:border-bloomberg-electric hover:text-bloomberg-electric transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {refreshing ? '⟳ DESCARGANDO...' : '↻ REFRESCAR UNIVERSO'}
            </button>
            <button
              onClick={() => startScan(false)}
              disabled={busy}
              className="px-4 py-1.5 border border-bloomberg-amber text-bloomberg-amber font-mono text-xs hover:bg-bloomberg-amber hover:text-black transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {running ? '⟳ ESCANEANDO...' : '▶ ESCANEAR LIVE'}
            </button>
          </div>
        </div>

        {/* Universe refresh progress */}
        {refreshing && (
          <div className="mt-3 text-2xs font-mono text-bloomberg-electric">
            ↻ Descargando universo de Yahoo… {data?.universe_refresh?.found ?? 0} acciones encontradas
          </div>
        )}
        {data?.universe_refresh?.error && !refreshing && (
          <div className="mt-3 text-2xs font-mono text-bloomberg-red">
            ⚠ Error al refrescar universo: {data.universe_refresh.error}
          </div>
        )}

        {/* Scan progress bar */}
        {running && status && (
          <div className="mt-3">
            <div className="flex justify-between text-2xs font-mono text-bloomberg-text-muted mb-1">
              <span>
                Valorando {status.current ?? '...'} · {status.done}/{status.total}
                {status.rate_limited && (
                  <span className="text-bloomberg-amber ml-2 animate-pulse">
                    · ⏳ Yahoo limita peticiones, esperando…
                  </span>
                )}
              </span>
              <span>{status.progress_pct.toFixed(0)}%</span>
            </div>
            <div className="h-2 bg-black border border-bloomberg-border overflow-hidden">
              <div
                className="h-full bg-bloomberg-amber transition-all duration-500"
                style={{ width: `${status.progress_pct}%` }}
              />
            </div>
            <div className="text-2xs font-mono text-bloomberg-text-muted mt-1">
              Escaneo de ~{status.total} acciones · se guarda el progreso automáticamente y
              puedes cerrar la web: continúa en segundo plano.
            </div>
          </div>
        )}

        {/* Summary cards */}
        {data && (data.results.length > 0) && (
          <div className="grid grid-cols-4 gap-3 mt-4">
            <StatCard label="VALORADAS" value={String(data.results.length)} color="text-bloomberg-electric" />
            <StatCard label="STRONG BUY" value={String(strongCount)} color="text-bloomberg-green" />
            <StatCard
              label="MEJOR MoS"
              value={data.results.length ? pct(Math.max(...data.results.map(r => r.mos_pct))) : '—'}
              color="text-bloomberg-green"
            />
            <StatCard label="ERRORES" value={String(data.errors.length)} color="text-bloomberg-text-muted" />
          </div>
        )}
      </div>

      {/* Universe editor */}
      {showUniverse && (
        <div className="bb-panel p-4">
          <div className="text-bloomberg-electric text-2xs tracking-widest mb-3">UNIVERSO DE BÚSQUEDA (EDITABLE)</div>
          <div className="flex gap-2 mb-3">
            <input
              value={newTicker}
              onChange={e => setNewTicker(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') addTicker() }}
              placeholder="Añadir ticker (p.ej. NVDA)"
              className="bg-black border border-bloomberg-border px-3 py-1.5 text-xs font-mono text-bloomberg-text-primary focus:border-bloomberg-amber outline-none flex-1 max-w-xs"
            />
            <button onClick={addTicker} className="px-3 py-1.5 border border-bloomberg-green text-bloomberg-green font-mono text-xs hover:bg-bloomberg-green hover:text-black transition-colors">
              + AÑADIR
            </button>
          </div>
          <div className="text-bloomberg-text-muted text-2xs mb-2">
            {universe.length} tickers en el universo
            {universe.length > MAX_CHIPS && ` · mostrando los primeros ${MAX_CHIPS}`}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {universe.slice(0, MAX_CHIPS).map(t => (
              <span key={t} className="inline-flex items-center gap-1 border border-bloomberg-border px-2 py-0.5 text-2xs font-mono text-bloomberg-text-secondary">
                {t}
                <button onClick={() => removeTicker(t)} className="text-bloomberg-red hover:text-bloomberg-amber ml-0.5" title="Quitar">×</button>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      {data && data.results.length > 0 && (
        <div className="bb-panel px-4 py-2 flex items-center gap-4 flex-wrap text-2xs font-mono text-bloomberg-text-muted">
          <label className="flex items-center gap-2">
            MoS mínimo:
            <select
              value={minMos}
              onChange={e => setMinMos(Number(e.target.value))}
              className="bg-black border border-bloomberg-border px-2 py-1 text-bloomberg-text-primary outline-none focus:border-bloomberg-amber"
            >
              <option value={-999}>Todos</option>
              <option value={0}>&gt; 0%</option>
              <option value={20}>&gt; 20% (Strong)</option>
              <option value={35}>&gt; 35%</option>
            </select>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={strongOnly} onChange={e => setStrongOnly(e.target.checked)} />
            Solo STRONG BUY
          </label>
          <button
            onClick={() => startScan(true)}
            disabled={busy}
            title="Re-valorar todo el universo desde cero con los precios actuales"
            className="text-bloomberg-text-muted hover:text-bloomberg-amber disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ↻ re-escanear desde cero
          </button>
          <span className="ml-auto">
            {rows.length} resultados{rows.length > MAX_ROWS && ` · mostrando top ${MAX_ROWS}`}
          </span>
        </div>
      )}

      {error && (
        <div className="bb-panel p-4 text-bloomberg-red text-xs font-mono">
          ⚠ ERROR: {error}
          <button onClick={fetchStatus} className="ml-4 text-bloomberg-amber hover:underline">↺ reintentar</button>
        </div>
      )}

      {/* Empty state */}
      {data && data.results.length === 0 && !running && (
        <div className="bb-panel p-8 text-center">
          <div className="text-bloomberg-text-muted text-sm font-mono mb-2">SIN RESULTADOS TODAVÍA</div>
          <div className="text-bloomberg-text-muted text-2xs mb-4">
            Pulsa <span className="text-bloomberg-amber">▶ ESCANEAR LIVE</span> para valorar el universo y rankear por Margen de Seguridad.
          </div>
        </div>
      )}

      {/* Results table */}
      {rows.length > 0 && (
        <div className="bb-panel">
          <div className="px-4 py-2 border-b border-bloomberg-border">
            <span className="text-bloomberg-electric text-2xs tracking-widest">
              RANKING POR MARGEN DE SEGURIDAD {running && <span className="text-bloomberg-amber animate-pulse ml-2">· actualizando en vivo</span>}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-bloomberg-border text-bloomberg-text-muted text-2xs">
                  <th className="text-left px-3 py-2">#</th>
                  <th className="text-left px-3 py-2">TICKER</th>
                  <th className="text-center px-3 py-2">MODELO</th>
                  <th className="text-right px-3 py-2">PRECIO</th>
                  <th className="text-right px-3 py-2">INTRÍNSECO</th>
                  <th className="text-right px-3 py-2">MoS</th>
                  <th className="text-center px-3 py-2">CONFIANZA</th>
                  <th className="text-right px-3 py-2">β</th>
                  <th className="text-right px-3 py-2">MCAP</th>
                  <th className="text-center px-3 py-2">VEREDICTO</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody className="stagger-children">
                {visibleRows.map((r, i) => (
                  <tr
                    key={r.ticker}
                    className="border-b border-bloomberg-border border-opacity-30 hover:bg-bloomberg-panel transition-all duration-200 hover:shadow-[inset_2px_0_0_#f5a623] cursor-pointer"
                    onClick={() => onAnalyze(r.ticker)}
                    title={r.key_risk}
                  >
                    <td className="px-3 py-2 text-bloomberg-text-muted">{i + 1}</td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        <span className="text-bloomberg-amber font-bold">{r.ticker}</span>
                        {r.financial_currency && r.financial_currency !== r.currency && (
                          <span
                            className="text-bloomberg-electric text-2xs border border-bloomberg-electric px-1 rounded-sm"
                            title={`Cuentas en ${r.financial_currency}, cotiza en ${r.currency} — convertido a ${r.currency}`}
                          >FX</span>
                        )}
                      </div>
                      <div className="text-bloomberg-text-muted text-2xs truncate max-w-[150px]">{r.company_name}</div>
                    </td>
                    <td className="text-center px-3 py-2">
                      {(() => { const m = modelLabel(r.model); return (
                        <span className="text-bloomberg-text-secondary text-2xs border border-bloomberg-border px-1.5 py-0.5" title={m.title}>{m.text}</span>
                      )})()}
                    </td>
                    <td className="text-right px-3 py-2 text-bloomberg-text-secondary">{r.current_price.toFixed(2)}</td>
                    <td className="text-right px-3 py-2 text-bloomberg-electric">{r.intrinsic_price.toFixed(2)}</td>
                    <td className={`text-right px-3 py-2 font-bold ${mosColor(r.mos_pct)}`}>{pct(r.mos_pct)}</td>
                    <td className="text-center px-3 py-2" title={(r.flags && r.flags.length) ? r.flags.join('\n') : 'Sin señales de alarma en la calidad de datos'}>
                      {r.confidence != null ? (
                        <span className={`text-2xs font-bold ${confColor(r.confidence_label)}`}>
                          {r.confidence_label ?? ''} {(r.flags && r.flags.length > 0) ? '⚠' : ''}
                        </span>
                      ) : <span className="text-bloomberg-text-muted text-2xs">—</span>}
                    </td>
                    <td className="text-right px-3 py-2 text-bloomberg-text-secondary">{r.beta.toFixed(2)}</td>
                    <td className="text-right px-3 py-2 text-bloomberg-text-muted">{fmtLarge(r.market_cap)}</td>
                    <td className="text-center px-3 py-2">
                      <span className={`inline-block border px-2 py-0.5 text-2xs ${verdictBadge(r.verdict)}`}>
                        {r.verdict}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span className="text-bloomberg-electric text-2xs hover:underline">analizar →</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-2 border-t border-bloomberg-border flex gap-4 text-2xs text-bloomberg-text-muted flex-wrap">
            <span><span className="text-bloomberg-green">■</span> MoS &gt; 20% — infravalorada</span>
            <span><span className="text-bloomberg-amber">■</span> MoS 0-20% — vigilar</span>
            <span><span className="text-bloomberg-red">■</span> MoS &lt; 0% — cara</span>
            <span className="ml-auto">Click en una fila para abrir el análisis DCF completo</span>
          </div>
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-black border border-bloomberg-border p-3">
      <div className="bb-label mb-1">{label}</div>
      <div className={`font-mono font-bold text-base ${color}`}>{value}</div>
    </div>
  )
}
