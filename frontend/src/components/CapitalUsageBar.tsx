/**
 * CapitalUsageBar — Phase 6
 * Displays a 0-100% progress bar showing how much of the initial capital
 * has been deployed into positions.
 */

interface Props {
  usedPct: number           // % invested (0-100)
  cashPct: number           // % in cash (0-100)
  initialCapital: number    // e.g. 100000
  cashBalance: number
}

function barColor(pct: number) {
  if (pct < 70) return 'bg-bloomberg-green'
  if (pct < 90) return 'bg-bloomberg-amber'
  return 'bg-bloomberg-red'
}

function labelColor(pct: number) {
  if (pct < 70) return 'text-bloomberg-green'
  if (pct < 90) return 'text-bloomberg-amber'
  return 'text-bloomberg-red'
}

function fmtLarge(n: number) {
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(0)
}

export default function CapitalUsageBar({ usedPct, cashPct, initialCapital, cashBalance }: Props) {
  const clampedUsed = Math.min(Math.max(usedPct, 0), 100)
  const clampedCash = Math.min(Math.max(cashPct, 0), 100 - clampedUsed)

  return (
    <div className="bb-panel px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-bloomberg-amber text-2xs font-mono tracking-widest">
          USO DE CAPITAL — CARTERA
        </span>
        <span className={`font-mono font-bold text-sm ${labelColor(clampedUsed)}`}>
          {clampedUsed.toFixed(1)}% INVERTIDO
        </span>
      </div>

      {/* Bar */}
      <div className="w-full h-3 bg-bloomberg-border rounded-none overflow-hidden">
        <div
          className={`h-full transition-all duration-500 ${barColor(clampedUsed)}`}
          style={{ width: `${clampedUsed}%` }}
        />
      </div>

      {/* Scale ticks */}
      <div className="flex justify-between text-bloomberg-text-muted mt-0.5" style={{ fontSize: '9px' }}>
        <span>0%</span>
        <span>25%</span>
        <span>50%</span>
        <span>75%</span>
        <span>100%</span>
      </div>

      {/* Stats row */}
      <div className="flex justify-between mt-2 text-2xs font-mono">
        <div>
          <span className="text-bloomberg-text-muted">CAPITAL INICIAL </span>
          <span className="text-bloomberg-text-secondary">{fmtLarge(initialCapital)}€</span>
        </div>
        <div>
          <span className="text-bloomberg-text-muted">EFECTIVO </span>
          <span className="text-bloomberg-electric">{fmtLarge(cashBalance)}€</span>
        </div>
        <div>
          <span className="text-bloomberg-text-muted">DISPONIBLE </span>
          <span className={labelColor(clampedUsed)}>
            {(100 - clampedUsed).toFixed(1)}%
          </span>
        </div>
      </div>

      {/* Capacity warning */}
      {clampedUsed >= 90 && (
        <div className="mt-2 text-bloomberg-red text-2xs font-mono border border-bloomberg-red border-opacity-40 px-2 py-1">
          {clampedUsed >= 100
            ? '✗ CAPITAL TOTALMENTE INVERTIDO — Vende una posición para abrir nuevas operaciones'
            : `⚠ Capacidad casi agotada — Solo queda ${(100 - clampedUsed).toFixed(1)}% disponible`
          }
        </div>
      )}
    </div>
  )
}
