import React from 'react';

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface State {
  hasError: boolean;
  message:  string;
}

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, message: '' };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div style={{
          padding: '24px',
          borderRadius: 12,
          background: 'rgba(244,63,94,.08)',
          border: '1px solid rgba(244,63,94,.3)',
          color: 'var(--rose)',
          fontSize: 13,
          textAlign: 'center',
        }}>
          <div style={{ fontSize: 22, marginBottom: 8 }}>⚠</div>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Something went wrong</div>
          <div style={{ fontSize: 11, color: 'var(--chalk3)', marginBottom: 12 }}>{this.state.message}</div>
          <button
            onClick={() => this.setState({ hasError: false, message: '' })}
            style={{
              padding: '5px 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
              background: 'rgba(244,63,94,.15)', color: 'var(--rose)',
              fontSize: 11, fontWeight: 700, fontFamily: 'var(--font)',
            }}
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
