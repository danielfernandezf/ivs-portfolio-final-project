import { useState, useCallback, useEffect } from 'react'
import {
  LivePortfolioResponse, LivePortfolioPosition, CorrelationMatrix, DailyReturnsResponse,
} from '../types/valuation'
import CorrelationHeatmap from './CorrelationHeatmap'
import DailyReturnsHeatmap from './DailyReturnsHeatmap'
import CapitalUsageBar from './CapitalUsageBar'
import SellModal from './SellModal'

function fmt2(n: number) { return n.toFixed(2) }
function fmtLarge(n: number) {
  const abs = Math.abs(n)
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(2)
}
function pct(n: number, decimals = 1) {
  return `${n >= 0 ? '+' : ''}${n.toFixed(decimals)}%`
}

function mosColor(mos: number) {
  if (mos > 20) return 'text-bloomberg-green'
  if (mos > 0) return 'text-bloomberg-amber'
  return 'text-bloomberg-red'
}
function returnColor(ret: number) {
  return ret >= 0 ? 'text-bloomberg-green' : 'text-bloomberg-red'
}

type LoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; live: LivePortfolioResponse }
  | { status: 'error'; message: string }

type CorrState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; data: CorrelationMatrix }
  | { status: 'error'; message: string }

type ReturnsState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; data: DailyReturnsResponse }
  | { status: 'error'; message: string }

type SellModalState = { isOpen: false } | { isOpen: true; position: LivePortfolioPosition }

