import { QualityMetrics } from '../types/valuation'

interface Props {
  quality: QualityMetrics
}

// ── Colour helpers ────────────────────────────────────────────────────────────

function zoneColor(zone: string) {
  if (zone === 'SAFE') return { text: 'text-bloomberg-green', border: 'border-bloomberg-green', bg: 'bg-green-950' }
  if (zone === 'GREY') return { text: 'text-bloomberg-amber', border: 'border-bloomberg-amber', bg: 'bg-amber-950' }
  if (zone === 'DISTRESS') return { text: 'text-bloomberg-red', border: 'border-bloomberg-red', bg: 'bg-red-950' }
  return { text: 'text-bloomberg-text-muted', border: 'border-bloomberg-border', bg: '' }
}

function fScoreColor(score: number) {
  if (score >= 7) return 'text-bloomberg-green'
  if (score >= 4) return 'text-bloomberg-amber'
  return 'text-bloomberg-red'
}

function multColor(vsAmt: number | null) {
  if (vsAmt === null) return 'text-bloomberg-text-muted'
  if (vsAmt < -10) return 'text-bloomberg-green'   // trading at significant discount to sector
  if (vsAmt < 10) return 'text-bloomberg-amber'
  return 'text-bloomberg-red'                        // expensive vs sector
}

const F_SIGNALS: Array<{ key: keyof QualityMetrics['piotroski']; label: string }> = [
  { key: 'f1_roa_positive',            label: 'F1 ROA > 0' },
  { key: 'f2_ocf_positive',            label: 'F2 OCF > 0' },
  { key: 'f3_roa_improving',           label: 'F3 ROA ↑' },
  { key: 'f4_accruals_quality',        label: 'F4 Accrual' },
  { key: 'f5_leverage_improving',      label: 'F5 Lev ↓' },
  { key: 'f6_liquidity_improving',     label: 'F6 CR ↑' },
  { key: 'f7_no_dilution',             label: 'F7 No dil.' },
  { key: 'f8_gross_margin_improving',  label: 'F8 GM ↑' },
  { key: 'f9_asset_turnover_improving',label: 'F9 AT ↑' },
]

