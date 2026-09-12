import { PortfolioAlert } from '../types/valuation'

interface Props {
  alerts: PortfolioAlert[]
}

export default function AlertsBanner({ alerts }: Props) {
  if (alerts.length === 0) return null

  const critical = alerts.filter(a => a.severity === 'critical')
  const warnings = alerts.filter(a => a.severity === 'warning')

  return (
    <div className="space-y-2 animate-fadeIn">
      {critical.length > 0 && (
        <div className="bb-panel border-l-2 border-bloomberg-red bg-red-950 bg-opacity-50">
          <div className="px-4 py-2 flex items-center gap-2 border-b border-bloomberg-red border-opacity-30">
            <span className="w-2 h-2 rounded-full bg-bloomberg-red shadow-[0_0_8px_rgba(255,51,51,0.8)] animate-pulse" />
            <span className="text-bloomberg-red font-mono text-2xs tracking-widest font-bold">
              ALERTAS CRITICAS — REVISION URGENTE
            </span>
            <span className="ml-auto text-bloomberg-red text-2xs font-mono">{critical.length}</span>
          </div>
          <div className="px-4 py-2 space-y-2">
            {critical.map((alert, i) => (
              <div key={`${alert.ticker}-${alert.type}-${i}`} className="flex items-start gap-3 text-2xs font-mono">
                <span className="text-bloomberg-red mt-0.5 shrink-0">!</span>
                <div className="flex-1">
                  <div className="text-bloomberg-red font-bold">{alert.title}</div>
                  <div className="text-bloomberg-text-secondary mt-0.5">{alert.detail}</div>
                </div>
                <div className="shrink-0 text-bloomberg-red font-bold">
                  {alert.z_score != null && `Z=${alert.z_score.toFixed(2)}`}
                  {alert.f_score != null && `F=${alert.f_score}/9`}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="bb-panel border-l-2 border-bloomberg-amber bg-amber-950 bg-opacity-30">
          <div className="px-4 py-2 flex items-center gap-2 border-b border-bloomberg-amber border-opacity-20">
            <span className="w-2 h-2 rounded-full bg-bloomberg-amber shadow-[0_0_6px_rgba(245,166,35,0.6)]" />
            <span className="text-bloomberg-amber font-mono text-2xs tracking-widest font-bold">
              ADVERTENCIAS — MONITORIZAR
            </span>
            <span className="ml-auto text-bloomberg-amber text-2xs font-mono">{warnings.length}</span>
          </div>
          <div className="px-4 py-2 space-y-2">
            {warnings.map((alert, i) => (
              <div key={`${alert.ticker}-${alert.type}-${i}`} className="flex items-start gap-3 text-2xs font-mono">
                <span className="text-bloomberg-amber mt-0.5 shrink-0">~</span>
                <div className="flex-1">
                  <div className="text-bloomberg-amber font-bold">{alert.title}</div>
                  <div className="text-bloomberg-text-muted mt-0.5">{alert.detail}</div>
                </div>
                <div className="shrink-0 text-bloomberg-amber">
                  {alert.z_score != null && `Z=${alert.z_score.toFixed(2)}`}
                  {alert.f_score != null && `F=${alert.f_score}/9`}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
