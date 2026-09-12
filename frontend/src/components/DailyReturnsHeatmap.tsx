import { useMemo, useState } from 'react'
import { DailyReturnsResponse } from '../types/valuation'

interface Props {
  data: DailyReturnsResponse
  onReload?: (days: number) => void
}

/**
 * Color de celda según el rendimiento diario, saturando en ±`scale` %.
 *
 * La escala es simétrica y se ancla al percentil 95 de la muestra, no a un ±3 %
 * fijo: en una semana tranquila un ±1 % ya pinta con fuerza, y en una de
 * resultados nadie se sale de la escala. La saturación fija aplanaba el mapa
 * justo cuando no pasaba nada, que es cuando más interesa ver el matiz.
 *   negativo → rojo   ·   ~0 → casi negro   ·   positivo → verde
 */
function returnBg(ret: number, scale: number): string {
  const t = Math.max(-1, Math.min(1, ret / scale))
  const a = Math.abs(t)
  if (t >= 0) {
    // 0 → #0D1117 · +1 → #2E9E4F (verde)
    const r = Math.round(a * 46 + (1 - a) * 13)
    const g = Math.round(a * 158 + (1 - a) * 17)
    const b = Math.round(a * 79 + (1 - a) * 23)
    return `rgb(${r},${g},${b})`
  }
  // 0 → #0D1117 · −1 → #C62828 (rojo)
  const r = Math.round(a * 198 + (1 - a) * 13)
  const g = Math.round(a * 40 + (1 - a) * 17)
  const b = Math.round(a * 40 + (1 - a) * 23)
  return `rgb(${r},${g},${b})`
}

function cellText(ret: number, scale: number): string {
  return Math.abs(ret) / scale > 0.45 ? '#ffffff' : '#7a8595'
}

function pct(n: number, d = 2) {
  return `${n >= 0 ? '+' : ''}${n.toFixed(d)}%`
}

function retColor(n: number) {
  return n >= 0 ? 'text-bloomberg-green' : 'text-bloomberg-red'
}

const RANGES = [
  { days: 14, label: '2S' },
  { days: 30, label: '1M' },
  { days: 90, label: '3M' },
]

export default function DailyReturnsHeatmap({ data, onReload }: Props) {
  const { tickers, dates, returns, stats } = data
  const [days, setDays] = useState(data.period_days ?? 30)

  // Percentil 95 de |rendimiento| como tope de la escala de color.
  const scale = useMemo(() => {
    const all: number[] = []
    for (const t of tickers) {
      for (const d of dates) {
        const v = returns[t]?.[d]
        if (v !== undefined) all.push(Math.abs(v))
      }
    }
    if (!all.length) return 3
    all.sort((a, b) => a - b)
    const p95 = all[Math.floor(all.length * 0.95)]
    // Suelo de 1 % para que un mercado plano no amplifique el ruido a colores chillones.
    return Math.max(p95, 1)
  }, [tickers, dates, returns])

  const changeRange = (d: number) => {
    setDays(d)
    onReload?.(d)
  }

  if (!tickers.length) {
    return (
      <div className="bb-panel p-6 text-center">
        <div className="text-bloomberg-text-muted text-2xs font-mono">
          RENDIMIENTOS DIARIOS — Sin datos de precios para las posiciones.
        </div>
      </div>
    )
  }

  return (
    <div className="bb-panel">
      {/* Header */}
      <div className="px-4 py-2 border-b border-bloomberg-border flex items-center justify-between gap-3 flex-wrap">
        <div>
          <span className="text-bloomberg-amber font-mono font-bold text-xs tracking-widest">
            RENDIMIENTOS DIARIOS
          </span>
          <span className="text-bloomberg-text-muted text-2xs ml-3">
            {dates.length} SESIONES · {tickers.length} POSICIONES
          </span>
        </div>
        <div className="flex items-center gap-1">
          {RANGES.map(r => (
            <button
              key={r.days}
              onClick={() => changeRange(r.days)}
              className={`
                px-2 py-0.5 font-mono text-2xs border transition-all duration-200
                ${days === r.days
                  ? 'border-bloomberg-amber text-bloomberg-amber bg-bloomberg-amber bg-opacity-10'
                  : 'border-transparent text-bloomberg-text-muted hover:text-bloomberg-amber hover:border-bloomberg-border'}
              `}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Heatmap */}
      <div className="overflow-x-auto p-3">
        <table className="font-mono text-2xs border-collapse">
          <thead>
            <tr>
              <th className="w-16 min-w-[4rem]" />
              {dates.map(d => (
                <th
                  key={d}
                  className="text-bloomberg-text-muted text-center pb-1 font-normal"
                  style={{ minWidth: '1.6rem', fontSize: '7px' }}
                  title={d}
                >
                  {/* Sólo el día del mes: la cabecera completa no cabe */}
                  {d.slice(8, 10)}
                </th>
              ))}
              <th className="text-bloomberg-amber text-right pl-3 pb-1" style={{ minWidth: '3.5rem' }}>
                ACUM
              </th>
              <th className="text-bloomberg-text-muted text-right pl-2 pb-1 font-normal" style={{ minWidth: '2.8rem' }}>
                % DÍAS+
              </th>
            </tr>
          </thead>
          <tbody>
            {tickers.map(t => {
              const st = stats[t]
              return (
                <tr key={t}>
                  <td className="text-bloomberg-amber font-bold pr-2 py-0.5 text-right">{t}</td>
                  {dates.map(d => {
                    const v = returns[t]?.[d]
                    if (v === undefined) {
                      // Sin dato ese día (p. ej. cotización suspendida): celda hueca,
                      // que no es lo mismo que un 0 %.
                      return (
                        <td
                          key={d}
                          className="text-center"
                          style={{ backgroundColor: '#0a0d12', border: '1px solid #141922' }}
                          title={`${t} · ${d} — sin dato`}
                        />
                      )
                    }
                    return (
                      <td
                        key={d}
                        style={{
                          backgroundColor: returnBg(v, scale),
                          color: cellText(v, scale),
                          border: '1px solid #141922',
                          fontSize: '7px',
                        }}
                        className="text-center py-1"
                        title={`${t} · ${d} · ${pct(v)}`}
                      >
                        {Math.abs(v) >= 1 ? v.toFixed(0) : ''}
                      </td>
                    )
                  })}
                  <td className={`text-right pl-3 font-bold ${st ? retColor(st.cumulative) : ''}`}>
                    {st ? pct(st.cumulative, 1) : '—'}
                  </td>
                  <td className="text-right pl-2 text-bloomberg-text-secondary">
                    {st ? `${st.win_rate.toFixed(0)}%` : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Leyenda */}
      <div className="px-4 py-2 border-t border-bloomberg-border text-2xs font-mono text-bloomberg-text-muted space-y-1">
        <div className="flex items-center gap-2">
          <span>Escala:</span>
          <div
            className="flex-1 h-3 rounded"
            style={{
              background: 'linear-gradient(to right, #C62828, #0D1117, #2E9E4F)',
              maxWidth: '180px',
            }}
          />
          <span className="text-bloomberg-text-secondary">
            −{scale.toFixed(1)}% → 0 → +{scale.toFixed(1)}%
          </span>
        </div>
        <div>
          Cada celda es una sesión; el número aparece a partir de ±1 %. Pasa el ratón
          para ver fecha y valor exactos. ACUM = rendimiento compuesto del período.
        </div>
      </div>
    </div>
  )
}
