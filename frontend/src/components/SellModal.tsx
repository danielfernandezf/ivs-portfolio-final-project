import { useState } from 'react'
import { LivePortfolioPosition } from '../types/valuation'

interface Props {
  isOpen: boolean
  onClose: () => void
  position: LivePortfolioPosition
  onSellComplete: () => void
}

function fmt2(n: number) { return n.toFixed(2) }
function fmtLarge(n: number) {
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(2)
}

type SellState = 'editing' | 'confirming' | 'executing' | 'done' | 'error'

export default function SellModal({ isOpen, onClose, position: pos, onSellComplete }: Props) {
  const [sharesToSell, setSharesToSell] = useState(pos.shares)
  const [sellState, setSellState] = useState<SellState>('editing')
  const [errorMsg, setErrorMsg] = useState('')

  if (!isOpen) return null

  const isPartialSell = sharesToSell < pos.shares
  const proceeds = sharesToSell * pos.live_price
  const remainingShares = pos.shares - sharesToSell
  const remainingValue = remainingShares * pos.live_price
  const remainingWeightPct = pos.current_market_value > 0
    ? (remainingValue / pos.current_market_value) * pos.allocated_weight_pct
    : 0

  const canSell = sharesToSell > 0 && sharesToSell <= pos.shares

  const executeSell = async () => {
    setSellState('executing')
    try {
      // For full sell, use existing endpoint
      if (!isPartialSell) {
        const res = await fetch(`/api/portfolio/sell/${pos.ticker}?at_live_price=true`, {
          method: 'POST',
        })
        if (!res.ok) {
          const err = await res.json()
          throw new Error(err.detail || `Sell failed: HTTP ${res.status}`)
        }
      } else {
        // Partial sell: sell all, then rebuy the remainder
        // This is a workaround since the DB only supports full liquidation
        const sellRes = await fetch(`/api/portfolio/sell/${pos.ticker}?at_live_price=true`, {
          method: 'POST',
        })
        if (!sellRes.ok) {
          const err = await sellRes.json()
          throw new Error(err.detail || `Sell failed: HTTP ${sellRes.status}`)
        }
        // Rebuy the remaining shares at live price
        if (remainingShares > 0) {
          const rebuyRes = await fetch('/api/portfolio/buy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              ticker: pos.ticker,
              company_name: pos.company_name,
              shares: remainingShares,
              price_per_share: pos.live_price,
              sector: pos.sector,
              currency: pos.currency,
              intrinsic_price: pos.intrinsic_price_at_purchase,
              mos_pct: pos.live_mos,
              allocated_weight_pct: remainingWeightPct,
              is_manual_override: true,
            }),
          })
          if (!rebuyRes.ok) {
            const err = await rebuyRes.json()
            throw new Error(err.detail || `Rebuy remainder failed: HTTP ${rebuyRes.status}`)
          }
        }
      }
      setSellState('done')
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e))
      setSellState('error')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center animate-fadeIn">
      <div className="absolute inset-0 bg-black bg-opacity-80 backdrop-blur-sm" onClick={onClose} />

      <div className="relative z-10 w-full max-w-md mx-4 bb-panel border border-bloomberg-red shadow-2xl shadow-bloomberg-red/10 animate-scaleIn">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-bloomberg-border bg-bloomberg-panel">
          <div>
            <span className="text-bloomberg-red font-mono font-bold tracking-widest">
              VENTA DE POSICIÓN
            </span>
            <span className="text-bloomberg-text-muted text-2xs ml-3">
              {pos.ticker} — {pos.company_name}
            </span>
          </div>
          <button onClick={onClose} className="text-bloomberg-text-muted hover:text-bloomberg-red text-lg font-mono">
            ✕
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {sellState === 'editing' && (
            <>
              {/* Position info */}
              <div className="grid grid-cols-3 gap-2 text-2xs font-mono">
                <div className="bg-black border border-bloomberg-border p-2">
                  <div className="text-bloomberg-text-muted mb-0.5">ACCIONES</div>
                  <div className="text-bloomberg-text-primary font-bold">{pos.shares.toFixed(0)}</div>
                </div>
                <div className="bg-black border border-bloomberg-border p-2">
                  <div className="text-bloomberg-text-muted mb-0.5">P. LIVE</div>
                  <div className="text-bloomberg-electric font-bold">${fmt2(pos.live_price)}</div>
                </div>
                <div className="bg-black border border-bloomberg-border p-2">
                  <div className="text-bloomberg-text-muted mb-0.5">VALOR</div>
                  <div className="text-bloomberg-text-primary font-bold">{fmtLarge(pos.current_market_value)}€</div>
                </div>
              </div>

              {/* Editable shares to sell */}
              <div className="bg-black border border-bloomberg-red border-opacity-30 p-3">
                <div className="text-bloomberg-red text-2xs tracking-widest mb-3">
                  ACCIONES A VENDER
                </div>
                <div className="flex items-center justify-between mb-3">
                  <input
                    type="number"
                    min={1}
                    max={pos.shares}
                    value={sharesToSell}
                    onChange={e => {
                      const v = parseInt(e.target.value, 10)
                      setSharesToSell(isNaN(v) ? 0 : Math.min(Math.max(v, 0), pos.shares))
                    }}
                    className="w-24 bg-bloomberg-border text-bloomberg-red font-mono font-bold text-right px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-bloomberg-red border border-transparent"
                  />
                  <span className="text-bloomberg-text-muted text-2xs font-mono">
                    de {pos.shares.toFixed(0)} totales
                  </span>
                  <button
                    onClick={() => setSharesToSell(pos.shares)}
                    className="text-bloomberg-red text-2xs border border-bloomberg-red px-2 py-0.5 hover:bg-bloomberg-red hover:text-black transition-colors font-mono"
                  >
                    VENDER TODO
                  </button>
                </div>

                {/* Impact preview */}
                <div className="space-y-1.5 text-2xs font-mono border-t border-bloomberg-border pt-2">
                  <div className="flex justify-between">
                    <span className="text-bloomberg-text-muted">Efectivo liberado</span>
                    <span className="text-bloomberg-green font-bold">+{fmtLarge(proceeds)}€</span>
                  </div>
                  {isPartialSell && (
                    <>
                      <div className="flex justify-between">
                        <span className="text-bloomberg-text-muted">Acciones restantes</span>
                        <span className="text-bloomberg-text-primary">{remainingShares.toFixed(0)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-bloomberg-text-muted">Valor restante</span>
                        <span className="text-bloomberg-text-primary">{fmtLarge(remainingValue)}€</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-bloomberg-text-muted">Peso resultante</span>
                        <span className="text-bloomberg-amber">{remainingWeightPct.toFixed(2)}%</span>
                      </div>
                    </>
                  )}
                  {!isPartialSell && (
                    <div className="text-bloomberg-red text-center mt-1">
                      LIQUIDACIÓN TOTAL — Posición eliminada de cartera
                    </div>
                  )}
                </div>
              </div>

              {/* Confirm */}
              <button
                onClick={() => setSellState('confirming')}
                disabled={!canSell}
                className="w-full py-2.5 border-2 border-bloomberg-red text-bloomberg-red font-mono font-bold text-xs tracking-widest hover:bg-red-950 transition-colors disabled:opacity-40"
              >
                REVISAR VENTA — {sharesToSell} × {pos.ticker} @ ${fmt2(pos.live_price)}
              </button>
            </>
          )}

          {sellState === 'confirming' && (
            <div className="space-y-4">
              <div className="text-bloomberg-amber font-mono text-sm text-center">
                ¿CONFIRMAR VENTA?
              </div>
              <div className="bg-black border border-bloomberg-red border-opacity-40 p-3 text-2xs font-mono space-y-1">
                <div className="flex justify-between">
                  <span className="text-bloomberg-text-muted">Ticker</span>
                  <span className="text-bloomberg-amber font-bold">{pos.ticker}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-bloomberg-text-muted">Acciones a vender</span>
                  <span className="text-bloomberg-red font-bold">{sharesToSell}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-bloomberg-text-muted">Precio live</span>
                  <span className="text-bloomberg-electric">${fmt2(pos.live_price)}</span>
                </div>
                <div className="flex justify-between border-t border-bloomberg-border pt-1 mt-1">
                  <span className="text-bloomberg-text-secondary font-bold">Efectivo a recibir</span>
                  <span className="text-bloomberg-green font-bold">{fmtLarge(proceeds)}€</span>
                </div>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => setSellState('editing')}
                  className="flex-1 py-2 border border-bloomberg-border text-bloomberg-text-muted font-mono text-xs hover:text-bloomberg-amber hover:border-bloomberg-amber transition-colors"
                >
                  CANCELAR
                </button>
                <button
                  onClick={executeSell}
                  className="flex-1 py-2 border-2 border-bloomberg-red text-bloomberg-red font-mono font-bold text-xs tracking-widest hover:bg-bloomberg-red hover:text-black transition-colors"
                >
                  CONFIRMAR VENTA
                </button>
              </div>
            </div>
          )}

          {sellState === 'executing' && (
            <div className="flex items-center justify-center py-8 gap-3">
              <div className="text-bloomberg-red font-mono text-xs animate-pulse">
                EJECUTANDO VENTA...
              </div>
            </div>
          )}

          {sellState === 'done' && (
            <div className="space-y-3">
              <div className="text-bloomberg-green font-mono font-bold text-sm flex items-center gap-2">
                <span>✓</span><span>VENTA COMPLETADA</span>
              </div>
              <p className="text-bloomberg-text-secondary text-xs">
                {sharesToSell} acciones de {pos.ticker} vendidas a ${fmt2(pos.live_price)}.
                Efectivo recibido: {fmtLarge(proceeds)}€
              </p>
              <button
                onClick={() => { onSellComplete(); onClose() }}
                className="w-full py-2 border border-bloomberg-border text-bloomberg-text-muted font-mono text-xs hover:border-bloomberg-amber hover:text-bloomberg-amber transition-colors"
              >
                CERRAR
              </button>
            </div>
          )}

          {sellState === 'error' && (
            <div className="space-y-3">
              <div className="text-bloomberg-red font-mono text-sm">⚠ ERROR</div>
              <p className="text-bloomberg-text-secondary text-xs break-all">{errorMsg}</p>
              <button
                onClick={() => setSellState('editing')}
                className="text-bloomberg-text-muted text-2xs hover:text-bloomberg-amber font-mono"
              >
                ↺ volver
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