export default function PortfolioTab() {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'idle' })
  const [sellModal, setSellModal] = useState<SellModalState>({ isOpen: false })
  const [corrState, setCorrState] = useState<CorrState>({ status: 'idle' })
  const [returnsState, setReturnsState] = useState<ReturnsState>({ status: 'idle' })

  const loadDailyReturns = useCallback(async (days = 30) => {
    setReturnsState({ status: 'loading' })
    try {
      const res = await fetch(`/api/portfolio/daily-returns?days=${days}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: DailyReturnsResponse = await res.json()
      setReturnsState({ status: 'loaded', data })
    } catch (e) {
      setReturnsState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }, [])

  const loadCorrelation = useCallback(async () => {
    setCorrState({ status: 'loading' })
    try {
      const res = await fetch('/api/portfolio/correlation')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: CorrelationMatrix = await res.json()
      setCorrState({ status: 'loaded', data })
    } catch (e) {
      setCorrState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }, [])

  const loadLive = useCallback(async () => {
    setLoadState({ status: 'loading' })
    try {
      const res = await fetch('/api/portfolio/live')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const live: LivePortfolioResponse = await res.json()
      setLoadState({ status: 'loaded', live })
    } catch (e) {
      setLoadState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }, [])

  // Auto-load correlation whenever live positions are loaded
  useEffect(() => {
    if (loadState.status === 'loaded' && loadState.live.live_positions.length >= 2) {
      loadCorrelation()
    }
  }, [loadState.status, loadCorrelation])

  // El heatmap de rendimientos sí tiene sentido con una sola posición
  useEffect(() => {
    if (loadState.status === 'loaded' && loadState.live.live_positions.length >= 1) {
      loadDailyReturns()
    }
  }, [loadState.status, loadDailyReturns])

  const openSellModal = useCallback((position: LivePortfolioPosition) => {
    setSellModal({ isOpen: true, position })
  }, [])

  const closeSellModal = useCallback(() => {
    setSellModal({ isOpen: false })
  }, [])

  // ── Initial state ───────────────────────────────────────────────────────────
  if (loadState.status === 'idle') {
    return (
      <div className="p-4 space-y-4">
        <PortfolioOverview onLoadLive={loadLive} summary={null} showRefresh={false} />
      </div>
    )
  }

  return (
    <div className="p-3 space-y-3">
      {/* Portfolio Header */}
      {loadState.status === 'loaded' && (
        <PortfolioOverview
          onLoadLive={loadLive}
          summary={{
            cash_balance: loadState.live.cash_balance,
            total_live_value: loadState.live.total_live_value,
            portfolio_return_pct: loadState.live.portfolio_return_pct,
            n_positions: loadState.live.live_positions.length,
          }}
          showRefresh
        />
      )}

      {/* Aviso de precios no disponibles: el retorno mostrado NO es real */}
      {loadState.status === 'loaded' && (loadState.live.stale_prices ?? 0) > 0 && (
        <div className="border border-bloomberg-red bg-bloomberg-red bg-opacity-10 p-3 font-mono text-xs text-bloomberg-red flex items-center justify-between">
          <span>
            ⚠ SIN PRECIOS LIVE PARA {loadState.live.stale_prices} DE{' '}
            {loadState.live.live_positions.length} POSICIONES — se muestra el precio
            de compra, el valor y retorno NO son reales. Suele indicar un problema
            con la fuente de datos (yfinance) o el entorno Python del backend.
          </span>
          <button onClick={loadLive} className="ml-4 text-bloomberg-amber hover:underline shrink-0">
            ↺ reintentar
          </button>
        </div>
      )}

      {loadState.status === 'loading' && (
        <div className="flex items-center justify-center h-32 gap-3">
          <div className="text-bloomberg-amber font-mono text-sm animate-pulse">
            ACTUALIZANDO PRECIOS LIVE...
          </div>
          <div className="flex gap-1">
            {[0, 1, 2].map(i => (
              <div key={i} className="w-1 h-4 bg-bloomberg-amber animate-bounce"
                style={{ animationDelay: `${i * 0.15}s` }} />
            ))}
          </div>
        </div>
      )}

      {loadState.status === 'error' && (
        <div className="bb-panel p-4 text-bloomberg-red text-xs font-mono">
          ⚠ ERROR: {loadState.message}
          <button onClick={loadLive} className="ml-4 text-bloomberg-amber hover:underline">↺ reintentar</button>
        </div>
      )}

      {loadState.status === 'loaded' && (
        loadState.live.live_positions.length === 0 ? (
          <EmptyPortfolio />
        ) : (
          <PositionsTable
            positions={loadState.live.live_positions}
            onSell={openSellModal}
          />
        )
      )}

      {/* ── Sell Modal ────────────────────────────────────────────────────── */}
      {sellModal.isOpen && (
        <SellModal
          isOpen
          onClose={closeSellModal}
          position={sellModal.position}
          onSellComplete={loadLive}
        />
      )}

      {/* ── Correlación + rendimientos diarios, lado a lado ─────────────────
          Ambas tablas son anchas, así que sólo se ponen en paralelo a partir de
          2xl; por debajo se apilan. Cada panel tiene su propio overflow-x, de
          modo que la página nunca hace scroll horizontal. */}
      {loadState.status === 'loaded' && loadState.live.live_positions.length >= 1 && (
        <div className="grid grid-cols-1 2xl:grid-cols-2 gap-3 items-start">
          {/* Matriz de correlación */}
          {loadState.live.live_positions.length >= 2 && (
            <div className="min-w-0">
              {corrState.status === 'loading' && (
                <div className="bb-panel px-4 py-6 flex items-center gap-3 text-2xs font-mono text-bloomberg-text-muted">
                  <div className="animate-pulse">CALCULANDO MATRIZ DE CORRELACIÓN (2 AÑOS)...</div>
                  <div className="flex gap-1">
                    {[0, 1, 2].map(i => (
                      <div key={i} className="w-1 h-3 bg-bloomberg-amber animate-bounce"
                        style={{ animationDelay: `${i * 0.15}s` }} />
                    ))}
                  </div>
                </div>
              )}
              {corrState.status === 'error' && (
                <div className="bb-panel p-3 text-bloomberg-red text-2xs font-mono">
                  ⚠ Correlación: {corrState.message}
                  <button onClick={loadCorrelation} className="ml-3 text-bloomberg-amber hover:underline">↺ reintentar</button>
                </div>
              )}
              {corrState.status === 'loaded' && (
                <CorrelationHeatmap data={corrState.data} />
              )}
            </div>
          )}

          {/* Rendimientos diarios */}
          <div className="min-w-0">
            {returnsState.status === 'loading' && (
              <div className="bb-panel px-4 py-6 flex items-center gap-3 text-2xs font-mono text-bloomberg-text-muted">
                <div className="animate-pulse">CALCULANDO RENDIMIENTOS DIARIOS...</div>
                <div className="flex gap-1">
                  {[0, 1, 2].map(i => (
                    <div key={i} className="w-1 h-3 bg-bloomberg-amber animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }} />
                  ))}
                </div>
              </div>
            )}
            {returnsState.status === 'error' && (
              <div className="bb-panel p-3 text-bloomberg-red text-2xs font-mono">
                ⚠ Rendimientos diarios: {returnsState.message}
                <button onClick={() => loadDailyReturns()} className="ml-3 text-bloomberg-amber hover:underline">↺ reintentar</button>
              </div>
            )}
            {returnsState.status === 'loaded' && (
              <DailyReturnsHeatmap data={returnsState.data} onReload={loadDailyReturns} />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

const INITIAL_CAPITAL = 100_000

function PortfolioOverview({
  onLoadLive,
  summary,
  showRefresh,
}: {
  onLoadLive: () => void
  summary: { cash_balance: number; total_live_value: number; portfolio_return_pct: number; n_positions: number } | null
  showRefresh: boolean
}) {
  const usedPct = summary
    ? Math.max((INITIAL_CAPITAL - summary.cash_balance) / INITIAL_CAPITAL * 100, 0)
    : 0
  const cashPct = summary ? summary.cash_balance / INITIAL_CAPITAL * 100 : 100

  return (
    <div className="space-y-3">
      <div className="bb-panel p-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <span className="text-bloomberg-amber font-mono font-bold text-sm tracking-widest">
              LIVE PORTFOLIO
            </span>
            <span className="text-bloomberg-text-muted text-2xs ml-3">
              Capital inicial: 100,000€
            </span>
          </div>
          <button
            onClick={onLoadLive}
            className="px-4 py-1.5 border border-bloomberg-amber text-bloomberg-amber font-mono text-xs hover:bg-bloomberg-amber hover:text-black transition-colors"
          >
            {showRefresh ? '↺ ACTUALIZAR LIVE' : '▶ CARGAR CARTERA'}
          </button>
        </div>

        {summary && (
          <div className="grid grid-cols-4 gap-3">
            {[
              { label: 'VALOR TOTAL', value: `${fmtLarge(summary.total_live_value)}€`, color: 'text-bloomberg-electric' },
              { label: 'EFECTIVO', value: `${fmtLarge(summary.cash_balance)}€`, color: 'text-bloomberg-text-primary' },
              {
                label: 'RETORNO TOTAL',
                value: pct(summary.portfolio_return_pct),
                color: returnColor(summary.portfolio_return_pct),
              },
              { label: 'POSICIONES', value: String(summary.n_positions), color: 'text-bloomberg-amber' },
            ].map(card => (
              <div key={card.label} className="bg-black border border-bloomberg-border p-3">
                <div className="bb-label mb-1">{card.label}</div>
                <div className={`font-mono font-bold text-base ${card.color}`}>{card.value}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Capital Usage Bar — always visible, shows 0% when portfolio not loaded */}
      <CapitalUsageBar
        usedPct={usedPct}
        cashPct={cashPct}
        initialCapital={INITIAL_CAPITAL}
        cashBalance={summary?.cash_balance ?? INITIAL_CAPITAL}
      />
    </div>
  )
}

function EmptyPortfolio() {
  return (
    <div className="bb-panel p-8 text-center">
      <div className="text-bloomberg-text-muted text-sm font-mono mb-2">
        CARTERA VACÍA
      </div>
      <div className="text-bloomberg-text-muted text-2xs">
        Analiza una empresa en la pestaña ANALYZER y confirma una operación para añadir posiciones.
      </div>
    </div>
  )
}

function PositionsTable({
  positions,
  onSell,
}: {
  positions: LivePortfolioPosition[]
  onSell: (position: LivePortfolioPosition) => void
}) {
  return (
    <div className="bb-panel">
      <div className="px-4 py-2 border-b border-bloomberg-border">
        <span className="text-bloomberg-electric text-2xs tracking-widest">
          POSICIONES ABIERTAS — ACTUALIZACIÓN LIVE
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="border-b border-bloomberg-border text-bloomberg-text-muted text-2xs">
              <th className="text-left px-4 py-2">TICKER</th>
              <th className="text-right px-3 py-2">ACCIONES</th>
              <th className="text-right px-3 py-2">P.COMPRA</th>
              <th className="text-right px-3 py-2">P.LIVE</th>
              <th className="text-right px-3 py-2">VALOR</th>
              <th className="text-right px-3 py-2">PESO %</th>
              <th className="text-right px-3 py-2">RETORNO</th>
              <th className="text-right px-3 py-2">MoS LIVE</th>
              <th className="text-right px-3 py-2">MoS COMPRA</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="stagger-children">
            {positions.map(pos => (
                <tr
                  key={pos.ticker}
                  className="border-b border-bloomberg-border border-opacity-30 hover:bg-bloomberg-panel transition-all duration-200 hover:shadow-[inset_2px_0_0_#f5a623]"
                >
                  <td className="px-4 py-2">
                    <div className="text-bloomberg-amber font-bold">{pos.ticker}</div>
                    <div className="text-bloomberg-text-muted text-2xs truncate max-w-[120px]">
                      {pos.company_name}
                    </div>
                  </td>
                  <td className="text-right px-3 py-2 text-bloomberg-text-primary">
                    {pos.shares.toFixed(0)}
                  </td>
                  <td className="text-right px-3 py-2 text-bloomberg-text-secondary">
                    ${fmt2(pos.purchase_price)}
                  </td>
                  <td className="text-right px-3 py-2 text-bloomberg-electric">
                    ${fmt2(pos.live_price)}
                  </td>
                  <td className="text-right px-3 py-2 text-bloomberg-text-primary">
                    {fmtLarge(pos.current_market_value)}€
                  </td>
                  <td className="text-right px-3 py-2 text-bloomberg-text-secondary">
                    {pos.allocated_weight_pct.toFixed(1)}%
                  </td>
                  <td className={`text-right px-3 py-2 font-bold ${returnColor(pos.return_pct)}`}>
                    {pct(pos.return_pct)}
                  </td>
                  <td className={`text-right px-3 py-2 font-bold ${mosColor(pos.live_mos)}`}>
                    {pct(pos.live_mos)}
                  </td>
                  <td className="text-right px-3 py-2 text-bloomberg-text-muted">
                    {pct(pos.mos_at_purchase)}
                  </td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => onSell(pos)}
                      className="text-bloomberg-red text-2xs border border-bloomberg-red px-2 py-0.5 hover:bg-bloomberg-red hover:text-black transition-colors"
                    >
                      VENDER
                    </button>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="px-4 py-2 border-t border-bloomberg-border flex gap-4 text-2xs text-bloomberg-text-muted">
        <span><span className="text-bloomberg-green">■</span> MoS &gt; 20% — mantener</span>
        <span><span className="text-bloomberg-amber">■</span> MoS 0-20% — vigilar</span>
        <span><span className="text-bloomberg-red">■</span> MoS &lt; 0% — candidato a venta</span>
        <span className="ml-auto">MoS = (Intrínseco en compra − Precio live) / Intrínseco en compra</span>
      </div>
    </div>
  )
}
