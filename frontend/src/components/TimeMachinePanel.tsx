import { useState, useCallback, useEffect, useMemo } from 'react'
import { AsOfResponse } from '../types/valuation'

type State =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; data: AsOfResponse }
  | { status: 'error'; message: string }

/** Ventana de comparación, en sesiones de bolsa. */
const MODES = [
  { sessions: 1, label: 'DÍA', hint: 'vs sesión anterior' },
  { sessions: 5, label: 'SEMANA', hint: 'vs hace 5 sesiones' },
  { sessions: 21, label: 'MES', hint: 'vs hace 21 sesiones' },
]

function fmtLarge(n: number) {
  const abs = Math.abs(n)
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(2)
}

function pct(n: number | null, d = 2) {
  if (n === null || n === undefined) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(d)}%`
}

function retColor(n: number | null) {
  if (n === null || n === undefined) return 'text-bloomberg-text-muted'
  return n >= 0 ? 'text-bloomberg-green' : 'text-bloomberg-red'
}

function todayISO() {
  return new Date().toISOString().slice(0, 10)
}

export default function TimeMachinePanel() {
  const [date, setDate] = useState<string>(todayISO())
  const [sessions, setSessions] = useState(5)
  const [state, setState] = useState<State>({ status: 'idle' })

  const load = useCallback(async (d: string, s: number) => {
    setState({ status: 'loading' })
    try {
      const res = await fetch(`/api/portfolio/as-of?date=${d}&compare_sessions=${s}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: AsOfResponse = await res.json()
      setState({ status: 'loaded', data })
    } catch (e) {
      setState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }, [])

  useEffect(() => { load(date, sessions) }, [date, sessions, load])

  const data = state.status === 'loaded' ? state.data : null

  // El slider recorre SESIONES de bolsa, no días naturales: así cada paso mueve
  // a un día con datos y no se atasca en sábados y domingos.
  const tradingDays = useMemo(() => data?.trading_days ?? [], [data])
  const sliderIdx = useMemo(() => {
    if (!tradingDays.length || !data) return 0
    const i = tradingDays.indexOf(data.date)
    return i >= 0 ? i : tradingDays.length - 1
  }, [tradingDays, data])

  const onSlider = (idx: number) => {
    if (tradingDays[idx]) setDate(tradingDays[idx])
  }

  const step = (delta: number) => {
    const next = sliderIdx + delta
    if (next >= 0 && next < tradingDays.length) setDate(tradingDays[next])
  }

  const modeHint = MODES.find(m => m.sessions === sessions)?.hint ?? ''
  const staleCount = data?.positions.filter(p => p.stale_price).length ?? 0

  return (
    <div className="bb-panel">
      {/* Header + controles */}
      <div className="px-4 py-2 border-b border-bloomberg-border">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
          <div>
            <span className="text-bloomberg-amber font-mono font-bold text-xs tracking-widest">
              MÁQUINA DEL TIEMPO
            </span>
            <span className="text-bloomberg-text-muted text-2xs ml-3">
              Cómo estaba la cartera en una fecha concreta
            </span>
          </div>

          <div className="flex items-center gap-2">
            {MODES.map(m => (
              <button
                key={m.sessions}
                onClick={() => setSessions(m.sessions)}
                title={m.hint}
                className={`
                  px-2 py-0.5 font-mono text-2xs border transition-all duration-200
                  ${sessions === m.sessions
                    ? 'border-bloomberg-amber text-bloomberg-amber bg-bloomberg-amber bg-opacity-10'
                    : 'border-transparent text-bloomberg-text-muted hover:text-bloomberg-amber hover:border-bloomberg-border'}
                `}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        {/* Selector de fecha */}
        <div className="flex items-center gap-3 flex-wrap">
          <input
            type="date"
            value={date}
            min={data?.available_from ?? undefined}
            max={data?.available_to ?? undefined}
            onChange={e => e.target.value && setDate(e.target.value)}
            className="bg-black border border-bloomberg-border text-bloomberg-amber font-mono text-2xs px-2 py-1 focus:border-bloomberg-amber outline-none"
          />
          <button
            onClick={() => step(-1)}
            disabled={sliderIdx <= 0}
            className="px-2 py-1 border border-bloomberg-border text-bloomberg-text-muted font-mono text-2xs hover:text-bloomberg-amber hover:border-bloomberg-amber transition-colors disabled:opacity-30"
          >
            ◀ SESIÓN
          </button>
          <button
            onClick={() => step(1)}
            disabled={sliderIdx >= tradingDays.length - 1}
            className="px-2 py-1 border border-bloomberg-border text-bloomberg-text-muted font-mono text-2xs hover:text-bloomberg-amber hover:border-bloomberg-amber transition-colors disabled:opacity-30"
          >
            SESIÓN ▶
          </button>
          <button
            onClick={() => setDate(todayISO())}
            className="px-2 py-1 border border-bloomberg-electric text-bloomberg-electric font-mono text-2xs hover:bg-bloomberg-electric hover:text-black transition-colors"
          >
            HOY
          </button>

          {tradingDays.length > 1 && (
            <div className="flex-1 min-w-[180px] flex items-center gap-2">
              <input
                type="range"
                min={0}
                max={tradingDays.length - 1}
                value={sliderIdx}
                onChange={e => onSlider(Number(e.target.value))}
                className="flex-1 accent-amber-500"
              />
              <span className="text-bloomberg-text-muted font-mono" style={{ fontSize: '8px' }}>
                {tradingDays.length} sesiones
              </span>
            </div>
          )}
        </div>

        {/* Aviso cuando la fecha pedida no fue día de bolsa */}
        {data && data.is_trading_day === false && (
          <div className="mt-2 text-2xs font-mono text-bloomberg-amber">
            {data.requested_date} no fue día de bolsa — se muestra el cierre del {data.date}.
          </div>
        )}
      </div>

      {state.status === 'loading' && (
        <div className="px-4 py-6 flex items-center gap-3 text-2xs font-mono text-bloomberg-text-muted">
          <div className="animate-pulse">RECONSTRUYENDO CARTERA...</div>
        </div>
      )}

      {state.status === 'error' && (
        <div className="p-3 text-bloomberg-red text-2xs font-mono">
          ⚠ {state.message}
          <button onClick={() => load(date, sessions)} className="ml-3 text-bloomberg-amber hover:underline">
            ↺ reintentar
          </button>
        </div>
      )}

      {data && data.message && (
        <div className="p-6 text-center text-bloomberg-text-muted text-2xs font-mono">
          {data.message}
        </div>
      )}

      {data && !data.message && (
        <>
          {/* Tarjetas resumen */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-4 border-b border-bloomberg-border">
            <div className="bg-black border border-bloomberg-border p-3">
              <div className="bb-label mb-1">VALOR AL CIERRE</div>
              <div className="font-mono font-bold text-base text-[#39ff14]">
                {fmtLarge(data.total_value)}€
              </div>
              <div className="text-bloomberg-text-muted" style={{ fontSize: '8px' }}>{data.date}</div>
            </div>
            <div className="bg-black border border-bloomberg-border p-3">
              <div className="bb-label mb-1">RETORNO ACUMULADO</div>
              <div className={`font-mono font-bold text-base ${retColor(data.return_pct)}`}>
                {pct(data.return_pct)}
              </div>
              <div className="text-bloomberg-text-muted" style={{ fontSize: '8px' }}>
                sobre {fmtLarge(data.capital_at_date)}€
              </div>
            </div>
            <div className="bg-black border border-bloomberg-border p-3">
              <div className="bb-label mb-1">VARIACIÓN {MODES.find(m => m.sessions === sessions)?.label}</div>
              <div className={`font-mono font-bold text-base ${retColor(data.period_change_pct)}`}>
                {pct(data.period_change_pct)}
              </div>
              <div className="text-bloomberg-text-muted" style={{ fontSize: '8px' }}>
                {data.comparison_date ? `${modeHint} (${data.comparison_date})` : 'sin histórico bastante'}
              </div>
            </div>
            <div className="bg-black border border-bloomberg-border p-3">
              <div className="bb-label mb-1">POSICIONES / EFECTIVO</div>
              <div className="font-mono font-bold text-base text-bloomberg-amber">
                {data.positions.length}
              </div>
              <div className="text-bloomberg-text-muted" style={{ fontSize: '8px' }}>
                {fmtLarge(data.cash)}€ en efectivo
              </div>
            </div>
          </div>

          {staleCount > 0 && (
            <div className="px-4 py-2 border-b border-bloomberg-border text-bloomberg-amber text-2xs font-mono">
              ⚠ {staleCount} posición(es) sin cotización en esa fecha — se usa el precio de compra.
            </div>
          )}

          {/* Detalle por posición */}
          <div className="overflow-x-auto">
            <table className="w-full text-2xs font-mono">
              <thead>
                <tr className="text-bloomberg-text-muted border-b border-bloomberg-border">
                  <th className="text-left px-4 py-2">TICKER</th>
                  <th className="text-right px-2 py-2">ACCIONES</th>
                  <th className="text-right px-2 py-2">P.COMPRA</th>
                  <th className="text-right px-2 py-2">P. EN FECHA</th>
                  <th className="text-right px-2 py-2">VALOR</th>
                  <th className="text-right px-2 py-2">PESO</th>
                  <th className="text-right px-2 py-2">VAR. {MODES.find(m => m.sessions === sessions)?.label}</th>
                  <th className="text-right px-4 py-2">DESDE COMPRA</th>
                </tr>
              </thead>
              <tbody>
                {data.positions.map(p => (
                  <tr
                    key={p.ticker}
                    className="border-b border-bloomberg-border border-opacity-30 hover:bg-bloomberg-panel transition-colors"
                  >
                    <td className="px-4 py-1.5">
                      <div className="text-bloomberg-amber font-bold">{p.ticker}</div>
                      <div className="text-bloomberg-text-muted truncate max-w-[140px]" style={{ fontSize: '8px' }}>
                        {p.company_name}
                      </div>
                    </td>
                    <td className="text-right px-2 py-1.5 text-bloomberg-text-primary">{p.shares.toFixed(0)}</td>
                    <td className="text-right px-2 py-1.5 text-bloomberg-text-secondary">
                      ${p.purchase_price.toFixed(2)}
                    </td>
                    <td className={`text-right px-2 py-1.5 ${p.stale_price ? 'text-bloomberg-amber' : 'text-bloomberg-electric'}`}>
                      ${p.price_at_date.toFixed(2)}{p.stale_price && '*'}
                    </td>
                    <td className="text-right px-2 py-1.5 text-bloomberg-text-primary">
                      {fmtLarge(p.market_value)}€
                    </td>
                    <td className="text-right px-2 py-1.5 text-bloomberg-text-secondary">
                      {p.weight_pct.toFixed(1)}%
                    </td>
                    <td className={`text-right px-2 py-1.5 ${retColor(p.period_pct)}`}>
                      {pct(p.period_pct, 1)}
                    </td>
                    <td className={`text-right px-4 py-1.5 font-bold ${retColor(p.return_pct)}`}>
                      {pct(p.return_pct, 1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pie con la limitación honesta del modelo */}
          <div className="px-4 py-2 border-t border-bloomberg-border text-2xs font-mono text-bloomberg-text-muted">
            Reconstruido con precios de cierre reales aplicados a las posiciones que tienes HOY.
            La base de datos no guarda un libro de operaciones, así que si vendiste algo no aparece
            en el pasado: esto responde a «cuánto valía lo que tengo» en esa fecha, no a «qué tenía
            exactamente» aquel día.
          </div>
        </>
      )}
    </div>
  )
}
