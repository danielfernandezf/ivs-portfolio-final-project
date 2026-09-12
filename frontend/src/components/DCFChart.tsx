import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
  LabelList,
} from 'recharts'

interface Props {
  pvFcfs: number[]
  pvTerminalValue: number
  projectedFcfs: number[]
}

function fmtLarge(n: number): string {
  const abs = Math.abs(n)
  if (abs >= 1e12) return `${(n / 1e12).toFixed(1)}T`
  if (abs >= 1e9) return `${(n / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  return n.toFixed(0)
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-bloomberg-panel border border-bloomberg-border p-2 text-2xs font-mono">
      <div className="text-bloomberg-amber mb-1">{label}</div>
      {payload.map((p: any) => (
        <div key={p.name} className="flex justify-between gap-4">
          <span style={{ color: p.fill }}>{p.name}</span>
          <span className="text-bloomberg-text-primary">${fmtLarge(p.value)}</span>
        </div>
      ))}
    </div>
  )
}

export default function DCFChart({ pvFcfs, pvTerminalValue, projectedFcfs }: Props) {
  const data = pvFcfs.map((pv, i) => ({
    name: `Y${i + 1}`,
    'PV of FCF': Math.max(pv, 0),
    'Terminal Value': i === pvFcfs.length - 1 ? Math.max(pvTerminalValue, 0) : 0,
    projected: projectedFcfs[i],
  }))

  return (
    <div className="bb-panel p-3">
      <div className="text-bloomberg-amber text-2xs tracking-widest mb-3">
        DCF BRIDGE — PV OF FCFs vs TERMINAL VALUE
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <XAxis
            dataKey="name"
            tick={{ fill: '#888', fontSize: 10, fontFamily: 'IBM Plex Mono' }}
            axisLine={{ stroke: '#1e1e1e' }}
            tickLine={false}
          />
          <YAxis
            tickFormatter={fmtLarge}
            tick={{ fill: '#888', fontSize: 10, fontFamily: 'IBM Plex Mono' }}
            axisLine={false}
            tickLine={false}
            width={48}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            wrapperStyle={{
              fontSize: '10px',
              fontFamily: 'IBM Plex Mono',
              color: '#888',
              paddingTop: '4px',
            }}
          />
          <Bar dataKey="PV of FCF" stackId="a" fill="#00aaff" maxBarSize={40}>
            {data.map((_, i) => (
              <Cell key={i} fill={i % 2 === 0 ? '#00aaff' : '#0077bb'} />
            ))}
          </Bar>
          <Bar dataKey="Terminal Value" stackId="a" fill="#f5a623" maxBarSize={40}>
            <LabelList
              dataKey="Terminal Value"
              position="top"
              formatter={(v: number) => v > 0 ? `TV` : ''}
              style={{ fill: '#f5a623', fontSize: 9, fontFamily: 'IBM Plex Mono' }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="mt-2 flex justify-center gap-6 text-2xs text-bloomberg-text-muted">
        <span><span className="text-bloomberg-electric">■</span> PV of Year FCFs</span>
        <span><span className="text-bloomberg-amber">■</span> PV of Terminal Value</span>
      </div>
    </div>
  )
}
