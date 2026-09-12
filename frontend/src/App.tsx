import { useState, useCallback } from 'react'
import SearchBar from './components/SearchBar'
import ValuationDashboard from './components/ValuationDashboard'
import PortfolioTab from './components/PortfolioTab'
import PerformanceTab from './components/PerformanceTab'
import ScreenerTab from './components/ScreenerTab'
import MarketStatus from './components/MarketStatus'
import ErrorBoundary from './components/ErrorBoundary'
import { ValuationResponse } from './types/valuation'

type Tab = 'ANALYZER' | 'SCREENER' | 'PORTFOLIO' | 'PERFORMANCE'

type AppState =
  | { status: 'idle' }
  | { status: 'loading'; ticker: string }
  | { status: 'success'; data: ValuationResponse; ticker: string }
  | { status: 'error'; message: string; ticker: string }

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('ANALYZER')
  const [state, setState] = useState<AppState>({ status: 'idle' })

  const handleSearch = useCallback(async (ticker: string) => {
    setState({ status: 'loading', ticker })
    try {
      const res = await fetch(`/api/valuation/${ticker.toUpperCase()}`)
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const data: ValuationResponse = await res.json()
      setState({ status: 'success', data, ticker: ticker.toUpperCase() })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error'
      setState({ status: 'error', message: msg, ticker: ticker.toUpperCase() })
    }
  }, [])

  // From the Screener tab: jump to the Analyzer and run a full valuation.
  const analyzeFromScreener = useCallback((ticker: string) => {
    setActiveTab('ANALYZER')
    handleSearch(ticker)
  }, [handleSearch])

  return (
    <div className="min-h-screen bg-bloomberg-bg flex flex-col">
      {/* Top Bar */}
      <header className="border-b border-bloomberg-border bg-bloomberg-panel px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-bloomberg-amber font-mono font-bold text-sm tracking-widest">
            IVS
          </span>
          <span className="text-bloomberg-text-muted text-xs">|</span>
          <span className="text-bloomberg-text-secondary text-xs tracking-widest uppercase">
            Institutional Valuation System
          </span>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-1">
          {(['ANALYZER', 'SCREENER', 'PORTFOLIO', 'PERFORMANCE'] as Tab[]).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`
                px-4 py-1.5 font-mono text-xs tracking-widest border transition-all duration-200
                ${activeTab === tab
                  ? 'border-bloomberg-amber text-bloomberg-amber bg-bloomberg-amber bg-opacity-10 shadow-[0_0_12px_rgba(245,166,35,0.15)]'
                  : 'border-transparent text-bloomberg-text-muted hover:text-bloomberg-amber hover:border-bloomberg-border'}
              `}
            >
              {tab}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-4 text-2xs text-bloomberg-text-muted font-mono">
          <span>DCF · CAPM · WACC</span>
          <MarketStatus />
        </div>
      </header>

      {/* Search Bar — only in ANALYZER tab */}
      {activeTab === 'ANALYZER' && (
        <div className="border-b border-bloomberg-border bg-bloomberg-panel px-4 py-3">
          <SearchBar
            onSearch={handleSearch}
            isLoading={state.status === 'loading'}
            currentTicker={state.status === 'success' || state.status === 'error' ? state.ticker : undefined}
          />
        </div>
      )}

      {/* Main Content */}
      <main className="flex-1 overflow-auto">
        {activeTab === 'SCREENER' && (
          <ErrorBoundary fallbackTitle="SCREENER MODULE ERROR">
            <ScreenerTab onAnalyze={analyzeFromScreener} />
          </ErrorBoundary>
        )}

        {activeTab === 'PORTFOLIO' && (
          <ErrorBoundary fallbackTitle="PORTFOLIO MODULE ERROR">
            <PortfolioTab />
          </ErrorBoundary>
        )}

        {activeTab === 'PERFORMANCE' && (
          <ErrorBoundary fallbackTitle="PERFORMANCE MODULE ERROR">
            <PerformanceTab />
          </ErrorBoundary>
        )}

        {activeTab === 'ANALYZER' && (
          <>
            {state.status === 'idle' && (
              <div className="flex flex-col items-center justify-center h-full min-h-[60vh] gap-6">
                <div className="text-center">
                  <div className="text-bloomberg-amber font-mono font-bold text-4xl ticker-glow mb-2">
                    IVS
                  </div>
                  <div className="text-bloomberg-text-secondary text-xs tracking-widest uppercase mb-6">
                    Institutional Valuation System
                  </div>
                  <div className="text-bloomberg-text-muted text-xs max-w-md text-center leading-relaxed">
                    Enter a ticker symbol above to compute a full DCF valuation
                    using CAPM-derived cost of equity, WACC, and 5-year FCF projection.
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-4 text-center text-2xs text-bloomberg-text-muted">
                  <div className="bb-panel p-3">
                    <div className="text-bloomberg-amber mb-1">CAPM</div>
                    <div>r = r_f + β × ERP</div>
                  </div>
                  <div className="bb-panel p-3">
                    <div className="text-bloomberg-electric mb-1">WACC</div>
                    <div>(E/V)·r_e + (D/V)·r_d·(1-T)</div>
                  </div>
                  <div className="bb-panel p-3">
                    <div className="text-bloomberg-green mb-1">DCF</div>
                    <div>Σ FCF/(1+WACC)^t + TV</div>
                  </div>
                </div>
              </div>
            )}

            {state.status === 'loading' && (
              <div className="flex flex-col items-center justify-center h-64 gap-4">
                <div className="flex items-center gap-3">
                  <div className="animate-pulse text-bloomberg-amber font-mono text-lg tracking-widest">
                    FETCHING {state.ticker}
                  </div>
                  <div className="flex gap-1">
                    {[0, 1, 2].map(i => (
                      <div
                        key={i}
                        className="w-1.5 h-5 bg-bloomberg-amber animate-bounce"
                        style={{ animationDelay: `${i * 0.15}s` }}
                      />
                    ))}
                  </div>
                </div>
                <div className="text-bloomberg-text-muted text-2xs font-mono animate-pulse">
                  Descargando datos de yfinance, calculando DCF y análisis técnico...
                </div>
                <div className="text-bloomberg-text-muted text-2xs font-mono">
                  Small/Mid Caps pueden tardar más por datos limitados
                </div>
              </div>
            )}

            {state.status === 'error' && (
              <div className="flex items-center justify-center h-64">
                <div className="bb-panel p-6 max-w-md text-center">
                  <div className="text-bloomberg-red font-mono text-sm mb-2">
                    ⚠ DATA FETCH ERROR
                  </div>
                  <div className="text-bloomberg-text-secondary text-xs mb-1">
                    Ticker: {state.ticker}
                  </div>
                  <div className="text-bloomberg-text-muted text-xs">
                    {state.message}
                  </div>
                </div>
              </div>
            )}

            {state.status === 'success' && (
              <ErrorBoundary fallbackTitle="VALUATION ENGINE ERROR">
                <ValuationDashboard data={state.data} onRefresh={() => handleSearch(state.ticker)} />
              </ErrorBoundary>
            )}
          </>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-bloomberg-border px-4 py-1 flex justify-between text-2xs text-bloomberg-text-muted">
        <span>Math: Risk-Return Analysis © Schoenmaker & Schramade 2023 · El Arte de Especular © Cava 2006</span>
        <span>yfinance · FastAPI · React · Recharts</span>
      </footer>
    </div>
  )
}
