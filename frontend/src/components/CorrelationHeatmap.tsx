import { CorrelationMatrix } from '../types/valuation'

interface Props {
  data: CorrelationMatrix
}

/**
 * Interpolate a cell background colour based on Pearson correlation.
 *   -1.0 → deep blue  (anti-correlated — ideal hedge)
 *    0.0 → near-black (Bloomberg dark bg — uncorrelated)
 *   +1.0 → bright red (perfectly correlated — max risk concentration)
 */
function corrBg(corr: number): string {
  const c = Math.max(-1, Math.min(1, corr))
  if (c >= 0) {
    // 0 → #0D1117 (near-black), 1 → #D32F2F (bright red)
    const r = Math.round(c * 211 + (1 - c) * 13)
    const g = Math.round((1 - c) * 17)
    const b = Math.round((1 - c) * 23)
    return `rgb(${r},${g},${b})`
  } else {
    // 0 → #0D1117 (near-black), -1 → #1565C0 (deep blue)
    const abs = Math.abs(c)
    const r = Math.round((1 - abs) * 13)
    const g = Math.round(abs * 79 + (1 - abs) * 17)
    const b = Math.round(abs * 192 + (1 - abs) * 23)
    return `rgb(${r},${g},${b})`
  }
}

function corrTextColor(corr: number): string {
  const abs = Math.abs(corr)
  if (abs > 0.6) return '#ffffff'
  if (abs > 0.3) return '#d0d8e4'
  return '#6b7685'
}

function corrLabel(corr: number): string {
  if (corr >= 0.75) return 'ALTO RIESGO'
  if (corr >= 0.5) return 'MODERADO'
  if (corr >= 0.25) return 'BAJO'
  if (corr >= 0) return 'MÍN'
  if (corr >= -0.25) return 'DIV'
  return 'COBERTURA'
}

export default function CorrelationHeatmap({ data }: Props) {
  const { tickers, matrix, warnings, n_observations } = data
  const missing = data.missing_tickers ?? []

  if (tickers.length < 2) {
    return (
      <div className="bb-panel p-6 text-center">
        <div className="text-bloomberg-text-muted text-2xs font-mono">
          MATRIZ DE CORRELACIÓN — Se necesitan ≥ 2 posiciones para calcular correlación.
        </div>
      </div>
    )
  }

  return (
    <div className="bb-panel">
      {/* Header */}
      <div className="px-4 py-2 border-b border-bloomberg-border flex items-center justify-between">
        <div>
          <span className="text-bloomberg-amber font-mono font-bold text-xs tracking-widest">
            CORRELATION MATRIX
          </span>
          <span className="text-bloomberg-text-muted text-2xs ml-3">
            PEARSON · ÚLTIMOS 2 AÑOS · {n_observations} OBSERVACIONES ·{' '}
            {tickers.length + missing.length > 0 && (
              <span className={missing.length > 0 ? 'text-bloomberg-red' : undefined}>
                {tickers.length} DE {tickers.length + missing.length} POSICIONES
              </span>
            )}
          </span>
        </div>
        <div className="flex items-center gap-3 text-2xs font-mono text-bloomberg-text-muted">
          <span><span style={{ color: '#1565C0' }}>■</span> Cobertura (−1)</span>
          <span><span style={{ color: '#444' }}>■</span> Neutro (0)</span>
          <span><span style={{ color: '#D32F2F' }}>■</span> Riesgo (+1)</span>
        </div>
      </div>

      {/* Posiciones fuera de la matriz por falta de histórico */}
      {missing.length > 0 && (
        <div className="px-4 py-2 border-b border-bloomberg-border">
          <div className="flex items-center gap-2 text-2xs font-mono bg-red-950 border border-bloomberg-red border-opacity-40 px-3 py-1.5">
            <span className="text-bloomberg-red">⚠</span>
            <span className="text-bloomberg-red font-bold">MATRIZ INCOMPLETA:</span>
            <span className="text-bloomberg-text-secondary">
              sin histórico para {missing.join(', ')} — {missing.length} de{' '}
              {tickers.length + missing.length} posiciones quedan fuera del cálculo
            </span>
            <span className="ml-auto text-bloomberg-text-muted">
              Suele ser un fallo temporal de la descarga: recarga la pestaña
            </span>
          </div>
        </div>
      )}

      {/* High-correlation warnings */}
      {warnings.length > 0 && (
        <div className="px-4 py-2 border-b border-bloomberg-border space-y-1">
          {warnings.map(w => (
            <div key={`${w.ticker1}-${w.ticker2}`}
              className="flex items-center gap-2 text-2xs font-mono bg-red-950 border border-bloomberg-red border-opacity-40 px-3 py-1.5">
              <span className="text-bloomberg-red">⚠</span>
              <span className="text-bloomberg-red font-bold">RIESGO DE CONCENTRACIÓN:</span>
              <span className="text-bloomberg-text-secondary">
                {w.ticker1} ↔ {w.ticker2} — correlación {(w.correlation * 100).toFixed(1)}%
              </span>
              <span className="ml-auto text-bloomberg-red">
                Alta correlación sistémica — sin diversificación real
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Heatmap table */}
      <div className="overflow-x-auto p-3">
        <table className="font-mono text-2xs border-collapse">
          <thead>
            <tr>
              {/* Top-left corner cell */}
              <th className="w-20 min-w-[5rem]" />
              {tickers.map(col => (
                <th
                  key={col}
                  className="text-bloomberg-amber text-center pb-2 px-1 font-bold"
                  style={{ minWidth: '4.5rem' }}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tickers.map(row => (
              <tr key={row}>
                {/* Row label */}
                <td className="text-bloomberg-amber font-bold pr-3 py-0.5 text-right">
                  {row}
                </td>
                {tickers.map(col => {
                  const corr = matrix[row]?.[col] ?? 0
                  const isDiag = row === col
                  return (
                    <td
                      key={col}
                      style={{
                        backgroundColor: isDiag ? '#1a2030' : corrBg(corr),
                        color: isDiag ? '#FFB300' : corrTextColor(corr),
                        border: isDiag ? '1px solid #FFB30060' : '1px solid #1e2530',
                      }}
                      className="text-center py-2 px-1 transition-colors"
                    >
                      <div className="font-bold">
                        {isDiag ? '—' : corr.toFixed(2)}
                      </div>
                      {!isDiag && (
                        <div style={{ fontSize: '7px', opacity: 0.7, marginTop: '1px' }}>
                          {corrLabel(corr)}
                        </div>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend bar */}
      <div className="px-4 py-2 border-t border-bloomberg-border text-2xs font-mono text-bloomberg-text-muted">
        <div className="flex items-center gap-2 mb-1">
          <span>Escala de color:</span>
          {/* Gradient bar */}
          <div
            className="flex-1 h-3 rounded"
            style={{
              background: 'linear-gradient(to right, #1565C0, #0D1117, #D32F2F)',
              maxWidth: '200px',
            }}
          />
          <span className="text-bloomberg-text-secondary ml-1">−1.0 → 0 → +1.0</span>
        </div>
        <div>
          Umbral de alerta: correlación &gt; 0.75 — riesgo de concentración sistémica.
          Valores negativos implican cobertura natural de cartera.
        </div>
      </div>
    </div>
  )
}
