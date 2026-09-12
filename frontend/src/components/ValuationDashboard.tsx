import { useState, useCallback, useMemo } from 'react'
import { ValuationResponse, SensitivityOverrides } from '../types/valuation'
import WACCPanel from './WACCPanel'
import DCFChart from './DCFChart'
import SensitivityPanel from './SensitivityPanel'
import TechnicalPanel from './TechnicalPanel'
import VerdictPanel from './VerdictPanel'
import MonteCarloChart from './MonteCarloChart'
import QualityPanel from './QualityPanel'
import { computeFrontendDCF } from '../utils/frontendDCF'

interface Props {
  data: ValuationResponse
  onRefresh: () => void
}

function fmt(n: number, decimals = 2) {
  return n.toFixed(decimals)
}

function fmtLarge(n: number): string {
  const abs = Math.abs(n)
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  return n.toFixed(0)
}

function pct(n: number) {
  return `${(n * 100).toFixed(2)}%`
}

export default function ValuationDashboard({ data, onRefresh }: Props) {
  const f = data.fundamental

  const [overrides, setOverrides] = useState<SensitivityOverrides>({
    wacc: f.wacc * 100,
    growthRate: f.assumptions.revenue_growth_rate * 100,
    terminalGrowth: f.assumptions.terminal_growth_rate * 100,
    fcfMargin: f.assumptions.fcf_margin * 100,
  })

  const liveValuation = useMemo(() => {
    return computeFrontendDCF(f, overrides)
  }, [f, overrides])

  const upside = liveValuation.intrinsicPrice > 0
    ? (liveValuation.intrinsicPrice - f.current_price) / f.current_price
    : 0

  const upsideColor = upside > 0.1
    ? 'text-bloomberg-green'
    : upside < -0.1
    ? 'text-bloomberg-red'
    : 'text-bloomberg-amber'

  const handleOverride = useCallback((key: keyof SensitivityOverrides, val: number) => {
    setOverrides(prev => ({ ...prev, [key]: val }))
  }, [])

  return (
    <div className="p-3 space-y-3">
      {/* ── Header Row ── */}
      <div className="bb-panel p-3 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="text-bloomberg-amber font-mono font-bold text-xl ticker-glow tracking-widest">
              {f.ticker}
            </span>
            <span className="text-bloomberg-text-secondary text-xs">
              {f.company_name}
            </span>
            <span className="text-bloomberg-text-muted text-2xs border border-bloomberg-border px-2 py-0.5">
              {f.sector}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <div>
              <span className="bb-label">PRICE </span>
              <span className="bb-value text-bloomberg-electric">${fmt(f.current_price)}</span>
            </div>
            <div>
              <span className="bb-label">INTRINSIC </span>
              <span className={`bb-value ${upsideColor}`}>
                ${fmt(liveValuation.intrinsicPrice)}
              </span>
            </div>
            <div>
              <span className="bb-label">UPSIDE </span>
              <span className={`bb-value ${upsideColor}`}>
                {upside >= 0 ? '+' : ''}{pct(upside)}
              </span>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-4 text-xs">
          <div className="text-center">
            <div className="bb-label">MARKET CAP</div>
            <div className="bb-value">${fmtLarge(f.market_cap)}</div>
          </div>
          <div className="text-center">
            <div className="bb-label">EV</div>
            <div className="bb-value">${fmtLarge(liveValuation.enterpriseValue)}</div>
          </div>
          <div className="text-center">
            <div className="bb-label">NET DEBT</div>
            <div className={`bb-value ${f.net_debt > 0 ? 'text-bloomberg-red' : 'text-bloomberg-green'}`}>
              ${fmtLarge(f.net_debt)}
            </div>
          </div>
          <div className="text-center">
            <div className="bb-label">BETA</div>
            <div className="bb-value">{fmt(f.beta)}</div>
          </div>
          <div className="text-center">
            <div className="bb-label">SHARES OUT</div>
            <div className="bb-value">{fmtLarge(f.shares_outstanding)}</div>
          </div>
          <button
            onClick={onRefresh}
            className="text-2xs font-mono px-3 py-1 border border-bloomberg-border text-bloomberg-text-muted hover:border-bloomberg-amber hover:text-bloomberg-amber transition-colors self-end"
          >
            ↺ REFRESH
          </button>
        </div>
      </div>

      {/* ── Main Grid ── */}
      <div className="grid grid-cols-12 gap-3 stagger-children">
        {/* Left: WACC + FCF History + Quality */}
        <div className="col-span-12 lg:col-span-4 space-y-3">
          <WACCPanel f={f} overrides={overrides} liveWacc={overrides.wacc / 100} />

          {/* FCF History */}
          <div className="bb-panel p-3">
            <div className="text-bloomberg-amber text-2xs tracking-widest mb-3">
              FREE CASH FLOW — HISTORICAL
            </div>
            <div className="space-y-1">
              {f.fcf_history.map((v, i) => (
                <div key={i} className="flex justify-between items-center">
                  <span className="text-bloomberg-text-muted text-2xs">
                    T-{f.fcf_history.length - i}
                  </span>
                  <div className="flex-1 mx-3 h-px bg-bloomberg-border" />
                  <span className={`font-mono text-xs ${v >= 0 ? 'text-bloomberg-green' : 'text-bloomberg-red'}`}>
                    ${fmtLarge(v)}
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-3 pt-2 border-t border-bloomberg-border flex justify-between">
              <span className="bb-label">BASE FCF (T0)</span>
              <span className="bb-value">${fmtLarge(f.base_fcf)}</span>
            </div>
          </div>

          {/* Phase 5: Quality Panel */}
          {data.quality && <QualityPanel quality={data.quality} />}
        </div>

        {/* Center: DCF Chart */}
        <div className="col-span-12 lg:col-span-5">
          <DCFChart
            pvFcfs={liveValuation.pvFcfs}
            pvTerminalValue={liveValuation.pvTerminalValue}
            projectedFcfs={liveValuation.projectedFcfs}
          />

          {/* Investment Committee Verdict Panel */}
          <div className="mt-3">
            <VerdictPanel
              verdict={f.verdict}
              liveValuation={liveValuation}
              f={f}
              overrides={overrides}
              technical={data.technical}
              quality={data.quality}
            />
          </div>

          {/* DCF Output Table */}
          <div className="bb-panel p-3 mt-3">
            <div className="text-bloomberg-electric text-2xs tracking-widest mb-3">
              DCF DECOMPOSITION — 5-YEAR PROJECTION
            </div>
            <table className="w-full text-2xs font-mono">
              <thead>
                <tr className="border-b border-bloomberg-border">
                  <th className="text-left text-bloomberg-text-muted pb-1">YEAR</th>
                  <th className="text-right text-bloomberg-text-muted pb-1">FCF</th>
                  <th className="text-right text-bloomberg-text-muted pb-1">PV(FCF)</th>
                  <th className="text-right text-bloomberg-text-muted pb-1">WEIGHT</th>
                </tr>
              </thead>
              <tbody>
                {liveValuation.projectedFcfs.map((fcf, i) => {
                  const pv = liveValuation.pvFcfs[i]
                  const weight = liveValuation.enterpriseValue > 0
                    ? pv / liveValuation.enterpriseValue
                    : 0
                  return (
                    <tr key={i} className="border-b border-bloomberg-border border-opacity-30">
                      <td className="py-1 text-bloomberg-text-secondary">Y{i + 1}</td>
                      <td className="py-1 text-right text-bloomberg-text-primary">${fmtLarge(fcf)}</td>
                      <td className="py-1 text-right text-bloomberg-electric">${fmtLarge(pv)}</td>
                      <td className="py-1 text-right text-bloomberg-text-muted">
                        {(weight * 100).toFixed(1)}%
                      </td>
                    </tr>
                  )
                })}
                <tr className="border-b border-bloomberg-border">
                  <td className="py-1 text-bloomberg-amber">TV</td>
                  <td className="py-1 text-right text-bloomberg-text-muted">${fmtLarge(liveValuation.terminalValue)}</td>
                  <td className="py-1 text-right text-bloomberg-amber">${fmtLarge(liveValuation.pvTerminalValue)}</td>
                  <td className="py-1 text-right text-bloomberg-text-muted">
                    {liveValuation.enterpriseValue > 0
                      ? ((liveValuation.pvTerminalValue / liveValuation.enterpriseValue) * 100).toFixed(1)
                      : '—'}%
                  </td>
                </tr>
              </tbody>
              <tfoot>
                <tr>
                  <td className="pt-2 text-bloomberg-text-secondary font-semibold" colSpan={2}>
                    ENTERPRISE VALUE
                  </td>
                  <td className="pt-2 text-right text-bloomberg-amber font-semibold">
                    ${fmtLarge(liveValuation.enterpriseValue)}
                  </td>
                  <td />
                </tr>
                <tr>
                  <td className="text-bloomberg-text-secondary" colSpan={2}>
                    EQUITY VALUE
                  </td>
                  <td className="text-right text-bloomberg-electric font-semibold">
                    ${fmtLarge(liveValuation.equityValue)}
                  </td>
                  <td />
                </tr>
                <tr>
                  <td className="text-bloomberg-amber font-semibold" colSpan={2}>
                    INTRINSIC / SHARE
                  </td>
                  <td className={`text-right font-bold ${upsideColor}`}>
                    ${fmt(liveValuation.intrinsicPrice)}
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        </div>

        {/* Right: Sensitivity + Technical */}
        <div className="col-span-12 lg:col-span-3 space-y-3">
          <SensitivityPanel
            overrides={overrides}
            onOverride={handleOverride}
            f={f}
          />
          {data.technical && (
            <TechnicalPanel tech={data.technical} currentPrice={f.current_price} />
          )}
        </div>
      </div>

      {/* ── Phase 4: Monte Carlo Quant Engine ── */}
      <MonteCarloChart ticker={f.ticker} currentPrice={f.current_price} />
    </div>
  )
}
