import { useState, KeyboardEvent } from 'react'
import { Search } from 'lucide-react'

interface Props {
  onSearch: (ticker: string) => void
  isLoading: boolean
  currentTicker?: string
}

const QUICK_TICKERS = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AMZN', 'TSLA', 'BRK-B', 'JPM', 'V']

export default function SearchBar({ onSearch, isLoading, currentTicker }: Props) {
  const [value, setValue] = useState('')

  const submit = () => {
    const t = value.trim().toUpperCase()
    if (t) { onSearch(t); setValue('') }
  }

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') submit()
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 flex-1 max-w-xl bb-panel px-3 py-2">
          <Search size={14} className="text-bloomberg-text-muted flex-shrink-0" />
          <input
            className="flex-1 bg-transparent outline-none font-mono text-sm text-bloomberg-amber placeholder-bloomberg-text-muted tracking-widest uppercase"
            placeholder="ENTER TICKER — AAPL, MSFT, NVDA..."
            value={value}
            onChange={e => setValue(e.target.value.toUpperCase())}
            onKeyDown={onKey}
            disabled={isLoading}
            autoFocus
          />
          {currentTicker && (
            <span className="text-bloomberg-text-muted text-2xs border border-bloomberg-border px-2 py-0.5">
              {currentTicker}
            </span>
          )}
        </div>
        <button
          onClick={submit}
          disabled={isLoading || !value.trim()}
          className="bb-panel px-4 py-2 text-xs text-bloomberg-amber hover:bg-bloomberg-amber hover:text-black transition-colors disabled:opacity-40 disabled:cursor-not-allowed font-mono tracking-widest"
        >
          {isLoading ? 'LOADING...' : 'ANALYSE'}
        </button>
      </div>

      {/* Quick tickers */}
      <div className="flex items-center gap-1 flex-wrap">
        <span className="text-bloomberg-text-muted text-2xs mr-1">QUICK:</span>
        {QUICK_TICKERS.map(t => (
          <button
            key={t}
            onClick={() => onSearch(t)}
            disabled={isLoading}
            className="text-2xs font-mono px-2 py-0.5 border border-bloomberg-border text-bloomberg-text-secondary hover:border-bloomberg-amber hover:text-bloomberg-amber transition-colors disabled:opacity-40"
          >
            {t}
          </button>
        ))}
      </div>
    </div>
  )
}
