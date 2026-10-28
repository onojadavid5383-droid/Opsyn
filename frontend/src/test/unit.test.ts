// ============================================================
// OPSYN FRONTEND TESTS
// usePermissions · auth.store · utils
// Run: npm run test
// ============================================================

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAuthStore } from '../store/auth.store';
import { toRelative, toShort, isOverdue, isToday, cx, parseApiError, getRoleLevel, getRoleBadgeColor } from '../utils/index';


// ══ AUTH STORE ════════════════════════════════════════════════
describe('auth.store', () => {
  beforeEach(() => {
    useAuthStore.getState().clearAuth();
    localStorage.clear();
  });

  it('starts unauthenticated', () => {
    const { isAuth, user, roleLevel } = useAuthStore.getState();
    expect(isAuth).toBe(false);
    expect(user).toBeNull();
    expect(roleLevel).toBe(0);
  });

  it('setUser authenticates and sets role level', () => {
    const mockUser = {
      id: 'test-id', username: 'test', email: 'test@opsyn.ng',
      role: { id: 'r1', name: 'Admin', level: 5, is_system_role: true },
      role_level: 5, is_active: true,
    };
    act(() => { useAuthStore.getState().setUser(mockUser, 'mock-token'); });

    const state = useAuthStore.getState();
    expect(state.isAuth).toBe(true);
    expect(state.user).toEqual(mockUser);
    expect(state.roleLevel).toBe(5);
  });

  it('clearAuth resets to initial state', () => {
    const mockUser = {
      id: 'x', username: 'x', email: 'x@opsyn.ng',
      role: { id: 'r', name: 'Staff', level: 1, is_system_role: false },
      role_level: 1, is_active: true,
    };
    act(() => { useAuthStore.getState().setUser(mockUser, 'token'); });
    act(() => { useAuthStore.getState().clearAuth(); });

    const state = useAuthStore.getState();
    expect(state.isAuth).toBe(false);
    expect(state.user).toBeNull();
    expect(state.roleLevel).toBe(0);
  });

  it('updateUser patches user fields', () => {
    const mockUser = {
      id: 'id1', username: 'u', email: 'u@opsyn.ng',
      role: { id: 'r', name: 'Manager', level: 4, is_system_role: false },
      role_level: 4, is_active: true,
    };
    act(() => { useAuthStore.getState().setUser(mockUser, 'tk'); });
    act(() => { useAuthStore.getState().updateUser({ username: 'updated_user' }); });
    expect(useAuthStore.getState().user?.username).toBe('updated_user');
  });
});


// ══ DATE UTILITIES ════════════════════════════════════════════
describe('formatDate utilities', () => {
  it('toShort formats date correctly', () => {
    const result = toShort('2026-04-13T08:12:00.000Z');
    expect(result).toMatch(/13\s+Apr\s+2026/);
  });

  it('isOverdue returns true for past dates', () => {
    expect(isOverdue('2020-01-01T00:00:00Z')).toBe(true);
  });

  it('isOverdue returns false for future dates', () => {
    const future = new Date(Date.now() + 86400000).toISOString();
    expect(isOverdue(future)).toBe(false);
  });

  it('isToday returns true for current date', () => {
    expect(isToday(new Date().toISOString())).toBe(true);
  });

  it('isToday returns false for yesterday', () => {
    const yesterday = new Date(Date.now() - 86400000).toISOString();
    expect(isToday(yesterday)).toBe(false);
  });

  it('toRelative returns "just now" for very recent date', () => {
    const seconds_ago = new Date(Date.now() - 10000).toISOString();
    expect(toRelative(seconds_ago)).toBe('just now');
  });

  it('toRelative returns minutes for recent dates', () => {
    const minutes_ago = new Date(Date.now() - 3 * 60 * 1000).toISOString();
    expect(toRelative(minutes_ago)).toBe('3 min ago');
  });

  it('toRelative returns hours for older dates', () => {
    const hours_ago = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
    expect(toRelative(hours_ago)).toBe('2h ago');
  });
});


