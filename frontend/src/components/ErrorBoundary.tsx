import { Component, ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallbackTitle?: string
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[IVS ErrorBoundary]', error, info.componentStack)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="flex items-center justify-center min-h-[200px] p-6">
        <div className="bb-panel border border-bloomberg-red max-w-lg w-full">
          <div className="px-5 py-3 border-b border-bloomberg-border bg-red-950">
            <div className="flex items-center gap-3">
              <span className="text-bloomberg-red text-lg animate-pulse">!</span>
              <div>
                <div className="text-bloomberg-red font-mono font-bold text-sm tracking-widest">
                  SYSTEM ERROR
                </div>
                <div className="text-bloomberg-text-muted text-2xs">
                  {this.props.fallbackTitle ?? 'COMPONENT RENDER FAILURE'}
                </div>
              </div>
            </div>
          </div>
          <div className="px-5 py-4 space-y-3">
            <div className="bg-black border border-bloomberg-border p-3 max-h-32 overflow-auto">
              <code className="text-bloomberg-red text-2xs font-mono break-all">
                {this.state.error?.message ?? 'Unknown error'}
              </code>
            </div>
            <div className="flex gap-3">
              <button
                onClick={this.handleReset}
                className="flex-1 py-2 border border-bloomberg-amber text-bloomberg-amber font-mono text-xs tracking-widest hover:bg-bloomberg-amber hover:text-black transition-colors"
              >
                REINTENTAR
              </button>
              <button
                onClick={() => window.location.reload()}
                className="flex-1 py-2 border border-bloomberg-border text-bloomberg-text-muted font-mono text-xs hover:text-bloomberg-amber hover:border-bloomberg-amber transition-colors"
              >
                RECARGAR APP
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }
}