export default function QualityPanel({ quality }: Props) {
  const { altman, piotroski, benchmark, liquidity } = quality
  const zc = zoneColor(altman.zone)

  return (
    <div className="bb-panel">
      {/* Header */}
      <div className="px-3 py-2 border-b border-bloomberg-border flex items-center justify-between">
        <span className="text-bloomberg-amber font-mono font-bold text-2xs tracking-widest">
          QUALITY & SURVIVAL FILTER
        </span>
        {quality.verdict_override && (
          <span className="text-bloomberg-red text-2xs font-mono font-bold animate-pulse">
            ⚠ OVERRIDE ACTIVO
          </span>
        )}
      </div>

      {/* Override banner */}
      {quality.verdict_override && (
        <div className="mx-3 mt-2 bg-red-950 border border-bloomberg-red border-opacity-60 px-3 py-2 text-bloomberg-red text-2xs font-mono leading-relaxed">
          <span className="font-bold">VEREDICTO INVALIDADO: </span>
          {quality.override_reason}
        </div>
      )}

      <div className="p-3 space-y-3">

        {/* ── Altman Z-Score ─────────────────────────────────────────────── */}
        <div className={`border ${zc.border} p-2 ${zc.bg}`}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-bloomberg-text-muted text-2xs font-mono">ALTMAN Z-SCORE</span>
            <span className={`font-mono font-bold text-sm ${zc.text}`}>
              {altman.zone === 'N/A' ? 'N/A' : altman.z_score.toFixed(2)}
            </span>
          </div>
          <div className={`text-2xs font-mono font-bold ${zc.text} mb-1`}>
            {altman.zone === 'SAFE' && '● ZONA SEGURA (Z > 2.99)'}
            {altman.zone === 'GREY' && '● ZONA GRIS (1.81–2.99)'}
            {altman.zone === 'DISTRESS' && '● ZONA DE PELIGRO (Z < 1.81)'}
            {altman.zone === 'N/A' && '● ' + (altman.note || 'No aplicable')}
          </div>

          {altman.zone !== 'N/A' && (
            <div className="grid grid-cols-5 gap-0.5 mt-1">
              {[
                { label: 'X1 WC/TA', val: altman.x1_wc_to_assets, w: '1.2×' },
                { label: 'X2 RE/TA', val: altman.x2_re_to_assets, w: '1.4×' },
                { label: 'X3 EB/TA', val: altman.x3_ebit_to_assets, w: '3.3×' },
                { label: 'X4 MC/TL', val: altman.x4_mktcap_to_liab, w: '0.6×' },
                { label: 'X5 R/TA',  val: altman.x5_rev_to_assets, w: '1.0×' },
              ].map(x => (
                <div key={x.label} className="text-center bg-black border border-bloomberg-border p-1">
                  <div className="text-bloomberg-text-muted" style={{ fontSize: '7px' }}>{x.label}</div>
                  <div className="text-bloomberg-electric font-mono text-2xs">{x.val.toFixed(2)}</div>
                  <div className="text-bloomberg-text-muted" style={{ fontSize: '7px' }}>{x.w}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Piotroski F-Score ──────────────────────────────────────────── */}
        <div className="bg-black border border-bloomberg-border p-2">
          <div className="flex items-center justify-between mb-2">
            <span className="text-bloomberg-text-muted text-2xs font-mono">PIOTROSKI F-SCORE</span>
            <div className="flex items-center gap-1.5">
              <span className={`font-mono font-bold text-base ${fScoreColor(piotroski.score)}`}>
                {piotroski.score}
                <span className="text-bloomberg-text-muted text-2xs">/9</span>
              </span>
              <span className={`text-2xs font-mono ${fScoreColor(piotroski.score)}`}>
                {piotroski.score >= 7 ? 'FUERTE' : piotroski.score >= 4 ? 'MODERADO' : 'DÉBIL'}
              </span>
            </div>
          </div>

          {/* Signal dots — 9 cells */}
          <div className="grid grid-cols-9 gap-0.5">
            {F_SIGNALS.map(sig => {
              const passed = piotroski[sig.key] as boolean
              return (
                <div key={sig.key} className="text-center" title={sig.label}>
                  <div
                    className={`h-2 rounded-sm ${passed ? 'bg-bloomberg-green' : 'bg-bloomberg-border'}`}
                  />
                  <div className="text-bloomberg-text-muted mt-0.5" style={{ fontSize: '7px' }}>
                    {sig.label.split(' ')[0]}
                  </div>
                </div>
              )
            })}
          </div>
          {piotroski.signals_computed < 9 && (
            <div className="text-bloomberg-text-muted text-2xs font-mono mt-1">
              *(Datos históricos para {piotroski.signals_computed}/9 señales)*
            </div>
          )}
        </div>

        {/* ── Sector Benchmarks ──────────────────────────────────────────── */}
        <div className="bg-black border border-bloomberg-border p-2">
          <div className="text-bloomberg-text-muted text-2xs font-mono mb-2">VALORACIÓN VS. SECTOR</div>
          <table className="w-full text-2xs font-mono">
            <thead>
              <tr className="text-bloomberg-text-muted border-b border-bloomberg-border">
                <th className="text-left pb-1">MÚLTIPLO</th>
                <th className="text-right pb-1">EMPRESA</th>
                <th className="text-right pb-1">SECTOR</th>
                <th className="text-right pb-1">DIFER.</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-bloomberg-border border-opacity-30">
                <td className="py-1 text-bloomberg-text-secondary">P/E Ratio</td>
                <td className="text-right py-1 text-bloomberg-electric">
                  {benchmark.pe_ratio != null ? `${benchmark.pe_ratio.toFixed(1)}×` : '—'}
                </td>
                <td className="text-right py-1 text-bloomberg-text-muted">
                  {benchmark.sector_pe.toFixed(1)}×
                </td>
                <td className={`text-right py-1 font-bold ${multColor(benchmark.pe_vs_sector_pct)}`}>
                  {benchmark.pe_vs_sector_pct != null
                    ? `${benchmark.pe_vs_sector_pct > 0 ? '+' : ''}${benchmark.pe_vs_sector_pct.toFixed(1)}%`
                    : '—'}
                </td>
              </tr>
              <tr>
                <td className="py-1 text-bloomberg-text-secondary">EV/EBITDA</td>
                <td className="text-right py-1 text-bloomberg-electric">
                  {benchmark.ev_ebitda != null ? `${benchmark.ev_ebitda.toFixed(1)}×` : '—'}
                </td>
                <td className="text-right py-1 text-bloomberg-text-muted">
                  {benchmark.sector_ev_ebitda.toFixed(1)}×
                </td>
                <td className={`text-right py-1 font-bold ${multColor(benchmark.ev_ebitda_vs_sector_pct)}`}>
                  {benchmark.ev_ebitda_vs_sector_pct != null
                    ? `${benchmark.ev_ebitda_vs_sector_pct > 0 ? '+' : ''}${benchmark.ev_ebitda_vs_sector_pct.toFixed(1)}%`
                    : '—'}
                </td>
              </tr>
            </tbody>
          </table>
          <div className="text-bloomberg-text-muted mt-1" style={{ fontSize: '7px' }}>
            Verde = descuento vs sector · Rojo = prima vs sector
          </div>
        </div>

        {/* ── Liquidity Alert ────────────────────────────────────────────── */}
        {liquidity.alert ? (
          <div className="border border-orange-500 border-opacity-60 bg-orange-950 px-2 py-1.5">
            <div className="text-orange-400 text-2xs font-mono font-bold mb-0.5">⚠ LIQUIDEZ</div>
            <div className="text-orange-300 text-2xs font-mono leading-relaxed">
              {liquidity.alert}
            </div>
          </div>
        ) : (
          <div className="flex justify-between text-2xs font-mono">
            <span className="text-bloomberg-text-muted">Vol. diario (10d)</span>
            <span className="text-bloomberg-text-secondary">
              {liquidity.avg_volume_10d.toLocaleString()} acc
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