// ══ CLASS NAMES UTILITY ═══════════════════════════════════════
describe('cx classNames utility', () => {
  it('joins class strings', () => {
    expect(cx('a', 'b', 'c')).toBe('a b c');
  });

  it('filters out falsy values', () => {
    expect(cx('a', null, undefined, false, 'b')).toBe('a b');
  });

  it('handles empty input', () => {
    expect(cx()).toBe('');
  });

  it('handles all falsy', () => {
    expect(cx(null, undefined, false)).toBe('');
  });
});


// ══ ERROR PARSER ══════════════════════════════════════════════
describe('parseApiError', () => {
  it('handles string detail', () => {
    expect(parseApiError({ detail: 'Not found' })).toBe('Not found');
  });

  it('handles array detail (Pydantic 422)', () => {
    const err = {
      detail: [
        { field: 'email', message: 'Invalid email', code: 'value_error' },
        { field: 'username', message: 'Too short', code: 'min_length' },
      ]
    };
    const result = parseApiError(err);
    expect(result).toContain('email: Invalid email');
    expect(result).toContain('username: Too short');
  });

  it('handles message property', () => {
    expect(parseApiError({ message: 'Network error' })).toBe('Network error');
  });

  it('handles null/undefined', () => {
    expect(parseApiError(null)).toBe('An unknown error occurred');
    expect(parseApiError(undefined)).toBe('An unknown error occurred');
  });

  it('handles Axios-style nested error', () => {
    const axiosErr = { response: { data: { detail: 'Unauthorized' } } };
    expect(parseApiError(axiosErr)).toBe('Unauthorized');
  });
});


// ══ ROLE LEVEL UTILITY ═══════════════════════════════════════
describe('getRoleLevel', () => {
  it('returns correct level for known roles', () => {
    expect(getRoleLevel('Admin')).toBe(5);
    expect(getRoleLevel('Manager')).toBe(4);
    expect(getRoleLevel('Team Lead')).toBe(3);
    expect(getRoleLevel('NOC Operator')).toBe(2);
    expect(getRoleLevel('MEC Reviewer')).toBe(2);
    expect(getRoleLevel('Executive Viewer')).toBe(2);
    expect(getRoleLevel('Staff')).toBe(1);
  });

  it('returns 0 for unknown roles', () => {
    expect(getRoleLevel('Unknown')).toBe(0);
    expect(getRoleLevel('')).toBe(0);
  });
});

describe('getRoleBadgeColor', () => {
  it('returns rose for Admin', () => {
    const { color } = getRoleBadgeColor('Admin');
    expect(color).toBe('var(--rose)');
  });

  it('returns blue for Staff', () => {
    const { color } = getRoleBadgeColor('Staff');
    expect(color).toBe('var(--blue)');
  });

  it('returns chalk3 for unknown', () => {
    const { color } = getRoleBadgeColor('Unknown Role');
    expect(color).toBe('var(--chalk3)');
  });
});


// ══ TASK STORE ════════════════════════════════════════════════
import { useTaskStore } from '../store/task.store';

describe('task.store', () => {
  beforeEach(() => {
    useTaskStore.getState().clearFilters();
    useTaskStore.setState({ selectedTaskId: null });
  });

  it('starts with no selected task', () => {
    expect(useTaskStore.getState().selectedTaskId).toBeNull();
  });

  it('starts with cleared filters', () => {
    const { filters } = useTaskStore.getState();
    expect(filters.search).toBe('');
    expect(filters.priority).toBe('');
    expect(filters.status).toBe('');
    expect(filters.deadline_bucket).toBe('');
  });

  it('setSelectedTask sets the selected ID', () => {
    act(() => { useTaskStore.getState().setSelectedTask('task-123'); });
    expect(useTaskStore.getState().selectedTaskId).toBe('task-123');
  });

  it('setSelectedTask accepts null to deselect', () => {
    act(() => { useTaskStore.getState().setSelectedTask('task-abc'); });
    act(() => { useTaskStore.getState().setSelectedTask(null); });
    expect(useTaskStore.getState().selectedTaskId).toBeNull();
  });

  it('setFilters patches only supplied fields', () => {
    act(() => { useTaskStore.getState().setFilters({ search: 'Lagos NOC', priority: 'high' }); });
    const { filters } = useTaskStore.getState();
    expect(filters.search).toBe('Lagos NOC');
    expect(filters.priority).toBe('high');
    expect(filters.status).toBe('');          // untouched
    expect(filters.dept_id).toBe('');         // untouched
  });

  it('clearFilters resets all filter fields', () => {
    act(() => { useTaskStore.getState().setFilters({ search: 'test', priority: 'critical', status: 'done' }); });
    act(() => { useTaskStore.getState().clearFilters(); });
    const { filters } = useTaskStore.getState();
    expect(filters.search).toBe('');
    expect(filters.priority).toBe('');
    expect(filters.status).toBe('');
  });
});


