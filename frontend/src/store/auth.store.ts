// ============================================================
// OPSYN AUTH STORE — Zustand
// Single source of truth for auth session
// ============================================================

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AuthUser } from '@shared';
import { tokenStore } from '../api/client';

export interface AuthState {
  user:          AuthUser | null;
  isAuth:        boolean;
  roleLevel:     number;
  tenantId:      string | null;
  _hasHydrated:  boolean;

  setUser:        (user: AuthUser, token: string, tenantId?: string | null) => void;
  clearAuth:      () => void;
  updateUser:     (partial: Partial<AuthUser>) => void;
  setHasHydrated: (v: boolean) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user:         null,
      isAuth:       false,
      roleLevel:    0,
      tenantId:     null,
      _hasHydrated: false,

      setUser: (user, token, tenantId = null) => {
        tokenStore.set(token);
        set({ user, isAuth: true, roleLevel: user.role.level, tenantId });
      },

      clearAuth: () => {
        tokenStore.clear();
        set({ user: null, isAuth: false, roleLevel: 0, tenantId: null });
      },

      updateUser: (partial) => {
        const user = get().user;
        if (user) set({ user: { ...user, ...partial } });
      },

      setHasHydrated: (v) => set({ _hasHydrated: v }),
    }),
    {
      name: 'opsyn-auth',
      partialize: state => ({
        user:      state.user,
        isAuth:    state.isAuth,
        roleLevel: state.roleLevel,
        tenantId:  state.tenantId,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    }
  )
);

// ── Selectors ─────────────────────────────────────────────────
export const selectUser      = (s: AuthState) => s.user;
export const selectIsAuth    = (s: AuthState) => s.isAuth;
export const selectRoleLevel = (s: AuthState) => s.roleLevel;
export const selectTenantId  = (s: AuthState) => s.tenantId;
