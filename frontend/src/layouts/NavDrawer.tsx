// ============================================================
// OPSYN — NavDrawer (tablet / field)
// The full navigation in a modal drawer. Solid chrome like the primary
// sidebar it stands in for — navigation is stable UI, not a floating surface.
// Focus trapped; Escape, outside tap, or following a link closes it.
// ============================================================

import {
  FloatingFocusManager, FloatingOverlay, FloatingPortal, useDismiss, useFloating,
  useInteractions, useRole, useTransitionStatus,
} from '@floating-ui/react';
import { X } from 'lucide-react';
import { Link } from 'react-router-dom';
import OpsynMark from '../components/brand/OpsynMark';
import { OVERLAY_ROOT_ID } from '../components/overlay/OverlayPortal';
import { NavTree, type NavTreeProps } from './PrimarySidebar';
import styles from './Shell.module.css';

export default function NavDrawer({
  open, onOpenChange, ...tree
}: NavTreeProps & { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { refs: { setFloating }, context } = useFloating({ open, onOpenChange });
  const dismiss = useDismiss(context, { outsidePressEvent: 'mousedown' });
  const role = useRole(context, { role: 'dialog' });
  const { getFloatingProps } = useInteractions([dismiss, role]);
  const { isMounted, status } = useTransitionStatus(context, { duration: 240 });
  const close = () => onOpenChange(false);

  return (
    <FloatingPortal root={document.getElementById(OVERLAY_ROOT_ID) ?? undefined}>
      {isMounted && (
        <FloatingOverlay lockScroll className={styles.drawerScrim} data-status={status}>
          <FloatingFocusManager context={context}>
            <div ref={setFloating} className={styles.drawer} data-status={status} aria-label="Navigation" {...getFloatingProps()}>
              <div className={styles.drawerHead}>
                <Link to="/dashboard" className={styles.brand} onClick={close}>
                  <OpsynMark size={28} glow={false} />
                  <span className={styles.brandName}>OpSyn</span>
                </Link>
                <button type="button" className={styles.iconBtn} onClick={close} aria-label="Close navigation">
                  <X size={20} aria-hidden="true" />
                </button>
              </div>
              <NavTree {...tree} onNavigate={close} />
            </div>
          </FloatingFocusManager>
        </FloatingOverlay>
      )}
    </FloatingPortal>
  );
}
