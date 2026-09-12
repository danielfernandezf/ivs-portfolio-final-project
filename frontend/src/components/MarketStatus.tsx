import { useState, useEffect } from 'react'

/**
 * Determines if the US stock market (NYSE/NASDAQ) is currently open.
 * US market hours: Mon-Fri, 9:30-16:00 ET.
 * In Spain (CET): approx 15:30-22:00 winter, 15:30-22:00 summer.
 * We use ET directly for correctness.
 */
function isMarketOpen(): boolean {
  const now = new Date()
  // Convert to ET using Intl
  const etStr = now.toLocaleString('en-US', { timeZone: 'America/New_York' })
  const et = new Date(etStr)
  const day = et.getDay() // 0=Sun, 6=Sat
  if (day === 0 || day === 6) return false
  const h = et.getHours()
  const m = et.getMinutes()
  const mins = h * 60 + m
  return mins >= 570 && mins < 960 // 9:30=570, 16:00=960
}

export default function MarketStatus() {
  const [open, setOpen] = useState(isMarketOpen)

  useEffect(() => {
    const id = setInterval(() => setOpen(isMarketOpen()), 30_000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="flex items-center gap-1.5">
      <div
        className={`w-2 h-2 rounded-full ${open ? 'bg-bloomberg-green shadow-[0_0_6px_rgba(0,255,127,0.7)]' : 'bg-bloomberg-text-muted'}`}
      />
      <span className={`font-mono text-2xs tracking-wider ${open ? 'text-bloomberg-green' : 'text-bloomberg-text-muted'}`}>
        {open ? 'LIVE' : 'CLOSED'}
      </span>
    </div>
  )
}
