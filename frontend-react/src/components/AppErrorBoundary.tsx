import { Component, type ErrorInfo, type ReactNode } from 'react'

type Props = {
  children: ReactNode
}

type State = {
  hasError: boolean
  message: string
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = {
    hasError: false,
    message: '',
  }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      message: String(error?.message || 'unknown_frontend_error'),
    }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Keep diagnostics in console for local debugging and QA.
    // eslint-disable-next-line no-console
    console.error('frontend_runtime_error', {
      message: String(error?.message || ''),
      stack: String(error?.stack || ''),
      component_stack: String(errorInfo?.componentStack || ''),
    })
  }

  private reset = () => {
    this.setState({ hasError: false, message: '' })
  }

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children
    return (
      <div className="min-h-screen bg-app-gradient p-6">
        <div className="mx-auto max-w-[880px] rounded-2xl border border-rose-200 bg-white/90 p-6 shadow-soft">
          <div className="text-lg font-semibold text-rose-700">Ошибка интерфейса</div>
          <div className="mt-2 text-sm text-slate-700">
            Произошла ошибка отображения. Данные не потеряны, можно перезагрузить страницу или сбросить ошибку.
          </div>
          <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
            {this.state.message || 'unknown_frontend_error'}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" className="gmz-btn gmz-btn-primary px-4 text-sm" onClick={this.reset}>
              Попробовать снова
            </button>
            <button
              type="button"
              className="gmz-btn gmz-btn-ghost px-4 text-sm"
              onClick={() => window.location.reload()}
            >
              Перезагрузить страницу
            </button>
          </div>
        </div>
      </div>
    )
  }
}
