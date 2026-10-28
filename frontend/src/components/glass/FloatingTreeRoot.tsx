// ============================================================
// OPSYN GLASS — WithFloatingTree
// Every floating surface joins one Floating UI tree. That is what lets a menu
// opened inside the task popup count as "inside" it: the popup's focus trap
// and outside-click dismissal leave the menu alone, and Escape closes only
// the top-most layer. Surfaces with no parent start the tree themselves.
// ============================================================

import { FloatingTree, useFloatingParentNodeId } from '@floating-ui/react';
import type { ReactNode } from 'react';

export function WithFloatingTree({ children }: { children: ReactNode }) {
  const parentId = useFloatingParentNodeId();
  return parentId === null ? <FloatingTree>{children}</FloatingTree> : <>{children}</>;
}