// ══ usePermissions HOOK ═══════════════════════════════════════
import { usePermissions } from '../hooks/usePermissions';

function setAuthLevel(level: number) {
  const mockUser: any = {
    id: `user-lvl-${level}`,
    username: `user${level}`,
    email: `user${level}@opsyn.ng`,
    role: { id: 'r1', name: level === 5 ? 'Admin' : 'Staff', level, is_system_role: true },
    role_level: level,
    is_active: true,
  };
  act(() => { useAuthStore.getState().setUser(mockUser, 'token'); });
}

describe('usePermissions', () => {
  beforeEach(() => {
    useAuthStore.getState().clearAuth();
  });

  it('unauthenticated user has no permissions', () => {
    const { result } = renderHook(() => usePermissions());
    expect(result.current.isAdmin).toBe(false);
    expect(result.current.isManager).toBe(false);
    expect(result.current.isStaff).toBe(false);
    expect(result.current.canCreateStaff).toBe(false);
    expect(result.current.canViewAuditLogs).toBe(false);
  });

  it('Staff (level 1) can manage tasks but not create staff', () => {
    setAuthLevel(1);
    const { result } = renderHook(() => usePermissions());
    expect(result.current.isStaff).toBe(true);
    expect(result.current.canManageTasks).toBe(true);
    expect(result.current.canCreateStaff).toBe(false);
    expect(result.current.canViewAuditLogs).toBe(false);
    expect(result.current.canApproveOnboarding).toBe(false);
  });

  it('NOC Operator (level 2) can manage outages', () => {
    setAuthLevel(2);
    const { result } = renderHook(() => usePermissions());
    expect(result.current.isAnyOperator).toBe(true);
    expect(result.current.canManageOutages).toBe(true);
    expect(result.current.canCreateStaff).toBe(false);
  });

  it('Team Lead (level 3) can submit onboarding', () => {
    setAuthLevel(3);
    const { result } = renderHook(() => usePermissions());
    expect(result.current.isTeamLead).toBe(true);
    expect(result.current.canSubmitOnboarding).toBe(true);
    expect(result.current.canApproveOnboarding).toBe(false);
  });

  it('Manager (level 4) can create staff and view reports', () => {
    setAuthLevel(4);
    const { result } = renderHook(() => usePermissions());
    expect(result.current.isManager).toBe(true);
    expect(result.current.canCreateStaff).toBe(true);
    expect(result.current.canViewReports).toBe(true);
    expect(result.current.canViewAuditLogs).toBe(false);
    expect(result.current.canAssignRoles).toBe(false);
  });

  it('Admin (level 5) has all permissions', () => {
    setAuthLevel(5);
    const { result } = renderHook(() => usePermissions());
    expect(result.current.isAdmin).toBe(true);
    expect(result.current.canCreateStaff).toBe(true);
    expect(result.current.canApproveOnboarding).toBe(true);
    expect(result.current.canAssignRoles).toBe(true);
    expect(result.current.canViewAuditLogs).toBe(true);
    expect(result.current.canManageOrg).toBe(true);
  });

  it('canAssignRole returns true only when target level is below caller', () => {
    setAuthLevel(5);
    const { result } = renderHook(() => usePermissions());
    expect(result.current.canAssignRole(4)).toBe(true);
    expect(result.current.canAssignRole(5)).toBe(false);  // own level
    expect(result.current.canAssignRole(6)).toBe(false);  // above
  });

  it('userInitials fallback to username prefix when no profile', () => {
    const mockUser: any = {
      id: 'u1', username: 'jdoe', email: 'j@opsyn.ng',
      role: { id: 'r', name: 'Staff', level: 1, is_system_role: false },
      role_level: 1, is_active: true,
    };
    act(() => { useAuthStore.getState().setUser(mockUser, 'token'); });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.userInitials).toBe('JD');
  });
});
