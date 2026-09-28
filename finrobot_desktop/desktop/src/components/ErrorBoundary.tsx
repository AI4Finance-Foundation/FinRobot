import { Component, ErrorInfo, ReactNode } from 'react'
import { tSync } from '../i18n'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('Render error:', error, errorInfo)
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div
          style={{
            padding: 40,
            color: 'var(--text-primary)',
            background: 'var(--base)',
            minHeight: '100vh',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <h2>{tSync('shell.error.renderFailed')}</h2>
          <p style={{ color: 'var(--negative)', maxWidth: 600, wordBreak: 'break-word' }}>
            {this.state.error?.message}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            style={{
              marginTop: 16,
              padding: '8px 16px',
              background: 'var(--info)',
              color: 'var(--base)',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            {tSync('common.retry')}
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
