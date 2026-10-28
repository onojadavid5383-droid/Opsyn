// ============================================================
// OPSYN ROUTE GUARDS — src/guards/index.tsx
// RequireAuth · RequireRole · RequireScope · RequireAdmin · RequireManager
// ============================================================

import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../store/auth.store';
import { usePermissions } from '../hooks/usePermissions';


// ── RequireAuth — redirect to /login if not authenticated ─────
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuth = useAuthStore(s => s.isAuth);
  const { pathname } = useLocation();

  if (!isAuth) {
    return <Navigate to={`/login?next=${encodeURIComponent(pathname)}`} replace />;
  }
  return <>{children}</>;
}


// ── RequireRole — render only if user role level >= minLevel ──
export function RequireRole({
  minLevel,
  children,
  fallback = null,
}: {
  minLevel: number;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const { roleLevel } = useAuthStore();
  if (roleLevel < minLevel) return <>{fallback}</>;
  return <>{children}</>;
}


// ── RequireAdmin — level 5 shortcut ───────────────────────────
export function RequireAdmin({ children, fallback }: { children: React.ReactNode; fallback?: React.ReactNode }) {
  return <RequireRole minLevel={5} fallback={fallback}>{children}</RequireRole>;
}


// ── RequireManager — level 4 shortcut ────────────────────────
export function RequireManager({ children, fallback }: { children: React.ReactNode; fallback?: React.ReactNode }) {
  return <RequireRole minLevel={4} fallback={fallback}>{children}</RequireRole>;
}


// ── RequireTeamLead — level 3 shortcut ───────────────────────
export function RequireTeamLead({ children, fallback }: { children: React.ReactNode; fallback?: React.ReactNode }) {
  return <RequireRole minLevel={3} fallback={fallback}>{children}</RequireRole>;
}


// ── RequireScope — render only if dept is in user scopes ──────
export function RequireScope({
  deptId,
  children,
  fallback = null,
}: {
  deptId?: string;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const { inScope, isAdmin } = usePermissions();
  // Admin always in scope
  if (isAdmin) return <>{children}</>;
  if (!deptId || !inScope(deptId)) return <>{fallback}</>;
  return <>{children}</>;
}


// ── ProtectedPage — combine auth + role check ─────────────────
export function ProtectedPage({
  minLevel = 1,
  children,
}: {
  minLevel?: number;
  children: React.ReactNode;
}) {
  return (
    <RequireAuth>
      <RequireRole minLevel={minLevel} fallback={
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          height: '100%', flexDirection: 'column', gap: 12,
          color: 'var(--chalk3)', fontFamily: 'var(--font)',
        }}>
          <div style={{ fontSize: 32 }}>🔒</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--chalk)' }}>Access Restricted</div>
          <div style={{ fontSize: 12 }}>You don't have permission to view this page.</div>
        </div>
      }>
        {children}
      </RequireRole>
    </RequireAuth>
  );
}
