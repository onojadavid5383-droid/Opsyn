// ============================================================
// OPSYN — PageBoundary: the page slot's safety net.
//
// Suspense  App.tsx wraps every route in one Suspense, so a lazy page's
//           first load replaced the WHOLE app — navigation included — with a
//           spinner. Catching it here keeps the shell in place.
// Errors    a page that throws no longer blanks the app: the shell stays
//           usable and the page area explains what happened. Keyed by route
//           (in AppShell), so navigating away always recovers.
// ============================================================

import { Component, Suspense, type ErrorInfo, type ReactNode } from 'react';
import { RotateCcw, TriangleAlert } from 'lucide-react';
import styles from './PageBoundary.module.css';

interface State { error: Error | null }

class PageErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[PageBoundary]', error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className={styles.wrap}>
        <div className={styles.panel} role="alert">
          <TriangleAlert size={24} className={styles.icon} aria-hidden="true" />
          <h2 className={styles.title}>This page couldn't be displayed</h2>
          <p className={styles.text}>
            Something in the page failed while loading its data. The rest of OpSyn still works —
            use the navigation to continue, or try the page again.
          </p>
          <p className={styles.detail}>{error.message}</p>
          <button type="button" className={styles.retry} onClick={() => this.setState({ error: null })}>
            <RotateCcw size={16} aria-hidden="true" /> Try again
          </button>
        </div>
      </div>
    );
  }
}

function PageLoading() {
  return (
    <div className={styles.loading} role="status" aria-label="Loading page">
      <span className={styles.bar} />
    </div>
  );
}

export default function PageBoundary({ children }: { children: ReactNode }) {
  return (
    <PageErrorBoundary>
      <Suspense fallback={<PageLoading />}>{children}</Suspense>
    </PageErrorBoundary>
  );
}
