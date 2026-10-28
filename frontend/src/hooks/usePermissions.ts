// ============================================================
// OPSYN usePermissions HOOK
// RBAC checks — mirrors backend policy logic.
// NOTE: These are UI hints only. Backend enforces all real access.
// ============================================================

import { useAuthStore } from '../store/auth.store';
import type { TaskStatus } from '@shared';

// Role levels:
//   1 = Staff
//   2 = NOC Operator / MEC Reviewer / Executive Viewer
//   3 = Team Lead
//   4 = Manager
//   5 = Admin

export function usePermissions() {
  const { user, roleLevel } = useAuthStore();

  // ── Role level checks ──────────────────────────────────────
  const isAdmin       = roleLevel >= 5;
  const isManager     = roleLevel >= 4;
  const isTeamLead    = roleLevel >= 3;
  const isAnyOperator = roleLevel >= 2;
  const isStaff       = roleLevel >= 1;

  // ── General action checks ──────────────────────────────────
  const canCreateStaff       = roleLevel >= 4;
  const canApproveOnboarding = roleLevel >= 5;
  const canSubmitOnboarding  = roleLevel >= 3;
  const canAssignRoles       = roleLevel >= 5;
  const canViewAuditLogs     = roleLevel >= 5;
  const canManageOutages     = roleLevel >= 2;
  const canManageTasks       = roleLevel >= 1;
  const canViewReports       = roleLevel >= 4;
  const canManageOrg         = roleLevel >= 5;

  // ── Task-specific permission methods ──────────────────────

  // Who can move a task to a given target state
  const canMoveTaskTo = (toStatus: TaskStatus): boolean => {
    switch (toStatus) {
      case 'done':     return roleLevel >= 2;  // operator+ can mark done
      case 'archived': return roleLevel >= 3;  // team lead+ can archive
      default:         return roleLevel >= 1;  // all authenticated users
    }
  };

  // Who can post APPROVAL comments (approve/reject tasks)
  const canApproveTask = roleLevel >= 2;

  // Who can post BLOCKER comments that force task to BLOCKED
  const canBlockTask = roleLevel >= 1;

  // Who can resolve ACTION comments
  const canResolveAction = roleLevel >= 2;

  // Who can edit/delete comments
  const canDeleteComment = (commentAuthorId?: string): boolean => {
    if (roleLevel >= 4) return true;          // managers can delete any comment
    return commentAuthorId === user?.id;       // authors can delete their own
  };

  // Who can manage automation rules
  const canManageAutomation = roleLevel >= 3;

  // Who can manage pipelines and stages
  const canManagePipelines = roleLevel >= 4;

  // Who can add/remove task dependencies
  const canManageDependencies = roleLevel >= 2;

  // ── Scope check ────────────────────────────────────────────
  const canAssignRole = (targetRoleLevel: number) => roleLevel > targetRoleLevel;

  const inScope = (deptId?: string): boolean => {
    if (roleLevel >= 5) return true;
    if (!deptId || !user?.staff_profile) return false;
    return true; // Simplified; real check is server-side
  };

  // ── User identity ──────────────────────────────────────────
  const userId = user?.id;
  const userName = user
    ? `${user.staff_profile?.first_name ?? ''} ${user.staff_profile?.last_name ?? ''}`.trim() || user.username
    : '';
  const userInitials = user
    ? ((user.staff_profile?.first_name?.[0] ?? '') + (user.staff_profile?.last_name?.[0] ?? '')).toUpperCase() ||
      user.username.slice(0, 2).toUpperCase()
    : 'OP';

  return {
    // Role levels
    isAdmin,
    isManager,
    isTeamLead,
    isAnyOperator,
    isStaff,

    // General
    canCreateStaff,
    canApproveOnboarding,
    canSubmitOnboarding,
    canAssignRoles,
    canViewAuditLogs,
    canManageOutages,
    canManageTasks,
    canViewReports,
    canManageOrg,

    // Task-specific
    canMoveTaskTo,
    canApproveTask,
    canBlockTask,
    canResolveAction,
    canDeleteComment,
    canManageAutomation,
    canManagePipelines,
    canManageDependencies,

    // Scope
    canAssignRole,
    inScope,

    // Identity
    userId,
    userName,
    userInitials,
  };
}
