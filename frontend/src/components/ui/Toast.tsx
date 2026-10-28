// ============================================================
// OPSYN UI — Toast / ToastContainer  (Phase 4)
// Floating feedback on the glass menu tier, driven by ui.store. Announced
// to screen readers: errors assertively, everything else politely. Sits
// above the bottom navigation on phones.
// ============================================================

import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from 'lucide-react';
import { useUIStore, type Toast } from '../../store/ui.store';
import { OverlayPortal } from '../overlay/OverlayPortal';
import styles from './Toast.module.css';

const ICON = { success: CircleCheck, error: CircleAlert, warning: TriangleAlert, info: Info } as const;

function ToastItem({ t, onDismiss }: { t: Toast; onDismiss: () => void }) {
  const Icon = ICON[t.type];
  return (
    <div className={`liquid-glass-menu ${styles.toast} ${styles[t.type]}`} role={t.type === 'error' ? 'alert' : 'status'}>
      <Icon size={18} className={styles.icon} aria-hidden="true" />
      <div className={styles.text}>
        <p className={styles.title}>{t.title}</p>
        {t.message && <p className={styles.message}>{t.message}</p>}
      </div>
      <button type="button" className={styles.dismiss} onClick={onDismiss} aria-label="Dismiss notification">
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

export function ToastContainer() {
  const { toasts, removeToast } = useUIStore();
  return (
    <OverlayPortal>
      {/* The region exists before any toast so screen readers track it */}
      <div className={styles.stack} aria-live="polite">
        {toasts.map(t => <ToastItem key={t.id} t={t} onDismiss={() => removeToast(t.id)} />)}
      </div>
    </OverlayPortal>
  );
}

// Convenience hook — wraps useUIStore.addToast with typed helpers
export function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, message?: string) => addToast({ type: 'success', title, message }),
    error:   (title: string, message?: string) => addToast({ type: 'error',   title, message }),
    warning: (title: string, message?: string) => addToast({ type: 'warning', title, message }),
    info:    (title: string, message?: string) => addToast({ type: 'info',    title, message }),
  };
}

// Keep default export for backwards compatibility with existing imports
export default ToastContainer;
